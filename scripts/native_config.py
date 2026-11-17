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

"""Shared target definitions, pinned inputs and source preparation."""

from dataclasses import dataclass
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = json.loads((ROOT / 'native/quiche.json').read_text())
TAG = UPSTREAM['tag']
ARCHIVE_SHA256 = UPSTREAM['archive_sha256']
ARCHIVE_URL = f'https://github.com/cloudflare/quiche/archive/refs/tags/{TAG}.tar.gz'
FEATURES = UPSTREAM['features']


@dataclass(frozen=True)
class Target:
    platform: str
    rust: str
    classifier: str
    binary: str
    machine: str
    jni: str
    baseline: str


TARGETS = {target.platform: target for target in (
    Target('linux-amd64', 'x86_64-unknown-linux-gnu', 'linux-x86_64',
           'libboson_quiche.so', 'EM_X86_64', 'linux', 'glibc 2.28'),
    Target('linux-arm64', 'aarch64-unknown-linux-gnu', 'linux-aarch64',
           'libboson_quiche.so', 'EM_AARCH64', 'linux', 'glibc 2.28'),
    Target('macos-arm64', 'aarch64-apple-darwin', 'macos-aarch64',
           'libboson_quiche.dylib', 'arm64', 'darwin', 'macOS 11.0'),
    Target('android-arm64', 'aarch64-linux-android', 'android-aarch64',
           'libboson_quiche.so', 'EM_AARCH64', 'android', 'Android API 33'),
    Target('windows-amd64', 'x86_64-pc-windows-msvc', 'windows-x86_64',
           'boson_quiche.dll', 'IMAGE_FILE_MACHINE_AMD64', 'win32', 'Windows 10'),
    Target('windows-arm64', 'aarch64-pc-windows-msvc', 'windows-aarch64',
           'boson_quiche.dll', 'IMAGE_FILE_MACHINE_ARM64', 'win32', 'Windows 10'),
)}


def target_id(value):
    system, arch = value.lower().replace('/', '-').split('-', 1)
    system = {'darwin': 'macos'}.get(system, system)
    arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(arch, arch)
    result = system + '-' + arch
    if result not in TARGETS:
        raise ValueError('Unsupported native target: ' + value)
    return result


def host_target():
    return target_id(platform.system() + '-' + platform.machine())


def output(*command, env=None):
    return subprocess.check_output(command, text=True, env=env, stderr=subprocess.STDOUT)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii')).hexdigest()


def write_if_changed(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != text:
        path.write_text(text, encoding='ascii')


@contextmanager
def build_lock(path):
    """Serialize a target's cache and staging operations across build processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def clean_environment():
    # SDK and compiler settings are selected by the target, not inherited from
    # the shell that launched a cross-build.
    prefixes = ('CMAKE_', 'CARGO_TARGET_', 'CC_', 'CXX_', 'AR_', 'BINDGEN_')
    exact = {'SDKROOT', 'MACOSX_DEPLOYMENT_TARGET', 'IPHONEOS_DEPLOYMENT_TARGET',
             'CC', 'CXX', 'AR', 'CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS',
             'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'LIBCLANG_PATH',
             'CARGO_BUILD_TARGET', 'CPATH', 'LIBRARY_PATH', 'C_INCLUDE_PATH',
             'CPLUS_INCLUDE_PATH'}
    return {key: value for key, value in os.environ.items()
            if key not in exact and not key.startswith(prefixes)}


def validate_inputs(root=ROOT):
    pin = json.loads((root / 'native/quiche.json').read_text())
    if digest(root / 'native/quiche.h') != pin['header_sha256']:
        raise ValueError('Vendored quiche.h differs from the upstream pin')
    pom = ET.parse(root / 'pom.xml').getroot()
    ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
    if pom.findtext('m:properties/m:quiche.version', namespaces=ns) != pin['tag']:
        raise ValueError('Maven quiche.version differs from the upstream pin')
    docs = json.loads((root / 'native/api-docs.json').read_text())
    if docs['version'] != pin['tag']:
        raise ValueError('Documentation snapshot differs from the upstream pin')
    if not (root / 'native/Cargo.lock').is_file():
        raise ValueError('Missing native/Cargo.lock; refresh it explicitly')
    return pom.findtext('m:version', namespaces=ns)


def download_verified(url, destination, expected):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if digest(destination) != expected:
            raise ValueError('Cached download checksum mismatch: ' + str(destination))
        return
    temporary = destination.with_suffix(destination.suffix + '.part')
    try:
        with urllib.request.urlopen(url, timeout=60) as response, temporary.open('wb') as stream:
            shutil.copyfileobj(response, stream)
        if digest(temporary) != expected:
            raise ValueError('Downloaded file checksum mismatch: ' + url)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def extract_source(archive, destination):
    """Extract regular files and materialize safe in-tree links only."""
    destination = destination.resolve()
    with tarfile.open(archive) as package:
        regular, links = [], []
        for member in package.getmembers():
            if not (destination / member.name).resolve().is_relative_to(destination):
                raise ValueError('Unsafe upstream archive member: ' + member.name)
            if member.isfile() or member.isdir():
                regular.append(member)
            elif member.issym() or member.islnk():
                links.append(member)
            else:
                raise ValueError('Unsupported upstream archive member: ' + member.name)
        package.extractall(destination, members=regular)
        for member in links:
            path = destination / member.name
            linked = ((path.parent if member.issym() else destination) / member.linkname).resolve()
            if not linked.is_relative_to(destination):
                raise ValueError('Unsafe upstream archive link: ' + member.name)
            if linked.is_file():
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(linked, path)


def source_digest(source):
    files = {}
    for directory, dirs, names in os.walk(source, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in ('.git', 'target', '.build'))
        for name in sorted(names):
            path = Path(directory) / name
            if not path.resolve().is_relative_to(source.resolve()):
                raise ValueError('Source link escapes checkout: ' + str(path))
            if path.is_file():
                files[path.relative_to(source).as_posix()] = digest(path)
    return identity(files)


def prepare_source(supplied=''):
    if supplied:
        source = Path(supplied).resolve()
    else:
        archive = ROOT / f'.build/downloads/quiche-{TAG}.tar.gz'
        legacy = ROOT / f'target/quiche-{TAG}.tar.gz'
        if not archive.exists() and legacy.is_file() and digest(legacy) == ARCHIVE_SHA256:
            archive.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(legacy, archive)
        download_verified(ARCHIVE_URL, archive, ARCHIVE_SHA256)
        source = ROOT / f'.build/sources/quiche-{TAG}'
        if not source.exists():
            temporary = ROOT / '.build/sources/extracting'
            if temporary.exists():
                shutil.rmtree(temporary)
            extract_source(archive, temporary)
            source.parent.mkdir(parents=True, exist_ok=True)
            (temporary / f'quiche-{TAG}').replace(source)
            shutil.rmtree(temporary)
    if not (source / 'quiche/include/quiche.h').is_file():
        raise ValueError('--source must point to a quiche source checkout')
    if digest(source / 'quiche/include/quiche.h') != UPSTREAM['header_sha256']:
        raise ValueError('Source header differs from the pinned quiche API')
    manifest = (source / 'quiche/Cargo.toml').read_text()
    if not re.search(r'^version\s*=\s*"' + re.escape(TAG) + r'"', manifest, re.M):
        raise ValueError('Source package version differs from the upstream pin')
    return source

