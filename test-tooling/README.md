# Published-artifact consumer checks

These consumers are independent of the production Maven reactor. The JVM
consumer uses published JARs; the Android application uses an ordinary AAR
coordinate and enables R8 for its release build. Both exercise TLS handshakes,
direct-buffer slices, streams, datagrams, native statistics and HTTP/3 callbacks.
The test certificate and private key are public fixtures from `api/src/test/resources/`.

Run commands from the repository root. First build all native targets, verify
the host, then install the complete distribution into an isolated repository:

```sh
python3 native/scripts/build_native.py --all
mvn -s .mvn/settings.xml -Pdistribution -Dnative.skip=true \
    -Dmaven.repo.local="$PWD/.build/artifact-repository" install
python3 scripts/test_artifacts.py --repository .build/artifact-repository
```

The isolated repository also caches the public Maven build plugins/dependencies
used during `install`. Keep it intact for the file-only JVM consumer. Production
artifact and plugin resolution use project settings; no personal publishing
settings are needed.

## JVM

Select the host's native classifier (`macos-aarch64` is the default):

```sh
mvn -s test-tooling/file-repository-settings.xml \
    -f test-tooling/jvm-consumer/pom.xml \
    -Dboson.repository="file://$PWD/.build/artifact-repository" \
    -Dmaven.repo.local="$PWD/.build/jvm-consumer-cache" \
    -Dnative.classifier=macos-aarch64 verify
```

The supplied test settings mirror every repository to the isolated file
repository, including plugin repositories. The fresh consumer cache cannot
supply a previously installed BosonQuiche artifact. To include all five desktop
classifiers and verify they coexist, run the same command with `-Pall-desktop`
and omit `-Dnative.classifier`. The loader selects the running host's library.
The artifact checker also verifies that classifier payload resource names are
disjoint; standard JAR manifests and directory entries are allowed.

## Android

Use JDK 17, Gradle 8.13 and Android SDK platform 36 with build-tools 35.0.0 or
later. The test harness pins Android Gradle Plugin 8.9.1. Gradle is only used by
this consumer application. It does not configure an external native build or
require a local NDK, Rust compiler or CMake.

Create a disposable test signing key outside source control:

```sh
mkdir -p .build/android-consumer
keytool -genkeypair -keystore .build/android-consumer/test.jks \
    -storepass consumer-test -keypass consumer-test -alias consumer-test \
    -keyalg RSA -keysize 2048 -validity 7 \
    -dname 'CN=BosonQuiche Consumer Test' -noprompt
```

Set `ANDROID_HOME` to the SDK. The file repository exclusively supplies the
`io.bosonnetwork` group; Google/Maven Central supply public build tools:

```sh
gradle -g "$PWD/.build/android-consumer/gradle-home" \
    -p test-tooling/android-consumer \
    -PbosonRepository="file://$PWD/.build/artifact-repository" \
    -PbosonVersion=0.30.1.1-SNAPSHOT \
    -PconsumerKeystore="$PWD/.build/android-consumer/test.jks" \
    -Pandroid.suppressUnsupportedCompileSdk=36 \
    resolvedBosonArtifacts assembleRelease
```

The SDK suppression acknowledges that AGP 8.9.1 was tested through compile SDK
35; platform 36 is used only by this test app. The runtime minimum remains 33.
`resolvedBosonArtifacts` must list the AAR and its transitive API JAR. No `@aar`
notation or separate API dependency is used. The app has no additional JNI
keep rules; it relies on those supplied by the AAR. R8 mappings and the APK
are under `test-tooling/android-consumer/build/`.

Start a disposable API 33+ ARM64 emulator, then select its serial explicitly:

```sh
python3 scripts/test_android_consumer.py \
    --android-sdk "$ANDROID_HOME" --serial emulator-5582 \
    --report .build/android-consumer/result.json
```

This installs the release test APK and runs its checks. The helper rejects
physical device serials and verifies the emulator flag, SDK level and ABI
before installation. It reads only the consumer process's result log. A
successful run prints `BosonQuiche packaged consumer PASS` and writes the
APK checksum and emulator properties when `--report` is supplied.


## Frozen release tooling

The shared release tests live under `scripts/tests/`; run them with
`python3 -m unittest discover -s scripts/tests -v`. The explicit
`python3 scripts/test_release_workflow.py` command tests Maven attachment and
GPG signing using synthetic native inputs, dummy settings and a disposable key.
Maven 3.9.2+ and Central's bundle-only profile produce the real Central ZIP
without uploading. Python verifies its body hashes, signatures and sidecars,
and the tests reject attempts to publish those fixtures.
See [RELEASING.md](../RELEASING.md) for the evidence contract and release flow.

## Complete packaged JNI qualification

The `jni-tests` profile on the JVM consumer compiles the existing API tests
and runs all 47 JNI/loader cases against the installed API and native JARs.
It also runs the transport/HTTP3 consumer. The isolated repository must contain
the test providers/dependencies, so run `install` with tests enabled as above.
A clean native cache is supported: tiny loader mismatch fixtures are compiled
separately with the pinned target compiler; Rust does not need to be rebuilt.
Their CMake build trees stay in the matching Docker cache volume, and only
fixture libraries are copied into the consumer work directory. Windows fixture
builds use the SDK cache prepared by the Windows native builder in that volume.

On the macOS build host, run:

```sh
python3 scripts/test_jvm_consumers.py \
    --repository .build/artifact-repository \
    --work .build/qualification/jvm --prepare-windows
```

Use a fresh work directory for each run. Maven resolves through the file-only
mirror and an empty consumer cache. The host and both Linux JVMs run the full
47-case suite and packaged consumer with CheckJNI. All five desktop classifier
JARs coexist on the runtime classpath. Linux Java runs with a read-only root
filesystem, writable temporary storage and no build tools on PATH.

The work directory contains `jvm-consumers.json`, per-platform runtime JSON,
logs and portable Windows kits. Test fixtures and JUnit dependencies are test
inputs; no additional test artifacts are published to Maven Central.

Copy each Windows kit directory to a Windows guest, then run its `run.ps1`
using the matching JDK 11+ installation (ARM64 or x64):

```powershell
.\run.ps1 -JavaHome 'C:\Path\To\MatchingJdk'
```

The kit needs no Rust, C compiler or Maven. Copy `result.xml` back to the build
host and import it against the exact installed distribution:

```sh
python3 scripts/test_jvm_consumers.py \
    --repository .build/artifact-repository \
    --import-runtime /absolute/path/to/result.xml --target windows-arm64 \
    --report .build/qualification/windows-arm64.json
```

Repeat for `windows-amd64`. Import verifies the actual JVM OS/architecture,
47 successful tests, binding version/ABI and native resource checksum. An x64
JVM does not qualify the ARM64 target. A missing guest result remains unverified.

## Android page-size qualification

Build the minified release APK as above, then run it on an unlocked, explicitly
selected ARM64 emulator. A fresh test data disk is useful for an AVD whose
saved owner is locked. No physical devices are accepted by the helper.

```sh
python3 scripts/test_android_consumer.py \
    --android-sdk "$ANDROID_HOME" --serial emulator-5582 --page-size 4096 \
    --repository .build/artifact-repository \
    --report .build/qualification/android4k.json
python3 scripts/test_android_consumer.py \
    --android-sdk "$ANDROID_HOME" --serial emulator-5584 --page-size 16384 \
    --repository .build/artifact-repository \
    --report .build/qualification/android16k.json
```

The helper reads `getconf PAGESIZE`, checks the APK native bytes against the
Maven AAR, validates ELF load alignment and runs SDK `zipalign -c -P 16 4`.
It verifies the R8 mapping and enables CheckJNI for the new app process,
restoring the emulator setting afterward. A fresh run ID prevents an old PASS
log from qualifying a new run. Both runs must pass; binary alignment alone is
not a 16 KB runtime test.

Each report has version/ABI, native/APK/mapping hashes and actual page size.
The helper also writes an `android-r8` sidecar. A successful 16 KB run adds
an `android-16k` sidecar. These sidecars bind all 15 distribution artifact hashes
and can be supplied to `build_all.py --evidence` alongside JVM/runtime receipts.
The raw Android suite runs 29 transport cases and the Android loading branch:

```sh
python3 native/scripts/test_runtime.py --target android-arm64 \
    --android-sdk "$ANDROID_HOME" --serial emulator-5584
```

The page-size and alignment checks follow the
[Android guidance](https://developer.android.com/guide/practices/page-sizes).
