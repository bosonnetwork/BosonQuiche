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
import json
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'native/scripts'))
from native_config import ROOT, digest


def run(sdk, serial, apk):
    if not re.fullmatch(r'emulator-\d+', serial):
        raise ValueError('--serial must select an emulator, never a physical device')
    adb = str(sdk / 'platform-tools/adb')

    def command(*args):
        return subprocess.check_output([adb, '-s', serial, *args], text=True, stderr=subprocess.STDOUT, timeout=60).strip()

    def property(name):
        return command('shell', 'getprop', name)

    if property('ro.kernel.qemu') != '1':
        raise ValueError('Selected device is not an emulator')
    api, abi = property('ro.build.version.sdk'), property('ro.product.cpu.abi')
    if int(api) < 33 or abi != 'arm64-v8a':
        raise ValueError('Consumer verification requires an API 33+ ARM64 emulator')
    if not apk.is_file():
        raise ValueError('Build the minified release APK first: ' + str(apk))
    package = 'io.bosonnetwork.quiche.consumer'
    print(command('install', '-r', str(apk)))
    command('shell', 'am', 'force-stop', package)
    command('shell', 'am', 'start', '-W', '-n', package + '/.ConsumerActivity')
    pid = command('shell', 'pidof', package)
    if not re.fullmatch(r'\d+', pid):
        raise ValueError('Consumer application did not start')
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        log = command('logcat', '--pid=' + pid, '-d', '-s', 'BosonQuicheConsumer:I', '*:S')
        if 'BosonQuiche packaged consumer FAIL' in log:
            raise ValueError(log)
        if 'BosonQuiche packaged consumer PASS' in log:
            print(log)
            return {'status': 'passed', 'emulator': serial, 'android_api': int(api),
                    'android_abi': abi, 'apk_sha256': digest(apk)}
        time.sleep(0.25)
    raise ValueError('Timed out waiting for the minified consumer result')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--android-sdk', type=Path, required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--apk', type=Path, default=ROOT / 'test-tooling/android-consumer/build/outputs/apk/release/boson-quiche-android-consumer-release.apk')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = run(args.android_sdk.resolve(), args.serial, args.apk.resolve())
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
