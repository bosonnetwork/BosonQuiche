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
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

import buildlog
import native_config as config
import native_toolchains as toolchains
from native_config import (ROOT, TAG, ARCHIVE_URL, ARCHIVE_SHA256, FEATURES, TARGETS,
                           digest, identity, output, write_if_changed)


def execute(*command, env=None, cwd=None):
    buildlog.command(command)
    subprocess.run(command, env=env, cwd=cwd, check=True)


def docker_image(target, pins):
    """Return the builder image and its identity, or stop with a clear message."""
    image = (pins['windows_image'] if target.startswith('windows-')
             else pins['linux_image_prefix'] + target.split('-')[1])
    try:
        return image, json.loads(output('docker', 'image', 'inspect', image))[0]
    except subprocess.CalledProcessError:
        pass
    try:
        output('docker', 'version', '--format', '{{.Server.Version}}')
    except (OSError, subprocess.CalledProcessError):
        raise ValueError('Docker engine is not reachable; start Docker Desktop or OrbStack'
                         ' and re-run scripts/check_toolchain.py --mode cross-build')
    raise ValueError('Missing builder image ' + image + '; scripts/check_toolchain.py'
                     ' --mode cross-build prints the docker buildx command that supplies it')


def toolchain_identity(target, pins):
    """Resolve the actual builder before selecting a cache directory."""
    if target.startswith(('linux-', 'windows-')) and platform.system() != 'Linux':
        image, info = docker_image(target, pins)
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
            ndk = toolchains.ndk_install(pins)
            result.update(ndk_revision=ndk['revision'], ndk_source=ndk['source'],
                          ndk_path=str(ndk['path']),
                          compiler=output(str(ndk['path'] / 'toolchains/llvm/prebuilt/darwin-x86_64/bin/clang'),
                                          '--version').strip())
    else:
        result.update(compiler=output('gcc', '--version').splitlines()[0],
                      libc=output('ldd', '--version').splitlines()[0])
    return result


def build_inputs(target, source_hash, binding_version, pins, tools):
    spec = TARGETS[target]
    return {'platform': target, 'rust_target': spec.rust, 'classifier': spec.classifier,
            'binary_name': spec.binary, 'android_abi': spec.android_abi,
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
            'cmake_sha256': digest(ROOT / 'native/CMakeLists.txt'),
            'cmake_presets_sha256': digest(ROOT / 'native/CMakePresets.json'),
            'cmake_support_sha256': identity({str(path.relative_to(ROOT / 'native')): digest(path)
                for path in sorted((ROOT / 'native/cmake').rglob('*')) if path.is_file()})}


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
        return {'provider': 'Android NDK', 'minimum_version': pins['android']['minimum_revision'],
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
    # The builder image pins the JDK and SDK, so its id is the identity.
    return {'provider': 'builder image', 'image_id': tools['image_id']}


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


def preset_for(target):
    """Select the configure preset that describes this target."""
    presets = json.loads((ROOT / 'native/CMakePresets.json').read_text())
    for preset in presets.get('configurePresets', []):
        if preset.get('cacheVariables', {}).get('BOSON_TARGET') == target:
            return preset['name']
    return target


def rust_archive_path(target, build):
    name = 'boson_quiche_build.lib' if target.startswith('windows-') else 'libboson_quiche_build.a'
    return build / 'rust' / TARGETS[target].rust / 'release' / name


def build_environment(target, pins, cache, container):
    """Select the tools for this target. Build flags belong to CMake."""
    if container:
        # The pinned image provides the compilers and the shared Cargo cache lives
        # in the mounted volume, so keep the image environment and only redirect
        # Cargo's home.
        return dict(os.environ, CARGO_HOME='/cache/cargo-home')
    env = config.clean_environment()
    env['CARGO_HOME'] = str(cache / ('cargo-home-macos' if platform.system() == 'Darwin' else 'cargo-home'))
    if target.startswith('linux-'):
        env.update(CC='gcc', CXX='g++', LIBCLANG_PATH='/usr/lib64')
    elif target == 'android-arm64':
        ndk = toolchains.ndk_path(pins)
        tools = ndk / 'toolchains/llvm/prebuilt/darwin-x86_64/bin'
        clang = tools / ('aarch64-linux-android' + str(pins['android']['api']) + '-clang')
        env.update(ANDROID_NDK_HOME=str(ndk),
                   CC_aarch64_linux_android=str(clang),
                   CXX_aarch64_linux_android=str(clang) + '++',
                   AR_aarch64_linux_android=str(tools / 'llvm-ar'),
                   CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER=str(clang),
                   BINDGEN_EXTRA_CLANG_ARGS='--target=aarch64-linux-android' + str(pins['android']['api']),
                   LIBCLANG_PATH=str(tools.parent / 'lib'))
    return env


def link_support(target, work, cargo_home):
    """Collect the MSVC import libraries the Rust archive expects."""
    directory = work / 'link-support'
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir()
    if target.startswith('windows-'):
        arch = 'x86_64' if target == 'windows-amd64' else 'aarch64'
        for library in sorted(cargo_home.glob('registry/src/*/windows_' + arch + '_msvc-*/lib/*.lib')):
            shutil.copyfile(library, directory / library.name)
    return directory
def configure_build_install(target, source, work, inputs, pins, cache, stage, env, container, test_natives):
    """Run the CMake project for this target and return its build report."""
    spec = TARGETS[target]
    build = work / 'cmake'
    install = work / 'install'
    cargo_home = Path(env['CARGO_HOME'])
    command = ['cmake', '--preset', preset_for(target), '-B', str(build),
               '-DCMAKE_INSTALL_PREFIX=' + str(install),
               '-DQUICHE_SOURCE=' + str(source),
               '-DJNI_INCLUDE=' + str(jni_headers(target, pins)),
               '-DBOSON_BINDING_ABI=' + str(inputs['binding_abi']),
               '-DBOSON_BINDING_VERSION=' + inputs['binding_version'],
               '-DBOSON_TEST_NATIVES=' + ('ON' if test_natives else 'OFF')]
    windows_sdk = None
    if target.startswith('windows-'):
        windows_sdk = toolchains.prepare_windows_toolchain(target, pins, cache, work, env, source, build)
        # The preset reads the toolchain path from the environment; the driver
        # only selects it. The archive is prebuilt because cargo-xwin owns the
        # MSVC toolchain integration.
        env['BOSON_WINDOWS_TOOLCHAIN'] = str(windows_sdk['toolchain'])
        command += ['-DQUICHE_ARCHIVE=' + str(rust_archive_path(target, build)),
                    '-DLINK_SUPPORT=' + str(link_support(target, work, cargo_home)),
                    '-DBOSON_CARGO_SUBCOMMAND=xwin']
    compiler = output('rustc', '--version').strip()
    if not toolchains.rust_version_supported(compiler, pins['rust_minimum']):
        raise RuntimeError('Rust ' + pins['rust_minimum'] + ' or later is required; found ' + compiler)
    installed = output('rustup', 'target', 'list', '--installed').split()
    if spec.rust not in installed:
        raise RuntimeError('Missing Rust target ' + spec.rust + "; run: rustup target add " + spec.rust)
    execute(*command, env=env, cwd=ROOT / 'native')
    build_command = ['cmake', '--build', str(build), '--parallel', '4']
    if stage == 'archive':
        build_command += ['--target', 'quiche_ffi']
    execute(*build_command, env=env, cwd=ROOT / 'native')

    archive = rust_archive_path(target, build)
    machines = toolchains.inspect_archive(archive, target, work, llvm_tools())
    report = {'status': 'passed', 'stage': 'quiche-static-archive', 'runtime_tested': False,
              'platform': target, 'rust_target': spec.rust, 'quiche_tag': TAG,
              'source_archive_sha256': ARCHIVE_SHA256,
              'cargo_lock_sha256': digest(ROOT / 'native/Cargo.lock'),
              'rustc': output('rustc', '--version').strip(), 'features': FEATURES,
              'archive': str(archive), 'archive_sha256': digest(archive),
              'machines': machines, 'ffi_symbols_checked': toolchains.SYMBOLS,
              'cmake': output('cmake', '--version').splitlines()[0],
              'llvm_inspector': output(str(llvm_tools() / 'llvm-nm'), '--version').strip(),
              'container': container}
    if windows_sdk:
        report.update(windows_sdk['report'])
        report['c_api_link_proof'] = toolchains.link_windows_smoke(
            archive, target, work, source, windows_sdk['sdk'], llvm_tools(), env,
            (ROOT / 'native/copyright-header.txt').read_text())
    elif target == 'android-arm64':
        ndk = toolchains.ndk_path(pins)
        report.update(ndk=pins['android'], compiler=output(
            str(ndk / 'toolchains/llvm/prebuilt/darwin-x86_64/bin/clang'), '--version').strip())
    elif target.startswith('linux-'):
        report.update(compiler=output('gcc', '--version').splitlines()[0],
                      libc=output('ldd', '--version').splitlines()[0])
    else:
        report['compiler'] = output('xcrun', 'clang', '--version').strip()

    if stage == 'jni':
        # Install into an empty tree so a cached work directory can never
        # contribute stale files to the staged artifact.
        shutil.rmtree(install, ignore_errors=True)
        execute('cmake', '--install', str(build), env=env)
        binary = install / 'native' / spec.classifier / spec.binary
        if not binary.is_file():
            raise ValueError('CMake did not install ' + spec.binary + ' for ' + target)
        report.update(inspect_binary(binary, target, work))
    report['licenses'] = install_notices(work)
    (work / 'proof.json').write_text(json.dumps(report, indent=2) + '\n')
    return report
def install_notices(work):
    """Copy the committed dependency notices into the build tree."""
    source = ROOT / 'native/notices'
    index = json.loads((source / 'notices.json').read_text())
    destination = work / 'licenses'
    if destination.exists():
        shutil.rmtree(destination)
    for record in index['packages']:
        for relative in record['notices']:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, target)
    return index['packages']


def update_notices(pins):
    """Regenerate the committed dependency notices from every target graph."""
    work = ROOT / '.build/notices'
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    source = config.prepare_source('')
    driver = toolchains.prepare_driver(source, work, ROOT / 'native/Cargo.lock',
                                       ROOT / 'native/copyright-header.txt')
    env = config.clean_environment()
    env['CARGO_HOME'] = str(ROOT / '.build/cache' /
                            ('cargo-home-macos' if platform.system() == 'Darwin' else 'cargo-home'))
    cargo_home = Path(env['CARGO_HOME'])
    merged = {}
    for target, spec in sorted(TARGETS.items()):
        directory = work / target
        directory.mkdir(parents=True, exist_ok=True)
        records = toolchains.collect_licenses(driver, source, directory, cargo_home,
                                              spec.rust, env, offline=False)
        for record in records:
            files = merged.setdefault((record['package'], record['version']), {})
            for relative in record['notices']:
                files.setdefault(relative, work / target / 'licenses' / relative)
    destination = ROOT / 'native/notices'
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    packages = []
    for (name, version), files in sorted(merged.items()):
        for relative, origin in sorted(files.items()):
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origin, target)
        packages.append({'package': name, 'version': version, 'notices': sorted(files)})
    document = {'schema': 1, 'cargo_lock_sha256': digest(ROOT / 'native/Cargo.lock'),
                'targets': sorted(TARGETS), 'packages': packages}
    (destination / 'notices.json').write_text(json.dumps(document, indent=2, sort_keys=True) + '\n')
    buildlog.done('wrote ' + str(len(packages)) + ' package notices to ' + buildlog.rel(destination))
    return document


def export_container_outputs(work, destination, target, stage, test_natives):
    """Export distributable files without copying Cargo or CMake build trees."""
    report = json.loads((work / 'proof.json').read_text())
    archive = Path(report['archive'])
    shutil.copyfile(archive, destination / archive.name)
    report['archive'] = str(destination / archive.name)
    for name in ('licenses', 'link-support', 'install'):
        shutil.rmtree(destination / name, ignore_errors=True)
    for name in ('licenses', 'link-support'):
        if (work / name).is_dir():
            shutil.copytree(work / name, destination / name)
    if stage == 'jni':
        shutil.copytree(work / 'install', destination / 'install')
    (destination / 'proof.json').write_text(json.dumps(report, indent=2) + '\n')


def build_in_container(target, stage, pins, test_natives, destination=Path('/output'),
                       source=Path('/source'), cache=Path('/cache')):
    inputs = json.loads((destination / 'inputs.json').read_text())
    work = cache / 'build' / target / identity(inputs)
    with config.build_lock(cache / 'locks' / (target + '.lock')):
        work.mkdir(parents=True, exist_ok=True)
        write_if_changed(work / 'inputs.json', json.dumps(inputs, indent=2) + '\n')
        try:
            env = build_environment(target, pins, cache, container=True)
            configure_build_install(target, source, work, inputs, pins, cache, stage, env,
                                    container=True, test_natives=test_natives)
            export_container_outputs(work, destination, target, stage, test_natives)
        finally:
            # Keep failure diagnostics available after the disposable container exits.
            for path in sorted(work.iterdir()):
                if path.is_file() and path.suffix in ('.log', '.txt'):
                    shutil.copyfile(path, destination / path.name)
            inventory = Path('/opt/build-packages.txt')
            if inventory.is_file():
                shutil.copyfile(inventory, destination / 'toolchain-packages.txt')


def run_container(target, source, work, tools, stage, test_natives=False):
    """Mount selected sources and final outputs; keep heavy work in a Docker volume."""
    volume = config.docker_cache_volume(target, tools['image_arch'])
    # inspect_binary checks the exported symbols against the Java declarations,
    # so that single file travels with the sources.
    mounts = [(source, '/source', True), (work, '/output', False),
              (ROOT / 'native', '/project/native', True),
              (ROOT / 'api/src/main/java/io/bosonnetwork/quiche/Native.java',
               '/project/api/src/main/java/io/bosonnetwork/quiche/Native.java', True)]
    command = ['docker', 'run', '--rm', '--platform', 'linux/' + tools['image_arch'],
               '--mount', f'type=volume,source={volume},target=/cache']
    for path, destination, readonly in mounts:
        command += ['--mount', f'type=bind,source={path},target={destination}' + (',readonly' if readonly else '')]
    command += [tools['image_id'], 'python3', '/project/native/scripts/build_native.py',
                '--inside', '--target', target, '--stage', stage]
    if test_natives:
        command.append('--test-natives')
    (work / 'proof.json').unlink(missing_ok=True)
    execute(*command)
    report = json.loads((work / 'proof.json').read_text())
    report['archive'] = str(work / Path(report['archive']).relative_to('/output'))
    report['builder'] = tools
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


def stage_output(target, stage, work, inputs, revision):
    report = json.loads((work / 'proof.json').read_text())
    destination = ROOT / '.build/staged' / target / stage
    temporary = destination.with_name(stage + '.assembling')
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    binary = (work / 'install' / 'native' / TARGETS[target].classifier / TARGETS[target].binary
              if stage == 'jni' else Path(report['archive']))
    shutil.copyfile(binary, temporary / binary.name)
    for name in ('licenses', 'link-support'):
        if (work / name).exists():
            shutil.copytree(work / name, temporary / name)
    inspection = {key: report[key] for key in ('machines', 'jni_exports') if key in report}
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
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--target', type=config.target_id, choices=TARGETS)
    selection.add_argument('--all', action='store_true', help='Select all six targets.')
    parser.add_argument('--stage', choices=('archive', 'jni'), default='jni')
    parser.add_argument('--validate-only', action='store_true',
                        help='Validate the staged output instead of building it.')
    parser.add_argument('--update-lock', action='store_true')
    parser.add_argument('--update-notices', action='store_true',
                        help='Regenerate the committed dependency notices.')
    parser.add_argument('--test-natives', action='store_true',
                        help='Build isolated native loader test fixtures.')
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    pins = json.loads((ROOT / 'native/toolchains.json').read_text())
    if args.update_notices:
        update_notices(pins)
        return 0
    if args.inside:
        build_in_container(args.target, args.stage, pins, args.test_natives)
        return 0
    if not args.target and not args.all:
        args.target = config.host_target()
    version = config.validate_inputs()
    source = config.prepare_source(args.source)
    source_hash = config.source_digest(source)
    targets = list(TARGETS) if args.all else [args.target]
    if args.update_lock:
        if args.all or args.validate_only:
            parser.error('--update-lock requires one build target')
        work = ROOT / '.build/lock-refresh'
        driver = toolchains.prepare_driver(source, work, ROOT / 'native/Cargo.lock',
                                           ROOT / 'native/copyright-header.txt')
        env = config.clean_environment()
        env['CARGO_HOME'] = str(ROOT / '.build/cache/cargo-home-macos')
        execute('cargo', 'generate-lockfile', '--manifest-path', str(driver / 'Cargo.toml'), env=env)
        shutil.copyfile(driver / 'Cargo.lock', ROOT / 'native/Cargo.lock')
    revision = output('git', '-C', str(ROOT), 'rev-parse', 'HEAD').strip()
    for target in targets:
        with config.build_lock(ROOT / '.build/locks' / (target + '.lock')):
            tools = toolchain_identity(target, pins)
            if args.stage == 'jni':
                tools['jni'] = target_jni_identity(target, pins, tools)
            inputs = build_inputs(target, source_hash, version, pins, tools)
            destination = ROOT / '.build/staged' / target / args.stage
            if args.validate_only:
                validate_manifest(destination, target, args.stage, inputs)
                buildlog.done(target + ' ' + args.stage + ' is current')
                continue
            work = ROOT / '.build/native' / target / identity(inputs)
            work.mkdir(parents=True, exist_ok=True)
            (work / 'inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
            if 'image_id' in tools:
                run_container(target, source, work, tools, args.stage, args.test_natives)
            else:
                env = build_environment(target, pins, ROOT / '.build/cache', container=False)
                configure_build_install(target, source, work, inputs, pins,
                                        ROOT / '.build/cache', args.stage, env, container=False,
                                        test_natives=args.test_natives)
            destination = stage_output(target, args.stage, work, inputs, revision)
            buildlog.done(target + ' ' + args.stage + ' -> ' + buildlog.rel(destination))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        buildlog.fail('native build failed: ' + str(error))
        sys.exit(1)
