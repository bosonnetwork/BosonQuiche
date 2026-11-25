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

"""Build selected native targets and record version-bound distribution validation."""

import argparse
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import release_support as release
from release_support import ROOT, config
import native_toolchains as toolchains


def run(command, log):
    print('Running:', ' '.join(map(str, command)), flush=True)
    with log.open('w') as output:
        try:
            subprocess.run(
                list(map(str, command)),
                cwd=ROOT,
                stdout=output,
                stderr=subprocess.STDOUT,
                check=True,
            )
        except subprocess.CalledProcessError:
            output.flush()
            print('Failed command log:', log, file=sys.stderr)
            print(
                '\n'.join(log.read_text(errors='replace').splitlines()[-20:]),
                file=sys.stderr,
            )
            raise
    return {
        'status': 'passed',
        'evidence': {'kind': 'command-log', 'sha256': config.digest(log)},
    }


def prepare_android_ndk(targets, prebuilt, logs):
    """Restore the disposable NDK cache before starting native builds."""
    if prebuilt or 'android-arm64' not in targets:
        return
    pins = json.loads((ROOT / 'native/toolchains.json').read_text())
    properties = toolchains.ndk_path(pins) / 'source.properties'
    if not properties.is_file() and not os.environ.get('ANDROID_NDK_HOME'):
        run(
            [sys.executable, ROOT / 'native/scripts/build_native.py', '--fetch-ndk'],
            logs / 'android-ndk-setup.log',
        )
    release.require(
        properties.is_file(),
        'Missing Android NDK metadata: ' + str(properties)
        + '; set ANDROID_NDK_HOME to the pinned NDK or unset it to use the project cache',
    )
    release.require(
        re.search(
            r'Pkg.Revision\s*=\s*' + re.escape(pins['android']['revision']) + r'\s*$',
            properties.read_text(),
            re.M,
        ),
        'Android NDK revision differs from native/toolchains.json: ' + str(properties),
    )


def test_summary():
    tests = failures = errors = skipped = 0
    reports = list((ROOT / 'api/target/surefire-reports').glob('TEST-*.xml'))
    for file in reports:
        report = ET.parse(file).getroot()
        tests += int(report.get('tests', '0'))
        failures += int(report.get('failures', '0'))
        errors += int(report.get('errors', '0'))
        skipped += int(report.get('skipped', '0'))
    release.require(
        tests > 0 and failures == errors == skipped == 0,
        'Host JNI tests failed, were skipped, or produced no reports',
    )
    return tests


def runtime(record, expected, evidence):
    release.require(
        record.get('status') == 'passed'
        and record.get('binding_version') == expected['binding_version']
        and record.get('binding_abi') == expected['binding_abi']
        and record.get('native_sha256') == expected['native_sha256'],
        'Runtime evidence is stale or failed',
    )
    result = dict(record)
    result['evidence'] = {'kind': 'runtime-record', 'sha256': config.digest(evidence)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--targets', default='all', help='all, or comma-separated platform IDs'
    )
    parser.add_argument(
        '--prebuilt',
        action='store_true',
        help='Validate compatible staged JNI outputs before packaging and tests',
    )
    parser.add_argument(
        '--reuse',
        action='store_true',
        help='Strictly validate and reuse existing native build inputs',
    )
    parser.add_argument('--settings', type=Path, default=ROOT / '.mvn/settings.xml')
    parser.add_argument('--maven-repository', type=Path)
    parser.add_argument('--android-sdk', type=Path)
    parser.add_argument('--serial', help='Explicit API 33+ ARM64 emulator serial')
    parser.add_argument(
        '--evidence',
        type=Path,
        action='append',
        default=[],
        help='Additional matching runtime or consumer qualification JSON record',
    )
    parser.add_argument(
        '--report', type=Path, default=ROOT / '.build/validation/build.json'
    )
    args = parser.parse_args()
    targets = (
        list(config.TARGETS)
        if args.targets == 'all'
        else [config.target_id(name.strip()) for name in args.targets.split(',')]
    )
    release.require(len(targets) == len(set(targets)), 'Duplicate build targets')
    full = set(targets) == set(config.TARGETS)
    release.require(
        config.host_target() in targets,
        'Include the host target to run the Java/JNI regression suite',
    )
    release.require(
        bool(args.android_sdk) == bool(args.serial),
        '--android-sdk and --serial must be supplied together',
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.unlink(missing_ok=True)
    logs = args.report.parent / 'logs'
    logs.mkdir(exist_ok=True)
    initial = release.source_fingerprint()
    checks = {}
    python_checks = []
    for suite in ('native/scripts/tests', 'scripts/tests'):
        release.require(
            (ROOT / suite).is_dir(), 'Missing required Python test suite: ' + suite
        )
        log = logs / (suite.replace('/', '-') + '.log')
        result = run(
            [sys.executable, '-m', 'unittest', 'discover', '-s', suite, '-q'], log
        )
        summary = log.read_text()
        count = re.search(r'Ran (\d+) tests?', summary)
        release.require(
            count is not None
            and int(count[1]) > 0
            and not re.search(r'skipped\s*=\s*[1-9]', summary),
            'Required Python tests were skipped or no tests ran: ' + suite,
        )
        result['tests'] = int(count[1])
        result['suite'] = suite
        python_checks.append(result)
    checks['python'] = {
        'status': 'passed',
        'tests': sum(item['tests'] for item in python_checks),
        'suites': python_checks,
    }
    release.require(
        not (args.prebuilt and args.reuse), 'Choose either --prebuilt or --reuse'
    )
    prepare_android_ndk(targets, args.prebuilt, logs)
    for target in targets:
        if args.prebuilt:
            release.packaging.validate(target)
            print('Validated prebuilt JNI input:', target, flush=True)
            continue
        command = [
            sys.executable,
            ROOT / 'native/scripts/build_native.py',
            '--target',
            target,
        ]
        if not target.startswith('android-'):
            command.append('--test-natives')
        if args.reuse:
            command += ['--skip', 'true']
        run(command, logs / (target + '-build.log'))
    maven = ['mvn', '-s', args.settings.resolve(), '-Dnative.skip=true']
    if args.maven_repository:
        maven.append('-Dmaven.repo.local=' + str(args.maven_repository.resolve()))
    if full:
        maven.append('-Pdistribution')
    host_check = run(maven + ['clean', 'verify'], logs / 'maven-verify.log')
    host_check['tests'] = test_summary()
    checks['host-jni'] = host_check
    checks['javadoc'] = dict(host_check)
    all_targets = release.validate_natives()
    artifact_files = release.artifact_paths(config.validate_inputs())
    if full:
        # Check repository layout using copies of the exact reactor outputs.
        repository = args.report.parent / 'artifact-check'
        if repository.exists():
            shutil.rmtree(repository)
        for name, source in artifact_files.items():
            destination = repository / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        release.test_artifacts.check(repository)
        checks['artifacts'] = {'status': 'passed'}
    else:
        checks['artifacts'] = {
            'status': 'unverified',
            'reason': 'Only selected targets were built',
        }
    files = release.hashes(
        {name: source for name, source in artifact_files.items() if source.is_file()}
    )
    records = {}
    for target, expected in all_targets.items():
        item = dict(
            expected,
            build='passed' if target in targets else 'unverified',
            inspection='passed' if target in targets else 'unverified',
            runtime={
                'status': 'unverified',
                'reason': 'No matching runtime test was run',
            },
        )
        if target == config.host_target():
            item['runtime'] = dict(host_check, **expected)
        elif target in targets and (
            target.startswith('linux-') or (target == 'android-arm64' and args.serial)
        ):
            command = [
                sys.executable,
                ROOT / 'native/scripts/test_runtime.py',
                '--target',
                target,
            ]
            if target == 'android-arm64':
                command += [
                    '--android-sdk',
                    args.android_sdk.resolve(),
                    '--serial',
                    args.serial,
                ]
            run(command, logs / (target + '-runtime.log'))
            evidence = ROOT / '.build/runtime-tests' / target / 'result.json'
            item['runtime'] = runtime(
                json.loads(evidence.read_text()), expected, evidence
            )
        records[target] = item
    for evidence in args.evidence:
        data = json.loads(evidence.read_text())
        target = data.get('platform')
        name = data.get('check')
        if name is not None:
            release.require(
                name in ('jvm-consumers', 'android-r8', 'android-16k'),
                'Unknown qualification evidence',
            )
            release.require(
                data.get('status') == 'passed'
                and data.get('artifact_set_sha256') == config.identity(files),
                'Qualification evidence must match the exact artifact set',
            )
            checks[name] = dict(
                data,
                evidence={
                    'kind': 'qualification-record',
                    'sha256': config.digest(evidence),
                },
            )
        elif target in records:
            records[target]['runtime'] = runtime(data, all_targets[target], evidence)
        else:
            raise ValueError('Unknown runtime or qualification evidence')
    release.require(
        release.source_fingerprint() == initial,
        'Source inputs changed during validation',
    )
    record = {
        'schema': 1,
        'binding_version': config.validate_inputs(),
        'binding_abi': config.binding_abi(),
        'source_fingerprint': initial,
        'artifacts': files,
        'checks': checks,
        'targets': records,
        'scope': 'distribution' if full else 'selected-targets',
        'native_mode': (
            'validated-prebuilt'
            if args.prebuilt
            else ('strict-reuse' if args.reuse else 'build')
        ),
    }
    if full:
        record['qualification'] = release.checked_validation(
            record, record['binding_version'], all_targets, files
        )
    release.write_json(args.report, record)
    print('Validation record:', args.report)
    print('Build scope:', record['scope'])
    if full:
        print('Publication qualification:', record['qualification'])


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print('Distribution build failed:', error, file=sys.stderr)
        sys.exit(1)
