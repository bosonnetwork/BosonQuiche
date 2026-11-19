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

"""Exercise normal Maven packaging/signing with a synthetic native test fixture."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

import verify_bundle
import release_support as release

sys.path.insert(0, str(Path(__file__).resolve().parent / 'tests'))
import release_fixtures


def prepare_fixture(root, work, maven, cache):
    """Compile the real Java API, with one packaging test and synthetic JNI inputs."""
    validation = release_fixtures.create(root)
    # Central's publish goal requires Maven online mode even with skipUpload.
    # A file-only mirror keeps this test local and uses no credential settings.
    settings = ET.Element('settings', xmlns='http://maven.apache.org/SETTINGS/1.2.0')
    mirror = ET.SubElement(ET.SubElement(settings, 'mirrors'), 'mirror')
    ET.SubElement(mirror, 'id').text = 'central'
    ET.SubElement(mirror, 'mirrorOf').text = '*'
    ET.SubElement(mirror, 'url').text = cache.resolve().as_uri()
    ET.ElementTree(settings).write(
        root / '.mvn/settings.xml', encoding='UTF-8', xml_declaration=True
    )
    # Synthetic libraries cannot run JNI tests. Limit this isolated fixture to
    # packaging; real JNI/runtime qualification is required for publication.
    pom = root / 'api/pom.xml'
    contents = pom.read_text()
    start = contents.index(
        '                    <execution>\n                        <id>native-library</id>'
    )
    end = contents.index('                    </execution>\n', start) + len(
        '                    </execution>\n'
    )
    pom.write_text(contents[:start] + contents[end:])
    tests = root / 'api/src/test/java'
    shutil.rmtree(tests)
    tests.mkdir()
    (tests / 'PackagingTest.java').write_text(
        (root / 'native/copyright-header.txt').read_text()
        + '''
package io.bosonnetwork.quiche;

import java.io.IOException;
import java.io.InputStream;
import java.util.Properties;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

class PackagingTest {
    @Test
    void readsBindingMetadata() throws IOException {
        Properties properties = new Properties();
        try (InputStream input = getClass().getResourceAsStream("/META-INF/boson-quiche.properties")) {
            assertNotNull(input);
            properties.load(input);
        }

        assertEquals("0.30.1.1", properties.getProperty("binding.version"));
        assertEquals("1", properties.getProperty("binding.abi"));
    }
}
'''
    )
    with (work / 'maven-package.log').open('w') as log:
        subprocess.run(
            [
                maven,
                '-o',
                '-Dmaven.repo.local=' + str(cache.resolve()),
                '-s',
                str(root / '.mvn/settings.xml'),
                '-Pdistribution',
                'clean',
                'verify',
            ],
            cwd=root,
            env=dict(os.environ, MAVEN_SKIP_RC='1', MAVEN_BASEDIR=str(root)),
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )
    validation['source_fingerprint'] = release.source_fingerprint(root)
    validation['artifacts'] = release.hashes(
        release.artifact_paths(release_fixtures.VERSION, root)
    )
    return validation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--output', type=Path, default=release.ROOT / '.build/release-workflow-test'
    )
    parser.add_argument('--maven', default='mvn', help='Maven 3.9.2+ executable')
    parser.add_argument(
        '--maven-cache',
        type=Path,
        default=Path.home() / '.m2/repository',
        help='Public dependency cache; synthetic artifacts are never installed there',
    )
    args = parser.parse_args()
    executable = shutil.which(args.maven)
    release.require(executable is not None, 'Maven executable was not found')
    args.maven = str(Path(executable).resolve())
    work = args.output.resolve()
    release.require(not work.exists(), 'Choose a new disposable test output directory')
    root = work / 'synthetic-project'
    root.mkdir(parents=True)
    validation = prepare_fixture(root, work, args.maven, args.maven_cache)
    directory = work / 'unsigned'
    release.freeze(release_fixtures.VERSION, validation, directory, root)
    before = (directory / 'SHA256SUMS').read_bytes()
    settings = root / '.mvn/settings.xml'
    with tempfile.TemporaryDirectory(prefix='bq-gpg-') as home:
        os.chmod(home, 0o700)
        env = dict(
            os.environ, GNUPGHOME=home, MAVEN_SKIP_RC='1', MAVEN_BASEDIR=str(root)
        )
        env.pop('GPG_AGENT_INFO', None)
        try:
            command = ['gpg', '--no-options', '--homedir', home]
            subprocess.run(
                command
                + [
                    '--batch',
                    '--pinentry-mode',
                    'loopback',
                    '--passphrase',
                    '',
                    '--quick-generate-key',
                    'BosonQuiche Synthetic Test <fixture@example.invalid>',
                    'rsa2048',
                    'sign',
                    '1d',
                ],
                env=env,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            keys = subprocess.check_output(
                command + ['--with-colons', '--list-keys'],
                env=env,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            fingerprint = next(
                line.split(':')[9]
                for line in keys.splitlines()
                if line.startswith('fpr:')
            )
            keyring = work / 'test-public-key.gpg'
            with keyring.open('wb') as output:
                subprocess.run(
                    command + ['--export', fingerprint],
                    env=env,
                    stdout=output,
                    check=True,
                )
            maven = [
                args.maven,
                '-nsu',
                '-Dmaven.repo.local=' + str(args.maven_cache.resolve()),
                '-Dmaven.install.skip=true',
                '-s',
                str(settings),
                '-Drelease.directory=' + str(directory),
                '-Dgpg.homedir=' + home,
                '-Dgpg.keyname=' + fingerprint,
                '-DcentralBaseUrl=http://127.0.0.1:9',
            ]
            with (work / 'maven-sign.log').open('w') as log:
                subprocess.run(
                    maven + ['-Prelease-bundle', 'clean', 'deploy'],
                    cwd=root,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=True,
                )
            release.require(
                (
                    root / 'api/target/classes/io/bosonnetwork/quiche/Native.class'
                ).read_bytes()[:4]
                == b'\xca\xfe\xba\xbe',
                'Normal signing did not compile the Java API',
            )
            reports = list((root / 'api/target/surefire-reports').glob('TEST-*.xml'))
            release.require(
                len(reports) == 1
                and ET.parse(reports[0]).getroot().get('tests') == '1',
                'Normal signing did not run the fixture packaging test',
            )
            record = release.verify(directory, root=root)
            for module in release.MODULES:
                release.verify_built(record, module, root)
            log_text = (work / 'maven-sign.log').read_text()
            release.require(
                '(skipUpload)' in log_text,
                'Central did not confirm that upload was skipped',
            )
            for module in release.MODULES:
                check = 'run (verify-release-artifacts) @ ' + module + ' ---'
                sign = 'sign (sign-artifacts) @ ' + module + ' ---'
                release.require(
                    check in log_text and log_text.index(check) < log_text.index(sign),
                    'Checksum check did not precede signing: ' + module,
                )
                release.require(
                    'run (verify-release-before-install) @ ' + module + ' ---'
                    in log_text,
                    'Pre-deployment checksum check did not run: ' + module,
                )
            release.require(
                (directory / 'SHA256SUMS').read_bytes() == before,
                'Signing changed the frozen release',
            )
            bundle = root / 'target/central-publishing/central-bundle.zip'
            result = verify_bundle.freeze(
                directory, bundle, keyring, work / 'signed', root
            )
            with zipfile.ZipFile(work / 'signed/central-bundle.zip') as archive:
                names = archive.namelist()
                release.require(
                    sum(name.endswith('.asc') for name in names) == 15,
                    'Missing signed artifacts in Central bundle',
                )
                for name, checksum in result['artifact_sha256'].items():
                    release.require(
                        hashlib.sha256(archive.read(name)).hexdigest() == checksum,
                        'Bundling changed a frozen artifact',
                    )
                    for suffix in ('.md5', '.sha1', '.sha256', '.sha512'):
                        release.require(
                            name + suffix in names, 'Missing Central checksum'
                        )
                original = {name: archive.read(name) for name in names}
            first = next(iter(record['files']))
            for label, changed_name, data, expected in (
                ('body', first, b'changed body', 'differs from prepared release'),
                ('checksum', first + '.md5', b'0' * 32, 'Invalid Central checksum'),
                (
                    'signature',
                    first + '.asc',
                    b'invalid signature',
                    'Invalid detached signature',
                ),
            ):
                changed = dict(original)
                changed[changed_name] = data
                # Keep optional signature sidecars valid so this case tests GPG.
                if label == 'signature':
                    for algorithm in ('md5', 'sha1', 'sha256', 'sha512'):
                        sidecar = changed_name + '.' + algorithm
                        if sidecar in changed:
                            changed[sidecar] = (
                                hashlib.new(algorithm, data).hexdigest().encode('ascii')
                            )
                damaged = work / ('invalid-' + label + '.zip')
                damaged.write_bytes(release_fixtures.zip_bytes(changed))
                try:
                    verify_bundle.verify(directory, damaged, keyring, root)
                except ValueError as error:
                    release.require(
                        expected in str(error),
                        'Unexpected corruption rejection: ' + label,
                    )
                else:
                    raise ValueError('Corrupt Central bundle was accepted: ' + label)
            for label, extra, expected in (
                (
                    'fixture-publication',
                    ['-Ppublish', 'validate'],
                    'qualification is incomplete',
                ),
                ('skip-rejection', ['-DskipTests', 'verify'], 'cannot be skipped'),
                (
                    'partial-reactor',
                    ['-pl', 'api', '-am', 'verify'],
                    'complete four-module reactor',
                ),
            ):
                rejected = subprocess.run(
                    maven + extra,
                    cwd=root,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                (work / (label + '.log')).write_text(rejected.stdout)
                release.require(
                    rejected.returncode != 0 and expected in rejected.stdout,
                    'Expected fail-closed rejection: ' + label,
                )
            artifact = (
                root
                / 'api/target'
                / ('boson-quiche-' + release_fixtures.VERSION + '.jar')
            )
            original = artifact.read_bytes()
            artifact.write_bytes(original + b'changed after packaging')
            try:
                for guard in (
                    'verify-release-artifacts',
                    'verify-release-before-install',
                ):
                    rejected = subprocess.run(
                        maven + ['antrun:run@' + guard],
                        cwd=root,
                        env=env,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                    )
                    (work / ('changed-output-' + guard + '.log')).write_text(
                        rejected.stdout
                    )
                    release.require(
                        rejected.returncode != 0
                        and 'Maven output differs from the prepared release'
                        in rejected.stdout,
                        'Changed Maven output was not rejected by ' + guard,
                    )
            finally:
                artifact.write_bytes(original)
            release.write_json(
                work / 'result.json',
                {
                    'status': 'passed',
                    'synthetic_fixture': True,
                    'signed_artifacts': 15,
                    'normal_maven_packaging': True,
                    'central_bundle_producer': 'central-publishing-maven-plugin:0.12.0',
                    'packaging_tests': 1,
                    'changed_output_rejected': True,
                    'corrupt_bundle_rejected': True,
                    'local_install_skipped': True,
                    'central_upload_attempted': False,
                    'real_signing_key_used': False,
                    'signing_fingerprint': fingerprint,
                },
            )
            print(
                'Standard Maven packaging/signing, 15 signatures, offline Central bundle and rejection checks: PASS'
            )
            print(
                'Synthetic fixture only; no real release was built or uploaded. Evidence:',
                work,
            )
        finally:
            subprocess.run(
                ['gpgconf', '--homedir', home, '--kill', 'gpg-agent'],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )


if __name__ == '__main__':
    main()
