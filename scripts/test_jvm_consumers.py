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

"""Qualify packaged JNI libraries with matching desktop JVMs."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import qualification
from qualification import release
from release_support import ROOT, config

sys.path.insert(0, str(ROOT / 'native/scripts'))
import test_runtime


def run(command, log):
    with log.open('w') as output:
        subprocess.run(
            list(map(str, command)),
            cwd=ROOT,
            check=True,
            env=dict(os.environ, MAVEN_SKIP_RC='1'),
            stdout=output,
            stderr=subprocess.STDOUT,
        )


def runtime_xml(path, identity, target=None):
    data = {item.get('key'): item.text for item in ET.parse(path).findall('entry')}
    os_name = data['java_os']
    if os_name.lower().startswith('windows'):
        os_id = 'windows'
    elif 'mac' in os_name.lower() or 'darwin' in os_name.lower():
        os_id = 'macos'
    elif os_name.lower() == 'linux':
        os_id = 'linux'
    else:
        raise ValueError('Unsupported runtime operating system: ' + os_name)
    platform = config.target_id(os_id + '-' + data['java_arch'])
    release.require(
        target is None or target == platform, 'Runtime used the wrong JVM architecture'
    )
    release.require(
        data['status'] == 'passed' and int(data['tests']) == 47,
        'Runtime did not pass all 47 JNI tests',
    )
    release.require(
        data['native_sha256'] == identity['native_sha256'][platform]
        and data['binding_version'] == identity['binding_version']
        and int(data['binding_abi']) == identity['binding_abi'],
        'Stale packaged runtime result',
    )
    return dict(
        data,
        schema=1,
        platform=platform,
        tests=47,
        binding_abi=int(data['binding_abi']),
        java_os='Windows' if os_id == 'windows' else os_name,
        artifact_set_sha256=identity['artifact_set_sha256'],
        runtime_log_sha256=config.digest(path),
    )


def prepare_windows(portable, work, identity):
    for target in ('windows-amd64', 'windows-arm64'):
        destination = work / target
        shutil.copytree(portable, destination)
        manifest = json.loads(
            (ROOT / '.build/staged' / target / 'jni/build.json').read_text()
        )
        test_runtime.loader_fixtures(target, destination, manifest)
        (destination / 'run.ps1').write_text(
            'param([Parameter(Mandatory=$true)][string]$JavaHome)\n'
            '$ErrorActionPreference = "Stop"\n'
            '$java = Join-Path $JavaHome "bin/java.exe"\n'
            '$cp = ((Get-ChildItem $PSScriptRoot -Filter "entry-*").FullName) -join ";"\n'
            '& $java -Xcheck:jni "-Dboson.quiche.test.libraries=$PSScriptRoot/test-libraries" '
            '-cp $cp io.bosonnetwork.quiche.NativeSuite --report "$PSScriptRoot/result.xml"\n'
            'if ($LASTEXITCODE -ne 0) { throw "JNI suite failed" }\n'
            '& $java -Xcheck:jni -cp $cp io.bosonnetwork.quiche.consumer.ConsumerProbe "$PSScriptRoot/fixtures"\n'
            'if ($LASTEXITCODE -ne 0) { throw "Packaged consumer failed" }\n',
            encoding='ascii',
        )
        release.write_json(destination / 'expected.json', identity)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--work', type=Path, default=ROOT / '.build/qualification/jvm')
    parser.add_argument('--maven', default='mvn')
    parser.add_argument('--prepare-windows', action='store_true')
    parser.add_argument('--import-runtime', type=Path)
    parser.add_argument('--target', choices=config.TARGETS)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    identity = qualification.repository_identity(args.repository.resolve())
    if args.import_runtime:
        release.require(
            args.report and args.target,
            '--report and --target are required for runtime import',
        )
        release.write_json(
            args.report, runtime_xml(args.import_runtime, identity, args.target)
        )
        return
    work = args.work.resolve()
    release.require(not work.exists(), 'Choose a fresh qualification work directory')
    work.mkdir(parents=True)
    host = config.host_target()
    fixtures = ROOT / 'native/target/native-install/test-libraries'
    command = [
        args.maven,
        '-s',
        ROOT / 'test-tooling/file-repository-settings.xml',
        '-f',
        ROOT / 'test-tooling/jvm-consumer/pom.xml',
        '-Dboson.repository=' + args.repository.resolve().as_uri(),
        '-Dmaven.repo.local=' + str(work / 'maven-cache'),
        '-Dboson.version=' + identity['binding_version'],
        '-Dnative.classifier=' + config.TARGETS[host].classifier,
        '-Dloader.fixtures=' + str(fixtures),
        '-Pjni-tests,all-desktop',
        'verify',
    ]
    run(command, work / 'host-maven.log')
    consumer = ROOT / 'test-tooling/jvm-consumer/target'
    reports = list((consumer / 'surefire-reports').glob('TEST-*.xml'))
    counts = [ET.parse(path).getroot() for path in reports]
    release.require(
        sum(int(item.get('tests', '0')) for item in counts) == 47
        and all(
            all(
                int(item.get(key, '0')) == 0
                for key in ('failures', 'errors', 'skipped')
            )
            for item in counts
        ),
        'Packaged host suite did not pass all 47 cases',
    )
    props = {
        item.get('name'): item.get('value')
        for item in counts[0].findall('properties/property')
    }
    host_result = {
        'schema': 1,
        'status': 'passed',
        'platform': host,
        'tests': 47,
        'java_os': props['os.name'],
        'java_arch': props['os.arch'],
        'binding_version': identity['binding_version'],
        'binding_abi': identity['binding_abi'],
        'native_sha256': identity['native_sha256'][host],
        'runtime_log_sha256': config.digest(work / 'host-maven.log'),
        'artifact_set_sha256': identity['artifact_set_sha256'],
    }
    release.write_json(work / (host + '.json'), host_result)
    portable = work / 'portable'
    portable.mkdir()
    entries = []
    for index, value in enumerate(
        (consumer / 'test-classpath.txt').read_text().strip().split(os.pathsep)
    ):
        source = Path(value)
        name = 'entry-' + str(index) + ('.jar' if source.is_file() else '')
        if source.is_dir():
            shutil.copytree(source, portable / name)
        else:
            shutil.copyfile(source, portable / name)
        entries.append(name)
    shutil.copytree(ROOT / 'api/src/test/resources', portable / 'fixtures')
    runtimes = {host: host_result}
    for target in ('linux-amd64', 'linux-arm64'):
        directory = work / target
        shutil.copytree(portable, directory)
        manifest = json.loads(
            (ROOT / '.build/staged' / target / 'jni/build.json').read_text()
        )
        test_runtime.loader_fixtures(target, directory, manifest)
        builder = manifest['inputs']['builder']
        docker = [
            'docker',
            'run',
            '--rm',
            '--read-only',
            '--tmpfs',
            '/tmp:rw,exec,nosuid,nodev,mode=1777',
            '--platform',
            'linux/' + builder['image_arch'],
            '--mount',
            f'type=bind,source={directory},target=/runtime',
            builder['image_id'],
            'sh',
            '-c',
            'exec env PATH=/no-build-tools "$JAVA_HOME/bin/java" "$@"',
            'java',
        ]
        classpath = ':'.join('/runtime/' + entry for entry in entries)
        run(
            docker
            + [
                '-Xcheck:jni',
                '-Dboson.quiche.test.libraries=/runtime/test-libraries',
                '-cp',
                classpath,
                'io.bosonnetwork.quiche.NativeSuite',
                '--report',
                '/runtime/result.xml',
            ],
            directory / 'jni.log',
        )
        run(
            docker
            + [
                '-Xcheck:jni',
                '-cp',
                classpath,
                'io.bosonnetwork.quiche.consumer.ConsumerProbe',
                '/runtime/fixtures',
            ],
            directory / 'consumer.log',
        )
        result = runtime_xml(directory / 'result.xml', identity, target)
        result['consumer_log_sha256'] = config.digest(directory / 'consumer.log')
        runtimes[target] = result
        release.write_json(work / (target + '.json'), result)
    if args.prepare_windows:
        prepare_windows(portable, work, identity)
    report = args.report or work / 'jvm-consumers.json'
    release.write_json(
        report, qualification.receipt('jvm-consumers', identity, platforms=runtimes)
    )
    print('Packaged JVM qualification passed:', ', '.join(runtimes))
    print('Receipts:', work)


if __name__ == '__main__':
    main()
