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

"""Run compiled native tests in Linux containers or an Android ARM64 emulator."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET

import build_native as build
import buildlog
from native_config import ROOT, TARGETS, digest, docker_cache_volume, identity


def run(*command, capture=False):
    buildlog.command(command)
    if capture:
        return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT, timeout=240)
    subprocess.run(command, check=True, timeout=240)
    return ''


def android_cases(output):
    """Read the case count the on-device suite reports."""
    match = re.search(r'Android JNI cases: (\d+)', output)
    if not match:
        raise ValueError('Android suite did not report its case count')
    return int(match.group(1))


def prepare(target):
    staged = ROOT / '.build/staged' / target / 'jni'
    manifest = build.validate_manifest(staged, target, 'jni')
    work = ROOT / '.build/runtime-tests' / target
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    classpath_file = ROOT / 'api/target/test-classpath.txt'
    if not classpath_file.is_file():
        raise ValueError('Missing api/target/test-classpath.txt; run Maven verify first')

    entries = []
    # The suite and the API classes are ordinary Maven build outputs.
    for folder, name in (('classes', 'api-classes'), ('test-classes', 'api-test-classes')):
        source = ROOT / 'api/target' / folder
        if not source.is_dir():
            raise ValueError('Missing Maven output: ' + str(source))
        shutil.copytree(source, work / name)
        entries.append(name)
    # Dependency JARs come from Maven. The host classifier must never travel with
    # them, because the selected target provides the native library.
    for index, value in enumerate(classpath_file.read_text().strip().split(os.pathsep)):
        source = Path(value)
        if not source.is_file():
            raise ValueError('Missing dependency JAR: ' + value)
        if source.name.startswith('boson-quiche-native-'):
            continue
        name = 'dependency-' + str(index) + '.jar'
        shutil.copyfile(source, work / name)
        entries.append(name)
    # The staged build joins the classpath as a directory, which is exactly how the
    # loader expects to find /native/<classifier>/<library>.
    native = work / 'target-native' / 'native' / TARGETS[target].classifier
    native.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(staged, native)
    entries.append('target-native')
    return work, manifest, entries


def loader_fixtures(target, work, manifest):
    """Build tiny loader fixtures with the pinned target compiler, independent of Rust caches."""
    builder = manifest['inputs']['builder']
    windows = target.startswith('windows-')
    volume = docker_cache_volume(target, builder['image_arch'])
    fixture_id = identity({'builder': builder, 'version': manifest['binding_version'],
                           'abi': manifest['binding_abi'],
                           'sources': {path.name: digest(path) for path in
                               sorted((ROOT / 'native/src/test/c').iterdir()) if path.is_file()}})
    directory = '/cache/loader-fixtures/' + target + '/' + fixture_id
    command = ['docker', 'run', '--rm', '--platform', 'linux/' + builder['image_arch'],
               '--mount', f'type=volume,source={volume},target=/cache',
               '--mount', f'type=bind,source={work},target=/runtime',
               '--mount', f'type=bind,source={ROOT / "native/src/test/c"},target=/fixtures,readonly',
               '--env', 'BOSON_VERSION=' + manifest['binding_version'],
               '--env', 'BOSON_ABI=' + str(manifest['binding_abi'])]
    extra = ''
    if windows:
        pins = json.loads((ROOT / 'native/toolchains.json').read_text())
        sdk = 'xwin-llvm20-sdk' + pins['windows_sdk']
        extra = 'export PATH=/cache/' + sdk + ':$PATH; '
        toolchain = '/cache/' + sdk + '/cmake/clang-cl/' + TARGETS[target].rust + '-toolchain.cmake'
        extra += 'export CMAKE_TOOLCHAIN_FILE=' + toolchain + '; '
    generator = 'Ninja' if windows else 'Unix Makefiles'
    script = extra + ('cmake -S /fixtures -B ' + directory + '/build -G "' + generator + '" '
              '-DCMAKE_BUILD_TYPE=Release "-DJNI_INCLUDE=$JAVA_HOME/include" '
              '-DJNI_PLATFORM=' + TARGETS[target].jni + ' "-DBOSON_BINDING_VERSION=$BOSON_VERSION" '
              '"-DBOSON_BINDING_ABI=$BOSON_ABI" && cmake --build ' + directory + '/build && '
              'mkdir -p /runtime/test-libraries && cp ' + directory + '/test-libraries/* /runtime/test-libraries/')
    run(*command, builder['image_id'], 'sh', '-c', script)
    return work / 'test-libraries'


def linux(target, work, manifest, entries):
    native_work = ROOT / '.build/native' / target / manifest['input_identity']
    if (native_work / 'install/test-libraries').is_dir():
        shutil.copytree(native_work / 'install/test-libraries', work / 'test-libraries')
    else:
        loader_fixtures(target, work, manifest)
    builder = manifest['inputs']['builder']
    run('docker', 'run', '--rm', '--platform', 'linux/' + builder['image_arch'],
        '--mount', f'type=bind,source={work},target=/runtime', '--workdir', '/runtime',
        builder['image_id'], 'java', '-Xcheck:jni',
        '-Dboson.quiche.test.libraries=/runtime/test-libraries',
        '-cp', ':'.join('/runtime/' + entry for entry in entries), 'io.bosonnetwork.quiche.NativeSuite', '--report', '/runtime/result.xml')


def android(work, entries, sdk, serial):
    if not serial or not re.fullmatch(r'emulator-\d+', serial):
        raise ValueError('--serial must explicitly select an Android emulator, never a physical device')
    adb = str(sdk / 'platform-tools/adb')
    emulator = subprocess.check_output([adb, '-s', serial, 'shell', 'getprop', 'ro.kernel.qemu'], text=True).strip()
    if emulator != '1':
        raise ValueError('Selected device is not an emulator')
    api = subprocess.check_output([adb, '-s', serial, 'shell', 'getprop', 'ro.build.version.sdk'], text=True).strip()
    abi = subprocess.check_output([adb, '-s', serial, 'shell', 'getprop', 'ro.product.cpu.abi'], text=True).strip()
    if int(api) < 33 or abi != 'arm64-v8a':
        raise ValueError('Tests require an API 33+ ARM64 emulator')
    tools = max((sdk / 'build-tools').iterdir(), key=lambda path: tuple(map(int, path.name.split('.'))))
    platform = max((sdk / 'platforms').glob('android-*'), key=lambda path: path.name)
    classes = work / 'classes.jar'
    resources = {}
    with zipfile.ZipFile(classes, 'w') as output:
        for entry in entries:
            path = work / entry
            if path.is_dir():
                for file in sorted(path.rglob('*')):
                    if file.is_file():
                        name = file.relative_to(path).as_posix()
                        if name.endswith('.class'):
                            output.write(file, name)
                        elif name == 'META-INF/boson-quiche.properties':
                            resources[name] = file.read_bytes()
    dex = work / 'suite.zip'
    run(str(tools / 'd8'), '--min-api', '33', '--lib', str(platform / 'android.jar'),
        '--output', str(dex), str(classes), *(str(work / item) for item in entries if item.endswith('.jar')))
    with zipfile.ZipFile(dex, 'a') as output:
        for name, content in resources.items():
            output.writestr(name, content)
    payload = work / 'payload'
    (payload / 'lib').mkdir(parents=True)
    (payload / 'fixtures').mkdir()
    shutil.copyfile(dex, payload / 'suite.zip')
    shutil.copyfile(ROOT / '.build/staged/android-arm64/jni/libboson_quiche.so', payload / 'lib/libboson_quiche.so')
    for name in ('server-cert.pem', 'server-key.pem'):
        shutil.copyfile(ROOT / 'api/src/test/resources' / name, payload / 'fixtures' / name)
    destination = '/data/local/tmp/boson-quiche-native-tests'
    run(adb, '-s', serial, 'shell', 'mkdir', '-p', destination)
    run(adb, '-s', serial, 'push', str(payload) + '/.', destination + '/')
    output = run(adb, '-s', serial, 'shell', 'env', 'CLASSPATH=' + destination + '/suite.zip',
        'dalvikvm', '-Xcheck:jni', '-Djava.library.path=' + destination + '/lib',
        '-Dboson.quiche.test.resources=' + destination + '/fixtures',
        '-Djava.io.tmpdir=' + destination, 'io.bosonnetwork.quiche.NativeSuite', 'android',
        capture=True)
    return android_cases(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=('linux-amd64', 'linux-arm64', 'android-arm64'), required=True)
    parser.add_argument('--android-sdk', type=Path)
    parser.add_argument('--serial')
    args = parser.parse_args()
    work, manifest, entries = prepare(args.target)
    cases = None
    if args.target.startswith('linux-'):
        linux(args.target, work, manifest, entries)
    elif args.android_sdk:
        cases = android(work, entries, args.android_sdk.resolve(), args.serial)
    else:
        parser.error('--android-sdk and --serial are required for Android')
    details = {}
    if args.target.startswith('linux-'):
        details = {item.get('key'): item.text for item in ET.parse(work / 'result.xml').findall('entry')}
        details['tests'] = int(details['tests'])
        details['java_os'] = 'Linux'
    else:
        details['page_size'] = int(subprocess.check_output([str(args.android_sdk / 'platform-tools/adb'), '-s', args.serial, 'shell', 'getconf', 'PAGESIZE'], text=True))
        details['tests'] = cases
    (work / 'result.json').write_text(json.dumps({**details, 'status': 'passed', 'platform': args.target,
        'native_sha256': digest(ROOT / '.build/staged' / args.target / 'jni' / TARGETS[args.target].binary),
        'binding_version': manifest['binding_version'], 'binding_abi': manifest['binding_abi']}, indent=2) + '\n')
    buildlog.done(args.target + ': ' + str(details['tests']) + ' runtime tests passed')


if __name__ == '__main__':
    main()
