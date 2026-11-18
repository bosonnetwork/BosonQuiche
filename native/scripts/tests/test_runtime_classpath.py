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

"""Keep host-only test resources out of cross-platform runtime classpaths."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_runtime as runtime


class RuntimeClasspathTest(unittest.TestCase):
    def test_selected_native_is_injected_once_after_host_resources_are_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tests = root / 'api/target/test-classes'
            api = root / 'api/target/classes'
            (api / 'io/bosonnetwork/quiche').mkdir(parents=True)
            (api / 'io/bosonnetwork/quiche/Native.class').write_bytes(b'API fixture')
            (tests / 'native/macos-aarch64').mkdir(parents=True)
            (tests / 'native/macos-aarch64/libboson_quiche.dylib').write_bytes(b'host fixture')
            staged = root / '.build/staged/linux-arm64/jni'
            staged.mkdir(parents=True)
            (staged / 'libboson_quiche.so').write_bytes(b'Linux fixture')
            (root / 'api/target/test-classpath.txt').write_text(os.pathsep.join(map(str, (tests, api))))
            with patch.object(runtime, 'ROOT', root), patch.object(runtime.build, 'validate_manifest', return_value={}):
                work, _, entries = runtime.prepare('linux-arm64')
            self.assertFalse((work / entries[0] / 'native').exists())
            self.assertEqual(b'Linux fixture',
                (work / entries[1] / 'native/linux-aarch64/libboson_quiche.so').read_bytes())
            self.assertTrue((tests / 'native/macos-aarch64/libboson_quiche.dylib').exists())


if __name__ == '__main__':
    unittest.main()
