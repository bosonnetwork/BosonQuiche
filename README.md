# Boson Quiche

Standalone Maven/JNI bindings for Cloudflare quiche 0.30.1. No Boson, Netty,
Vert.x, ice4j or other Java runtime dependencies are required. The library owns
no sockets, threads or event loops. QUIC and HTTP/3 are both available; HTTP/3
is optional for applications.

## Build

Requirements: JDK 11+, Maven 3.6+, Python 3.9+, Rust 1.99.1, C/C++ compiler,
CMake 3.22+ and the host platform development tools. The Maven JNI build supports
macOS and Linux hosts, with integration tests validated on macOS arm64.
Cross-platform static-library validation is available through the toolchains
described below.

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
Maven resources are copied into `target/generated-resources/`; `mvn clean`
preserves the native inputs. A supplied checkout is not modified.
`-Dnative.skip=true` validates and restores an existing host library without
rebuilding it. Missing or stale inputs cause an error.
This project intentionally manages its own dependency versions and has no
parent POM or dependency on another Boson project.

Coordinates: `io.bosonnetwork:boson-quiche:0.30.1.1-SNAPSHOT`. The host native
library is bundled under `native/<os>-<arch>/` in the JAR. The loader extracts
it into a private temporary directory. An explicit library can be selected
with `-Dboson.quiche.library=/absolute/path/to/libboson_quiche.dylib` (or `.so`).
The native version must match 0.30.1. Native quiche/BoringSSL symbols are hidden
to allow coexistence with other TLS implementations in the JVM.

## Cross-platform native toolchains

`scripts/build_native.py` builds and inspects quiche static archives for
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
docker build --platform linux/arm64 -f docker/Dockerfile.windows \
    -t boson-quiche-toolchain:windows-arm64 docker
docker build --platform linux/arm64 -f docker/Dockerfile.linux \
    -t boson-quiche-toolchain:linux-arm64 docker
docker build --platform linux/amd64 -f docker/Dockerfile.linux \
    -t boson-quiche-toolchain:linux-amd64 docker
rustup component add llvm-tools
rustup target add aarch64-linux-android
python3 scripts/build_native.py --fetch-ndk
python3 scripts/build_native.py --preflight
```

Build and validate a target by its platform ID:

```sh
python3 scripts/build_native.py --target windows-amd64 --stage archive
python3 scripts/build_native.py --all --stage archive
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
python3 scripts/build_native.py --all --stage archive --inspect
python3 scripts/build_native.py --all --stage archive --report > .build/toolchain-report.json
```

Report generation rechecks archive and lockfile hashes. Reports describe a
particular build environment and belong with generated artifacts under the
ignored `.build/` directory.

The default stage is `jni`, which compiles the shim with CMake and checks its
architecture and exported JNI methods. macOS arm64 JNI builds are validated;
Windows and Android JNI runtime compatibility is not established. JNI headers
come from the target's JDK or NDK:

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
or compiler changes is not guaranteed. `scripts/prove_toolchains.py` remains
an alias for archive validation.

Run build-tool checks independently with:

```sh
python3 -m unittest discover -s scripts/tests -v
```

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
`native/copyright-header.txt`. Generated Java/C files retain the generation
marker immediately below that header. Review upstream changes, update the
pin and header together, update `native/Cargo.lock` explicitly with the build
script's `--update-lock`, then rerun the native tests. Do not replace the native
library with an arbitrary quiche build.

## Java API documentation

Public classes, methods, enum values and struct fields have JavaDoc adapted
from the pinned quiche 0.30.1 Rust API. Defaults, protocol rules and units are
retained; direct-buffer ranges, disposal, copied snapshots, exceptions and
null/-1 DONE results describe this Java binding. Rust examples remain available
through versioned upstream API links. The package documentation explains the
connection-driving model. Upstream BSD attribution is retained in `NOTICE`
and in the generated documentation's `doc-files`.

`mvn verify` generates HTML under `target/reports/apidocs/` and attaches
`target/boson-quiche-0.1.0-SNAPSHOT-javadoc.jar`. JavaDoc uses full doclint and
fails on warnings. Normal generation uses the checked-in documentation snapshot
`native/api-docs.json`, so no upstream checkout or network is needed for it.

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
