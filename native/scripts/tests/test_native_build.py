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

"""Failure and reproducibility checks for native build inputs and staging."""

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_native as build
import native_config as config
import native_toolchains as toolchains


class NativeBuildTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / 'stage'
        self.directory.mkdir()
        (self.directory / 'libboson_quiche.dylib').write_bytes(b'compiled native input')
        (self.directory / 'licenses').mkdir()
        (self.directory / 'licenses/LICENSE').write_text('test license')
        self.inputs = {'platform': 'macos-arm64', 'binding_version': '0.30.1.1-SNAPSHOT',
                       'quiche_version': '0.30.1', 'cargo_lock_sha256': 'locked'}
        self.manifest = {'schema': 1, 'status': 'passed', 'stage': 'jni',
                         'platform': 'macos-arm64', 'rust_target': 'aarch64-apple-darwin',
                         'classifier': 'macos-aarch64', 'machines': ['arm64'],
                         'binding_version': '0.30.1.1-SNAPSHOT', 'quiche_version': '0.30.1',
                         'input_identity': config.identity(self.inputs), 'inputs': self.inputs,
                         'files': {name: config.digest(self.directory / name) for name in
                             ('libboson_quiche.dylib', 'licenses/LICENSE')}}
        self.save_manifest()

    def save_manifest(self):
        (self.directory / 'build.json').write_text(json.dumps(self.manifest))

    def validate(self, target='macos-arm64', expected=None):
        return build.validate_manifest(self.directory, target, 'jni', expected)

    def test_target_aliases_are_normalized(self):
        self.assertEqual(config.target_id('linux/x86_64'), 'linux-amd64')
        self.assertEqual(config.target_id('Darwin-aarch64'), 'macos-arm64')
        with self.assertRaises(ValueError):
            config.target_id('ios-arm64')

    def test_host_binary_cannot_satisfy_windows_target(self):
        with self.assertRaisesRegex(ValueError, 'wrong-target'):
            self.validate('windows-arm64')

    def test_changed_lock_or_toolchain_rejects_reuse(self):
        changed = dict(self.inputs, cargo_lock_sha256='new lock')
        with self.assertRaisesRegex(ValueError, 'Stale build inputs'):
            self.validate(expected=changed)

    def test_missing_native_file_is_rejected(self):
        (self.directory / 'libboson_quiche.dylib').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing or changed'):
            self.validate()

    def test_changed_native_file_is_rejected(self):
        (self.directory / 'libboson_quiche.dylib').write_bytes(b'wrong file')
        with self.assertRaisesRegex(ValueError, 'Missing or changed'):
            self.validate()

    def test_missing_notices_are_rejected(self):
        del self.manifest['files']['licenses/LICENSE']
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'missing the native library or licenses'):
            self.validate()

    def test_manifest_path_cannot_escape_staging(self):
        self.manifest['files']['../outside'] = '0' * 64
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'Unsafe build manifest path'):
            self.validate()

    def test_truncated_manifest_is_rejected(self):
        (self.directory / 'build.json').write_text('{')
        with self.assertRaises(ValueError):
            self.validate()

    def test_non_object_manifest_is_rejected(self):
        (self.directory / 'build.json').write_text('[]')
        with self.assertRaisesRegex(ValueError, 'must be objects'):
            self.validate()

    def test_manifest_input_corruption_is_rejected(self):
        self.manifest['inputs']['binding_version'] = 'different'
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'input identity is corrupt'):
            self.validate()

    def test_archive_assembly_is_independent_of_file_mtime_and_mode(self):
        first, second = self.root / 'first.tar', self.root / 'second.tar'
        build.assemble_bundle(self.directory, first, self.manifest)
        for path in self.directory.rglob('*'):
            os.utime(path, (123456789, 123456789))
            if path.is_file():
                path.chmod(0o600)
        build.assemble_bundle(self.directory, second, self.manifest)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with tarfile.open(first) as archive:
            self.assertEqual(archive.getnames(), sorted(archive.getnames()))
            self.assertTrue(all(item.mtime == 0 and item.uid == 0 for item in archive))

    def test_resources_restore_after_maven_output_is_deleted(self):
        with patch.object(build, 'ROOT', self.root):
            build.stage_maven(self.directory, 'macos-arm64')
            shutil.rmtree(self.root / 'api/target')
            build.stage_maven(self.directory, 'macos-arm64')
        self.assertTrue((self.root / 'api/target/native-test-resources/native/macos-aarch64/libboson_quiche.dylib').is_file())

    def test_cross_environment_drops_macos_and_compiler_settings(self):
        with patch.dict(os.environ, {'SDKROOT': '/host/sdk', 'CC': 'host-cc',
                                     'CMAKE_OSX_ARCHITECTURES': 'host', 'RUSTFLAGS': 'host flags'}):
            env = config.clean_environment()
        self.assertFalse(any(key in env for key in ('SDKROOT', 'CC', 'CMAKE_OSX_ARCHITECTURES', 'RUSTFLAGS')))

    def test_build_lock_excludes_another_process(self):
        lock = self.root / 'build.lock'
        code = ('import fcntl, sys\n'
                'with open(sys.argv[1], "a") as stream:\n'
                '    try:\n'
                '        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)\n'
                '    except BlockingIOError:\n'
                '        sys.exit(0)\n'
                'sys.exit(1)\n')
        with config.build_lock(lock):
            blocked = subprocess.run([sys.executable, '-c', code, str(lock)])
        acquired = subprocess.run([sys.executable, '-c', code, str(lock)])
        self.assertEqual(blocked.returncode, 0)
        self.assertEqual(acquired.returncode, 1)

    def test_archive_traversal_is_rejected(self):
        archive = self.root / 'unsafe.tar'
        with tarfile.open(archive, 'w') as package:
            entry = tarfile.TarInfo('../outside')
            entry.size = 1
            package.addfile(entry, io.BytesIO(b'x'))
        with self.assertRaisesRegex(ValueError, 'Unsafe upstream archive member'):
            config.extract_source(archive, self.root / 'extracted')
        self.assertFalse((self.root / 'outside').exists())

    def test_archive_escaping_link_is_rejected(self):
        archive = self.root / 'unsafe-link.tar'
        with tarfile.open(archive, 'w') as package:
            entry = tarfile.TarInfo('link')
            entry.type, entry.linkname = tarfile.SYMTYPE, '../../outside'
            package.addfile(entry)
        with self.assertRaisesRegex(ValueError, 'Unsafe upstream archive link'):
            config.extract_source(archive, self.root / 'extracted')

    def test_cached_download_is_verified_without_network(self):
        path = self.root / 'download'
        path.write_bytes(b'corrupt cache')
        with self.assertRaisesRegex(ValueError, 'Cached download checksum mismatch'):
            config.download_verified('https://example.invalid/file', path, 'expected')

    def test_lowercase_windows_license_names_are_collected(self):
        crate = self.root / 'cargo/registry/src/registry/windows-sys-0.59.0'
        crate.mkdir(parents=True)
        (crate / 'license-mit').write_text('test MIT notice')
        work = self.root / 'work'
        work.mkdir()
        with patch.object(toolchains, 'output', return_value='windows-sys v0.59.0\n'):
            records = toolchains.collect_licenses(self.root, self.root, work,
                self.root / 'cargo', 'x86_64-pc-windows-msvc', {})
        self.assertEqual(records[0]['notices'], ['windows-sys-0.59.0/license-mit'])
        self.assertEqual((work / 'licenses/windows-sys-0.59.0/license-mit').read_text(), 'test MIT notice')

    def make_jdk(self, system='Darwin', version='17.0.17', platform_headers='darwin'):
        home = self.root / 'jdk'
        (home / 'include' / platform_headers).mkdir(parents=True, exist_ok=True)
        (home / 'include/jni.h').write_text('test JNI definitions')
        (home / 'include' / platform_headers / 'jni_md.h').write_text('test platform definitions')
        (home / 'release').write_text(
            f'JAVA_VERSION="{version}"\nOS_NAME="{system}"\nOS_ARCH="amd64"\nIMPLEMENTOR="Test JDK"\n')
        return home.resolve()

    def test_java_home_supplies_bundled_headers_without_download(self):
        home = self.make_jdk()
        with patch.dict(os.environ, {'JAVA_HOME': str(home)}), \
                patch.object(config, 'download_verified', side_effect=AssertionError('Unexpected download')):
            self.assertEqual(build.jni_headers('macos-arm64', {}), home / 'include')
            record = build.jni_identity('macos-arm64', {})
        self.assertEqual(record['version'], '17.0.17')
        self.assertEqual(record['provider'], 'Test JDK')

    def test_macos_jdk_is_discovered_when_java_home_is_unset(self):
        home = self.make_jdk()
        with patch.dict(os.environ, {'JAVA_HOME': ''}), \
                patch.object(build.platform, 'system', return_value='Darwin'), \
                patch.object(build, 'output', return_value=str(home)) as discover:
            self.assertEqual(build.jni_headers('macos-arm64', {}), home / 'include')
        discover.assert_called_once_with('/usr/libexec/java_home')

    def test_jdk_patch_or_header_updates_are_recorded_without_a_fixed_hash_gate(self):
        home = self.make_jdk()
        with patch.dict(os.environ, {'JAVA_HOME': str(home)}):
            before = build.jni_identity('macos-arm64', {})
            (home / 'include/jni.h').write_text('updated valid SDK definitions')
            (home / 'release').write_text('JAVA_VERSION="17.0.18"\nOS_NAME="Darwin"\n')
            after = build.jni_identity('macos-arm64', {})
        self.assertEqual(after['version'], '17.0.18')
        self.assertNotEqual(before['headers'], after['headers'])

    def test_missing_platform_header_is_rejected(self):
        home = self.make_jdk()
        with patch.dict(os.environ, {'JAVA_HOME': str(home)}):
            with self.assertRaisesRegex(ValueError, 'Missing target JDK header'):
                build.jni_headers('windows-amd64', {})

    def test_jdk_release_platform_must_match_the_target(self):
        home = self.make_jdk(system='Windows')
        with patch.dict(os.environ, {'JAVA_HOME': str(home)}):
            with self.assertRaisesRegex(ValueError, 'do not match target platform'):
                build.jni_identity('macos-arm64', {})

    def test_container_jni_headers_are_resolved_inside_the_image(self):
        expected = {'provider': 'container JDK', 'version': '17.0.19'}
        tools = {'image_id': 'sha256:test', 'image_arch': 'arm64'}
        with patch.object(build, 'output', return_value=json.dumps(expected)) as run, \
                patch.object(build, 'jni_headers', side_effect=AssertionError('Host JDK was consulted')):
            actual = build.target_jni_identity('linux-arm64', {}, tools)
        self.assertEqual(actual, expected)
        self.assertEqual(run.call_args.args[:3], ('docker', 'run', '--rm'))
        self.assertNotIn('/headers', run.call_args.args)

    def test_windows_jdk_headers_support_both_target_architectures(self):
        home = self.make_jdk(system='Windows', platform_headers='win32')
        with patch.dict(os.environ, {'JAVA_HOME': str(home)}):
            amd64 = build.jni_identity('windows-amd64', {})
            arm64 = build.jni_identity('windows-arm64', {})
        self.assertEqual(amd64['headers'], arm64['headers'])

    def test_pre_java_11_jdk_is_rejected(self):
        home = self.make_jdk(version='1.8.0_462')
        with patch.dict(os.environ, {'JAVA_HOME': str(home)}):
            with self.assertRaisesRegex(ValueError, 'JDK 11 or later'):
                build.jni_identity('macos-arm64', {})

    def test_maven_and_documentation_pins_must_agree(self):
        shutil.copytree(config.ROOT / 'native', self.root / 'native',
                        ignore=shutil.ignore_patterns('toolchain-proofs.json', 'target', '__pycache__'))
        shutil.copyfile(config.ROOT / 'pom.xml', self.root / 'pom.xml')
        docs = self.root / 'native/api-docs.json'
        docs.write_text(json.dumps({'version': '0.0.0'}))
        with self.assertRaisesRegex(ValueError, 'Documentation snapshot'):
            config.validate_inputs(self.root)

    def test_vendored_header_mismatch_is_rejected(self):
        shutil.copytree(config.ROOT / 'native', self.root / 'native',
                        ignore=shutil.ignore_patterns('toolchain-proofs.json', 'target', '__pycache__'))
        (self.root / 'native/quiche.h').write_text('wrong header')
        with self.assertRaisesRegex(ValueError, 'Vendored quiche.h'):
            config.validate_inputs(self.root)

    def test_binding_abi_is_a_positive_integer_in_the_pom(self):
        pom = (config.ROOT / 'pom.xml').read_text()
        (self.root / 'pom.xml').write_text(pom)
        self.assertEqual(config.binding_abi(self.root), 1)
        for invalid in ('0', '-1', 'not-an-integer'):
            (self.root / 'pom.xml').write_text(pom.replace(
                '<quiche.binding.abi>1</quiche.binding.abi>',
                '<quiche.binding.abi>' + invalid + '</quiche.binding.abi>'))
            with self.assertRaisesRegex(ValueError, 'positive integer'):
                config.binding_abi(self.root)


if __name__ == '__main__':
    unittest.main()

