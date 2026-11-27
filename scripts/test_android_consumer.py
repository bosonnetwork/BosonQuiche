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

"""Run the minified AAR consumer on an explicitly selected ARM64 emulator."""

import argparse
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid
import zipfile

import qualification
from qualification import release
from release_support import ROOT, config


def check_apk(sdk, apk, mapping, identity):
    release.require(
        apk.is_file() and mapping.is_file(),
        'Build the R8 release APK and mapping first',
    )
    text = mapping.read_text()
    release.require(
        '# compiler: R8' in text
        and 'io.bosonnetwork.quiche.Native -> io.bosonnetwork.quiche.Native:' in text,
        'Missing R8 mapping or preserved JNI class',
    )
    with zipfile.ZipFile(apk) as archive:
        names = [
            name
            for name in archive.namelist()
            if name.startswith('lib/') and name.endswith('.so')
        ]
        release.require(
            names == ['lib/arm64-v8a/libboson_quiche.so'],
            'Unexpected APK native libraries',
        )
        library = archive.read(names[0])
    checksum = hashlib.sha256(library).hexdigest()
    release.require(
        checksum == identity['native_sha256']['android-arm64'],
        'APK native library differs from the Maven AAR',
    )
    with tempfile.TemporaryDirectory(prefix='bq-elf-') as home:
        binary = Path(home) / 'libboson_quiche.so'
        binary.write_bytes(library)
        release.check_binary_baseline(binary, 'android-arm64')
    tools = sorted(
        (sdk / 'build-tools').glob('*/zipalign'),
        key=lambda path: tuple(int(n) for n in re.findall(r'\d+', path.parent.name)),
    )
    release.require(bool(tools), 'Android SDK zipalign is missing')
    output = subprocess.check_output(
        [str(tools[-1]), '-c', '-P', '16', '4', str(apk)],
        text=True,
        stderr=subprocess.STDOUT,
        timeout=60,
    )
    return {
        'apk_sha256': config.digest(apk),
        'mapping_sha256': config.digest(mapping),
        'native_sha256': checksum,
        'elf_16k': True,
        'zipalign_16k': True,
        'zipalign_log_sha256': hashlib.sha256(output.encode()).hexdigest(),
    }


def run(sdk, serial, apk, expected_page_size=None):
    if not re.fullmatch(r'emulator-\d+', serial):
        raise ValueError('--serial must select an emulator, never a physical device')
    adb = str(sdk / 'platform-tools/adb')

    def command(*args):
        return subprocess.check_output(
            [adb, '-s', serial, *args], text=True, stderr=subprocess.STDOUT, timeout=60
        ).strip()

    def property(name):
        return command('shell', 'getprop', name)

    release.require(
        property('ro.kernel.qemu') == '1', 'Selected device is not an emulator'
    )
    api, abi = property('ro.build.version.sdk'), property('ro.product.cpu.abi')
    release.require(
        int(api) >= 33 and abi == 'arm64-v8a',
        'Consumer verification requires an API 33+ ARM64 emulator',
    )
    page_size = int(command('shell', 'getconf', 'PAGESIZE'))
    release.require(page_size in (4096, 16384), 'Unsupported emulator page size')
    release.require(
        expected_page_size is None or page_size == expected_page_size,
        'Emulator page size does not match --page-size',
    )
    release.require(apk.is_file(), 'Build the minified release APK first')
    package = 'io.bosonnetwork.quiche.consumer'
    previous = property('debug.checkjni')
    run_id = uuid.uuid4().hex
    try:
        command('shell', 'setprop', 'debug.checkjni', '1')
        print(command('install', '-r', str(apk)))
        command('shell', 'am', 'force-stop', package)
        launch = command(
            'shell',
            'am',
            'start',
            '-W',
            '-n',
            package + '/.ConsumerActivity',
            '--es',
            'run-id',
            run_id,
        )
        release.require(
            'Error:' not in launch,
            'Cannot launch the consumer (check that the emulator user is unlocked): '
            + launch,
        )
        pid = command('shell', 'pidof', package)
        release.require(
            bool(re.fullmatch(r'\d+', pid)), 'Consumer application did not start'
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            log = command('logcat', '--pid=' + pid, '-d', '-v', 'brief')
            release.require(
                'BosonQuiche packaged consumer FAIL ' + run_id not in log, log
            )
            if 'BosonQuiche packaged consumer PASS ' + run_id in log:
                release.require(
                    '-Xcheck:jni' in log or 'CheckJNI is ON' in log,
                    'Consumer process did not confirm CheckJNI',
                )
                release.require(
                    'JNI DETECTED ERROR' not in log, 'CheckJNI reported an error'
                )
                for line in log.splitlines():
                    if run_id in line or '-Xcheck:jni' in line or 'CheckJNI' in line:
                        print(line)
                return {
                    'schema': 1,
                    'status': 'passed',
                    'platform': 'android-arm64',
                    'emulator': serial,
                    'android_api': int(api),
                    'android_abi': abi,
                    'page_size': page_size,
                    'checkjni': True,
                    'tests': 1,
                    'apk_sha256': config.digest(apk),
                    'run_id': run_id,
                    'runtime_log_sha256': hashlib.sha256(log.encode()).hexdigest(),
                }
            time.sleep(0.25)
        raise ValueError('Timed out waiting for the minified consumer result')
    finally:
        command('shell', 'am', 'force-stop', package)
        command('shell', 'setprop', 'debug.checkjni', previous or '0')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--android-sdk', type=Path, required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--page-size', type=int, choices=(4096, 16384))
    parser.add_argument(
        '--apk',
        type=Path,
        default=ROOT
        / 'test-tooling/android-consumer/build/outputs/apk/release/boson-quiche-android-consumer-release.apk',
    )
    parser.add_argument(
        '--mapping',
        type=Path,
        default=ROOT
        / 'test-tooling/android-consumer/build/outputs/mapping/release/mapping.txt',
    )
    parser.add_argument(
        '--repository',
        type=Path,
        help='Complete installed Maven distribution for qualification receipts',
    )
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.unlink(missing_ok=True)
        for name in ('android-r8', 'android-16k'):
            args.report.with_name(args.report.stem + '-' + name + '.json').unlink(
                missing_ok=True
            )
    identity = (
        qualification.repository_identity(args.repository.resolve())
        if args.repository
        else None
    )
    alignment = (
        check_apk(
            args.android_sdk.resolve(),
            args.apk.resolve(),
            args.mapping.resolve(),
            identity,
        )
        if identity
        else {}
    )
    result = run(
        args.android_sdk.resolve(), args.serial, args.apk.resolve(), args.page_size
    )
    if identity:
        result.update(
            alignment,
            binding_version=identity['binding_version'],
            binding_abi=identity['binding_abi'],
            artifact_set_sha256=identity['artifact_set_sha256'],
        )
    if args.report:
        release.write_json(args.report, result)
        if identity:
            details = dict(result)
            details.pop('status')
            details.pop('schema')
            details.pop('artifact_set_sha256')
            details.pop('binding_version')
            details.pop('binding_abi')
            qualification.sidecar(args.report, 'android-r8', identity, **details)
            if result['page_size'] == 16384:
                qualification.sidecar(args.report, 'android-16k', identity, **details)


if __name__ == '__main__':
    main()
