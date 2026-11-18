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

"""Build, inspect and stage quiche archives or JNI libraries for explicit targets."""

import argparse
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile

import native_config as config
import native_toolchains as toolchains
from native_config import (ROOT, TAG, ARCHIVE_URL, ARCHIVE_SHA256, FEATURES, TARGETS,
                           digest, identity, output, write_if_changed)


def execute(*command, env=None):
    print('Running:', *command, flush=True)
    subprocess.run(command, env=env, check=True)


def toolchain_identity(target, pins):
    """Resolve the actual builder before selecting a cache directory."""
    if target.startswith(('linux-', 'windows-')) and platform.system() != 'Linux':
        image = (pins['windows_image'] if target.startswith('windows-') else
                 pins['linux_image_prefix'] + target.split('-')[1])
        info = json.loads(output('docker', 'image', 'inspect', image))[0]
        return {'image_id': info['Id'], 'image_arch': info['Architecture'],
                'recipe_sha256': digest(ROOT / 'native/docker' / (
                    'Dockerfile.windows' if target.startswith('windows-') else 'Dockerfile.linux'))}
    if target.startswith('windows-'):
        raise ValueError('Windows targets require the pinned Docker builder on macOS')
    if target.startswith('linux-') and config.host_target() != target:
        raise ValueError('Linux builds require a matching host architecture')
    result = {'rustc': output('rustc', '-vV').strip(),
              'cmake': output('cmake', '--version').splitlines()[0]}
    if target in ('macos-arm64', 'android-arm64'):
        if platform.system() != 'Darwin' or platform.machine() != 'arm64':
            raise ValueError('macOS and Android builds require an Apple Silicon Mac')
        if target == 'macos-arm64':
            result.update(compiler=output('xcrun', 'clang', '--version').strip(),
                          sdk=output('xcrun', '--show-sdk-path').strip(),
                          sdk_version=output('xcrun', '--show-sdk-version').strip())
        else:
            ndk = toolchains.ndk_path(pins)
            properties = (ndk / 'source.properties').read_text()
            if not re.search(r'Pkg.Revision\s*=\s*' + re.escape(pins['android']['revision']) + r'\s*$', properties, re.M):
                raise ValueError('NDK revision differs from native/toolchains.json')
            result.update(ndk_revision=pins['android']['revision'], ndk_path=str(ndk),
                          compiler=output(str(ndk / 'toolchains/llvm/prebuilt/darwin-x86_64/bin/clang'), '--version').strip())
    else:
        result.update(compiler=output('gcc', '--version').splitlines()[0],
                      libc=output('ldd', '--version').splitlines()[0])
    return result


def build_inputs(target, source_hash, binding_version, pins, tools):
    spec = TARGETS[target]
    return {'platform': target, 'rust_target': spec.rust, 'classifier': spec.classifier,
            'binary_name': spec.binary, 'android_abi': 'arm64-v8a' if spec.jni == 'android' else None,
            'baseline': spec.baseline, 'binding_version': binding_version, 'binding_abi': config.binding_abi(),
            'quiche_version': TAG, 'quiche_tag': TAG, 'quiche_archive_url': ARCHIVE_URL,
            'quiche_archive_sha256': ARCHIVE_SHA256, 'source_tree_sha256': source_hash,
            'cargo_lock_sha256': digest(ROOT / 'native/Cargo.lock'), 'features': FEATURES,
            'toolchains': pins, 'builder': tools,
            'build_scripts_sha256': identity({path.name: digest(path) for path in
                sorted(list((ROOT / 'native/scripts').glob('native_*.py')) + [Path(__file__)])}),
            'jni_sources_sha256': identity({str(path.relative_to(ROOT / 'native')): digest(path) for path in
                sorted((ROOT / 'native/src/main/c').glob('*')) if path.is_file()}),
            'jni_declarations_sha256': digest(ROOT / 'api/src/main/java/io/bosonnetwork/quiche/Native.java'),
            'cmake_sha256': digest(ROOT / 'native/CMakeLists.txt')}


def jni_headers(target, pins):
    if TARGETS[target].jni == 'android':
        return toolchains.ndk_path(pins) / 'toolchains/llvm/prebuilt/darwin-x86_64/sysroot/usr/include'
    home = os.environ.get('JAVA_HOME')
    if not home and platform.system() == 'Darwin':
        home = output('/usr/libexec/java_home').strip()
    if not home:
        javac = shutil.which('javac')
        if javac:
            home = str(Path(javac).resolve().parents[1])
    if not home:
        raise ValueError('A JDK is required for JNI compilation; set JAVA_HOME')
    directory = Path(home).resolve() / 'include'
    required = (directory / 'jni.h', directory / TARGETS[target].jni / 'jni_md.h')
    for path in required:
        if not path.is_file():
            raise ValueError('Missing target JDK header: ' + str(path))
    return directory


def jni_identity(target, pins):
    """Record the actual SDK inputs without requiring a specific header hash."""
    directory = jni_headers(target, pins)
    if TARGETS[target].jni == 'android':
        return {'provider': 'Android NDK', 'version': pins['android']['revision'],
                'headers': {'jni.h': digest(directory / 'jni.h')}}
    release = directory.parent / 'release'
    if not release.is_file():
        raise ValueError('Missing JDK release metadata: ' + str(release))
    properties = dict(re.findall(r'^(\w+)="([^"]*)"', release.read_text(), re.M))
    version = properties.get('JAVA_VERSION', '')
    major = re.match(r'(\d+)', version)
    if not major or int(major[1]) < 11:
        raise ValueError('JDK 11 or later is required; found ' + version)
    expected_os = {'darwin': 'Darwin', 'linux': 'Linux', 'win32': 'Windows'}[TARGETS[target].jni]
    if properties.get('OS_NAME') != expected_os:
        raise ValueError('JDK headers do not match target platform ' + target)
    return {'provider': properties.get('IMPLEMENTOR', 'JDK'), 'version': version,
            'jdk_os': properties['OS_NAME'], 'jdk_arch': properties.get('OS_ARCH'),
            'headers': {name: digest(directory / name) for name in
                        ('jni.h', TARGETS[target].jni + '/jni_md.h')}}


def target_jni_identity(target, pins, tools):
    if 'image_id' not in tools:
        return jni_identity(target, pins)
    # Read the SDK metadata inside the builder, never from the macOS JDK.
    command = ('import json, build_native as b; '
               'p=json.loads((b.ROOT/"native/toolchains.json").read_text()); '
               'print(json.dumps(b.jni_identity(' + repr(target) + ', p)))')
    return json.loads(output('docker', 'run', '--rm', '--platform', 'linux/' + tools['image_arch'],
        '--mount', f'type=bind,source={ROOT / "native"},target=/project/native,readonly',
        '--workdir', '/project/native/scripts', tools['image_id'], 'python3', '-c', command))


def llvm_tools():
    host = re.search(r'^host: (.+)$', output('rustc', '-vV'), re.M)[1]
    return Path(output('rustc', '--print', 'sysroot').strip()) / 'lib/rustlib' / host / 'bin'


def inspect_binary(binary, target, work):
    tools = llvm_tools()
    if target == 'macos-arm64':
        headers = output('lipo', '-info', str(binary))
        if 'architecture: arm64' not in headers:
            raise ValueError('JNI binary is not macOS arm64')
        exports = output('nm', '-gU', str(binary))
        names = re.findall(r'\b_([A-Za-z0-9_]+)\s*$', exports, re.M)
        dependencies = output('otool', '-L', str(binary))
        machines = ['arm64']
    else:
        windows = target.startswith('windows-')
        flags = ['--coff-exports', '--coff-imports'] if windows else ['--dyn-symbols', '--needed-libs', '--version-info']
        headers = output(str(tools / 'llvm-readobj'), '--file-headers', *flags, str(binary))
        machines = sorted(set(re.findall(r'^\s*Machine: (\S+)', headers, re.M)))
        if machines != [TARGETS[target].machine]:
            raise ValueError('JNI binary has the wrong machine type: ' + repr(machines))
        exports = output(str(tools / 'llvm-nm'), '--defined-only', '--extern-only',
                         *([] if windows else ['--dynamic']), str(binary)) if not windows else headers
        names = (re.findall(r'^\s*Name: (\w+)\s*$', output(str(tools / 'llvm-readobj'), '--coff-exports', str(binary)), re.M)
                 if windows else re.findall(r'\b([A-Za-z0-9_]+)\s*$', exports, re.M))
        dependencies = headers
    declarations = (ROOT / 'api/src/main/java/io/bosonnetwork/quiche/Native.java').read_text()
    expected = {'JNI_OnLoad', 'JNI_OnUnload'} | {
        'Java_io_bosonnetwork_quiche_Native_' + method
        for method in re.findall(r'static native \S+ (\w+)\(', declarations)}
    if set(names) != expected:
        raise ValueError('JNI exports differ: missing=' + repr(sorted(expected - set(names))) +
                         ', unexpected=' + repr(sorted(set(names) - expected)))
    (work / 'binary-inspection.txt').write_text(headers + '\n' + exports + '\n' + dependencies)
    return {'machines': machines, 'jni_exports': sorted(set(names)), 'runtime_tested': False}


def compile_jni(target, source, work, inputs, pins, cache, headers, test_natives=False):
    """Compile only against headers; no target JVM library is linked."""
    report = json.loads((work / 'proof.json').read_text())
    archive = Path(report['archive'])
    env = config.clean_environment()
    flags = []
    if target == 'macos-arm64':
        flags += ['-DCMAKE_TOOLCHAIN_FILE=' + str(work / 'macos.cmake')]
    elif target == 'android-arm64':
        flags += ['-DCMAKE_TOOLCHAIN_FILE=' + str(work / 'android.cmake')]
    elif target.startswith('windows-'):
        sdk = cache / ('xwin-llvm20-sdk' + pins['windows_sdk'] + '-crt' + pins['windows_crt'])
        flags += ['-DCMAKE_TOOLCHAIN_FILE=' + str(sdk / 'cmake/clang-cl' / (TARGETS[target].rust + '-toolchain.cmake'))]
        env['PATH'] = str(sdk) + os.pathsep + env['PATH']
    cmake = work / 'jni'
    build = json.loads((work / 'inputs.json').read_text())
    execute('cmake', '-S', str(inputs), '-B', str(cmake), '-DCMAKE_BUILD_TYPE=Release',
            '-DBOSON_SOURCE=' + str(inputs / 'src/main/c'),
            '-DBOSON_JAVA_SOURCE=' + str(ROOT / 'api/src/main/java/io/bosonnetwork/quiche/Native.java'),
            '-DQUICHE_INCLUDE=' + str(source / 'quiche/include'),
            '-DQUICHE_ARCHIVE=' + str(archive), '-DLINK_SUPPORT=' + str(work / 'link-support'),
            '-DJNI_INCLUDE=' + str(headers),
            '-DJNI_PLATFORM_INCLUDE=' + str(headers / TARGETS[target].jni),
            '-DBOSON_BINDING_ABI=' + str(build['binding_abi']),
            '-DBOSON_BINDING_VERSION=' + build['binding_version'],
            '-DBOSON_TEST_NATIVES=' + ('ON' if test_natives else 'OFF'),
            *flags, env=env)
    execute('cmake', '--build', str(cmake), '--parallel', '4', env=env)
    binary = cmake / TARGETS[target].binary
    inspect_binary(binary, target, work)
    return binary


def run_container(target, source, work, tools, stage, test_natives=False):
    """Mount only selected inputs, never a home directory or publishing state."""
    cache = ROOT / '.build/cache'
    cache.mkdir(parents=True, exist_ok=True)
    mounts = [(source, '/source', True), (work, '/work', False), (cache, '/cache', False),
              (ROOT / 'native', '/project/native', True),
              (ROOT / 'api/src/main/java/io/bosonnetwork/quiche/Native.java',
               '/project/api/src/main/java/io/bosonnetwork/quiche/Native.java', True)]
    command = ['docker', 'run', '--rm', '--platform', 'linux/' + tools['image_arch']]
    for path, destination, readonly in mounts:
        command += ['--mount', f'type=bind,source={path},target={destination}' + (',readonly' if readonly else '')]
    command += [tools['image_id'], 'python3', '/project/native/scripts/build_native.py',
                '--inside', '--target', target, '--stage', stage]
    if test_natives:
        command.append('--test-natives')
    execute(*command)
    report = json.loads((work / 'proof.json').read_text())
    report['archive'] = str(work / Path(report['archive']).relative_to('/work'))
    report['builder'] = tools
    packages = output('docker', 'run', '--rm', '--platform', 'linux/' + tools['image_arch'],
                      tools['image_id'], 'cat', '/opt/build-packages.txt')
    (work / 'toolchain-packages.txt').write_text(packages)
    report['os_packages_sha256'] = digest(work / 'toolchain-packages.txt')
    (work / 'proof.json').write_text(json.dumps(report, indent=2) + '\n')


def validate_manifest(directory, target, stage, expected=None):
    manifest = json.loads((directory / 'build.json').read_text())
    if not isinstance(manifest, dict) or not isinstance(manifest.get('inputs'), dict):
        raise ValueError('Build manifest and inputs must be objects')
    spec = TARGETS[target]
    if (manifest.get('schema') != 1 or manifest.get('stage') != stage or
            manifest.get('status') != 'passed' or manifest.get('platform') != target or
            manifest.get('rust_target') != spec.rust or manifest.get('classifier') != spec.classifier or
            manifest.get('machines') != [spec.machine]):
        raise ValueError('Invalid or wrong-target build manifest: ' + str(directory))
    if manifest.get('input_identity') != identity(manifest.get('inputs')):
        raise ValueError('Build manifest input identity is corrupt')
    if (manifest['inputs'].get('platform') != target or
            manifest.get('binding_version') != manifest['inputs'].get('binding_version') or
            manifest.get('quiche_version') != manifest['inputs'].get('quiche_version')):
        raise ValueError('Build manifest versions or target are inconsistent')
    if expected is not None and manifest['inputs'] != expected:
        raise ValueError('Stale build inputs: ' + str(directory))
    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('Build manifest has no files')
    required = spec.binary if stage == 'jni' else ('boson_quiche_build.lib' if target.startswith('windows-') else 'libboson_quiche_build.a')
    if required not in files or not any(name.startswith('licenses/') for name in files):
        raise ValueError('Build manifest is missing the native library or licenses')
    for name, checksum in files.items():
        if not isinstance(name, str) or not isinstance(checksum, str) or not re.fullmatch(r'[a-f0-9]{64}', checksum):
            raise ValueError('Invalid build manifest file or checksum')
        file = directory / name
        if Path(name).is_absolute() or not file.resolve().is_relative_to(directory.resolve()):
            raise ValueError('Unsafe build manifest path: ' + name)
        if not file.is_file() or digest(file) != checksum:
            raise ValueError('Missing or changed build output: ' + str(file))
    return manifest


def assemble_bundle(directory, destination, manifest):
    """Stable order, timestamps and ownership make repeat assembly deterministic."""
    with tarfile.open(destination, 'w', format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(list(manifest['files']) + ['build.json']):
            data = (directory / name).read_bytes()
            member = tarfile.TarInfo(name)
            member.size, member.mode, member.mtime = len(data), 0o644, 0
            archive.addfile(member, io.BytesIO(data))


def stage_output(target, stage, work, inputs, revision):
    report = json.loads((work / 'proof.json').read_text())
    destination = ROOT / '.build/staged' / target / stage
    temporary = destination.with_name(stage + '.assembling')
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    binary = work / 'jni' / TARGETS[target].binary if stage == 'jni' else Path(report['archive'])
    shutil.copyfile(binary, temporary / binary.name)
    for name in ('licenses', 'link-support'):
        if (work / name).exists():
            shutil.copytree(work / name, temporary / name)
    inspection = inspect_binary(binary, target, work) if stage == 'jni' else {'machines': report['machines']}
    files = {path.relative_to(temporary).as_posix(): digest(path)
             for path in sorted(temporary.rglob('*')) if path.is_file()}
    # Keep native compiler reports portable, while preserving their provenance.
    details = json.dumps(report).replace(str(work), '${BUILD}').replace(str(ROOT), '${PROJECT}')
    manifest = {'schema': 1, 'status': 'passed', 'stage': stage, 'platform': target,
                'rust_target': TARGETS[target].rust, 'classifier': TARGETS[target].classifier,
                'binding_version': inputs['binding_version'], 'binding_abi': inputs['binding_abi'], 'quiche_version': TAG,
                'source_revision': revision, 'runtime_tested': False, **inspection,
                'input_identity': identity(inputs), 'inputs': inputs,
                'native': json.loads(details), 'files': files}
    (temporary / 'build.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n', encoding='ascii')
    validate_manifest(temporary, target, stage, inputs)
    if destination.exists():
        shutil.rmtree(destination)
    temporary.replace(destination)
    assemble_bundle(destination, destination.parent / (stage + '.tar'), manifest)
    return destination


def stage_maven(directory, target):
    """Restore host resources after Maven clean without deleting native inputs."""
    manifest = validate_manifest(directory, target, 'jni')
    generated = ROOT / 'api/target/native-test-resources'
    native = generated / 'native' / TARGETS[target].classifier
    native.mkdir(parents=True, exist_ok=True)
    for name in (TARGETS[target].binary, 'build.json'):
        shutil.copyfile(directory / name, native / name)
    licenses = generated / 'META-INF/native-licenses'
    if licenses.exists():
        shutil.rmtree(licenses)
    shutil.copytree(directory / 'licenses', licenses)
    return manifest


def stage_test_natives(work):
    directory = ROOT / 'api/target/native-test-libraries'
    if directory.exists():
        shutil.rmtree(directory)
    shutil.copytree(work / 'jni/test-libraries', directory)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='')
    parser.add_argument('--skip', default='false')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--target', type=config.target_id, choices=TARGETS)
    selection.add_argument('--all', action='store_true', help='Select all six targets.')
    parser.add_argument('--stage', choices=('archive', 'jni'), default='jni')
    parser.add_argument('--quiche-only', action='store_true', help='Alias for --stage archive.')
    parser.add_argument('--update-lock', action='store_true')
    parser.add_argument('--inspect', action='store_true', help='Validate staged outputs without building.')
    parser.add_argument('--report', action='store_true', help='Validate and print all selected manifests as JSON.')
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--fetch-ndk', action='store_true')
    parser.add_argument('--test-natives', action='store_true', help='Build isolated native loader test fixtures.')
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    pins = json.loads((ROOT / 'native/toolchains.json').read_text())
    if args.fetch_ndk:
        toolchains.fetch_ndk(pins)
        return 0
    if args.preflight:
        return toolchains.preflight(pins)
    stage = 'archive' if args.quiche_only else args.stage
    if args.inside:
        work, source, cache = Path('/work'), Path('/source'), Path('/cache')
        toolchains.build_archive(args.target, source, work, ROOT / 'native', pins, cache)
        if stage == 'jni':
            compile_jni(args.target, source, work, ROOT / 'native', pins, cache,
                        jni_headers(args.target, pins), args.test_natives)
        return 0
    version = config.validate_inputs()
    source = config.prepare_source(args.source)
    source_hash = config.source_digest(source)
    targets = list(TARGETS) if args.all or (args.report and not args.target) else [args.target or config.host_target()]
    if args.update_lock:
        if args.all or args.inspect or args.report or args.skip.lower() == 'true':
            parser.error('--update-lock requires one build target')
        work = ROOT / '.build/lock-refresh'
        driver = toolchains.prepare_driver(source, work, ROOT / 'native/Cargo.lock', ROOT / 'native/copyright-header.txt')
        env = config.clean_environment()
        env['CARGO_HOME'] = str(ROOT / '.build/cache/cargo-home-macos')
        execute('cargo', 'generate-lockfile', '--manifest-path', str(driver / 'Cargo.toml'), env=env)
        shutil.copyfile(driver / 'Cargo.lock', ROOT / 'native/Cargo.lock')
    revision = output('git', '-C', str(ROOT), 'rev-parse', 'HEAD').strip()
    reports = []
    for target in targets:
        with config.build_lock(ROOT / '.build/locks' / (target + '.lock')):
            tools = toolchain_identity(target, pins)
            if stage == 'jni':
                tools['jni'] = target_jni_identity(target, pins, tools)
            inputs = build_inputs(target, source_hash, version, pins, tools)
            destination = ROOT / '.build/staged' / target / stage
            if args.inspect or args.report or args.skip.lower() == 'true':
                manifest = validate_manifest(destination, target, stage, inputs)
                inspected = ROOT / '.build/inspections' / target
                inspected.mkdir(parents=True, exist_ok=True)
                if stage == 'jni':
                    inspect_binary(destination / TARGETS[target].binary, target, inspected)
                else:
                    archive = 'boson_quiche_build.lib' if target.startswith('windows-') else 'libboson_quiche_build.a'
                    toolchains.inspect_archive(destination / archive, target, inspected, llvm_tools())
                reports.append(manifest)
                if args.skip.lower() == 'true' and stage == 'jni' and len(targets) == 1 and target == config.host_target():
                    stage_maven(destination, target)
                    if args.test_natives:
                        stage_test_natives(ROOT / '.build/native' / target / identity(inputs))
                if not args.report:
                    print('Validated:', target, stage)
                continue
            work = ROOT / '.build/native' / target / identity(inputs)
            work.mkdir(parents=True, exist_ok=True)
            (work / 'inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
            if 'image_id' in tools:
                run_container(target, source, work, tools, stage, args.test_natives)
            else:
                toolchains.build_archive(target, source, work, ROOT / 'native', pins, ROOT / '.build/cache')
                if stage == 'jni':
                    compile_jni(target, source, work, ROOT / 'native', pins, ROOT / '.build/cache',
                                jni_headers(target, pins), args.test_natives)
            destination = stage_output(target, stage, work, inputs, revision)
            if stage == 'jni' and not args.all and target == config.host_target():
                stage_maven(destination, target)
                if args.test_natives:
                    stage_test_natives(work)
            print('Staged:', target, stage, destination)
    if args.report:
        print(json.dumps({'generated_by': 'native/scripts/build_native.py --report', 'builds': reports}, indent=2))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print('Native build failed:', error, file=sys.stderr)
        sys.exit(1)
