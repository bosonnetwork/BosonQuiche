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

"""Report the local toolchain state for host or full cross-builds; installs nothing."""

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'native/scripts'))
import buildlog
import native_config as config
import native_toolchains as toolchains

PYTHON_MINIMUM = '3.9'
JDK_MINIMUM = '11'
HEADER = ('tool', 'found', 'required', 'status')


def capture(*command):
    """Return the merged output of a probe command, or '' when it cannot run."""
    try:
        result = subprocess.run(
            list(map(str, command)),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError:
        return ''
    return result.stdout if result.returncode == 0 else ''


def first_line(text):
    lines = text.strip().splitlines()
    return lines[0].strip() if lines else ''


def version_at_least(found, minimum):
    def parts(text):
        return tuple(int(item) for item in re.findall(r'\d+', str(text)))

    value, required = parts(found), parts(minimum)
    if not value:
        return False
    return value >= required + (0,) * max(len(value) - len(required), 0)


def row(tool, found, required, ok, hint=None):
    return {
        'cells': (tool, found, required, 'ok' if ok else 'missing'),
        'ok': ok,
        'hint': hint,
    }


def python_row():
    version = platform.python_version()
    ok = version_at_least(version, PYTHON_MINIMUM)
    return row('python3', version, '>= ' + PYTHON_MINIMUM, ok,
               None if ok else 'install Python ' + PYTHON_MINIMUM + ' or newer')


def rust_row(pins):
    text = first_line(capture('rustc', '--version'))
    found = re.search(r'rustc (\S+)', text)
    ok = toolchains.rust_version_supported(text, pins['rust_minimum'])
    return row('rustc', found[1] if found else 'not found', '>= ' + pins['rust_minimum'], ok,
               None if ok else 'rustup update stable (quiche ' + config.TAG
               + ' needs ' + pins['rust_minimum'] + ')')


def cargo_row(pins):
    text = first_line(capture('cargo', '--version'))
    found = re.search(r'cargo (\S+)', text)
    ok = found is not None and version_at_least(found[1], pins['rust_minimum'])
    return row('cargo', found[1] if found else 'not found', '>= ' + pins['rust_minimum'], ok,
               None if ok else 'rustup update stable')


def cmake_row(pins):
    text = first_line(capture('cmake', '--version'))
    found = re.search(r'cmake version (\S+)', text)
    ok = found is not None and version_at_least(found[1], pins['cmake_minimum'])
    return row('cmake', found[1] if found else 'not found', '>= ' + pins['cmake_minimum'], ok,
               None if ok else 'install CMake ' + pins['cmake_minimum'] + ' or newer')


def compiler_row():
    if platform.system() == 'Darwin':
        text = first_line(capture('xcrun', 'clang', '--version'))
        sdk = capture('xcrun', '--show-sdk-version').strip()
        version = re.search(r'clang version (\S+)', text)
        ok = version is not None
        found = (('Apple clang ' + version[1]) if ok else 'not found') + (' (SDK ' + sdk + ')' if sdk else '')
        return row('clang', found, 'Xcode tools', ok,
                   None if ok else 'xcode-select --install')
    text = first_line(capture('cc', '--version'))
    return row('cc', text or 'not found', 'C toolchain', bool(text),
               None if text else 'install gcc and the libc development files')


def jdk_home():
    """Resolve the JDK the native build would use, without requiring JAVA_HOME."""
    home = os.environ.get('JAVA_HOME')
    if home:
        return Path(home)
    if platform.system() == 'Darwin':
        found = capture('/usr/libexec/java_home').strip()
        if found:
            return Path(found)
    javac = shutil.which('javac')
    return Path(javac).resolve().parents[1] if javac else None


def jdk_row():
    text = first_line(capture('javac', '-version')) or first_line(capture('java', '-version'))
    found = re.search(r'(\d+(?:\.\d+)*)', text)
    home = jdk_home()
    headers = home / 'include/jni.h' if home else None
    version_ok = found is not None and version_at_least(found[1], JDK_MINIMUM)
    headers_ok = headers is not None and headers.is_file()
    if not version_ok:
        hint = 'install JDK ' + JDK_MINIMUM + '+ and put javac on PATH'
    elif not headers_ok:
        hint = 'set JAVA_HOME to a JDK so that include/jni.h is available'
    else:
        hint = None
    return row('javac', found[1] if found else 'not found', '>= ' + JDK_MINIMUM,
               version_ok and headers_ok, hint)


def maven_row():
    text = first_line(capture('mvn', '-v'))
    found = re.search(r'Apache Maven (\S+)', text)
    ok = found is not None
    return row('mvn', found[1] if found else 'not found', 'Maven 3.9+', ok,
               None if ok else 'install Maven 3.9+ or run the Maven steps through ./mvnw')


def llvm_tools_row():
    text = capture('rustup', 'component', 'list', '--installed')
    ok = 'llvm-tools' in text
    return row('llvm-tools', 'installed' if ok else 'not installed', 'rustup component', ok,
               None if ok else 'rustup component add llvm-tools')


def android_target_row():
    text = capture('rustup', 'target', 'list', '--installed')
    ok = 'aarch64-linux-android' in text
    return row('rust target', 'aarch64-linux-android' if ok else 'not installed',
               'android-arm64 build', ok,
               None if ok else 'rustup target add aarch64-linux-android')


def docker_row():
    version = capture('docker', 'version', '--format', '{{.Server.Version}}').strip()
    ok = bool(version)
    return row('docker', 'engine ' + version if ok else 'not running', 'Docker engine', ok,
               None if ok else 'start Docker Desktop or OrbStack')


def ndk_row(pins):
    minimum = pins['android']['minimum_revision']
    entry = toolchains.find_ndk(pins)
    if entry is None:
        return row('ndk', 'not found', '>= ' + minimum, False,
                   'sdkmanager "ndk;' + minimum + '" installs it in the Android SDK;'
                   ' ANDROID_NDK_HOME can point at an existing install')
    found = entry['revision'] + ' (' + entry['source'] + ')'
    if entry['ok']:
        return row('ndk', found, '>= ' + minimum, True)
    return row('ndk', found, '>= ' + minimum, False,
               'point ANDROID_NDK_HOME at a newer NDK or install one in the Android SDK')


def image_row(image, pins):
    identity = capture('docker', 'image', 'inspect', image, '--format', '{{.Id}}').strip()
    label = 'image ' + image.rsplit(':', 1)[1]
    if identity:
        return row(label, identity.replace('sha256:', '')[:12], 'built', True)
    if image == pins['windows_image']:
        recipe = 'docker buildx build --platform linux/arm64 -f native/docker/Dockerfile.windows'
    else:
        architecture = image.rsplit('-', 1)[1]
        recipe = ('docker buildx build --platform linux/' + architecture
                  + ' -f native/docker/Dockerfile.linux')
    return row(label, 'not built', 'built', False,
               recipe + ' -t ' + image + ' --load native/docker')


def host_row():
    system, machine = platform.system(), platform.machine()
    found = system + ' ' + machine
    if system == 'Darwin' and machine != 'arm64':
        return row('host', found, 'Apple Silicon', False,
                   'macOS and Android native builds require an Apple Silicon Mac')
    return row('host', found, 'native build host', True)


def rows_for(mode, pins):
    rows = [host_row(), python_row(), rust_row(pins), cargo_row(pins), cmake_row(pins),
            compiler_row(), jdk_row(), maven_row()]
    if mode == 'cross-build':
        rows += [llvm_tools_row(), android_target_row(), docker_row(), ndk_row(pins)]
        rows += [image_row(image, pins) for image in
                 (pins['windows_image'],
                  pins['linux_image_prefix'] + 'arm64',
                  pins['linux_image_prefix'] + 'amd64')]
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--mode',
        choices=('host', 'cross-build'),
        default='host',
        help='host: tools the local Maven build needs (default); '
             'cross-build: also Docker images, the NDK and cross targets',
    )
    args = parser.parse_args(argv)
    pins = json.loads((config.ROOT / 'native/toolchains.json').read_text())
    rows = rows_for(args.mode, pins)
    buildlog.step(args.mode + ' toolchain (' + config.host_target() + ')'
                  + (' - all six targets' if args.mode == 'cross-build' else ''))
    buildlog.table([HEADER] + [item['cells'] for item in rows], indent='  ')
    if args.mode == 'cross-build':
        ndk = toolchains.find_ndk(pins)
        if ndk:
            buildlog.info('ndk: ' + str(ndk['path']))
    missing = [item for item in rows if not item['ok']]
    for item in missing:
        if item['hint']:
            buildlog.warn(item['cells'][0] + ': ' + item['hint'])
    if missing:
        buildlog.fail(str(len(missing)) + ' requirement(s) missing or too old; nothing was installed')
        return 1
    buildlog.done('every requirement for ' + args.mode + ' builds is present')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError) as error:
        buildlog.fail('toolchain check failed: ' + str(error))
        sys.exit(1)
