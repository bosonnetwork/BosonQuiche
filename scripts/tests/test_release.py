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

"""Release preparation must reject stale, incomplete, mixed-version and mutable inputs."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import release_support as release
import verify_release
from unittest.mock import patch
from release_support import config, packaging
import release_fixtures


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'project'
        self.root.mkdir()
        self.validation = release_fixtures.create(self.root)
        self.output = Path(self.temporary.name) / 'releases' / release_fixtures.VERSION

    def freeze(self):
        return release.freeze(
            release_fixtures.VERSION, self.validation, self.output, self.root
        )

    def manifest(self, target):
        path = self.root / '.build/staged' / target / 'jni/build.json'
        return path, json.loads(path.read_text())

    def test_snapshot_and_non_aligned_release_versions_are_rejected(self):
        for value in (
            '0.30.1.1-SNAPSHOT',
            '0.30.1',
            '0.30.1.0',
            '0.30.1.1-rc1',
            '0.31.0.1',
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                release.release_version(value)
        self.assertEqual(
            release_fixtures.VERSION, release.release_version(release_fixtures.VERSION)
        )

    def test_freeze_preserves_every_payload_and_records_incomplete_qualification(self):
        original = release.hashes(
            release.artifact_paths(release_fixtures.VERSION, self.root)
        )
        record = self.freeze()
        self.assertEqual(15, len(record['files']))
        self.assertEqual(original, record['files'])
        self.assertFalse(record['qualification']['complete'])
        self.assertIn('windows-arm64:runtime', record['qualification']['missing'])
        self.assertIn('synthetic-test-fixture', record['qualification']['missing'])
        verified = release.verify(self.output, root=self.root)
        self.assertEqual(record, verified)

    def test_an_existing_release_is_never_overwritten(self):
        self.freeze()
        before = (self.output / 'SHA256SUMS').read_bytes()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.freeze()
        self.assertEqual(before, (self.output / 'SHA256SUMS').read_bytes())

    def test_normal_maven_outputs_must_match_before_signing(self):
        record = self.freeze()
        for module in release.MODULES:
            release.verify_built(record, module, self.root)
        paths = release.artifact_paths(release_fixtures.VERSION, self.root)
        for name, path in paths.items():
            if name.endswith('.pom'):
                continue
            original = path.read_bytes()
            with self.subTest(name=name):
                path.write_bytes(original + b'changed after packaging')
                with self.assertRaisesRegex(ValueError, 'Maven output differs'):
                    release.verify_built(record, name.split('/')[2], self.root)
                path.write_bytes(original)

    def test_missing_maven_output_is_rejected_before_signing(self):
        record = self.freeze()
        paths = release.artifact_paths(release_fixtures.VERSION, self.root)
        name = next(name for name in paths if name.endswith('.jar'))
        paths[name].unlink()
        with self.assertRaisesRegex(ValueError, 'Missing Maven release output'):
            release.verify_built(record, name.split('/')[2], self.root)

    def test_android_main_zip_must_match_the_prepared_aar(self):
        record = self.freeze()
        paths = release.artifact_paths(release_fixtures.VERSION, self.root)
        aar = next(path for name, path in paths.items() if name.endswith('.aar'))
        aar.with_suffix('.jar').write_bytes(b'changed main artifact')
        with self.assertRaisesRegex(ValueError, 'Android main artifact differs'):
            release.verify_built(record, 'boson-quiche-android', self.root)

    def test_wrong_pom_group_is_rejected(self):
        path = self.root / 'pom.xml'
        path.write_text(
            path.read_text().replace(
                '<groupId>io.bosonnetwork</groupId>',
                '<groupId>com.example</groupId>',
                1,
            )
        )
        with self.assertRaisesRegex(ValueError, 'groupId'):
            self.freeze()

    def test_wrong_pom_packaging_is_rejected(self):
        path = self.root / 'android/pom.xml'
        path.write_text(
            path.read_text().replace(
                '<packaging>aar</packaging>', '<packaging>pom</packaging>'
            )
        )
        with self.assertRaisesRegex(ValueError, 'packaging mismatch'):
            self.freeze()

    def test_host_only_record_cannot_qualify_a_distribution(self):
        self.validation['scope'] = 'selected-targets'
        with self.assertRaisesRegex(ValueError, 'complete distribution validation'):
            self.freeze()

    def test_mutated_frozen_artifact_is_rejected(self):
        record = self.freeze()
        file = (
            self.output
            / 'repository'
            / next(name for name in record['files'] if name.endswith('.jar'))
        )
        file.chmod(0o644)
        file.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'artifact changed'):
            release.verify(self.output, root=self.root)

    def test_extra_repository_file_is_rejected(self):
        self.freeze()
        (self.output / 'repository/unexpected.jar').write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'extra or missing'):
            release.verify(self.output, root=self.root)

    def test_changed_source_pom_is_rejected(self):
        self.freeze()
        with (self.root / 'api/pom.xml').open('a') as file:
            file.write('\n<!-- modified after preparation -->\n')
        with self.assertRaisesRegex(ValueError, 'Source POM changed'):
            release.verify(self.output, root=self.root)

    def test_changed_source_inputs_are_rejected(self):
        self.freeze()
        with (self.root / 'native/src/main/c/logging.inc').open('a') as file:
            file.write('\n/* later source change */\n')
        with self.assertRaisesRegex(ValueError, 'Sources changed'):
            release.verify(self.output, root=self.root)

    def test_missing_native_prevents_any_release_directory(self):
        (self.root / '.build/staged/windows-arm64/jni/boson_quiche.dll').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing or changed'):
            self.freeze()
        self.assertFalse(self.output.exists())

    def test_wrong_architecture_cannot_be_hidden_by_a_new_checksum(self):
        path, manifest = self.manifest('windows-arm64')
        binary = path.parent / 'boson_quiche.dll'
        binary.write_bytes(
            release_fixtures.binary('windows-amd64', release_fixtures.VERSION)
        )
        manifest['files']['boson_quiche.dll'] = config.digest(binary)
        release.write_json(path, manifest)
        with self.assertRaisesRegex(ValueError, 'architecture'):
            self.freeze()

    def test_wrong_baseline_is_rejected(self):
        path, manifest = self.manifest('linux-amd64')
        manifest['inputs']['baseline'] = 'glibc 2.39'
        manifest['input_identity'] = config.identity(manifest['inputs'])
        release.write_json(path, manifest)
        with self.assertRaisesRegex(ValueError, 'Stale native input'):
            self.freeze()

    def test_linux_binary_cannot_exceed_its_declared_glibc_baseline(self):
        path, manifest = self.manifest('linux-amd64')
        file = path.parent / 'libboson_quiche.so'
        file.write_bytes(file.read_bytes().replace(b'GLIBC_2.28', b'GLIBC_2.39'))
        manifest['files'][file.name] = config.digest(file)
        release.write_json(path, manifest)
        with self.assertRaisesRegex(ValueError, 'glibc 2.28 baseline'):
            self.freeze()

    def test_android_binary_requires_16k_load_alignment(self):
        import struct

        path, manifest = self.manifest('android-arm64')
        file = path.parent / 'libboson_quiche.so'
        data = bytearray(file.read_bytes())
        struct.pack_into('<Q', data, 64 + 48, 4096)
        file.write_bytes(data)
        manifest['files'][file.name] = config.digest(file)
        release.write_json(path, manifest)
        with self.assertRaisesRegex(ValueError, '16 KB pages'):
            self.freeze()

    def test_macos_binary_cannot_raise_the_minimum_os(self):
        import struct

        path, manifest = self.manifest('macos-arm64')
        file = path.parent / 'libboson_quiche.dylib'
        data = bytearray(file.read_bytes())
        struct.pack_into('<I', data, 32 + 12, 0x000C0000)
        file.write_bytes(data)
        manifest['files'][file.name] = config.digest(file)
        release.write_json(path, manifest)
        with self.assertRaisesRegex(ValueError, 'macOS 11 baseline'):
            self.freeze()

    def test_snapshot_native_metadata_cannot_be_relabelled(self):
        path, manifest = self.manifest('linux-arm64')
        manifest['binding_version'] = '0.30.1.1-SNAPSHOT'
        manifest['inputs']['binding_version'] = '0.30.1.1-SNAPSHOT'
        manifest['input_identity'] = config.identity(manifest['inputs'])
        release.write_json(path, manifest)
        with self.assertRaisesRegex(ValueError, 'Stale native input'):
            self.freeze()

    def test_binary_version_is_checked_independently_of_manifest(self):
        path, manifest = self.manifest('android-arm64')
        binary = path.parent / 'libboson_quiche.so'
        binary.write_bytes(
            release_fixtures.binary('android-arm64', '0.30.1.1-SNAPSHOT')
        )
        manifest['files'][binary.name] = config.digest(binary)
        release.write_json(path, manifest)
        with self.assertRaisesRegex(
            ValueError, 'binary has no matching binding version'
        ):
            self.freeze()

    def test_missing_jni_export_inspection_is_rejected(self):
        path, manifest = self.manifest('macos-arm64')
        manifest['jni_exports'] = []
        release.write_json(path, manifest)
        with self.assertRaisesRegex(ValueError, 'JNI export inspection'):
            self.freeze()

    def test_snapshot_api_metadata_is_rejected_even_with_updated_artifact_hashes(self):
        path = next(
            path
            for name, path in release.artifact_paths(
                release_fixtures.VERSION, self.root
            ).items()
            if name.endswith('boson-quiche-' + release_fixtures.VERSION + '.jar')
        )
        import zipfile

        with zipfile.ZipFile(path) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        files['META-INF/boson-quiche.properties'] = (
            b'binding.version=0.30.1.1-SNAPSHOT\nbinding.abi=1\nquiche.version=0.30.1\n'
        )
        path.write_bytes(release_fixtures.zip_bytes(files))
        self.validation['artifacts'] = release.hashes(
            release.artifact_paths(release_fixtures.VERSION, self.root)
        )
        with self.assertRaisesRegex(ValueError, 'API binding metadata mismatch'):
            self.freeze()
        self.assertFalse(self.output.exists())
        self.assertFalse(
            self.output.with_name(self.output.name + '.assembling').exists()
        )

    def test_skipped_or_missing_required_checks_are_rejected(self):
        for status in ('skipped', 'failed', None):
            self.validation['checks']['host-jni']['status'] = status
            with self.subTest(status=status), self.assertRaisesRegex(
                ValueError, 'Required build validation'
            ):
                self.freeze()

    def test_stale_runtime_evidence_is_rejected(self):
        self.validation['targets']['linux-amd64']['runtime'] = {
            'status': 'passed',
            'native_sha256': 'wrong',
            'binding_version': release_fixtures.VERSION,
            'binding_abi': 1,
        }
        with self.assertRaisesRegex(ValueError, 'Stale runtime evidence'):
            self.freeze()

    def test_windows_arm64_requires_an_arm64_windows_jvm(self):
        item = self.validation['targets']['windows-arm64']
        item['runtime'] = dict(
            item,
            status='passed',
            java_os='Windows',
            java_arch='amd64',
            tests=47,
            evidence={'kind': 'fixture', 'sha256': 'fixture'},
        )
        with self.assertRaisesRegex(ValueError, 'matching Windows JVM'):
            self.freeze()

    def test_stale_android_qualification_is_rejected(self):
        self.validation['checks']['android-r8'] = {
            'status': 'passed',
            'artifact_set_sha256': 'old',
            'evidence': {'kind': 'fixture', 'sha256': 'fixture'},
        }
        with self.assertRaisesRegex(
            ValueError, 'Stale consumer/platform qualification'
        ):
            self.freeze()

    def test_unsigned_preparation_does_not_claim_publication_qualification(self):
        self.freeze()
        with self.assertRaisesRegex(ValueError, 'qualification is incomplete'):
            release.verify(self.output, publication=True, root=self.root)

    def test_partial_reactor_cannot_sign_a_partial_release(self):
        with patch.dict('os.environ', {'MAVEN_CMD_LINE_ARGS': '-pl api verify'}):
            with self.assertRaisesRegex(ValueError, 'complete four-module reactor'):
                verify_release.check_maven_cli()

    def test_changed_checksum_manifest_is_rejected(self):
        self.freeze()
        file = self.output / 'SHA256SUMS'
        file.chmod(0o644)
        file.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'checksum manifest changed'):
            release.verify(self.output, root=self.root)


if __name__ == '__main__':
    unittest.main()
