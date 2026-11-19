#!/usr/bin/env python3

# Copyright (c) 2026 bosonnetwork.io
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Reject false platform qualification and stale packaged native payloads."""

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qualification
import test_android_consumer as android
import test_jvm_consumers as jvm
import release_fixtures
from qualification import release


class QualificationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'root'
        self.root.mkdir()
        self.validation = release_fixtures.create(self.root)
        self.repository = Path(self.temporary.name) / 'candidate'
        release.freeze(
            release_fixtures.VERSION, self.validation, self.repository, self.root
        )
        self.identity = qualification.repository_identity(
            self.repository / 'repository', self.root
        )

    def test_repository_receipt_binds_all_fifteen_files(self):
        self.assertEqual(15, len(self.identity['artifacts']))
        self.assertEqual(6, len(self.identity['native_sha256']))

    def test_consumer_source_changes_invalidate_validation(self):
        before = release.source_fingerprint(self.root)
        source = self.root / 'test-tooling/consumer-common/src/main/java/Probe.java'
        source.parent.mkdir(parents=True)
        source.write_text('class Probe {}')
        self.assertNotEqual(before, release.source_fingerprint(self.root))
        (source.parent / 'target').mkdir()
        (source.parent / 'target/output.java').write_text('generated output')
        stable = release.source_fingerprint(self.root)
        (source.parent / 'target/output.java').write_text('changed output')
        self.assertEqual(stable, release.source_fingerprint(self.root))

    def runtime_xml(self, arch='arm64', checksum=None, tests='47'):
        data = dict(
            status='passed',
            java_os='Windows 11',
            java_arch=arch,
            tests=tests,
            binding_version=release_fixtures.VERSION,
            binding_abi='1',
            native_sha256=checksum or self.identity['native_sha256']['windows-arm64'],
        )
        root = ET.Element('properties')
        for key, value in data.items():
            ET.SubElement(root, 'entry', key=key).text = value
        path = self.root / 'runtime.xml'
        ET.ElementTree(root).write(path)
        return path

    def test_matching_windows_receipt_requires_exact_jvm_and_native(self):
        report = jvm.runtime_xml(self.runtime_xml(), self.identity, 'windows-arm64')
        self.assertEqual('Windows', report['java_os'])
        self.assertEqual(47, report['tests'])
        for arch, checksum, tests in (
            ('amd64', None, '47'),
            ('arm64', 'wrong', '47'),
            ('arm64', None, '46'),
        ):
            with self.subTest(
                arch=arch, checksum=checksum, tests=tests
            ), self.assertRaises(ValueError):
                jvm.runtime_xml(
                    self.runtime_xml(arch, checksum, tests),
                    self.identity,
                    'windows-arm64',
                )

    def apk(self, changed=False):
        binary = release_fixtures.binary('android-arm64', release_fixtures.VERSION)
        apk = self.root / 'consumer.apk'
        apk.write_bytes(
            release_fixtures.zip_bytes(
                {
                    'lib/arm64-v8a/libboson_quiche.so': binary
                    + (b'bad' if changed else b'')
                }
            )
        )
        mapping = self.root / 'mapping.txt'
        mapping.write_text(
            '# compiler: R8\nio.bosonnetwork.quiche.Native -> io.bosonnetwork.quiche.Native:'
        )
        sdk = self.root / 'sdk'
        tool = sdk / 'build-tools/35.0.0/zipalign'
        tool.parent.mkdir(parents=True, exist_ok=True)
        tool.touch()
        return sdk, apk, mapping

    def test_apk_native_must_match_the_maven_aar(self):
        sdk, apk, mapping = self.apk(changed=True)
        with self.assertRaisesRegex(ValueError, 'differs from the Maven AAR'):
            android.check_apk(sdk, apk, mapping, self.identity)

    def test_apk_checks_both_elf_and_zip_alignment(self):
        sdk, apk, mapping = self.apk()
        with patch.object(
            android.subprocess, 'check_output', return_value='Verification successful'
        ) as check:
            result = android.check_apk(sdk, apk, mapping, self.identity)
        self.assertTrue(result['elf_16k'] and result['zipalign_16k'])
        self.assertIn('16', check.call_args.args[0])

    def test_android_16k_receipt_cannot_claim_a_4k_runtime(self):
        self.validation['checks']['android-16k'] = dict(
            status='passed',
            artifact_set_sha256=self.identity['artifact_set_sha256'],
            checkjni=True,
            elf_16k=True,
            zipalign_16k=True,
            page_size=4096,
            native_sha256=self.identity['native_sha256']['android-arm64'],
            apk_sha256='apk',
            mapping_sha256='mapping',
            runtime_log_sha256='log',
            evidence={'sha256': 'fixture'},
        )
        with self.assertRaisesRegex(ValueError, 'wrong runtime page size'):
            release.checked_validation(
                self.validation,
                release_fixtures.VERSION,
                release.validate_natives(self.root),
                self.identity['artifacts'],
                self.root,
            )

    def test_jvm_qualification_rejects_missing_architectures(self):
        self.validation['checks']['jvm-consumers'] = dict(
            status='passed',
            artifact_set_sha256=self.identity['artifact_set_sha256'],
            platforms={},
            evidence={'sha256': 'fixture'},
        )
        with self.assertRaisesRegex(ValueError, 'cover macOS and both Linux'):
            release.checked_validation(
                self.validation,
                release_fixtures.VERSION,
                release.validate_natives(self.root),
                self.identity['artifacts'],
                self.root,
            )

    def test_physical_device_is_rejected_before_adb(self):
        with patch.object(android.subprocess, 'check_output') as adb:
            with self.assertRaisesRegex(ValueError, 'never a physical device'):
                android.run(self.root, 'physical-serial', self.root / 'test.apk')
            adb.assert_not_called()


if __name__ == '__main__':
    unittest.main()
