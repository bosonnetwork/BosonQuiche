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

"""Bind platform qualification receipts to the actual Maven distribution."""

import hashlib
import zipfile

import release_support as release
from release_support import config


def repository_identity(repository):
    version = config.validate_inputs()
    release.test_artifacts.check(repository)
    files = {
        name: config.digest(repository / name)
        for name in release.artifact_paths(version)
    }
    natives = {}
    for target, spec in config.TARGETS.items():
        artifact = (
            'boson-quiche-android' if spec.jni == 'android' else 'boson-quiche-native'
        )
        suffix = '.aar' if spec.jni == 'android' else '-' + spec.classifier + '.jar'
        archive = (
            repository
            / 'io/bosonnetwork'
            / artifact
            / version
            / (artifact + '-' + version + suffix)
        )
        with zipfile.ZipFile(archive) as package:
            name = (
                'jni/' + spec.android_abi + '/' + spec.binary
                if spec.jni == 'android'
                else 'native/' + spec.classifier + '/' + spec.binary
            )
            natives[target] = hashlib.sha256(package.read(name)).hexdigest()
    return {
        'binding_version': version,
        'binding_abi': config.binding_abi(),
        'artifact_set_sha256': config.identity(files),
        'artifacts': files,
        'native_sha256': natives,
        'source_fingerprint': release.source_fingerprint(),
    }


def receipt(check, identity, **details):
    return dict(
        details,
        schema=1,
        check=check,
        status='passed',
        artifact_set_sha256=identity['artifact_set_sha256'],
        binding_version=identity['binding_version'],
        binding_abi=identity['binding_abi'],
        source_fingerprint=identity['source_fingerprint'],
    )


def sidecar(report, check, identity, **details):
    path = report.with_name(report.stem + '-' + check + '.json')
    release.write_json(path, receipt(check, identity, **details))
    return path
