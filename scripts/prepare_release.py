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

"""Prepare an immutable unsigned release from matching prebuilt artifacts."""

import argparse
import json
from pathlib import Path
import sys

import release_support as release
import buildlog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument(
        '--validation', type=Path, default=release.ROOT / '.build/validation/build.json'
    )
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    release.release_version(args.version)
    record = json.loads(args.validation.read_text())
    output = (args.output or release.ROOT / '.build/releases' / args.version).resolve()
    result = release.freeze(args.version, record, output)
    buildlog.done('frozen release -> ' + buildlog.rel(output))
    qualification = result['qualification']
    if qualification['complete']:
        buildlog.done('publication qualification: complete')
    else:
        buildlog.warn(
            'publication qualification incomplete: ' + ', '.join(qualification['missing'])
        )


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        buildlog.fail('release preparation failed: ' + str(error))
        sys.exit(1)
