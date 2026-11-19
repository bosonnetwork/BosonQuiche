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

"""Synthetic release fixtures; their payloads must never be published or executed."""

import io
import json
from pathlib import Path
import re
import shutil
import struct
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import release_support as release
from release_support import config, packaging
import build_native

VERSION = '0.30.1.1'


def zip_bytes(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)), content)
    return output.getvalue()


def binary(target, version):
    data = bytearray(256)
    if target.startswith('windows-'):
        data[:2] = b'MZ'
        struct.pack_into('<I', data, 60, 128)
        data[128:132] = b'PE\0\0'
        struct.pack_into(
            '<H', data, 132, 0x8664 if target.endswith('amd64') else 0xAA64
        )
    elif target.startswith('macos-'):
        data[:4] = b'\xcf\xfa\xed\xfe'
        struct.pack_into('<I', data, 4, 0x0100000C)
        struct.pack_into('<II', data, 16, 1, 24)
        struct.pack_into('<IIIIII', data, 32, 0x32, 24, 1, 0x000B0000, 0, 0)
    else:
        data[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<H', data, 18, 62 if target.endswith('amd64') else 183)
        struct.pack_into('<Q', data, 32, 64)
        struct.pack_into('<HH', data, 54, 56, 1)
        struct.pack_into('<IIQQQQQQ', data, 64, 1, 5, 0, 0, 0, 256, 256, 16384)
    return (
        bytes(data)
        + version.encode()
        + b'\0GLIBC_2.28\0SYNTHETIC TEST FIXTURE - NEVER PUBLISH\0'
    )


def create(root):
    source = release.ROOT
    for folder in (
        'api/src',
        'native/src',
        'android/src',
        'native/scripts',
        'native/docker',
        'scripts',
        '.mvn',
    ):
        shutil.copytree(
            source / folder,
            root / folder,
            ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'target', 'build'),
        )
    for file in (
        'LICENSE',
        'NOTICE',
        'native/quiche.h',
        'native/quiche.json',
        'native/api-docs.json',
        'native/Cargo.lock',
        'native/toolchains.json',
        'native/CMakeLists.txt',
        'native/copyright-header.txt',
    ):
        destination = root / file
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / file, destination)
    for module in release.MODULES.values():
        destination = root / module / 'pom.xml'
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            (source / module / 'pom.xml')
            .read_text()
            .replace('0.30.1.1-SNAPSHOT', VERSION)
        )
    (root / 'SYNTHETIC-RELEASE-DO-NOT-PUBLISH').write_text(
        'Automated fixture, not a release.\n'
    )
    pins = json.loads((root / 'native/toolchains.json').read_text())
    declarations = (
        root / 'api/src/main/java/io/bosonnetwork/quiche/Native.java'
    ).read_text()
    exports = sorted(
        {'JNI_OnLoad', 'JNI_OnUnload'}
        | {
            'Java_io_bosonnetwork_quiche_Native_' + name
            for name in re.findall(r'static native \S+ (\w+)\(', declarations)
        }
    )
    manifests = {}
    for target, spec in config.TARGETS.items():
        directory = root / '.build/staged' / target / 'jni'
        directory.mkdir(parents=True)
        (directory / spec.binary).write_bytes(binary(target, VERSION))
        (directory / 'licenses').mkdir()
        (directory / 'licenses/LICENSE').write_text(
            'Synthetic fixture license notice\n'
        )
        inputs = build_native.build_inputs(
            target, 'synthetic-source-tree', VERSION, pins, {}
        )
        manifest = {
            'schema': 1,
            'status': 'passed',
            'stage': 'jni',
            'platform': target,
            'rust_target': spec.rust,
            'classifier': spec.classifier,
            'machines': [spec.machine],
            'binding_version': VERSION,
            'binding_abi': 1,
            'quiche_version': config.TAG,
            'inputs': inputs,
            'input_identity': config.identity(inputs),
            'jni_exports': exports,
            'source_revision': 'synthetic-fixture',
            'native': {
                'status': 'passed',
                'source_archive_sha256': config.ARCHIVE_SHA256,
            },
            'files': {
                name: config.digest(directory / name)
                for name in (spec.binary, 'licenses/LICENSE')
            },
        }
        release.write_json(directory / 'build.json', manifest)
        manifests[target] = manifest
    paths = release.artifact_paths(VERSION, root)
    for name, path in paths.items():
        if name.endswith('.pom'):
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        artifact = name.split('/')[2]
        filename = path.name
        files = {'README.md': b'SYNTHETIC TEST FIXTURE - NEVER PUBLISH\n'}
        if artifact == 'boson-quiche':
            if filename.endswith('-sources.jar'):
                files['io/bosonnetwork/quiche/Quiche.java'] = (
                    b'// Synthetic source fixture\n'
                )
            elif filename.endswith('-javadoc.jar'):
                files['io/bosonnetwork/quiche/Quiche.html'] = (
                    b'Synthetic documentation fixture'
                )
            else:
                files['io/bosonnetwork/quiche/Native.class'] = (
                    b'not executable - synthetic fixture'
                )
                files['META-INF/boson-quiche.properties'] = (
                    'binding.version='
                    + VERSION
                    + '\nbinding.abi=1\nquiche.version='
                    + config.TAG
                    + '\n'
                ).encode()
        elif artifact == 'boson-quiche-native':
            target = next(
                target
                for target, spec in config.TARGETS.items()
                if filename.endswith('-' + spec.classifier + '.jar')
            )
            spec = config.TARGETS[target]
            directory = root / '.build/staged' / target / 'jni'
            prefix = 'native/' + spec.classifier + '/'
            notices = 'META-INF/boson-quiche-native/' + spec.classifier + '/'
            files = {
                prefix + spec.binary: (directory / spec.binary).read_bytes(),
                prefix + 'build.json': (directory / 'build.json').read_bytes(),
                notices + 'LICENSE': b'fixture',
                notices + 'NOTICE': b'fixture',
            }
        elif filename.endswith('.aar'):
            directory = root / '.build/staged/android-arm64/jni'
            prefix = 'META-INF/boson-quiche-native/android-aarch64/'
            files.update(
                {
                    'AndroidManifest.xml': (
                        root / 'android/src/main/AndroidManifest.xml'
                    ).read_bytes(),
                    'classes.jar': zip_bytes({}),
                    'proguard.txt': (
                        root / 'android/src/main/proguard.txt'
                    ).read_bytes(),
                    'jni/arm64-v8a/libboson_quiche.so': (
                        directory / 'libboson_quiche.so'
                    ).read_bytes(),
                    prefix + 'build.json': (directory / 'build.json').read_bytes(),
                    prefix + 'LICENSE': b'fixture',
                }
            )
        path.write_bytes(zip_bytes(files))
        if filename.endswith('.aar'):
            path.with_suffix('.jar').write_bytes(path.read_bytes())
    targets = release.validate_natives(root)
    for item in targets.values():
        item.update(
            build='passed',
            inspection='passed',
            runtime={'status': 'unverified', 'reason': 'Synthetic fixture'},
        )
    validation = {
        'schema': 1,
        'fixture': True,
        'scope': 'distribution',
        'binding_version': VERSION,
        'binding_abi': 1,
        'source_fingerprint': release.source_fingerprint(root),
        'artifacts': release.hashes(paths),
        'targets': targets,
        'checks': {
            name: {'status': 'passed', 'fixture': True}
            for name in release.REQUIRED_CHECKS
        },
    }
    return validation
