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
import sys
import zipfile

import build_native as build
from native_config import ROOT, TARGETS, digest


def run(*command):
    print('Running:', *command, flush=True)
    subprocess.run(command, check=True, timeout=240)


def prepare(target):
    staged = ROOT / '.build/staged' / target / 'jni'
    manifest = build.validate_manifest(staged, target, 'jni')
    work = ROOT / '.build/runtime-tests' / target
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    classpath_file = ROOT / 'api/target/test-classpath.txt'
    if not classpath_file.is_file():
        raise ValueError('Run Maven process-test-classes or verify before runtime tests')
    entries = []
    for index, value in enumerate(classpath_file.read_text().strip().split(os.pathsep)):
        source = Path(value)
        name = 'entry-' + str(index) + ('.jar' if source.is_file() else '')
        destination = work / name
        if source.is_dir():
            shutil.copytree(source, destination)
            # Maven keeps host natives in test resources. Remove them from every
            # copied directory before injecting the selected target once.
            shutil.rmtree(destination / 'native', ignore_errors=True)
            if (destination / 'io/bosonnetwork/quiche/Native.class').is_file():
                shutil.copytree(staged, destination / 'native' / TARGETS[target].classifier)
        elif source.is_file():
            shutil.copyfile(source, destination)
        else:
            raise ValueError('Missing test classpath input: ' + value)
        entries.append(name)
    return work, manifest, entries


def linux(target, work, manifest, entries):
    native_work = ROOT / '.build/native' / target / manifest['input_identity']
    shutil.copytree(native_work / 'jni/test-libraries', work / 'test-libraries')
    builder = manifest['inputs']['builder']
    run('docker', 'run', '--rm', '--platform', 'linux/' + builder['image_arch'],
        '--mount', f'type=bind,source={work},target=/runtime', '--workdir', '/runtime',
        builder['image_id'], 'java', '-Xcheck:jni',
        '-Dboson.quiche.test.libraries=/runtime/test-libraries',
        '-cp', ':'.join('/runtime/' + entry for entry in entries), 'io.bosonnetwork.quiche.NativeSuite')


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
    run(adb, '-s', serial, 'shell', 'env', 'CLASSPATH=' + destination + '/suite.zip',
        'dalvikvm', '-Xcheck:jni', '-Djava.library.path=' + destination + '/lib',
        '-Dboson.quiche.test.resources=' + destination + '/fixtures',
        '-Djava.io.tmpdir=' + destination, 'io.bosonnetwork.quiche.NativeSuite', 'android')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=('linux-amd64', 'linux-arm64', 'android-arm64'), required=True)
    parser.add_argument('--android-sdk', type=Path)
    parser.add_argument('--serial')
    args = parser.parse_args()
    work, manifest, entries = prepare(args.target)
    if args.target.startswith('linux-'):
        linux(args.target, work, manifest, entries)
    elif args.android_sdk:
        android(work, entries, args.android_sdk.resolve(), args.serial)
    else:
        parser.error('--android-sdk and --serial are required for Android')
    (work / 'result.json').write_text(json.dumps({'status': 'passed', 'platform': args.target,
        'native_sha256': digest(ROOT / '.build/staged' / args.target / 'jni' / TARGETS[args.target].binary),
        'binding_version': manifest['binding_version'], 'binding_abi': manifest['binding_abi']}, indent=2) + '\n')


if __name__ == '__main__':
    main()

