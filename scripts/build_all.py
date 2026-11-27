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

"""Build selected native targets and record version-bound distribution validation.

The build uses the toolchains already installed on this machine and installs
nothing; run scripts/check_toolchain.py to see what is available.
"""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import release_support as release
from release_support import ROOT, config
import buildlog


class StepFailed(Exception):
    """A build step already reported its own failure."""


def run(command, log):
    buildlog.step(log.stem)
    buildlog.command(command)
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
            buildlog.fail('failed, log -> ' + buildlog.rel(log))
            buildlog.tail(log, 25)
            raise StepFailed(log.stem) from None
    buildlog.done(log.stem)
    return {
        'status': 'passed',
        'evidence': {'kind': 'command-log', 'sha256': config.digest(log)},
    }


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
    parser.add_argument('--settings', type=Path, help='Optional Maven settings file')
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
    release.require(
        not (args.prebuilt and args.reuse), 'Choose either --prebuilt or --reuse'
    )
    for target in targets:
        if args.prebuilt:
            release.packaging.validate(target)
            buildlog.done(target + ' prebuilt JNI input is current')
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
            command.append('--validate-only')
        run(command, logs / (target + '-build.log'))
    maven = ['mvn']
    if args.settings:
        maven += ['-s', str(args.settings.resolve())]
    if args.maven_repository:
        maven.append('-Dmaven.repo.local=' + str(args.maven_repository.resolve()))
    if full:
        maven.append('-Pdistribution')
    host_check = run(maven + ['clean', 'verify'], logs / 'maven-verify.log')
    host_check['tests'] = test_summary()
    checks['host-jni'] = host_check
    checks['javadoc'] = dict(host_check)
    all_targets = release.validate_natives(selected=targets)
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
        # Linux and Android evidence comes from the release-grade build in its own
        # runtime, which is stronger than the host JVM. The host JVM run stays in
        # checks['host-jni'].
        if target in targets and (
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
        elif target == config.host_target():
            item['runtime'] = dict(host_check, **expected)
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
    summarise(record, args.report)


def qualification_text(qualification):
    """Describe publication qualification without inventing a status field."""
    if qualification.get('complete'):
        return 'complete'
    missing = qualification.get('missing', [])
    return 'incomplete: ' + ', '.join(missing)


def summarise(record, report):
    """Print the outcome as a table and keep the same table next to the record."""

    def runtime(item):
        status = item['runtime'].get('status', 'unverified')
        tests = item['runtime'].get('tests')
        return status if tests is None else status + ' (' + str(tests) + ' tests)'

    rows = [
        (target, target_record['build'], target_record['inspection'], runtime(target_record))
        for target, target_record in sorted(record['targets'].items())
    ]
    checks = [(name, item.get('status', '?')) for name, item in sorted(record['checks'].items())]
    buildlog.step(
        'summary (' + record['scope'] + ', native source: ' + record['native_mode'] + ')'
    )
    print('  targets')
    buildlog.table(
        [(name, 'build ' + build + ', inspection ' + inspection + ', runtime ' + status)
         for name, build, inspection, status in rows],
        indent='    ',
    )
    print('  checks')
    buildlog.table(checks, indent='    ')
    if 'qualification' in record:
        print()
        buildlog.info('qualification: ' + qualification_text(record['qualification']))
    buildlog.done('record -> ' + buildlog.rel(report))

    lines = [
        '# Build validation summary',
        '',
        '- binding version: ' + record['binding_version'],
        '- source fingerprint: ' + record['source_fingerprint'],
        '- scope: ' + record['scope'],
        '- native source: ' + record['native_mode'],
        '',
        '| target | build | inspection | runtime |',
        '| --- | --- | --- | --- |',
    ]
    lines += ['| ' + ' | '.join(row) + ' |' for row in rows]
    lines += ['', '| check | status |', '| --- | --- |']
    lines += ['| ' + name + ' | ' + status + ' |' for name, status in checks]
    if 'qualification' in record:
        lines += ['', 'Qualification: ' + qualification_text(record['qualification'])]
    summary = report.parent / 'summary.md'
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    try:
        main()
    except StepFailed:
        sys.exit(1)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        buildlog.fail('distribution build failed: ' + str(error))
        sys.exit(1)
