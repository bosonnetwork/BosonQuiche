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
mvn -s .mvn/settings.xml verify
mvn -s .mvn/settings.xml -Pdistribution -DskipTests \
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
The artifact checker also verifies that classifier resource names are disjoint.

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
