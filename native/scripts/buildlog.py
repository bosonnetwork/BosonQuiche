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

"""Console output that reads like a build log instead of a data dump."""

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
_COLOUR = sys.stdout.isatty() and 'NO_COLOR' not in os.environ


def _paint(text, code):
    return '\033[' + code + 'm' + text + '\033[0m' if _COLOUR else text


def rel(path):
    """Show project paths relative to the repository root."""
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except (ValueError, OSError):
        return str(path)


def step(message):
    print()
    print(_paint('==> ', '1') + message, flush=True)


def info(message):
    print('    ' + message, flush=True)


def done(message=''):
    print(_paint('  ok', '32') + ('  ' + message if message else ''), flush=True)


def warn(message):
    print(_paint('  !', '33') + '  ' + message, file=sys.stderr, flush=True)


def fail(message):
    print(_paint('  x', '31') + '  ' + message, file=sys.stderr, flush=True)


def command(argv):
    """Show a command line with project-relative paths."""
    parts = []
    for item in argv:
        text = str(item)
        parts.append(rel(text) if os.sep in text or '/' in text else text)
    print('    $ ' + ' '.join(parts), flush=True)


def tail(path, lines=20):
    """Echo the end of a log file to stderr, if one exists."""
    try:
        text = Path(path).read_text(errors='replace').splitlines()
    except OSError:
        return
    for line in text[-lines:]:
        print('    | ' + line, file=sys.stderr, flush=True)


def table(rows, indent='  '):
    """Print aligned rows; each row is a tuple of cells of equal length."""
    widths = []
    for row in rows:
        for index, cell in enumerate(row):
            width = len(str(cell))
            if index < len(widths):
                widths[index] = max(widths[index], width)
            else:
                widths.append(width)
    for row in rows:
        cells = [str(cell).ljust(widths[index]) for index, cell in enumerate(row)]
        print(indent + '  '.join(cells).rstrip())
