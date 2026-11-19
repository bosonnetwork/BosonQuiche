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

"""Shared, offline validation for frozen BosonQuiche release payloads."""

import json
from pathlib import Path
import re
import shutil
import struct
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'native/scripts'))
import native_config as config
import package_artifacts as packaging
import test_artifacts

ROOT = config.ROOT
NS = {'m': 'http://maven.apache.org/POM/4.0.0'}
MODULES = {
    'boson-quiche-parent': '.',
    'boson-quiche': 'api',
    'boson-quiche-native': 'native',
    'boson-quiche-android': 'android',
}
REQUIRED_CHECKS = ('python', 'host-jni', 'javadoc', 'artifacts')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def release_version(version):
    require(
        bool(re.fullmatch(r'\d+\.\d+\.\d+\.[1-9]\d*', version)),
        'Release version must be upstream.build (for example 0.30.1.1), without SNAPSHOT or qualifiers',
    )
    require(
        version.rsplit('.', 1)[0] == config.TAG,
        'Binding release must match the pinned upstream quiche version',
    )
    return version


def artifact_paths(version, root=ROOT):
    """Map each Maven repository path to the exact file produced by the reactor."""
    result = {}
    for artifact, module in MODULES.items():
        prefix = (
            'io/bosonnetwork/'
            + artifact
            + '/'
            + version
            + '/'
            + artifact
            + '-'
            + version
        )
        result[prefix + '.pom'] = root / module / 'pom.xml'
        output = root / module / 'target'
        suffixes = []
        if artifact == 'boson-quiche':
            suffixes = ['.jar', '-sources.jar', '-javadoc.jar']
        elif artifact == 'boson-quiche-native':
            suffixes = [
                '-' + spec.classifier + '.jar'
                for spec in config.TARGETS.values()
                if spec.jni != 'android'
            ]
        elif artifact == 'boson-quiche-android':
            suffixes = ['.aar', '-sources.jar', '-javadoc.jar']
        for suffix in suffixes:
            result[prefix + suffix] = output / (artifact + '-' + version + suffix)
    return result


def source_fingerprint(root=ROOT):
    files = [root / module / 'pom.xml' for module in MODULES.values()]
    for folder in (
        'api/src',
        'native/src',
        'android/src',
        'scripts',
        'native/scripts',
        'native/docker',
        'test-tooling',
    ):
        files.extend(
            path
            for path in (root / folder).rglob('*')
            if path.is_file()
            and not set(path.relative_to(root / folder).parts).intersection(
                ('__pycache__', 'target', 'build', '.gradle')
            )
            and path.suffix != '.pyc'
            and path.name not in ('.DS_Store', 'local.properties')
        )
    files.extend(
        root / 'native' / name
        for name in (
            'quiche.h',
            'quiche.json',
            'api-docs.json',
            'Cargo.lock',
            'CMakeLists.txt',
            'toolchains.json',
            'copyright-header.txt',
        )
    )
    return config.identity(
        {
            path.relative_to(root).as_posix(): config.digest(path)
            for path in sorted(set(files))
        }
    )


def validate_poms(version, root=ROOT):
    parent = ET.parse(root / 'pom.xml').getroot()
    require(
        parent.findtext('m:version', namespaces=NS) == version,
        'Set the Maven release version before building release inputs',
    )
    require(
        parent.findtext('m:groupId', namespaces=NS) == 'io.bosonnetwork',
        'Publication groupId must be io.bosonnetwork',
    )
    for artifact, module in MODULES.items():
        model = ET.parse(root / module / 'pom.xml').getroot()
        require(
            model.findtext('m:groupId', 'io.bosonnetwork', NS) == 'io.bosonnetwork'
            and model.findtext('m:version', version, NS) == version,
            'Mixed publication coordinates: ' + module,
        )
        expected_type = (
            'aar' if module == 'android' else ('jar' if module == 'api' else 'pom')
        )
        require(
            model.findtext('m:packaging', 'jar', NS) == expected_type,
            'Publication POM packaging mismatch: ' + module,
        )
        require(
            model.findtext('m:artifactId', namespaces=NS) == artifact,
            'Unexpected publication module: ' + module,
        )
        if module != '.':
            require(
                model.findtext('m:parent/m:groupId', namespaces=NS) == 'io.bosonnetwork'
                and model.findtext('m:parent/m:artifactId', namespaces=NS)
                == 'boson-quiche-parent',
                'Publication parent coordinate mismatch: ' + module,
            )
            require(
                model.findtext('m:parent/m:version', namespaces=NS) == version,
                'Mixed parent versions: ' + module,
            )
    for element in (
        'm:name',
        'm:description',
        'm:url',
        'm:licenses/m:license/m:name',
        'm:licenses/m:license/m:url',
        'm:developers/m:developer/m:name',
        'm:developers/m:developer/m:email',
        'm:scm/m:connection',
        'm:scm/m:url',
    ):
        require(
            bool(parent.findtext(element, namespaces=NS)),
            'Missing Central POM metadata: ' + element,
        )


def check_binary_baseline(binary, target):
    data = binary.read_bytes()
    if target.startswith('linux-'):
        versions = [
            tuple(map(int, value.decode().split('.')))
            for value in re.findall(rb'\bGLIBC_(\d+(?:\.\d+)+)', data)
        ]
        require(
            versions
            and max(value + (0,) * (3 - len(value)) for value in versions)
            <= (2, 28, 0),
            'Linux binary exceeds the glibc 2.28 baseline: ' + target,
        )
    elif target == 'android-arm64':
        offset = struct.unpack_from('<Q', data, 32)[0]
        size, count = struct.unpack_from('<HH', data, 54)
        require(
            size >= 56 and offset + size * count <= len(data),
            'Invalid Android ELF program headers',
        )
        loads = [
            struct.unpack_from('<IIQQQQQQ', data, offset + index * size)
            for index in range(count)
            if struct.unpack_from('<I', data, offset + index * size)[0] == 1
        ]
        require(
            loads
            and all(
                item[7] >= 16384 and item[2] % 16384 == item[3] % 16384
                for item in loads
            ),
            'Android native library is not aligned for 16 KB pages',
        )
    elif target == 'macos-arm64':
        offset = 32
        minimums = []
        for _ in range(struct.unpack_from('<I', data, 16)[0]):
            command, size = struct.unpack_from('<II', data, offset)
            require(
                size >= 8 and offset + size <= len(data), 'Invalid Mach-O load command'
            )
            if command == 0x32 and size >= 24:
                minimums.append(struct.unpack_from('<I', data, offset + 12)[0])
            elif command == 0x24 and size >= 16:
                minimums.append(struct.unpack_from('<I', data, offset + 8)[0])
            offset += size
        require(
            minimums and max(minimums) <= 0x000B0000,
            'Native library exceeds the macOS 11 baseline',
        )


def validate_natives(root=ROOT):
    version = config.validate_inputs(root)
    abi = config.binding_abi(root)
    declarations = (
        root / 'api/src/main/java/io/bosonnetwork/quiche/Native.java'
    ).read_text()
    exports = {'JNI_OnLoad', 'JNI_OnUnload'} | {
        'Java_io_bosonnetwork_quiche_Native_' + name
        for name in re.findall(r'static native \S+ (\w+)\(', declarations)
    }
    targets = {}
    for target, spec in config.TARGETS.items():
        directory, manifest = packaging.validate(target, root=root)
        require(
            set(manifest.get('jni_exports', [])) == exports,
            'JNI export inspection missing or stale: ' + target,
        )
        require(
            manifest['native'].get('status') == 'passed',
            'Native archive inspection failed: ' + target,
        )
        require(
            manifest['native'].get('source_archive_sha256') == config.ARCHIVE_SHA256,
            'Native archive pin mismatch: ' + target,
        )
        require(
            manifest['inputs'].get('android_abi')
            == ('arm64-v8a' if spec.jni == 'android' else None),
            'Android ABI mismatch: ' + target,
        )
        binary = directory / spec.binary
        require(
            (version + '\0').encode('ascii') in binary.read_bytes(),
            'Native binary has no matching binding version: ' + target,
        )
        check_binary_baseline(binary, target)
        targets[target] = {
            'native_sha256': config.digest(binary),
            'manifest_sha256': config.digest(directory / 'build.json'),
            'input_identity': manifest['input_identity'],
            'baseline': spec.baseline,
            'binding_version': version,
            'binding_abi': abi,
        }
    return targets


def hashes(paths):
    return {name: config.digest(path) for name, path in sorted(paths.items())}


def checked_validation(record, version, targets, artifacts, root=ROOT):
    require(
        record.get('scope') == 'distribution',
        'Release preparation requires complete distribution validation',
    )
    require(
        record.get('schema') == 1
        and record.get('binding_version') == version
        and record.get('binding_abi') == config.binding_abi(root),
        'Validation record version/ABI mismatch',
    )
    require(
        record.get('source_fingerprint') == source_fingerprint(root),
        'Validation record has stale source inputs',
    )
    require(
        record.get('artifacts') == artifacts,
        'Validation record does not match the packaged artifacts',
    )
    require(
        all(
            record.get('checks', {}).get(name, {}).get('status') == 'passed'
            for name in REQUIRED_CHECKS
        ),
        'Required build validation is missing, failed or skipped',
    )
    require(
        set(record.get('targets', {})) == set(config.TARGETS),
        'Validation record must describe all six targets',
    )
    missing = []
    for target, expected in targets.items():
        item = record['targets'][target]
        require(
            all(item.get(key) == value for key, value in expected.items()),
            'Stale native validation record: ' + target,
        )
        require(
            item.get('build') == 'passed' and item.get('inspection') == 'passed',
            'Missing native build/inspection: ' + target,
        )
        runtime = item.get('runtime', {})
        require(
            runtime.get('status') in ('passed', 'unverified'),
            'Invalid runtime status: ' + target,
        )
        if runtime['status'] == 'passed':
            require(
                runtime.get('native_sha256') == expected['native_sha256']
                and runtime.get('binding_version') == version
                and runtime.get('binding_abi') == expected['binding_abi'],
                'Stale runtime evidence: ' + target,
            )
            evidence = runtime.get('evidence', {})
            require(
                evidence.get('sha256') and evidence.get('kind'),
                'Missing runtime evidence: ' + target,
            )
            if target.startswith('windows-'):
                require(
                    runtime.get('java_os') == 'Windows'
                    and runtime.get('tests', 0) > 0
                    and config.target_id(
                        'windows-' + runtime.get('java_arch', 'unknown')
                    )
                    == target,
                    'Windows runtime evidence requires a matching Windows JVM and test count: '
                    + target,
                )
        else:
            missing.append(target + ':runtime')
    for check in ('jvm-consumers', 'android-r8', 'android-16k'):
        item = record.get('checks', {}).get(check, {})
        if item.get('status') != 'passed':
            missing.append(check)
        else:
            require(
                item.get('artifact_set_sha256') == config.identity(artifacts)
                and item.get('evidence', {}).get('sha256'),
                'Stale consumer/platform qualification evidence: ' + check,
            )
            if check in ('android-r8', 'android-16k'):
                require(
                    item.get('checkjni') is True
                    and item.get('elf_16k') is True
                    and item.get('zipalign_16k') is True
                    and item.get('native_sha256')
                    == targets['android-arm64']['native_sha256']
                    and item.get('apk_sha256')
                    and item.get('mapping_sha256')
                    and item.get('runtime_log_sha256'),
                    'Incomplete Android consumer evidence: ' + check,
                )
                require(
                    (
                        item.get('page_size') == 16384
                        if check == 'android-16k'
                        else item.get('page_size') in (4096, 16384)
                    ),
                    'Android qualification has the wrong runtime page size: ' + check,
                )
            if check == 'jvm-consumers':
                platforms = item.get('platforms', {})
                require(
                    {'macos-arm64', 'linux-amd64', 'linux-arm64'} <= set(platforms),
                    'Packaged JVM qualification must cover macOS and both Linux architectures',
                )
                for platform, result in platforms.items():
                    require(
                        platform in targets
                        and result.get('status') == 'passed'
                        and result.get('tests') == 47
                        and result.get('native_sha256')
                        == targets[platform]['native_sha256']
                        and result.get('binding_version') == version
                        and result.get('binding_abi')
                        == targets[platform]['binding_abi'],
                        'Incomplete packaged JVM runtime evidence: ' + platform,
                    )
    if record.get('fixture'):
        missing.append('synthetic-test-fixture')
    return {'complete': not missing, 'missing': missing}


def checksum_text(files):
    return ''.join(
        checksum + '  ' + name + '\n' for name, checksum in sorted(files.items())
    )


def write_json(path, value):
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='ascii'
    )


def freeze(version, validation, output, root=ROOT):
    release_version(version)
    require(
        version == config.validate_inputs(root),
        'Release version differs from Maven/native inputs; rebuild with the release version',
    )
    validate_poms(version, root)
    require(
        not output.exists(),
        'Release directory already exists; prepared releases cannot be overwritten',
    )
    targets = validate_natives(root)
    paths = artifact_paths(version, root)
    files = hashes(paths)
    qualification = checked_validation(validation, version, targets, files, root)
    temporary = output.with_name(output.name + '.assembling')
    require(
        not temporary.exists(),
        'Release assembly directory already exists: ' + str(temporary),
    )
    temporary.mkdir(parents=True)
    try:
        repository = temporary / 'repository'
        for name, source in paths.items():
            destination = repository / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        test_artifacts.check(repository, root)
        record = {
            'schema': 1,
            'binding_version': version,
            'binding_abi': config.binding_abi(root),
            'quiche_version': config.TAG,
            'files': files,
            'targets': targets,
            'source_fingerprint': source_fingerprint(root),
            'qualification': qualification,
            'validation': validation,
        }
        write_json(temporary / 'manifest.json', record)
        sums = dict(files)
        sums['manifest.json'] = config.digest(temporary / 'manifest.json')
        # Payload paths in SHA256SUMS are relative to the immutable release root.
        sums = {
            (
                'manifest.json' if name == 'manifest.json' else 'repository/' + name
            ): value
            for name, value in sums.items()
        }
        (temporary / 'SHA256SUMS').write_text(checksum_text(sums), encoding='ascii')
        verify(temporary, root=root)
        temporary.rename(output)
        for file in output.rglob('*'):
            if file.is_file():
                file.chmod(0o444)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return record


def verify_built(record, module, root=ROOT):
    """Check this module's normal Maven outputs before signing or deployment."""
    require(module in MODULES, 'Unexpected release module: ' + module)
    paths = artifact_paths(record['binding_version'], root)
    for name, path in paths.items():
        if name.split('/')[2] != module:
            continue
        require(path.is_file(), 'Missing Maven release output: ' + str(path))
        require(
            config.digest(path) == record['files'][name],
            'Maven output differs from the prepared release: ' + name,
        )
        if name.endswith('.aar'):
            # The aar lifecycle publishes/signs the jar goal's ZIP file.
            main = path.with_suffix('.jar')
            require(
                main.is_file() and config.digest(main) == record['files'][name],
                'Maven Android main artifact differs from the prepared AAR',
            )


def verify(directory, publication=False, root=ROOT):
    record = json.loads((directory / 'manifest.json').read_text())
    version = release_version(record['binding_version'])
    require(record.get('schema') == 1, 'Unsupported release manifest')
    validate_poms(version, root)
    expected = artifact_paths(version, root)
    require(
        set(record['files']) == set(expected),
        'Release has an incomplete or unexpected artifact set',
    )
    repository = directory / 'repository'
    actual = {
        path.relative_to(repository).as_posix()
        for path in repository.rglob('*')
        if path.is_file()
    }
    require(actual == set(expected), 'Release repository has extra or missing files')
    for name, checksum in record['files'].items():
        path = repository / name
        require(
            not path.is_symlink()
            and path.resolve().is_relative_to(repository.resolve()),
            'Unsafe release path: ' + name,
        )
        require(
            config.digest(path) == checksum, 'Frozen release artifact changed: ' + name
        )
        if name.endswith('.pom'):
            require(
                config.digest(expected[name]) == checksum,
                'Source POM changed after preparation: ' + name,
            )
    require(
        record.get('source_fingerprint') == source_fingerprint(root),
        'Sources changed after release preparation',
    )
    targets = validate_natives(root)
    require(
        targets == record['targets'], 'Staged native inputs changed after preparation'
    )
    qualification = checked_validation(
        record['validation'], version, targets, record['files'], root
    )
    require(
        record['qualification'] == qualification, 'Release qualification record changed'
    )
    sums = {
        'repository/' + name: checksum for name, checksum in record['files'].items()
    }
    sums['manifest.json'] = config.digest(directory / 'manifest.json')
    require(
        (directory / 'SHA256SUMS').read_text() == checksum_text(sums),
        'Release checksum manifest changed',
    )
    test_artifacts.check(repository, root)
    if publication:
        require(
            qualification['complete'],
            'Release qualification is incomplete: '
            + ', '.join(qualification['missing']),
        )
    return record
