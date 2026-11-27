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

"""Verify Docker cache isolation and the boundary between build trees and exports."""

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_native as build
import native_config as config
import test_runtime as runtime


class DockerBuildTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.destination = self.root / 'output'
        self.destination.mkdir()
        self.cache = self.root / 'cache'
        self.inputs = {'platform': 'linux-arm64', 'binding_version': '0.30.1.1-SNAPSHOT',
                       'binding_abi': 1}
        (self.destination / 'inputs.json').write_text(json.dumps(self.inputs))

    def test_volumes_separate_builder_families_and_linux_architectures(self):
        names = {config.docker_cache_volume(target, arch) for target, arch in (
            ('linux-arm64', 'arm64'), ('linux-amd64', 'amd64'), ('windows-arm64', 'arm64'))}
        self.assertEqual(len(names), 3)
        self.assertEqual(config.docker_cache_volume('windows-amd64', 'arm64'),
                         config.docker_cache_volume('windows-arm64', 'arm64'))
        with self.assertRaises(ValueError):
            config.docker_cache_volume('macos-arm64', 'arm64')

    def fake_build(self, target, source, work, inputs, pins, cache, stage, env, container, test_natives):
        spec = config.TARGETS[target]
        shutil.rmtree(work / 'install', ignore_errors=True)
        build_tree = work / 'cmake'
        (build_tree / 'rust').mkdir(parents=True, exist_ok=True)
        (build_tree / 'CMakeCache.txt').write_text('internal configuration')
        archive = build_tree / 'rust' / ('boson_quiche_build.lib' if target.startswith('windows-')
                                         else 'libboson_quiche_build.a')
        archive.write_bytes(b'static archive')
        native = work / 'install' / 'native' / spec.classifier
        native.mkdir(parents=True, exist_ok=True)
        (native / spec.binary).write_bytes(b'JNI library')
        if test_natives:
            (work / 'install/test-libraries').mkdir(parents=True, exist_ok=True)
            (work / 'install/test-libraries/libloader_abi.so').write_bytes(b'loader fixture')
        (work / 'licenses').mkdir(exist_ok=True)
        (work / 'licenses/LICENSE').write_text('fixture notice')
        (work / 'link-support').mkdir(exist_ok=True)
        (work / 'cargo.log').write_text('build diagnostics')
        (work / 'archive-symbols.txt').write_text('archive symbols')
        (work / 'proof.json').write_text(json.dumps({'archive': str(archive), 'status': 'passed'}))

    def inside(self, target='linux-arm64', stage='jni', test_natives=True):
        build.build_in_container(target, stage, {}, test_natives, self.destination,
                                 self.root / 'source', self.cache)

    def test_incremental_work_survives_deleted_host_exports(self):
        with patch.object(build, 'configure_build_install', side_effect=self.fake_build) as run:
            self.inside()
            work = run.call_args.args[2]
            (work / 'cmake/incremental-marker').write_text('cached objects')
            # Simulate deleting host build outputs while retaining the Docker volume.
            shutil.rmtree(self.destination)
            self.destination.mkdir()
            (self.destination / 'inputs.json').write_text(json.dumps(self.inputs))
            self.inside()
        self.assertEqual(run.call_args.args[2], work)
        self.assertTrue((work / 'cmake/incremental-marker').is_file())
        self.assertTrue((work / 'cmake/CMakeCache.txt').is_file())
        self.assertFalse((self.destination / 'rust').exists())
        self.assertFalse((self.destination / 'cmake').exists())
        self.assertFalse((self.destination / 'driver').exists())
        self.assertFalse((self.destination / 'cmake/CMakeCache.txt').exists())
        self.assertEqual((self.destination / 'install/native/linux-aarch64/libboson_quiche.so').read_bytes(),
                         b'JNI library')
        self.assertTrue((self.destination / 'install/test-libraries/libloader_abi.so').is_file())
        self.assertTrue((self.destination / 'licenses/LICENSE').is_file())
        self.assertTrue((self.destination / 'cargo.log').is_file())
        proof = json.loads((self.destination / 'proof.json').read_text())
        self.assertTrue(Path(proof['archive']).is_file())

    def test_targets_and_changed_inputs_use_separate_work_directories(self):
        with patch.object(build, 'configure_build_install', side_effect=self.fake_build) as run:
            self.inside(stage='archive')
            first = run.call_args.args[2]
            self.inside(target='linux-amd64', stage='archive')
            second = run.call_args.args[2]
            (self.destination / 'inputs.json').write_text(json.dumps(dict(self.inputs, binding_abi=2)))
            self.inside(stage='archive')
            third = run.call_args.args[2]
        self.assertEqual(len({first, second, third}), 3)
        self.assertTrue(all(path.is_relative_to(self.cache) for path in (first, second, third)))

    def test_jni_failure_exports_diagnostics_without_a_success_proof(self):
        with patch.object(build, 'configure_build_install', side_effect=RuntimeError('link failed')):
            with self.assertRaisesRegex(RuntimeError, 'link failed'):
                self.inside()
        self.assertFalse((self.destination / 'proof.json').exists())

    def test_windows_exports_preserve_import_libraries_and_remove_old_fixtures(self):
        target = 'windows-arm64'
        self.inputs['platform'] = target
        (self.destination / 'inputs.json').write_text(json.dumps(self.inputs))
        with patch.object(build, 'configure_build_install', side_effect=self.fake_build) as run:
            self.inside(target=target)
            work = run.call_args.args[2]
            (work / 'link-support/windows.lib').write_bytes(b'import library')
            self.inside(target=target, test_natives=False)
        self.assertTrue((self.destination / 'boson_quiche_build.lib').is_file())
        self.assertTrue((self.destination / 'install/native/windows-aarch64/boson_quiche.dll').is_file())
        self.assertEqual((self.destination / 'link-support/windows.lib').read_bytes(), b'import library')
        self.assertFalse((self.destination / 'install/test-libraries').exists())

    def test_container_mounts_export_directory_and_named_volume(self):
        tools = {'image_id': 'sha256:test', 'image_arch': 'arm64'}
        (self.destination / 'proof.json').write_text('stale success')

        def execute(*command):
            self.assertFalse((self.destination / 'proof.json').exists())
            (self.destination / 'proof.json').write_text(json.dumps({'archive': '/output/fixture.a'}))
            (self.destination / 'toolchain-packages.txt').write_text('builder packages')

        with patch.object(build, 'execute', side_effect=execute) as run:
            build.run_container('windows-amd64', self.root / 'source', self.destination,
                                tools, 'jni', True)
        command = run.call_args.args
        self.assertIn('type=volume,source=boson-quiche-windows-cache-arm64,target=/cache', command)
        self.assertIn(f'type=bind,source={self.destination},target=/output', command)
        self.assertFalse(any('target=/work' in value or '.build/cache' in value for value in command))
        self.assertIn('--rm', command)
        self.assertIn('--test-natives', command)
        report = json.loads((self.destination / 'proof.json').read_text())
        self.assertEqual(report['archive'], str(self.destination / 'fixture.a'))
        self.assertEqual(report['os_packages_sha256'], config.digest(self.destination / 'toolchain-packages.txt'))

    def test_fixture_cmake_work_stays_in_the_matching_volume(self):
        pins = json.loads((config.ROOT / 'native/toolchains.json').read_text())
        for target in ('linux-amd64', 'windows-amd64', 'windows-arm64'):
            with self.subTest(target=target):
                arch = 'amd64' if target == 'linux-amd64' else 'arm64'
                manifest = {'binding_version': '0.30.1.1-SNAPSHOT', 'binding_abi': 1,
                            'inputs': {'builder': {'image_arch': arch, 'image_id': 'sha256:test'}}}
                with patch.object(runtime, 'run') as run:
                    runtime.loader_fixtures(target, self.destination, manifest)
                command = run.call_args.args
                self.assertIn('type=volume,source=' + config.docker_cache_volume(target, arch) + ',target=/cache', command)
                self.assertNotIn('/runtime/loader-build', command[-1])
                self.assertIn('/cache/loader-fixtures/' + target + '/', command[-1])
                self.assertIn('/runtime/test-libraries/', command[-1])
                if target.startswith('windows-'):
                    self.assertIn('/cache/xwin-llvm20-sdk' + pins['windows_sdk'], command[-1])


if __name__ == '__main__':
    unittest.main()
