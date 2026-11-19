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

"""Reject stale distribution inputs and verify native artifact boundaries."""

import json
from pathlib import Path
import re
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_native as build
import native_config as config
import package_artifacts as packaging


class PackagingTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.stage = self.root / 'jni'
        self.stage.mkdir()
        header = bytearray(64)
        header[:4] = b'\xcf\xfa\xed\xfe'
        struct.pack_into('<I', header, 4, 0x0100000c)
        (self.stage / 'libboson_quiche.dylib').write_bytes(header)
        (self.stage / 'licenses').mkdir()
        (self.stage / 'licenses/LICENSE').write_text('fixture license')
        pins = json.loads((config.ROOT / 'native/toolchains.json').read_text())
        inputs = build.build_inputs('macos-arm64', 'source-digest', config.validate_inputs(), pins, {})
        self.manifest = {'schema': 1, 'status': 'passed', 'stage': 'jni',
                         'platform': 'macos-arm64', 'rust_target': 'aarch64-apple-darwin',
                         'classifier': 'macos-aarch64', 'machines': ['arm64'],
                         'binding_version': inputs['binding_version'], 'binding_abi': config.binding_abi(),
                         'quiche_version': config.TAG, 'inputs': inputs,
                         'files': {name: config.digest(self.stage / name) for name in
                                   ('libboson_quiche.dylib', 'licenses/LICENSE')}}
        self.save()

    def save(self):
        self.manifest['input_identity'] = config.identity(self.manifest['inputs'])
        (self.stage / 'build.json').write_text(json.dumps(self.manifest))

    def test_current_compile_inputs_allow_prebuilt_packaging(self):
        # Packaging a prebuilt library must not require its SDK/cache or rebuild it
        # just because Maven resource staging changed.
        self.manifest['inputs']['build_scripts_sha256'] = 'older orchestration'
        self.save()
        packaging.validate('macos-arm64', self.stage)

    def test_changed_compile_inputs_are_rejected(self):
        keys = ('binding_abi', 'binding_version', 'quiche_archive_sha256', 'quiche_tag',
                'features', 'cargo_lock_sha256', 'toolchains', 'jni_sources_sha256',
                'jni_declarations_sha256', 'cmake_sha256', 'baseline')
        for key in keys:
            with self.subTest(key=key):
                original = self.manifest['inputs'][key]
                self.manifest['inputs'][key] = 'changed'
                if key == 'binding_version':
                    self.manifest['binding_version'] = 'changed'
                self.save()
                with self.assertRaisesRegex(ValueError, 'Stale native input'):
                    packaging.validate('macos-arm64', self.stage)
                self.manifest['inputs'][key] = original
                self.manifest['binding_version'] = self.manifest['inputs']['binding_version']
        self.save()

    def test_manifest_abi_is_checked_separately(self):
        self.manifest['binding_abi'] += 1
        self.save()
        with self.assertRaisesRegex(ValueError, 'ABI mismatch'):
            packaging.validate('macos-arm64', self.stage)

    def test_binary_architecture_is_checked_even_with_valid_checksum(self):
        binary = self.stage / 'libboson_quiche.dylib'
        data = bytearray(binary.read_bytes())
        struct.pack_into('<I', data, 4, 0x01000007)
        binary.write_bytes(data)
        self.manifest['files'][binary.name] = config.digest(binary)
        self.save()
        with self.assertRaisesRegex(ValueError, 'Wrong native architecture'):
            packaging.validate('macos-arm64', self.stage)

    def test_missing_and_modified_inputs_are_rejected(self):
        binary = self.stage / 'libboson_quiche.dylib'
        binary.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'Missing or changed'):
            packaging.validate('macos-arm64', self.stage)
        binary.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing or changed'):
            packaging.validate('macos-arm64', self.stage)

    def test_truncated_binary_is_rejected(self):
        binary = self.root / 'truncated.dll'
        binary.write_bytes(b'MZ')
        with self.assertRaisesRegex(ValueError, 'Truncated'):
            packaging.machine(binary)

    def test_all_targets_validate_before_any_resource_is_staged(self):
        output = self.root / 'artifacts'
        with patch.object(packaging, 'validate', side_effect=[(self.stage, self.manifest), ValueError('missing')]):
            with self.assertRaisesRegex(ValueError, 'missing'):
                packaging.desktop(['macos-arm64', 'windows-arm64'], output)
        self.assertFalse(output.exists())

    def test_desktop_resources_contain_only_target_native_and_notices(self):
        output = self.root / 'artifacts'
        with patch.object(packaging, 'validate', return_value=(self.stage, self.manifest)):
            packaging.desktop(['macos-arm64'], output)
        resources = output / 'macos-aarch64'
        names = {file.relative_to(resources).as_posix() for file in resources.rglob('*') if file.is_file()}
        self.assertIn('native/macos-aarch64/libboson_quiche.dylib', names)
        self.assertIn('META-INF/boson-quiche-native/macos-aarch64/LICENSE', names)
        self.assertTrue(all(name.startswith(('native/macos-aarch64/',
            'META-INF/boson-quiche-native/macos-aarch64/')) for name in names))
        self.assertFalse(list(output.rglob('*.jar')))

    def test_reselecting_host_removes_other_targets_from_resource_staging(self):
        output = self.root / 'artifacts'
        stale = output / 'windows-aarch64/native/stale.dll'
        stale.parent.mkdir(parents=True)
        stale.write_bytes(b'old target')
        with patch.object(packaging, 'validate', return_value=(self.stage, self.manifest)):
            packaging.desktop(['macos-arm64'], output)
        self.assertEqual(['macos-aarch64'], [path.name for path in output.iterdir()])

    def test_android_stages_native_resources_without_building_jars(self):
        (self.stage / 'libboson_quiche.so').write_bytes(b'fixture Android library')
        output = self.root / 'aar'
        with patch.object(packaging, 'validate', return_value=(self.stage, self.manifest)):
            packaging.android(output)
        self.assertFalse(list(output.rglob('*.jar')))
        self.assertEqual(b'fixture Android library', (output / 'jni/arm64-v8a/libboson_quiche.so').read_bytes())
        self.assertIn('minSdkVersion="33"', (output / 'AndroidManifest.xml').read_text())
        self.assertTrue((output / 'proguard.txt').is_file())

    def test_consumer_rules_cover_every_named_jni_class(self):
        source = '\n'.join(path.read_text() for path in (config.ROOT / 'native/src/main/c').glob('*') if path.is_file())
        referenced = set(re.findall(r'construct\(env,\s*"(\w+)"', source))
        referenced.update(re.findall(r'FindClass\(env, PACKAGE "(\w+)"', source))
        rules = (config.ROOT / 'android/src/main/proguard.txt').read_text()
        kept = set(re.findall(r'-keep class io.bosonnetwork.quiche.(\w+) \{ \*; \}', rules))
        self.assertTrue(referenced <= kept, 'Missing JNI keep rules: ' + str(referenced - kept))


if __name__ == '__main__':
    unittest.main()
