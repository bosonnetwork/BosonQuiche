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

"""Validate prebuilt JNI inputs and prepare native Maven artifacts."""

import argparse
import io
import json
from pathlib import Path
import shutil
import struct
import sys
import zipfile

import build_native as build
import native_config as config
from native_config import ROOT, TARGETS, digest, identity

DESKTOP = [name for name in TARGETS if not name.startswith('android-')]


def machine(path):
    """Check the executable's architecture without requiring native build tools."""
    with path.open('rb') as stream:
        header = stream.read(64)
        if len(header) < 64:
            raise ValueError('Truncated native executable: ' + str(path))
        if header[:4] == b'\x7fELF' and header[4] == 2 and header[5] == 1:
            return {62: 'EM_X86_64', 183: 'EM_AARCH64'}.get(struct.unpack_from('<H', header, 18)[0])
        if header[:4] == b'\xcf\xfa\xed\xfe':
            return 'arm64' if struct.unpack_from('<I', header, 4)[0] == 0x0100000c else None
        if header[:2] == b'MZ':
            stream.seek(struct.unpack_from('<I', header, 60)[0])
            pe = stream.read(6)
            if len(pe) == 6 and pe[:4] == b'PE\0\0':
                return {0x8664: 'IMAGE_FILE_MACHINE_AMD64', 0xaa64: 'IMAGE_FILE_MACHINE_ARM64'}.get(
                    struct.unpack_from('<H', pe, 4)[0])
    raise ValueError('Unsupported native executable: ' + str(path))


def validate(target, staged=None):
    directory = staged or ROOT / '.build/staged' / target / 'jni'
    manifest = build.validate_manifest(directory, target, 'jni')
    inputs = manifest['inputs']
    expected = {'binding_version': config.validate_inputs(), 'binding_abi': config.binding_abi(),
                'quiche_version': config.TAG, 'features': config.FEATURES,
                'quiche_tag': config.TAG, 'quiche_archive_sha256': config.ARCHIVE_SHA256,
                'quiche_archive_url': config.ARCHIVE_URL,
                'rust_target': TARGETS[target].rust, 'classifier': TARGETS[target].classifier,
                'binary_name': TARGETS[target].binary, 'baseline': TARGETS[target].baseline,
                'toolchains': json.loads((ROOT / 'native/toolchains.json').read_text()),
                'cargo_lock_sha256': digest(ROOT / 'native/Cargo.lock'),
                'cmake_sha256': digest(ROOT / 'native/CMakeLists.txt'),
                'jni_declarations_sha256': digest(ROOT / 'src/main/java/io/bosonnetwork/quiche/Native.java'),
                'jni_sources_sha256': identity({str(path.relative_to(ROOT)): digest(path)
                    for path in sorted((ROOT / 'src/main/c').glob('*')) if path.is_file()})}
    for key, value in expected.items():
        if inputs.get(key) != value:
            raise ValueError('Stale native input ' + target + ': ' + key)
    if manifest.get('binding_abi') != expected['binding_abi']:
        raise ValueError('Native manifest ABI mismatch: ' + target)
    binary = directory / TARGETS[target].binary
    if machine(binary) != TARGETS[target].machine:
        raise ValueError('Wrong native architecture: ' + target)
    # Source/ABI/SDK provenance stays in build.json. Packaging does not require
    # the original compiler, SDK or cache paths to remain installed locally.
    return directory, manifest


def zip_bytes(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(files.items()):
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, content)
    return output.getvalue()


def native_notices(directory, prefix):
    files = {prefix + '/LICENSE': (ROOT / 'LICENSE').read_bytes(),
             prefix + '/NOTICE': (ROOT / 'NOTICE').read_bytes()}
    for file in sorted((directory / 'licenses').rglob('*')):
        if file.is_file():
            files[prefix + '/licenses/' + file.relative_to(directory / 'licenses').as_posix()] = file.read_bytes()
    return files


def desktop(targets, output):
    # Validate the complete requested set before writing any artifact.
    validated = {target: validate(target) for target in targets}
    output.mkdir(parents=True, exist_ok=True)
    version = config.validate_inputs()
    for target, (directory, _) in validated.items():
        spec = TARGETS[target]
        prefix = 'native/' + spec.classifier
        files = {prefix + '/' + spec.binary: (directory / spec.binary).read_bytes(),
                 prefix + '/build.json': (directory / 'build.json').read_bytes()}
        files.update(native_notices(directory, 'META-INF/boson-quiche-native/' + spec.classifier))
        artifact = output / ('boson-quiche-native-' + version + '-' + spec.classifier + '.jar')
        artifact.write_bytes(zip_bytes(files))
        print('Packaged:', artifact)
    if len(targets) == 1:
        (output / 'selection.properties').write_text('native.classifier=' + TARGETS[targets[0]].classifier + '\n')


def android(output):
    directory, _ = validate('android-arm64')
    temporary = output.with_name(output.name + '.assembling')
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    files = {'AndroidManifest.xml': (ROOT / 'android/src/main/AndroidManifest.xml').read_bytes(),
             'proguard.txt': (ROOT / 'android/src/main/proguard.txt').read_bytes(),
             'classes.jar': zip_bytes({}), 'R.txt': b'',
             'jni/arm64-v8a/libboson_quiche.so': (directory / 'libboson_quiche.so').read_bytes(),
             'META-INF/boson-quiche-native/android-aarch64/build.json': (directory / 'build.json').read_bytes()}
    files.update(native_notices(directory, 'META-INF/boson-quiche-native/android-aarch64'))
    for name, content in files.items():
        file = temporary / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
    if output.exists():
        shutil.rmtree(output)
    temporary.replace(output)
    print('Prepared AAR contents:', output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('validate', 'desktop', 'android'))
    parser.add_argument('--distribution', choices=('true', 'false'), default='false')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    targets = list(TARGETS) if args.distribution == 'true' else [config.host_target()]
    if args.kind == 'validate':
        for target in targets:
            validate(target)
            print('Validated native packaging input:', target)
    elif args.output is None:
        parser.error('--output is required for archive preparation')
    elif args.kind == 'desktop':
        desktop(DESKTOP if args.distribution == 'true' else targets, args.output.resolve())
    else:
        android(args.output.resolve())


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        print('Native artifact packaging failed:', error, file=sys.stderr)
        sys.exit(1)

