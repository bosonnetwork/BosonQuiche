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

"""Verify a prepared release before signing or Central publication."""

import argparse
import os
import shlex
from pathlib import Path
import sys

import release_support as release


def check_maven_cli():
    arguments = os.environ.get('MAVEN_CMD_LINE_ARGS')
    release.require(
        arguments is not None,
        'Run signing/publication with the Maven command-line launcher',
    )
    for token in shlex.split(arguments):
        release.require(
            not token.startswith(('-pl', '-rf', '--projects', '--resume-from'))
            and token not in ('-N', '--non-recursive', '-f', '--file')
            and not token.startswith(('--file=', '-f=')),
            'Signing/publication requires the complete four-module reactor from the repository root; do not use -pl, -N, -rf or -f',
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--publication', action='store_true')
    parser.add_argument('--maven-cli', action='store_true')
    parser.add_argument('--built-module', choices=release.MODULES)
    parser.add_argument('--flag', action='append', default=[])
    args = parser.parse_args()
    release.release_version(release.config.validate_inputs())
    if args.maven_cli:
        check_maven_cli()
        release.require(
            args.directory.is_absolute(), 'Use an absolute release.directory path'
        )
    for flag in args.flag:
        name, _, value = flag.partition('=')
        release.require(
            value.lower() not in ('true', 'yes', '1'),
            'Required release validation/signing cannot be skipped: ' + name,
        )
    record = release.verify(args.directory.resolve(), args.publication)
    if args.built_module:
        release.verify_built(record, args.built_module)
        print('Maven outputs match prepared checksums:', args.built_module)
    print('Verified frozen release:', record['binding_version'])


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        print('Release verification failed:', error, file=sys.stderr)
        sys.exit(1)
