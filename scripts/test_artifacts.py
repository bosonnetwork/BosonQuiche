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

"""Check installed Maven artifacts, their native payloads and dependency boundaries."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'native/scripts'))
import native_config as config

NS = {'m': 'http://maven.apache.org/POM/4.0.0'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check(repository, root=config.ROOT):
    version = config.validate_inputs(root)
    base = repository / 'io/bosonnetwork'

    def artifact(name, suffix):
        return base / name / version / (name + '-' + version + suffix)

    def pom(name, packaging):
        model = ET.parse(artifact(name, '.pom')).getroot()
        require(model.findtext('m:packaging', 'jar', NS) == packaging, 'Wrong POM packaging: ' + name)
        if name != 'boson-quiche-parent':
            require(model.findtext('m:parent/m:artifactId', namespaces=NS) == 'boson-quiche-parent',
                    'Missing independent parent: ' + name)
            require(model.findtext('m:parent/m:version', namespaces=NS) == version, 'Wrong parent version: ' + name)
        return model

    parent = pom('boson-quiche-parent', 'pom')
    require(parent.find('m:parent', NS) is None, 'Parent must be independent of other projects')
    api = pom('boson-quiche', 'jar')
    for dependency in api.findall('m:dependencies/m:dependency', NS):
        require(dependency.findtext('m:scope', namespaces=NS) == 'test', 'API has a runtime dependency')
    require(not api.findall('.//m:profile/m:dependencies', NS), 'API selects runtime dependencies by profile')
    pom('boson-quiche-native', 'pom')
    android = pom('boson-quiche-android', 'aar')
    dependencies = android.findall('m:dependencies/m:dependency', NS)
    require(len(dependencies) == 1, 'Android POM must depend only on the API')
    dependency = dependencies[0]
    require(dependency.findtext('m:groupId', namespaces=NS) == 'io.bosonnetwork'
            and dependency.findtext('m:artifactId', namespaces=NS) == 'boson-quiche'
            and dependency.findtext('m:version', namespaces=NS) in (version, '${project.version}')
            and dependency.findtext('m:scope', 'compile', NS) == 'compile', 'Android API dependency mismatch')

    with zipfile.ZipFile(artifact('boson-quiche', '.jar')) as archive:
        names = archive.namelist()
        require('io/bosonnetwork/quiche/Native.class' in names, 'Missing API classes')
        require(not any(name.startswith('native/') or name.endswith(('.so', '.dylib', '.dll', '.pem'))
                        or 'test-libraries' in name for name in names), 'API contains native libraries or test fixtures')
        metadata = archive.read('META-INF/boson-quiche.properties').decode()
        properties = dict(line.split('=', 1) for line in metadata.splitlines()
                          if '=' in line and not line.startswith('#'))
        require(properties.get('binding.version') == version
                and properties.get('binding.abi') == str(config.binding_abi(root))
                and properties.get('quiche.version') == config.TAG,
                'API binding metadata mismatch')
    for suffix, required in (('-sources.jar', 'io/bosonnetwork/quiche/Quiche.java'),
                              ('-javadoc.jar', 'io/bosonnetwork/quiche/Quiche.html')):
        with zipfile.ZipFile(artifact('boson-quiche', suffix)) as archive:
            require(required in archive.namelist(), 'Missing API attachment content: ' + suffix)

    resources = set()
    libraries = {}

    def payload(archive, binary, manifest_name, target):
        manifest = json.loads(archive.read(manifest_name))
        require(manifest['binding_version'] == version and manifest['binding_abi'] == config.binding_abi(root)
                and manifest['quiche_version'] == config.TAG, 'Native version mismatch: ' + target)
        checksum = hashlib.sha256(archive.read(binary)).hexdigest()
        require(manifest['files'][config.TARGETS[target].binary] == checksum, 'Native payload changed: ' + target)
        libraries[target] = checksum

    for target, spec in config.TARGETS.items():
        if target.startswith('android-'):
            continue
        with zipfile.ZipFile(artifact('boson-quiche-native', '-' + spec.classifier + '.jar')) as archive:
            names = {item.filename for item in archive.infolist() if not item.is_dir()}
            payload_names = names - {'META-INF/MANIFEST.MF'}
            require(not resources.intersection(payload_names), 'Duplicate resources across desktop classifiers')
            resources.update(payload_names)
            native = 'native/' + spec.classifier + '/'
            notices = 'META-INF/boson-quiche-native/' + spec.classifier + '/'
            require(all(name.startswith((native, notices)) and not name.endswith('.class') for name in payload_names),
                    'Unexpected native JAR content: ' + target)
            require(notices + 'LICENSE' in names and notices + 'NOTICE' in names, 'Missing native notices')
            payload(archive, native + spec.binary, native + 'build.json', target)

    with zipfile.ZipFile(artifact('boson-quiche-android', '.aar')) as archive:
        require(not any(name.endswith('.class') or name.startswith('libs/') for name in archive.namelist()),
                'Android AAR duplicates API classes')
        with zipfile.ZipFile(io.BytesIO(archive.read('classes.jar'))) as classes:
            require(all(item.is_dir() or item.filename == 'META-INF/MANIFEST.MF'
                        for item in classes.infolist()), 'Android classes.jar must contain no classes or application resources')
        manifest = ET.fromstring(archive.read('AndroidManifest.xml'))
        minimum = manifest.find('uses-sdk').get('{http://schemas.android.com/apk/res/android}minSdkVersion')
        require(minimum == '33', 'Android minimum SDK mismatch')
        rules = archive.read('proguard.txt').decode()
        require('-keep class io.bosonnetwork.quiche.Native { *; }' in rules, 'Missing JNI consumer rules')
        prefix = 'META-INF/boson-quiche-native/android-aarch64/'
        require(prefix + 'LICENSE' in archive.namelist(), 'Missing Android notices')
        payload(archive, 'jni/arm64-v8a/libboson_quiche.so', prefix + 'build.json', 'android-arm64')

    for suffix in ('-sources.jar', '-javadoc.jar'):
        with zipfile.ZipFile(artifact('boson-quiche-android', suffix)) as companion:
            require('README.md' in companion.namelist(), 'Missing Android source/documentation pointer')

    return {'status': 'passed', 'binding_version': version, 'binding_abi': config.binding_abi(root),
            'desktop_classifier_resources_are_disjoint': True, 'native_payload_sha256': libraries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, required=True, help='Isolated Maven file repository')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    report = check(args.repository.resolve())
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n')
    print('Artifact boundaries, native checksums, POMs and API attachments: PASS')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, ET.ParseError, zipfile.BadZipFile) as error:
        print('Artifact verification failed:', error, file=sys.stderr)
        sys.exit(1)
