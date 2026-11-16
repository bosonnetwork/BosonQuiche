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
"""Snapshot documentation from the pinned Rust sources for offline generation."""
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DOCS = r'(?P<docs>(?:[ \t]*///[^\n]*\n)+)(?:[ \t]*#\[[^\n]*\]\n|[ \t]*\n)*'
ITEM = re.compile(DOCS + r'[ \t]*(?:(?:pub(?:\([^)]*\))?|const|unsafe|async)\s+)*(?P<kind>fn|struct|enum)\s+(?P<name>\w+)', re.M)


def text(block):
    return '\n'.join(re.sub(r'^\s*/// ?', '', line) for line in block.splitlines()).strip()


def block_end(source, position):
    return re.search(r'^}', source[position:], re.M).end() + position


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='quiche 0.30.1 source root')
    args = parser.parse_args()
    base = args.source / 'quiche/src'
    if (args.source / 'quiche/include/quiche.h').read_bytes() != (ROOT / 'native/quiche.h').read_bytes():
        raise SystemExit('The supplied source does not match the pinned public header')
    paths = {'lib': 'lib.rs', 'h3': 'h3/mod.rs', 'packet': 'packet.rs',
             'path': 'path.rs', 'error': 'error.rs', 'recovery': 'recovery/mod.rs',
             'params': 'transport_params.rs'}
    snapshot = {'version': '0.30.1', 'source': 'https://github.com/cloudflare/quiche/tree/0.30.1',
                'notice': 'Documentation adapted from Cloudflare quiche under BSD-2-Clause; see NOTICE and META-INF/LICENSE-quiche.',
                'types': {}, 'functions': {}}
    for module, filename in paths.items():
        source = (base / filename).read_text()
        scopes = []
        for match in re.finditer(r'^impl(?:<[^\n]*>)? (?:Config|Connection)(?:<[^\n]*>)? \{', source, re.M):
            owner = 'Config' if re.search(r'\bConfig\b', match[0]) else 'Connection'
            scopes.append((match.start(), block_end(source, match.start()), module + '.' + owner))
        for match in ITEM.finditer(source):
            name, kind = match['name'], match['kind']
            doc = {'text': text(match['docs']), 'source': filename,
                   'line': source.count('\n', 0, match.start()) + 1}
            if kind == 'fn':
                owner = next((owner for start, end, owner in scopes if start < match.start() < end), None)
                if owner:
                    snapshot['types'].setdefault(owner, {}).setdefault('methods', {})[name] = doc
                elif match.start() < source.find('#[cfg(test)]') or '#[cfg(test)]' not in source:
                    snapshot['functions'][module + '.' + name] = doc
            else:
                key = module + '.' + name
                record = snapshot['types'].setdefault(key, {})
                record.update(doc)
                end = block_end(source, match.end())
                contents = source[match.end():end]
                # Fields/variants start at four spaces. Nested enum fields are
                # excluded; callback payloads are described in the Java layer.
                members = {}
                pattern = re.compile(DOCS + r'    (?:(?:pub(?:\([^)]*\))?)\s+)?(?P<name>\w+)(?:\s*[:(=,]|\s*\{)', re.M)
                for member in pattern.finditer(contents):
                    members[member['name']] = text(member['docs'])
                record['variants' if kind == 'enum' else 'fields'] = members
    output = ROOT / 'native/api-docs.json'
    output.write_text(json.dumps(snapshot, ensure_ascii=True, indent=2) + '\n', encoding='ascii')
    print('Imported documentation for', len(snapshot['types']), 'types and',
          sum(len(item.get('methods', {})) for item in snapshot['types'].values()), 'methods')


if __name__ == '__main__':
    main()
