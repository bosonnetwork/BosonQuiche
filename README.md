# Boson Quiche

Standalone Maven/JNI bindings for Cloudflare quiche 0.30.1. No Boson, Netty,
Vert.x, ice4j or other Java runtime dependencies are required. The library owns
no sockets, threads or event loops. QUIC and HTTP/3 are both available; HTTP/3
is optional for applications.

## Maven artifacts

All artifacts use the same binding version, currently `0.30.1.1-SNAPSHOT`.
The first three version components identify the upstream quiche release; the
fourth is the BosonQuiche release number.

| Artifact | Packaging | Contents |
| --- | --- | --- |
| `io.bosonnetwork:boson-quiche-parent` | POM | Independent project parent |
| `io.bosonnetwork:boson-quiche` | JAR | Java API and loader; sources and JavaDoc attachments |
| `io.bosonnetwork:boson-quiche-native` | Classified JARs | One desktop native library per classifier |
| `io.bosonnetwork:boson-quiche-android` | AAR | Android ARM64 library and consumer keep rules; depends on the API |

For a desktop JVM, select the API and a native classifier explicitly:

```xml
<dependency>
    <groupId>io.bosonnetwork</groupId>
    <artifactId>boson-quiche</artifactId>
    <version>0.30.1.1-SNAPSHOT</version>
</dependency>
<dependency>
    <groupId>io.bosonnetwork</groupId>
    <artifactId>boson-quiche-native</artifactId>
    <version>0.30.1.1-SNAPSHOT</version>
    <classifier>macos-aarch64</classifier>
    <scope>runtime</scope>
</dependency>
```

Available desktop classifiers are `linux-x86_64`, `linux-aarch64`,
`macos-aarch64`, `windows-x86_64` and `windows-aarch64`. Multiple classifiers
can coexist on the classpath; their native resources, notices and metadata
have distinct paths. The API POM does not select a native platform.

Android applications use an ordinary transitive AAR dependency:

```groovy
dependencies {
    implementation 'io.bosonnetwork:boson-quiche-android:0.30.1.1-SNAPSHOT'
}
```

The AAR requires Android API 33 or later and includes
`jni/arm64-v8a/libboson_quiche.so`. It supplies JNI keep rules for R8/ProGuard
and obtains Java classes from its API dependency. Consumer builds require no
Rust, NDK or CMake. Artifact availability depends on the configured Maven
repository; these coordinates also work with a local file repository.

Desktop native libraries are extracted from `native/<classifier>/` into a
private temporary directory. An explicit library can be selected with
`-Dboson.quiche.library=/absolute/path/to/libboson_quiche.dylib` (or `.so` or
`.dll`). Android uses `System.loadLibrary("boson_quiche")`. The loader checks
the internal binding ABI, exact binding version and upstream version before
ordinary native calls. `Quiche.version()` reports the upstream version,
`0.30.1`. Native quiche/BoringSSL symbols are hidden to allow coexistence with
other TLS implementations.

## Build

Requirements: JDK 11+, Maven 3.6+, Python 3.9+, Rust 1.88+, C/C++ compiler,
CMake 3.22+ and the host platform development tools. These are minimums:
newer compilers, SDKs and build tools are accepted, and only the values in
[native/toolchains.json](native/toolchains.json) and `native/CMakeLists.txt`
are checked. Release bundling and
publishing require Maven 3.9.2+. The Maven JNI build supports
macOS and Linux hosts. Cross-platform JNI builds for all six targets use the
toolchains described below. Runtime regressions cover macOS arm64, Linux
amd64/arm64 and Android arm64 on API 33 with 4 KB pages and API 37 with 16 KB
pages. Android checks include the R8-minified packaged consumer and CheckJNI.
Windows ARM64 and x64 JVMs also pass all 47 JNI tests and the packaged consumer.
The Windows x64 runtime checks use x64 emulation on Windows ARM64.

Install the LLVM tools component for the selected Rust toolchain before building:

```sh
rustup component add llvm-tools
mvn verify
```

The first build downloads the upstream source pinned to release tag `0.30.1`
from `https://github.com/cloudflare/quiche/archive/refs/tags/0.30.1.tar.gz`
and verifies its SHA-256 checksum. [native/quiche.json](native/quiche.json)
defines the upstream tag, source/header checksums and features. The builder
checks agreement with Maven's `quiche.version` and the API documentation
snapshot. Native dependencies are pinned by
`native/Cargo.lock`; the `ffi`, `qlog`,
`gcongestion` and `sfv` features are enabled. BoringSSL is built and linked
with quiche. No system installation of quiche or BoringSSL is required.

To build against an existing checkout with the matching public header:

```sh
mvn -Dquiche.source=/absolute/path/to/quiche verify
```

Host sources, native build products and Cargo caches are under ignored `.build/`.
Docker builds keep incremental work and dependencies in named volumes, as
described under [native toolchains](#cross-platform-native-toolchains). A
supplied checkout is not modified.

Maven builds the host native library by running CMake from the `native` module;
CMake in turn drives Cargo for the pinned quiche archive. No Maven lifecycle
phase runs Python. The build tree stays in `native/target/cmake` and the install
tree in `native/target/native-install`, which is where the Java JNI tests find
both the library and the loader fixtures. `mvn clean` removes both, so the next
build recompiles the native code. The same build works without Maven:

```sh
cd native
cmake --preset host-macos-arm64 -DBOSON_BINDING_ABI=1 \
    -DBOSON_BINDING_VERSION=0.30.1.1-SNAPSHOT
cmake --build target/cmake --parallel 4
```

Use `host-linux-amd64` or `host-linux-arm64` on Linux. Maven selects the preset
automatically; presets carry the deployment target, JNI platform and target
triple, while `native/platforms.json` remains the single platform matrix.

The project has its own parent POM and manages its dependency versions
independently of other Boson projects. Normal `verify` builds the host native
library, runs host JNI tests and attaches the host native classifier JAR. Build
outputs are under `native/target/` and `api/target/`. The Java API JAR contains
no native libraries or test fixtures. `-Dnative.skip=true` is an expert escape
hatch that reuses an existing `native/target/native-install` tree; it needs a
previous host build in the same workspace.

The API module declares the host native classifier as a test dependency, so any
build that runs the JNI tests must reach the `package` phase where that
classifier JAR is attached. Use `mvn verify` (or `mvn -pl native,api verify`);
`mvn test` alone cannot resolve the classifier and stops with a dependency
error. Building the API module in isolation needs the classifier in the local
repository or `-am`/`-pl native,api`.

After building all six staged JNI targets, package the complete distribution:

```sh
python3 native/scripts/build_native.py --all
mvn -Pdistribution -DskipTests verify
```

The `distribution` profile adds the Android module and attaches all five
desktop JARs. It validates the complete staged set before packaging, rejecting
missing files, changed checksums, incompatible versions/ABI, source or
dependency pin changes, and incorrect architectures. Prebuilt packaging does
not require the original compiler or SDK caches to remain installed. Build
provenance stays in each artifact's `build.json`.

The AAR is produced by Maven using a pinned `aar` lifecycle provider and
standard ZIP/JAR assembly. Maven creates and attaches the desktop classifier
JARs and Android source/documentation JARs. Python validates native inputs and
stages their resources. Production builds do not invoke Gradle. The AAR's
published POM retains `aar` packaging and its transitive API dependency.
Its output is `android/target/boson-quiche-android-<version>.aar`, with source
and documentation companion JARs for Maven Central. Use `-Pandroid` to build or
check only the AAR (`mvn -Pandroid verify` after staging `android-arm64`); the
`distribution` profile additionally needs every desktop classifier staged.
See [consumer verification](test-tooling/README.md) for isolated repository,
JVM and minified Android consumer checks.

The repository ships a verification-only GitHub Actions workflow
(`.github/workflows/ci.yml`) with generated-sources, macOS arm64 and Linux
amd64/arm64 jobs. It never signs or publishes: release artifacts still come from
the pinned builder path described above, because runner images drift and the
frozen checksums require byte-identical rebuilds.

## Release preparation

Build and record the complete local distribution with:

```sh
python3 scripts/build_all.py --targets all
```

The run prints a per-target and per-check summary as it finishes and writes the
same table to `.build/validation/summary.md` next to the validation record.

Android builds use an NDK that already exists on the machine. The builder looks
at `ANDROID_NDK_HOME`, `ANDROID_NDK_ROOT` and the installed SDKs (`ANDROID_HOME`,
`ANDROID_SDK_ROOT`, the Android Studio default locations), preferring the pinned
revision and accepting anything at or above the configured minimum. It never
installs one: `sdkmanager "ndk;<revision>"` or an explicit `ANDROID_NDK_HOME`
supplies it, and `python3 scripts/check_toolchain.py` reports what the machine
provides before you build.

After setting a matching release version before building, freeze the exact
artifact files with `python3 scripts/prepare_release.py --version 0.30.1.1`.
Preparation rejects snapshots, mixed versions, stale inputs and incomplete
build validation. Standard Maven packaging, signing and publishing check that
the outputs match the frozen artifact checksums;
publication waits for manual review in the Portal. Normal builds remain
credential-free. See [RELEASING.md](RELEASING.md) for validation evidence,
immutable outputs, disposable-key tests and the user-run upload command.

## Distribution verification

Packaged JNI qualification runs the 47-case suite and transport/HTTP3 consumer
against the installed JARs on macOS ARM64 and Linux x64/ARM64. The minified
Android consumer is tested with CheckJNI on actual 4 KB and 16 KB page-size
emulators. Native ELF and APK alignment are checked separately from runtime
results. Matching Windows JVM results are required before full release
qualification; cross-compilation alone does not supply them.

See [consumer verification](test-tooling/README.md#complete-packaged-jni-qualification)
for the commands, portable Windows kits and artifact-bound evidence reports.

`mvn clean` removes Maven outputs. Host build work and exported Docker outputs
are under `.build/native/<target>`; staged libraries are under
`.build/staged/<target>`. Host Cargo caches are under `.build/cache` and fetched
upstream sources are under `.build/downloads`. Removing `.build` discards these
generated files; the next build uses the host toolchains again and does not
install replacements. Docker named volumes survive this cleanup and can supply
incremental work for the next build.

## Cross-platform native toolchains

`native/scripts/build_native.py` drives the same CMake project for Linux
amd64/arm64, macOS arm64, Android arm64 and Windows amd64/arm64. It selects the
configure preset, the toolchain and the Cargo cache, then stages the library,
the notices and a `build.json` manifest. It uses the same quiche tag, checksum,
Cargo lockfile and features as the Maven build, and it never passes compiler or
linker flags itself: those live in `native/cmake`, in the presets and in the
Docker images. These checks validate static-library compilation and
architecture. Windows checks also validate C-API linking and PE metadata; they
do not execute the Windows binaries.

`native/CMakePresets.json` describes every target. Host presets carry the
deployment target, the JNI platform and the target triple; `android-arm64`
references the committed
[native/cmake/toolchains/android-arm64.cmake](native/cmake/toolchains/android-arm64.cmake),
which fixes the ABI, the static C++ runtime and includes the NDK toolchain from
`ANDROID_NDK_HOME`; the Windows presets read the cargo-xwin `clang-cl`
toolchain from `BOSON_WINDOWS_TOOLCHAIN`. `native/platforms.json` stays the
single platform matrix: preset names, Maven classifiers and the CI jobs derive
from it, so a mismatch shows up as a failed build rather than as drift.

Use an Apple Silicon Mac with a running Docker-compatible engine (OrbStack or
Docker Desktop), Rust 1.88+, the Rust `llvm-tools` component, Xcode tools and
CMake. Rust 1.88 is quiche 0.30.1's declared minimum; Cargo also checks the
requirements of the locked dependencies. Newer Rust compilers are accepted.
`python3 scripts/check_toolchain.py` reports each item for the local Maven
build; `--mode cross-build` adds the Docker images, the NDK and the Rust cross
targets.
Docker recipes use readable base-image tags and versioned native compilers/tools.
The Linux images use `almalinux:8.10` to preserve glibc 2.28 compatibility.
The Windows image uses `ubuntu:24.04`, runs Linux
ARM64 and cross-compiles both MSVC targets with LLVM 20 and cargo-xwin 0.23.1.
[native/toolchains.json](native/toolchains.json) holds the minimum versions a
build accepts and the Windows SDK/CRT selectors used inside the container
images; the Android NDK is taken from the host, so only its minimum revision is
recorded there.
The Windows CRT component selector (`windows_crt_component`, such as
`14.44.17.14`) chooses what cargo-xwin downloads; the package build it
resolves is recorded in `build.json` rather than pinned.

Host builds use the selected Rust toolchain. Docker images install `stable`
by default when their Rust installation layer is built; `RUST_TOOLCHAIN` is an
optional Docker build argument for selecting another toolchain. Rebuild with
`--no-cache` to refresh `stable` in an existing image. Existing images retain
their installed compiler. The actual Rust compiler version and Docker image
identity remain part of native build metadata and cache validation. Compiler
upgrades require fresh native outputs. Install `llvm-tools` and any cross
targets for the selected toolchain after a Rust upgrade.

The builder downloads upstream sources automatically. An existing checkout can
be selected with `--source /absolute/path/to/quiche`. Create the build images,
add the Rust pieces the cross builds need, and check what is still missing:

```sh
docker buildx build --platform linux/arm64 -f native/docker/Dockerfile.windows \
    -t boson-quiche-toolchain:windows-arm64 --load native/docker
docker buildx build --platform linux/arm64 -f native/docker/Dockerfile.linux \
    -t boson-quiche-toolchain:linux-arm64 --load native/docker
docker buildx build --platform linux/amd64 -f native/docker/Dockerfile.linux \
    -t boson-quiche-toolchain:linux-amd64 --load native/docker
rustup component add llvm-tools
rustup target add aarch64-linux-android
python3 scripts/check_toolchain.py --mode cross-build
```

The check reports the version it found, the version required and whether the
item is missing, with the command that supplies it. It never installs anything.
A missing builder image is reported by name together with the `docker buildx`
line; a build that runs without it stops with the same name instead of a Docker
traceback. Android needs an NDK at or above `native/toolchains.json`;
`sdkmanager "ndk;<revision>"` installs one in the Android SDK, or
`ANDROID_NDK_HOME` points at an existing one. Everything else is a Docker image
built above or a Rust component added above. A build with an incomplete
toolchain fails immediately and names what is missing; it does not try to fix
it.

Build and validate a target by its platform ID:

```sh
python3 native/scripts/build_native.py --target windows-amd64 --stage archive
python3 native/scripts/build_native.py --all --stage archive
```

Build or inspect the JNI shared libraries for all targets:

```sh
python3 native/scripts/build_native.py --all
```

The other IDs are `linux-amd64`, `linux-arm64`, `macos-arm64` and
`android-arm64`. Use Linux ARM64 for the local development loop; Linux x64
verification uses architecture translation on an ARM64 Mac. Enable Rosetta for
Linux in the Docker engine when available.

The images contain reusable toolchains. Application compilation and tests use
`docker run --rm`; changing application source does not require rebuilding an
image. Docker creates these persistent cache volumes automatically:

| Builder | Named volume |
| --- | --- |
| Linux ARM64 | `boson-quiche-linux-cache-arm64` |
| Linux AMD64 | `boson-quiche-linux-cache-amd64` |
| Windows cross-compiler on Linux ARM64 | `boson-quiche-windows-cache-arm64` |

Cargo dependencies, Rust target directories, CMake build trees and Windows SDK
downloads stay in these volumes at `/cache`. Work directories under
`/cache/build/<target>/<input-identity>/` are keyed by source, lockfile,
toolchain, features and baseline. Both Windows targets share SDK downloads in
the ARM64 builder volume; their build directories remain separate. Loader
fixture builds use `/cache/loader-fixtures/` in the same matching volume.

Containers mount project sources read-only and export libraries, notices,
test fixture libraries and diagnostic records to `.build/native/`. Rust and
CMake build trees remain inside Docker. Host macOS/Android builds retain their
work directories under `.build/native/`. Staged outputs under
`.build/staged/<platform>/<stage>/` contain
the library, dependency notices and a checksummed `build.json` manifest.
The manifest records versions, architecture, compiler/SDK details and image
identity. Debug sidecars stay outside runtime resources.

To inspect a cached Linux build interactively, reuse its toolchain image:

```sh
docker run --rm -it --platform linux/arm64 \
    --mount type=volume,source=boson-quiche-linux-cache-arm64,target=/cache \
    boson-quiche-toolchain:linux-arm64 bash
```

Inspect libraries under `/cache/build/` with `ldd` or `readelf`. Repeat the
normal target build command to rebuild after editing source. To discard Docker
incremental work and downloaded dependencies, remove the selected volume while
no build is running, for example:

```sh
docker volume rm boson-quiche-linux-cache-arm64
```

Remove the other listed volumes individually when their caches are no longer
needed. The next build recreates them and downloads dependencies again.

Inspect staged static archives or generate a machine-readable report:

```sh
python3 native/scripts/build_native.py --all --stage archive --inspect
python3 native/scripts/build_native.py --all --stage archive --report > .build/toolchain-report.json
```

Report generation rechecks archive and lockfile hashes. Reports describe a
particular build environment and belong with generated artifacts under the
ignored `.build/` directory.

The default stage is `jni`, which compiles the shim with CMake and checks its
architecture and exported JNI methods. JNI uses version 1.6 on all targets.
Android is detected before generic Linux and loads `libboson_quiche.so` through
`System.loadLibrary("boson_quiche")`; applications package it for `arm64-v8a`.
Desktop libraries retain distinct `native/<classifier>/` resources.
JNI headers come from the target's JDK or NDK:

- macOS uses `JAVA_HOME`, or the JDK selected by `/usr/libexec/java_home`.
- Linux Docker images install the OpenJDK 17 development package.
- The Windows Docker image extracts bundled headers from a versioned Temurin
  Windows JDK archive, verifying the publisher's archive checksum.
- Android uses the NDK headers.

The selected JDK version and actual header hashes are recorded in build metadata
and cache identity. Individual header hashes are not pinned in configuration.
JDK updates are accepted when the required target headers and JDK 11+ metadata
are present. Rebuild Docker images after changing their JDK setup. No JVM
library is linked into the native binary.

Each staged directory is a deterministic snapshot of the target's JNI library and
its `build.json` manifest. Repeat assembly from the same inputs produces the same
bytes; binary reproducibility across SDK or compiler changes is not guaranteed.

Maven builds isolated loader-test libraries outside runtime resources. They
verify rejection of legacy libraries and mismatched binding ABI, binding
version and upstream version in fresh JVMs. `--test-natives` builds these
fixtures for a selected target.

Build the host artifacts and the test classpath, then run the same suite on the
matching Linux container JVMs:

```sh
mvn -pl native,api verify
python3 native/scripts/build_native.py --target linux-amd64 --test-natives
python3 native/scripts/test_runtime.py --target linux-amd64
python3 native/scripts/build_native.py --target linux-arm64 --test-natives
python3 native/scripts/test_runtime.py --target linux-arm64
```

For a running ARM64 Android emulator with API 33 or later:

```sh
python3 native/scripts/build_native.py --target android-arm64
python3 native/scripts/test_runtime.py --target android-arm64 \
    --android-sdk /absolute/path/to/android-sdk --serial emulator-5554
```

The Android runner requires an explicit emulator serial and executes the
transport regressions on ART with CheckJNI. Desktop loader subprocess tests
run on the JVMs. Runtime logs and results stay under `.build/`.

## Packet I/O and zero-copy at the JNI boundary

`Connection.recv`, `send`, `streamRecv`, `streamSend`, `dgramRecv`, `dgramSend`
and the HTTP/3 body methods operate directly on **direct ByteBuffers**. JNI
uses `GetDirectBufferAddress` plus the buffer's current position. There is no
payload staging array, JNI array pinning or payload memcpy in these wrappers.
Direct slices, nonzero positions and restricted limits are supported. Read-only
direct buffers are accepted for const input, but not for output or `recv`.

This guarantees no extra payload copy in the binding. quiche itself can copy
data into its stream/retransmission queues; this is not an end-to-end zero-copy
guarantee. Small IDs, certificates, headers, errors and statistics are copied
into Java-owned values. The explicit datagram-purge predicate also receives a
copy, rather than exposing borrowed native memory to an application callback.

All bulk methods use `[position, limit)` and advance the position by the
successful byte count. `recv` decrypts packets in place. `headerInfo` inspects
without advancing the position. Use reusable direct buffers and preserve a
packet's storage until the transport has actually sent it. No native reference
to a supplied buffer is retained after its JNI call returns.

```java
try (Config config = new Config()) {
    config.setApplicationProtos("my-protocol")
          .verifyPeer(true)
          .loadVerifyLocationsFromFile("trusted-peer.pem")
          .setInitialMaxData(1_000_000)
          .setInitialMaxStreamDataBidiLocal(64_000)
          .setInitialMaxStreamDataBidiRemote(64_000)
          .setInitialMaxStreamsBidi(16);

    try (Connection connection = Connection.connect(
            "peer.example", sourceConnectionId, localAddress, peerAddress, config)) {
        ByteBuffer incoming = ByteBuffer.allocateDirect(1350);
        ByteBuffer outgoing = ByteBuffer.allocateDirect(1350);

        // Fill incoming via your UDP/ICE transport, then flip it:
        // connection.recv(incoming, new RecvInfo(observedPeer, observedLocal));

        SendInfo packet;
        while ((packet = connection.send(outgoing.clear())) != null) {
            outgoing.flip();
            // Send the full datagram through your transport to packet.to,
            // from packet.from, respecting packet.delayNanos.
            // Do not reuse outgoing until that send is finished.
        }
        // Schedule connection.timeoutAsNanos(), when not -1.
        // On expiry: connection.onTimeout(), then drain send() again.
    }
}
```

The commented transport operations are supplied by the application. The tests
contain a complete in-memory datagram pump and real client/server handshakes.
For ICE, use its nominated application-data path and keep STUN/consent/relay
maintenance in the ICE layer. Coherent source/destination metadata is required
for QUIC path validation; address changes must be coordinated with ICE.

## API and ownership

- `Config`, `Connection`, `H3Config` and `H3Connection` own native allocations
  and implement `AutoCloseable`. Always close them. `close()` releases memory;
  `Connection.close(application, code, reason)` instead queues a protocol close,
  after which outgoing packets should still be drained.
- Native calls and disposal are serialized per owner. An HTTP/3 connection
  shares its transport's lock and checks that the transport remains open.
  Buffer sharing between application threads remains the caller's concern.
- Structs map to Java value classes: `RecvInfo`, `SendInfo`, `Timespec`, `Stats`,
  `TransportParams`, `PathStats`, `PathEvent`, `H3Header`, `H3Priority` and
  `H3Stats`. Native iterators are consumed and freed inside JNI and returned as
  Java arrays. Events and borrowed byte strings are copied before native memory
  is freed. Java enums preserve the upstream numeric discriminants.
- `send()`, `streamRecv()`, path-event polling and HTTP/3 polling return `null`
  for upstream `DONE`. Count-returning nonblocking methods return `-1` for
  `DONE`; other native errors throw `QuicheException` or `H3Exception`.
  Stream reset/stop exceptions preserve their application error code.
- Partial stream writes are normal. Retry the remaining buffer when writable;
  draining output can generate ACKs, flow-control updates and retransmissions.
  Drive timers even when the transport receives no packets.
- Durations retain upstream units: idle timeouts are milliseconds; path RTT
  fields and `timeoutAsNanos()` are nanoseconds. Native uint64 values use the
  Java long bit pattern. `-1` is the no-timeout sentinel for `UINT64_MAX`.
- `SendInfo.at` preserves quiche's native timespec. `delayNanos` is computed
  against the native monotonic clock and must be scheduled as a relative delay.
  Upstream 0.30.1 returns a zero timespec on macOS/iOS/Windows; pacing timing is
  consequently unavailable through the C API there. Do not interpret it as a
  wall-clock date or a Java `System.nanoTime()` epoch.
- The optional upstream debug logger is process-global and installed once.
  Logging callbacks must not throw (native logging drops callback exceptions).
  Native callbacks cannot re-enter or dispose native owners; purge-predicate
  exceptions propagate after native processing returns.

The standard quiche TLS configuration is used. **Upstream certificate
verification is disabled by default**; clients must explicitly use
`verifyPeer(true)` and an appropriate trust store, or implement an authenticated
pinning policy. Enabling server verification requests a client certificate but
does not require one; inspect `peerCert()` when mutual authentication is needed.
There are no Java TrustManager/private-key callbacks in this vanilla binding.

## Coverage and deliberate boundaries

The public QUIC transport and HTTP/3 functions in the pinned header are mapped,
including configuration, handshake creation, headers/version negotiation/retry,
packet I/O, streams, DATAGRAM queues, connection IDs, path probing/migration,
path events, peer parameters, errors, statistics, ALPN, certificates, sessions,
keylog/qlog paths, HTTP/3 settings/headers/bodies/priorities and GOAWAY.

The external `void *ssl` constructors are not exposed: they require ownership
of an externally constructed BoringSSL object and would defeat the vanilla
configuration boundary. Unix file-descriptor keylog/qlog setters are also not
exposed; the portable path-based functions are available. The deprecated
`set_use_initial_max_data_as_flow_control_win` no-op is omitted. Rust-only APIs
absent from `quiche.h` are outside this binding's scope.

`scripts/generate_api.py` regenerates enums, configuration setters and numeric
struct snapshots from `native/quiche.h`, using the full MIT header in
`native/copyright-header.txt`. Generated Java/C files retain the
generation marker immediately below that header. Review upstream changes,
update the pin and header together, update `native/Cargo.lock`
explicitly with the build script's `--update-lock`, then rerun the native tests. Do not replace the native
library with an arbitrary quiche build.

## Java API documentation

Public classes, methods, enum values and struct fields have JavaDoc adapted
from the pinned quiche 0.30.1 Rust API. Defaults, protocol rules and units are
retained; direct-buffer ranges, disposal, copied snapshots, exceptions and
null/-1 DONE results describe this Java binding. Rust examples remain available
through versioned upstream API links. The package documentation explains the
connection-driving model. Upstream BSD attribution is retained in `NOTICE`
and in the generated documentation's `doc-files`.

`mvn verify` generates HTML under `api/target/reports/apidocs/` and attaches
`api/target/boson-quiche-0.30.1.1-SNAPSHOT-javadoc.jar`. JavaDoc uses full
doclint and fails on warnings. Normal generation uses the checked-in snapshot
`native/api-docs.json`, so no upstream checkout or network is needed.

To refresh documentation after reviewing an upstream release:

```sh
python3 scripts/import_api_docs.py /absolute/path/to/quiche
python3 scripts/generate_api.py
python3 scripts/api_docs.py
mvn verify
```

`scripts/api_docs.py` renders the snapshot and applies Java-specific contracts
to handwritten public classes; the source generator uses the same renderer.
Review the resulting comments when updating the upstream API. This process
does not alter Java or native method implementations.

## Tests and references

`mvn verify` runs JUnit with `-Xcheck:jni`. Tests exercise native QUIC peers over
memory-delivered datagrams, including certificate validation, IPv4/IPv6, partial
stream writes, DATAGRAMs, timer recovery, reset/close errors, disposal and HTTP/3.
The committed PEM key is a public test fixture and must never be deployed.

References: Cloudflare's [quiche C API](https://github.com/cloudflare/quiche/blob/0.30.1/quiche/include/quiche.h)
and Netty 4.2.20.Final's `codec-native-quic` and `codec-classes-quic`. The binding
is an independent implementation; it does not depend on Netty's internal APIs.

The Java/JNI source is MIT licensed. The upstream header retains its original
BSD notice. Native JAR resources include the quiche and dependency licenses,
BoringSSL notices, and build metadata under `META-INF/` and `native/`.
Dependency notices come from the committed `native/notices/` tree, which
`python3 native/scripts/build_native.py --update-notices` regenerates after a
dependency change; a test fails when it drifts from `native/Cargo.lock`.
