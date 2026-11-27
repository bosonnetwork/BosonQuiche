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

"""Keep the host classifier out of cross-platform runtime classpaths."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_runtime as runtime


class RuntimeClasspathTest(unittest.TestCase):
    def test_selected_target_replaces_the_host_classifier(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api = root / 'api/target/classes'
            (api / 'io/bosonnetwork/quiche').mkdir(parents=True)
            (api / 'io/bosonnetwork/quiche/Native.class').write_bytes(b'API fixture')
            tests = root / 'api/target/test-classes'
            (tests / 'io/bosonnetwork/quiche').mkdir(parents=True)
            (tests / 'io/bosonnetwork/quiche/NativeSuite.class').write_bytes(b'suite fixture')
            host_jar = root / 'repo/boson-quiche-native-1-macos-aarch64.jar'
            junit_jar = root / 'repo/junit-jupiter-api-5.jar'
            for jar in (host_jar, junit_jar):
                jar.parent.mkdir(parents=True, exist_ok=True)
                jar.write_bytes(b'jar fixture')
            staged = root / '.build/staged/linux-arm64/jni'
            staged.mkdir(parents=True)
            (staged / 'libboson_quiche.so').write_bytes(b'Linux fixture')
            (root / 'api/target/test-classpath.txt').write_text(
                os.pathsep.join(map(str, (host_jar, junit_jar))))
            with patch.object(runtime, 'ROOT', root), \
                    patch.object(runtime.build, 'validate_manifest', return_value={}):
                work, _, entries = runtime.prepare('linux-arm64')
            self.assertEqual('target-native', entries[-1])
            native = work / 'target-native/native/linux-aarch64/libboson_quiche.so'
            self.assertEqual(b'Linux fixture', native.read_bytes())
            # The host classifier jar is dropped; the remaining dependency keeps
            # its index, so the skipped one is visible in the gap.
            self.assertEqual(['api-classes', 'api-test-classes', 'dependency-1.jar', 'target-native'],
                             entries)
            self.assertEqual(b'API fixture',
                             (work / 'api-classes/io/bosonnetwork/quiche/Native.class').read_bytes())
            self.assertEqual(b'suite fixture',
                             (work / 'api-test-classes/io/bosonnetwork/quiche/NativeSuite.class').read_bytes())


class AndroidCaseCountTest(unittest.TestCase):
    def test_measured_case_count_is_read_from_the_device_output(self):
        output = 'Passed some cases\nAndroid JNI cases: 30\n'
        self.assertEqual(30, runtime.android_cases(output))

    def test_missing_case_count_is_rejected(self):
        with self.assertRaises(ValueError):
            runtime.android_cases('no report here')


if __name__ == '__main__':
    unittest.main()
