# Local release preparation and publishing

BosonQuiche builds and packages its six native targets locally. Maven packages,
signs and publishes the distribution through its standard lifecycle. Checksums
ensure the outputs match the immutable prepared release. Upload stops after
Central validates it; a person publishes it from the Central Portal.

Use Maven 3.9.2+ from the repository root for release bundling/publishing. Production
builds and publishing are Maven-driven. Gradle is confined to the independent
Android consumer checks. Normal `mvn verify` neither signs artifacts nor loads
the Central publishing extension.

## Version the inputs first

For upstream quiche `0.30.1`, binding releases use `0.30.1.1`, `0.30.1.2`, etc.
Set the root POM version and the three child POM parent versions together
before building release inputs. Keep `quiche.version` aligned with the pinned
upstream tag. `quiche.binding.abi` is an independent positive ABI number.

Release preparation accepts a matching four-component release version. It
rejects `-SNAPSHOT`, qualifiers, mixed versions and stale native/API metadata.
It never renames snapshot binaries or archives into release files. After a
version change, rebuild native libraries so their embedded binding version
matches the Java metadata and POMs.

## Build and record validation

Set up the native toolchains described in [README.md](README.md), then run:

```sh
python3 scripts/build_all.py --targets all
```

This builds all six JNI targets, runs Python tests and clean Maven verification,
packages the distribution, runs the Linux JVM suites and writes
`.build/validation/build.json`. The host JNI suite, strict JavaDoc, artifact
boundaries and current native versions/ABI/source pins are checked. Logs are
under `.build/validation/logs/`. A failed build removes the preceding report
rather than leaving stale success evidence.

Useful options:

- `--targets macos-arm64`: verify a selected target set including the host.
  Such a record cannot qualify a complete distribution.
- `--reuse`: ask the native builder to strictly validate/reuse its existing
  source, SDK and build-script cache identities.
- `--prebuilt`: validate compatible staged binaries, including their version,
  architecture and compiled-source/dependency pins, before packaging and tests.
- `--maven-repository /absolute/path`: choose the public Maven dependency cache.
- `--android-sdk /absolute/path --serial emulator-5582`: run ART transport tests
  on an explicitly selected API 33+ ARM64 emulator. Physical devices are rejected.
- `--evidence /absolute/path/record.json`: include matching runtime or additional
  qualification evidence, as described below. Repeat for multiple records.
- `--report /absolute/path/build.json`: choose a different validation record.

The default settings file is the credential-free project `.mvn/settings.xml`.
Build tooling does not need personal publishing settings or a signing key.

Build/inspection success and runtime qualification are separate results. Each
selected target is recorded with native/manifest checksums, version, ABI and
baseline. Missing runtime coverage is explicitly `unverified`. Windows
cross-compilation does not qualify a Windows runtime. The ARM64 target needs
an ARM64 Windows JVM, rather than an x64 JVM running under emulation.

Additional runtime JSON records identify `platform`, `status: "passed"`,
`binding_version`, `binding_abi` and `native_sha256`. Windows records also
include `java_os: "Windows"`, `java_arch` and a positive `tests` count.
Android/JVM qualification receipts use `check` values `jvm-consumers`,
`android-r8` or `android-16k`, `status: "passed"` and `artifact_set_sha256`.
The latter is the SHA-256 of the sorted compact JSON mapping of Maven paths
to artifact SHA-256 values (`native_config.identity(report["artifacts"])`).
Receipts must come from the matching consumer/runtime verification; changing a
status field does not establish test coverage. Their hashes are retained in
the combined validation record. See [consumer checks](test-tooling/README.md).

Consumer receipt producers and matching Windows JVM instructions are described
in [consumer verification](test-tooling/README.md#complete-packaged-jni-qualification).
After running the packaged JVM and both Android page-size checks, combine the
receipts with a fresh distribution verification, for example:

```sh
python3 scripts/build_all.py --targets all --prebuilt \
    --android-sdk "$ANDROID_HOME" --serial emulator-5584 \
    --evidence .build/qualification/jvm/jvm-consumers.json \
    --evidence .build/qualification/android16k-android-r8.json \
    --evidence .build/qualification/android16k-android-16k.json
```

Add each imported Windows runtime JSON with another `--evidence` argument.
Qualification checks include the real Android page size, CheckJNI, APK/ELF
alignment, preserved JNI mapping and matching native bytes. The packaged JVM
receipt must cover all 47 cases on macOS and both Linux architectures. Missing
Windows runtimes remain visible and keep full publication qualification incomplete.

## Freeze an unsigned release

After the matching version has been built and validated:

```sh
python3 scripts/prepare_release.py --version 0.30.1.1
```

The default output is `.build/releases/0.30.1.1/`:

```text
repository/io/bosonnetwork/       Exact Maven repository payload
manifest.json                    Versions, ABI, source/native/artifact hashes and evidence
SHA256SUMS                       Frozen payload and manifest checksums
```

The payload contains all four POMs, the API JAR/source/JavaDoc, five desktop
classifier JARs and the Android AAR/source/JavaDoc companions: 15 files total.
Android sources include its manifest, keep rules and shared JNI implementation.
Its documentation companion points to the transitive API's full JavaDoc.

Preparation checks all six native manifests and file checksums, physical
architectures, JNI export records, binding version strings, ABI, dependency
pins and target baselines. It checks Linux glibc symbols against 2.28, the
macOS minimum against 11.0 and Android load segments for 16 KB alignment.
These checks complement runtime qualification. Native build provenance and
notices are preserved in the packaged files.

Existing release directories are never overwritten. Prepared files are made
read-only. Use `--output` for a new candidate directory when evidence changes.
Verify an existing candidate with:

```sh
python3 scripts/verify_release.py --directory "$PWD/.build/releases/0.30.1.1"
```

Unsigned preparation may record incomplete runtime qualification. Central
publication requires all six runtimes, packaged JVM consumers, Android R8 and
16 KB runtime evidence. Adding `--publication` performs that stricter check.
Missing matching Windows runtime records are reported as incomplete
qualification and block publication.

## Sign and validate locally

An absolute `release.directory` activates distribution packaging and GPG signing.
Maven runs the normal compilation, tests and package-phase attachments. Each
module's POM, JARs or AAR must match the prepared SHA-256 checksums before
verify-phase GPG signing. A further check during `install` precedes deployment.
A different output stops the build: use the same JDK/toolchains and unchanged
inputs, or build, validate and prepare a new candidate.

Validation records and source/POM hashes are also checked again. Signing
requires the complete reactor; project selection, resume, nonrecursive builds
and skip flags are rejected. No Central extension is loaded for this command:

```sh
mvn -s .mvn/settings.xml \
    -Dnative.skip=true \
    -Drelease.directory="$PWD/.build/releases/0.30.1.1" verify
```

`native.skip=true` reuses the host JNI build after the native builder's strict
cache/input checks; Java compilation, tests and archive packaging still run.
Omit it to rebuild the host JNI library. A changed native manifest also requires
fresh validation and a new prepared candidate.

This user-run command uses the selected GPG signing key/agent. Supply an explicit
`-Dgpg.homedir` and `-Dgpg.keyname` when choosing another key. The automated
workflow test below always creates its own disposable key and dummy settings.
No preparation command invokes GPG automatically.

To let Maven produce the complete Central bundle locally, without upload:

```sh
mvn -s .mvn/settings.xml -Prelease-bundle \
    -Dnative.skip=true \
    -Drelease.directory="$PWD/.build/releases/0.30.1.1" deploy
```

The `release-bundle` profile fixes the Central plugin's `skipUpload` option to
`true`. It runs packaging, tests, signing and local staging, then leaves the
bundle at `target/central-publishing/central-bundle.zip`. No Central credentials
are needed. This goal requires Maven's online mode even when upload is skipped;
do not add `-o`. Public dependencies must be available as usual.

Verify the Maven-generated bundle with an explicitly exported public keyring:

```sh
python3 scripts/verify_bundle.py \
    --directory "$PWD/.build/releases/0.30.1.1" \
    --keyring /absolute/path/to/exported-public-keyring.gpg
```

This verifies all 15 body hashes, detached signatures and plugin-generated
MD5/SHA-1/SHA-256/SHA-512 sidecars. It copies the original ZIP unchanged into
`.build/releases/0.30.1.1-signed/`, alongside a signature/artifact manifest and
`SHA256SUMS`. It does not create repository archives or Central sidecars.
Use `--bundle` to check another Maven output and `--output` for a new protected
candidate directory. Existing signed outputs are never overwritten. An
incomplete qualification record still blocks the actual `publish` profile.

## Upload and manually publish

Run this step yourself after qualification and review, using the existing
Maven server entry named `central` and the intended GPG key:

```sh
mvn -Ppublish \
    -Dnative.skip=true \
    -Drelease.directory="$PWD/.build/releases/0.30.1.1" deploy
```

This command performs a network upload. It runs the normal Maven lifecycle,
checks output equality, signs and stages all four modules into one Central
deployment, including the independent parent. Configuration matches Boson's policy:
`publishingServerId=central`, `autoPublish=false`, `waitUntil=validated`, and
`deploymentName=BosonQuiche <version>`. Publication is completed manually in
the [Central Portal](https://central.sonatype.com/publishing/deployments).

The pinned Central plugin is `0.12.0`. Its `skipUpload` option supports local
bundle generation; `skipPublishing` excludes artifacts and must not be used
for this purpose. Plugin behavior and archive requirements are documented by
[Sonatype](https://central.sonatype.org/publish/publish-portal-maven/) and the
[Central requirements](https://central.sonatype.org/publish/requirements/).

A GitHub Release can optionally distribute these same frozen JAR/AAR/POM files
and checksums, or the signed bundle. Use the prepared files as upload inputs;
no second build is needed. GitHub Release creation is a separate manual action.

## Test the release tooling

```sh
python3 -m unittest discover -s native/scripts/tests -v
python3 -m unittest discover -s scripts/tests -v
python3 scripts/test_release_workflow.py
```

The workflow test compiles the real Java API with one packaging test and
explicitly synthetic native inputs. It packages, prepares the candidate and
runs the real Maven `deploy` lifecycle with the bundle-only profile, a
short-lived key in a temporary `GNUPGHOME` and dummy settings. Local artifact
installation is skipped so fixtures stay out of the dependency cache. A
file-only mirror and loopback Central endpoint keep the test local. Use
`--maven /absolute/path/to/mvn` to select Maven 3.9.2+ and `--maven-cache` to
select a populated public dependency cache.

The test verifies all 15 signatures/checksums and rejects changed outputs,
corrupt bundles, fixture publication, skipped validation and partial reactors.
It checks the plugin's upload-skipped confirmation. Synthetic native inputs
cannot execute QUIC or qualify a release. The temporary private key is deleted
afterward; only a public test key and ignored evidence remain.
