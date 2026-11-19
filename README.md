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

Requirements: JDK 11+, Maven 3.6+, Python 3.9+, Rust 1.99.1, C/C++ compiler,
CMake 3.22+ and the host platform development tools. Release bundling and
publishing require Maven 3.9.2+. The Maven JNI build supports
macOS and Linux hosts. Cross-platform JNI builds for all six targets use the
toolchains described below. Runtime regressions cover macOS arm64, Linux
amd64/arm64 and Android arm64 on API 33 with 4 KB pages and API 37 with 16 KB
pages. Android checks include the R8-minified packaged consumer and CheckJNI.
Windows ARM64 and x64 JVMs also pass all 47 JNI tests and the packaged consumer.
The Windows x64 runtime checks use x64 emulation on Windows ARM64.

```sh
mvn -s .mvn/settings.xml verify
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
mvn -s .mvn/settings.xml -Dquiche.source=/absolute/path/to/quiche verify
```

Sources, native build products and Cargo caches are under ignored `.build/`.
Host native test resources are copied into `api/target/native-test-resources/`;
`mvn clean` preserves the cached native inputs. A supplied checkout is not modified.
`-Dnative.skip=true` validates and restores an existing host library without
rebuilding it. Missing or stale inputs cause an error.

The project has its own parent POM and manages its dependency versions
independently of other Boson projects. Normal `verify` builds the API,
runs host JNI tests and packages the host native classifier. Build outputs
are under `api/target/` and `native/target/`. The Java API JAR
contains no native libraries or test fixtures.

After building all six staged JNI targets, package the complete distribution:

```sh
python3 native/scripts/build_native.py --all
mvn -s .mvn/settings.xml -Pdistribution -DskipTests verify
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
and documentation companion JARs for Maven Central.
See [consumer verification](test-tooling/README.md) for isolated repository,
JVM and minified Android consumer checks.

## Release preparation

Build and record the complete local distribution with:

```sh
python3 scripts/build_all.py --targets all
```

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

`mvn clean` removes Maven outputs. Rebuildable target caches are under
`.build/native/<target>` and `.build/staged/<target>`; removing these forces a
fresh target build. Shared SDK/source/Cargo downloads are under `.build/cache`.
Release candidates and qualification evidence use separate directories.

## Cross-platform native toolchains

`native/scripts/build_native.py` builds and inspects quiche static archives for
Linux amd64/arm64, macOS arm64, Android arm64 and Windows amd64/arm64. It uses
the same quiche tag, checksum, Cargo lockfile and features as the Maven build.
These checks validate static-library compilation and architecture. Windows
checks also validate C-API linking and PE metadata; they do not execute the
Windows binaries. The Maven JNI package is built separately as described above.

Use an Apple Silicon Mac with a running Docker-compatible engine (OrbStack or
Docker Desktop), Rust 1.99.1, the Rust `llvm-tools` component, Xcode tools and
CMake. Docker recipes pin base-image digests and compiler/tool versions. The
Linux images use AlmaLinux 8.10 and glibc 2.28. The Windows image runs Linux
ARM64 and cross-compiles both MSVC targets with LLVM 20 and cargo-xwin 0.23.1.
[native/toolchains.json](native/toolchains.json) pins the Windows SDK/CRT and
Android NDK/API versions and is a required, version-controlled build input.

The builder downloads upstream sources automatically. An existing checkout can
be selected with `--source /absolute/path/to/quiche`. Create the build images
and install the pinned Android NDK:

```sh
docker build --platform linux/arm64 -f native/docker/Dockerfile.windows \
    -t boson-quiche-toolchain:windows-arm64 native/docker
docker build --platform linux/arm64 -f native/docker/Dockerfile.linux \
    -t boson-quiche-toolchain:linux-arm64 native/docker
docker build --platform linux/amd64 -f native/docker/Dockerfile.linux \
    -t boson-quiche-toolchain:linux-amd64 native/docker
rustup component add llvm-tools
rustup target add aarch64-linux-android
python3 native/scripts/build_native.py --fetch-ndk
python3 native/scripts/build_native.py --preflight
```

Build and validate a target by its platform ID:

```sh
python3 native/scripts/build_native.py --target windows-amd64 --stage archive
python3 native/scripts/build_native.py --all --stage archive
```

Build or inspect the JNI shared libraries for all targets:

```sh
python3 native/scripts/build_native.py --all
python3 native/scripts/build_native.py --all --inspect
```

The other IDs are `linux-amd64`, `linux-arm64`, `macos-arm64` and
`android-arm64`. Linux x64 runs under architecture translation on an ARM64 Mac.
Outputs, SDKs and dependency caches are under `.build/`.
`ANDROID_NDK_HOME` can select an existing NDK with the exact pinned revision.

Target-specific work directories under `.build/native/` are keyed by source,
lockfile, toolchain, features and baseline. Build logs and inspection results
remain there. Staged outputs under `.build/staged/<platform>/<stage>/` contain
the library, dependency notices and a checksummed `build.json` manifest.
The manifest records versions, architecture, compiler/SDK details and image
identity. Debug sidecars stay outside runtime resources.

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

Each staged directory also has a sibling `<stage>.tar` bundle with stable file
order, timestamps, permissions and ownership. Repeat assembly from the same
inputs produces identical archive bytes; binary reproducibility across SDK
or compiler changes is not guaranteed. `native/scripts/prove_toolchains.py` remains
an alias for archive validation.

Run build-tool checks independently with:

```sh
python3 -m unittest discover -s native/scripts/tests -v
```

Maven builds isolated loader-test libraries outside runtime resources. They
verify rejection of legacy libraries and mismatched binding ABI, binding
version and upstream version in fresh JVMs. `--test-natives` builds these
fixtures for a selected target.

Prepare compiled tests and run them on the matching Linux container JVMs:

```sh
mvn -s .mvn/settings.xml process-test-classes
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
mvn -s .mvn/settings.xml verify
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
