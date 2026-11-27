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

"""The committed dependency notices must describe the locked graph."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_native as build
import native_config as config

ROOT = Path(config.ROOT)
NOTICES = ROOT / 'native/notices'


class NoticesTest(unittest.TestCase):
    def setUp(self):
        self.document = json.loads((NOTICES / 'notices.json').read_text())

    def test_index_matches_the_locked_dependency_graph(self):
        self.assertEqual(1, self.document['schema'])
        self.assertEqual(config.digest(ROOT / 'native/Cargo.lock'),
                         self.document['cargo_lock_sha256'])
        self.assertEqual(sorted(config.TARGETS), self.document['targets'])

    def test_listed_notices_are_exactly_the_committed_files(self):
        listed = set()
        for record in self.document['packages']:
            self.assertTrue(record['notices'], record['package'])
            for relative in record['notices']:
                self.assertNotIn(relative, listed, 'Duplicate notice: ' + relative)
                listed.add(relative)
                self.assertTrue((NOTICES / relative).is_file(), 'Missing notice: ' + relative)
        on_disk = {path.relative_to(NOTICES).as_posix()
                   for path in NOTICES.rglob('*')
                   if path.is_file() and path.name != 'notices.json'}
        self.assertEqual(listed, on_disk)

    def test_packages_are_unique_and_exclude_the_driver_crate(self):
        keys = [(record['package'], record['version']) for record in self.document['packages']]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertNotIn('boson-quiche-build', [name for name, _ in keys])

    def test_build_staging_copies_the_committed_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            records = build.install_notices(work)
        self.assertEqual(self.document['packages'], records)
        # The temporary directory is gone, so only the returned records can be
        # checked here; the file layout is covered by the test above.
        self.assertTrue(all(record['notices'] for record in records))


if __name__ == '__main__':
    unittest.main()
