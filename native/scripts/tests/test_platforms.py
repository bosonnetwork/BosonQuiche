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

"""Cross-layer checks for the single platform matrix."""

import json
from pathlib import Path
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_config as config

ROOT = Path(config.ROOT)
NS = {'m': 'http://maven.apache.org/POM/4.0.0'}
DESKTOP = sorted(spec.classifier for spec in config.TARGETS.values() if spec.jni != 'android')
# Only these platforms can run a JVM build host; Windows remains a cross target.
HOSTS = ['linux-aarch64', 'linux-x86_64', 'macos-aarch64']


class PlatformMatrixTest(unittest.TestCase):
    def test_matrix_is_internally_consistent(self):
        classifiers = {spec.classifier for spec in config.TARGETS.values()}
        triples = {spec.rust for spec in config.TARGETS.values()}
        self.assertEqual(len(classifiers), len(config.TARGETS))
        self.assertEqual(len(triples), len(config.TARGETS))
        for spec in config.TARGETS.values():
            self.assertEqual(spec.android_abi is not None, spec.jni == 'android', spec.platform)

    def test_maven_packages_every_desktop_classifier(self):
        pom = ET.parse(ROOT / 'native/pom.xml').getroot()
        classifiers = {
            element.text
            for element in pom.findall('m:build/m:plugins/m:plugin/m:executions/m:execution/m:configuration/m:classifier', NS)
        }
        self.assertEqual(set(DESKTOP), classifiers)

    def test_api_tests_consume_every_host_classifier(self):
        pom = ET.parse(ROOT / 'api/pom.xml').getroot()
        classifiers = {
            element.text
            for element in pom.findall('m:profiles/m:profile/m:dependencies/m:dependency/m:classifier', NS)
        }
        self.assertEqual(set(HOSTS), classifiers)

    def test_native_host_profiles_match_the_matrix(self):
        pom = ET.parse(ROOT / 'native/pom.xml').getroot()
        classifiers = {}
        for profile in pom.findall('m:profiles/m:profile', NS):
            classifier = profile.findtext('m:properties/m:native.classifier', namespaces=NS)
            if classifier:
                classifiers[profile.findtext('m:id', namespaces=NS)] = classifier
        self.assertEqual(set(HOSTS), set(classifiers.values()))

    def test_cmake_presets_match_the_matrix(self):
        presets = json.loads((ROOT / 'native/CMakePresets.json').read_text())
        seen = {}
        for preset in presets['configurePresets']:
            variables = preset.get('cacheVariables', {})
            if 'BOSON_TARGET' not in variables:
                continue
            spec = config.TARGETS[variables['BOSON_TARGET']]
            self.assertEqual(spec.classifier, variables['BOSON_CLASSIFIER'], preset['name'])
            self.assertEqual(spec.rust, variables['RUST_TARGET'], preset['name'])
            self.assertEqual(spec.jni, variables['BOSON_JNI_PLATFORM'], preset['name'])
            if 'condition' in preset:
                self.assertEqual('host-' + spec.platform, preset['name'])
            seen[preset['name']] = spec.classifier
        self.assertEqual(set(HOSTS), {classifier for name, classifier in seen.items()
                                      if name.startswith('host-')})
        for target in config.TARGETS:
            expected = 'host-' + target if target in ('macos-arm64', 'linux-amd64', 'linux-arm64') else target
            self.assertIn(expected, seen)

    def test_android_toolchain_pins_the_api_that_toolchains_json_declares(self):
        pins = json.loads((ROOT / 'native/toolchains.json').read_text())
        toolchain = (ROOT / 'native/cmake/toolchains/android-arm64.cmake').read_text()
        self.assertIn('ANDROID_NDK_HOME', toolchain)
        # boring-sys re-enters CMake with only this file, so the API level and
        # the ABI must be defined here rather than in the preset cache.
        self.assertIn('android-' + str(pins['android']['api']), toolchain)
        self.assertIn('arm64-v8a', toolchain)
        self.assertIn('c++_static', toolchain)

    def test_generated_sources_match_the_pinned_header(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/generate_api.py'), '--check'],
                                capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == '__main__':
    unittest.main()
