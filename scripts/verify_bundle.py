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

"""Verify a Maven-generated Central bundle against the prepared release."""

import argparse
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

import release_support as release
from release_support import ROOT, config


def verify(directory, archive, keyring, root=ROOT):
    record = release.verify(directory, root=root)
    release.require(
        keyring.is_file(), 'An explicit exported public keyring is required'
    )
    algorithms = ('md5', 'sha1', 'sha256', 'sha512')
    fingerprints = set()
    with zipfile.ZipFile(archive) as bundle, tempfile.TemporaryDirectory(
        prefix='bq-gpgv-'
    ) as home:
        entries = [item.filename for item in bundle.infolist() if not item.is_dir()]
        release.require(
            len(entries) == len(set(entries)), 'Duplicate Central bundle entries'
        )
        expected = set(record['files'])
        expected.update(name + '.asc' for name in record['files'])
        expected.update(
            name + '.' + algorithm
            for name in record['files']
            for algorithm in algorithms
        )
        # Some plugin versions also checksum signatures. Verify any such sidecars.
        optional = {
            name + '.asc.' + algorithm
            for name in record['files']
            for algorithm in algorithms
        }
        release.require(
            expected <= set(entries) <= expected | optional,
            'Central bundle has missing or unexpected entries',
        )
        for name, checksum in record['files'].items():
            data = bundle.read(name)
            release.require(
                hashlib.sha256(data).hexdigest() == checksum,
                'Central bundle differs from prepared release: ' + name,
            )
            for body in (name, name + '.asc'):
                for algorithm in algorithms:
                    sidecar = body + '.' + algorithm
                    if sidecar in entries:
                        release.require(
                            bundle.read(sidecar).decode('ascii').strip()
                            == hashlib.new(algorithm, bundle.read(body)).hexdigest(),
                            'Invalid Central checksum: ' + sidecar,
                        )
            payload = Path(home) / 'artifact'
            signature = Path(home) / 'artifact.asc'
            payload.write_bytes(data)
            signature.write_bytes(bundle.read(name + '.asc'))
            checked = subprocess.run(
                [
                    'gpgv',
                    '--homedir',
                    home,
                    '--keyring',
                    str(keyring.resolve()),
                    '--status-fd',
                    '1',
                    str(signature),
                    str(payload),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            release.require(
                checked.returncode == 0, 'Invalid detached signature: ' + name
            )
            fingerprints.update(
                re.findall(r'\[GNUPG:\] VALIDSIG ([A-F0-9]+) ', checked.stdout)
            )
    release.require(len(fingerprints) == 1, 'Release must be signed by one signing key')
    return {
        'status': 'passed',
        'schema': 1,
        'binding_version': record['binding_version'],
        'signing_fingerprint': next(iter(fingerprints)),
        'signed_artifacts': len(record['files']),
        'qualification': record['qualification'],
        'unsigned_manifest_sha256': config.digest(directory / 'manifest.json'),
        'artifact_sha256': record['files'],
        'central_bundle_sha256': config.digest(archive),
    }


def freeze(directory, archive, keyring, output, root=ROOT):
    """Preserve an already verified Maven ZIP without regenerating its contents."""
    record = verify(directory, archive, keyring, root)
    release.require(not output.exists(), 'Signed release directory already exists')
    temporary = output.with_name(output.name + '.assembling')
    release.require(
        not temporary.exists(), 'Signed release assembly directory already exists'
    )
    temporary.mkdir(parents=True)
    try:
        shutil.copyfile(archive, temporary / 'central-bundle.zip')
        release.require(
            config.digest(temporary / 'central-bundle.zip')
            == record['central_bundle_sha256'],
            'Maven bundle changed while being preserved',
        )
        release.write_json(temporary / 'manifest.json', record)
        (temporary / 'SHA256SUMS').write_text(
            release.checksum_text(
                {
                    name: config.digest(temporary / name)
                    for name in ('central-bundle.zip', 'manifest.json')
                }
            ),
            encoding='ascii',
        )
        temporary.rename(output)
        for file in output.iterdir():
            file.chmod(0o444)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument(
        '--bundle',
        type=Path,
        default=ROOT / 'target/central-publishing/central-bundle.zip',
    )
    parser.add_argument(
        '--keyring',
        type=Path,
        required=True,
        help='Explicit exported public keyring, never a private key',
    )
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or args.directory.with_name(args.directory.name + '-signed')
    record = freeze(
        args.directory.resolve(),
        args.bundle.resolve(),
        args.keyring.resolve(),
        output.resolve(),
    )
    print('Verified Maven Central bundle:', output / 'central-bundle.zip')
    print('Publication qualification:', record['qualification'])


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        print('Central bundle verification failed:', error, file=sys.stderr)
        sys.exit(1)
