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

"""Check full-build recovery after disposable toolchain caches are removed."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_all as build


class FullBuildTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.logs = self.root / 'logs'
        self.logs.mkdir()
        (self.root / 'native').mkdir()
        self.pins = {'android': {'directory': 'android-ndk-test', 'revision': '30.0.123'}}
        (self.root / 'native/toolchains.json').write_text(json.dumps(self.pins))
        self.ndk = self.root / '.build/toolchains/android-ndk-test'
        for target, name in ((build, 'ROOT'), (build.toolchains, 'ROOT')):
            change = patch.object(target, name, self.root)
            change.start()
            self.addCleanup(change.stop)
        environment = patch.dict(os.environ, {'ANDROID_NDK_HOME': ''})
        environment.start()
        self.addCleanup(environment.stop)

    def install(self, directory=None, revision='30.0.123'):
        directory = directory or self.ndk
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'source.properties').write_text('Pkg.Revision = ' + revision + '\n')

    def test_deleted_cache_is_restored_before_the_build(self):
        def fetch(command, log):
            self.assertIn('--fetch-ndk', command)
            self.install()

        with patch.object(build, 'run', side_effect=fetch) as setup:
            build.prepare_android_ndk(['linux-amd64', 'android-arm64'], False, self.logs)
        setup.assert_called_once()
        self.assertTrue((self.ndk / 'source.properties').is_file())

    def test_installed_ndk_does_not_require_a_download(self):
        self.install()
        with patch.object(build, 'run') as setup:
            build.prepare_android_ndk(['android-arm64'], False, self.logs)
        setup.assert_not_called()

    def test_external_ndk_is_used_without_creating_a_project_cache(self):
        external = self.root / 'external-ndk'
        self.install(external)
        with patch.dict(os.environ, {'ANDROID_NDK_HOME': str(external)}), \
                patch.object(build, 'run') as setup:
            build.prepare_android_ndk(['android-arm64'], False, self.logs)
        setup.assert_not_called()
        self.assertFalse(self.ndk.exists())

    def test_missing_external_ndk_is_rejected_without_fallback(self):
        with patch.dict(os.environ, {'ANDROID_NDK_HOME': str(self.root / 'missing')}), \
                patch.object(build, 'run') as setup:
            with self.assertRaisesRegex(ValueError, 'Missing Android NDK metadata'):
                build.prepare_android_ndk(['android-arm64'], False, self.logs)
        setup.assert_not_called()

    def test_wrong_revision_is_rejected_without_replacing_the_ndk(self):
        self.install(revision='29.0.0')
        with patch.object(build, 'run') as setup:
            with self.assertRaisesRegex(ValueError, 'NDK revision differs'):
                build.prepare_android_ndk(['android-arm64'], False, self.logs)
        setup.assert_not_called()
        self.assertIn('29.0.0', (self.ndk / 'source.properties').read_text())

    def test_prebuilt_and_non_android_builds_need_no_ndk(self):
        with patch.object(build, 'run') as setup:
            build.prepare_android_ndk(['android-arm64'], True, self.logs)
            build.prepare_android_ndk(['macos-arm64', 'linux-arm64'], False, self.logs)
        setup.assert_not_called()

    def test_failed_command_displays_the_log_and_original_error(self):
        log = self.logs / 'failed.log'
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(subprocess.CalledProcessError):
                build.run([sys.executable, '-c',
                           'import sys; print("missing pinned NDK"); sys.exit(1)'], log)
        self.assertIn(str(log), stderr.getvalue())
        self.assertIn('missing pinned NDK', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
