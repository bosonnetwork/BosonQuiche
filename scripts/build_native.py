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

"""Build the host JNI library against pinned, unmodified quiche sources."""
import argparse
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

ROOT = Path(__file__).resolve().parents[1]
TAG = "0.30.1"
ARCHIVE_URL = f"https://github.com/cloudflare/quiche/archive/refs/tags/{TAG}.tar.gz"
ARCHIVE_SHA256 = "c2c55d42677f0f1f42045e4c3e31469dc2107059bb519551b4c1c5a42f662a51"


def run(*args, **kwargs):
    print("Running:", *args, flush=True)
    subprocess.run(args, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="")
    parser.add_argument("--skip", default="false")
    parser.add_argument("--quiche-only", action="store_true")
    parser.add_argument("--update-lock", action="store_true")
    args = parser.parse_args()
    if args.skip.lower() == "true":
        return
    target = ROOT / "target"
    target.mkdir(exist_ok=True)
    source = Path(args.source).resolve() if args.source else target / f"quiche-{TAG}"
    if not args.source and not source.exists():
        archive = target / f"quiche-{TAG}.tar.gz"
        with urllib.request.urlopen(ARCHIVE_URL, timeout=60) as response:
            with archive.open("wb") as output:
                shutil.copyfileobj(response, output)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
            raise SystemExit("Pinned upstream archive checksum mismatch")
        with tarfile.open(archive) as tar:
            destination = (target / "upstream").resolve()
            regular = []
            links = []
            for member in tar.getmembers():
                if not (destination / member.name).resolve().is_relative_to(destination):
                    raise SystemExit("Unsafe upstream archive member")
                if member.isfile() or member.isdir():
                    regular.append(member)
                elif member.issym() or member.islnk():
                    links.append(member)
                else:
                    raise SystemExit("Unsupported upstream archive member")
            # Never create archive links. Materialize in-tree file links such
            # as quiche/COPYING; directory links in tools are not build inputs.
            tar.extractall(destination, members=regular)
            for member in links:
                output = destination / member.name
                linked = ((output.parent if member.issym() else destination) / member.linkname).resolve()
                if linked.is_relative_to(destination) and linked.is_file():
                    output.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(linked, output)
        shutil.move(str(target / "upstream" / f"quiche-{TAG}"), source)
    if not (source / "quiche/include/quiche.h").is_file():
        raise SystemExit("--source must point to a quiche source checkout")
    if (source / "quiche/include/quiche.h").read_bytes() != (ROOT / "native/quiche.h").read_bytes():
        raise SystemExit(f"Source header differs from the pinned quiche {TAG} API")
    # An isolated Cargo workspace resolves only quiche's dependencies. It does
    # not write build products or Cargo.lock into the supplied source checkout.
    build = target / "native"
    build.mkdir(exist_ok=True)
    crate = build / "driver"
    (crate / "src").mkdir(parents=True, exist_ok=True)
    manifest = (
        '[package]\nname = "boson-quiche-build"\nversion = "0.1.0"\nedition = "2021"\n'
        '[workspace]\n[lib]\ncrate-type = ["staticlib"]\n'
        '[dependencies]\nquiche = { path = ' + json.dumps(str(source / "quiche")) +
        ', features = ["ffi", "qlog", "gcongestion", "sfv"] }\n'
        '[profile.release]\ndebug = false\n')
    if not (crate / "Cargo.toml").exists() or (crate / "Cargo.toml").read_text() != manifest:
        (crate / "Cargo.toml").write_text(manifest, encoding="ascii")
    rust_source = (
        (ROOT / "native/copyright-header.txt").read_text() +
        '// Generated by scripts/build_native.py.\n'
        'pub use quiche::*;\n')
    if not (crate / "src/lib.rs").exists() or (crate / "src/lib.rs").read_text() != rust_source:
        (crate / "src/lib.rs").write_text(rust_source, encoding="ascii")
    lock = ROOT / "native/Cargo.lock"
    if lock.exists():
        shutil.copyfile(lock, crate / "Cargo.lock")
    cargo_env = dict(os.environ, CARGO_TARGET_DIR=str(build / "rust"))
    if platform.system() == "Darwin":
        cargo_env.setdefault("MACOSX_DEPLOYMENT_TARGET", "11.0")
        toolchain = build / "macos-toolchain.cmake"
        sdk = subprocess.check_output(["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True).strip()
        toolchain.write_text('set(CMAKE_SYSTEM_NAME Darwin)\n'
                             f'set(CMAKE_OSX_SYSROOT "{sdk}")\n'
                             f'set(CMAKE_OSX_ARCHITECTURES "{platform.machine()}")\n'
                             f'set(CMAKE_OSX_DEPLOYMENT_TARGET "{cargo_env["MACOSX_DEPLOYMENT_TARGET"]}" CACHE STRING "" FORCE)\n', encoding="ascii")
        cargo_env["CMAKE_TOOLCHAIN_FILE"] = str(toolchain)
    # Keep Cargo caches within the writable project so sandboxed builds work.
    cargo_env["CARGO_HOME"] = str(target / "cargo-home")
    if args.update_lock:
        run("cargo", "generate-lockfile", "--manifest-path", str(crate / "Cargo.toml"), env=cargo_env)
        shutil.copyfile(crate / "Cargo.lock", lock)
    run("cargo", "build", "--release", "--manifest-path", str(crate / "Cargo.toml"),
        *(["--locked"] if lock.exists() else []), env=cargo_env)
    if not lock.exists():
        lock.parent.mkdir(exist_ok=True)
        shutil.copyfile(crate / "Cargo.lock", lock)
    if args.quiche_only:
        return
    java_home = os.environ.get("JAVA_HOME")
    if not java_home and platform.system() == "Darwin":
        java_home = subprocess.check_output(["/usr/libexec/java_home"], text=True).strip()
    if not java_home:
        java_home = str(Path(shutil.which("javac")).resolve().parents[1])
    system = platform.system()
    os_name = {"Darwin": "macos", "Linux": "linux"}.get(system)
    if not os_name:
        raise SystemExit("This build script currently supports macOS and Linux hosts")
    arch = {"arm64": "aarch64", "AMD64": "x86_64"}.get(platform.machine(), platform.machine())
    name = "libboson_quiche." + ("dylib" if system == "Darwin" else "so")
    output = target / "generated-resources/native" / f"{os_name}-{arch}"
    output.mkdir(parents=True, exist_ok=True)
    # Export only JNI entry points. Hide the statically linked BoringSSL and
    # Rust symbols so Netty or another TLS library can coexist in the JVM.
    exports = build / "jni.exports"
    methods = re.findall(r'static native \S+ (\w+)\(', (ROOT / "src/main/java/io/bosonnetwork/quiche/Native.java").read_text())
    if system == "Darwin":
        exports.write_text('\n'.join(["_JNI_OnLoad", "_JNI_OnUnload"] +
                                    ["_Java_io_bosonnetwork_quiche_Native_" + method for method in methods]) + '\n', encoding="ascii")
        linker_exports = ["-Wl,-exported_symbols_list," + str(exports), "-Wl,-install_name,@rpath/" + name]
    else:
        exports.write_text('{ global: JNI_OnLoad; JNI_OnUnload; Java_io_bosonnetwork_quiche_Native_*; local: *; };\n', encoding="ascii")
        linker_exports = ["-Wl,--version-script=" + str(exports), "-Wl,-z,defs"]
    run(os.environ.get("CC", "cc"), "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
        "-Wno-unused-parameter", "-fPIC", "-fvisibility=hidden",
        "-dynamiclib" if system == "Darwin" else "-shared",
        *(["-mmacosx-version-min=" + cargo_env["MACOSX_DEPLOYMENT_TARGET"]] if system == "Darwin" else []),
        "-I" + str(Path(java_home) / "include"),
        "-I" + str(Path(java_home) / "include" / ("darwin" if system == "Darwin" else "linux")),
        "-I" + str(source / "quiche/include"),
        str(ROOT / "src/main/c/boson_quiche.c"),
        str(build / "rust/release/libboson_quiche_build.a"),
        *linker_exports,
        *(["-framework", "Security", "-framework", "CoreFoundation", "-lresolv", "-lc++"]
          if system == "Darwin" else ["-lpthread", "-ldl", "-lm", "-lstdc++"]),
        "-o", str(output / name))
    # Keep host debugging sidecars outside runtime JAR resources.
    debug_bundle = output / (name + ".dSYM")
    if debug_bundle.exists():
        debug_destination = build / debug_bundle.name
        if debug_destination.exists():
            shutil.rmtree(debug_destination)
        shutil.move(str(debug_bundle), debug_destination)
    previous_debug = target / "classes/native" / f"{os_name}-{arch}" / debug_bundle.name
    if previous_debug.exists():
        shutil.rmtree(previous_debug)
    licenses = target / "generated-resources/META-INF/native-licenses"
    packages = re.findall(r'\[\[package\]\]\nname = "([^"]+)"\nversion = "([^"]+)"', lock.read_text())
    for package, version in packages:
        for directory in (target / "cargo-home/registry/src").glob(f"*/{package}-{version}"):
            for license_file in directory.iterdir():
                if license_file.is_file() and (license_file.name.startswith("LICENSE") or license_file.name.startswith("COPYING")):
                    dest = licenses / f"{package}-{version}"
                    dest.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(license_file, dest / license_file.name)
            if package == "boring-sys":
                dest = licenses / "BoringSSL"
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(directory / "deps/boringssl/LICENSE", dest / "LICENSE")
    for package in ("octets", "qlog"):
        if (source / package / "COPYING").exists():
            dest = licenses / package
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / package / "COPYING", dest / "COPYING")
    (output / "build.json").write_text(json.dumps({
        "quiche_version": TAG, "quiche_tag": TAG,
        "quiche_archive_url": ARCHIVE_URL, "quiche_archive_sha256": ARCHIVE_SHA256,
        "cargo_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "features": ["ffi", "qlog", "gcongestion", "sfv"], "target": f"{os_name}-{arch}"
    }, indent=2) + '\n', encoding="ascii")


if __name__ == "__main__":
    main()
