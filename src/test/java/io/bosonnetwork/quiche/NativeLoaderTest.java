/*
 * Copyright (c) 2026 bosonnetwork.io
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

package io.bosonnetwork.quiche;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

import static org.junit.jupiter.api.Assertions.*;

class NativeLoaderTest {
    @ParameterizedTest
    @CsvSource({"Linux,amd64,HotSpot,Java Runtime Environment,linux-x86_64",
                "Linux,aarch64,HotSpot,Java Runtime Environment,linux-aarch64",
                "Mac OS X,arm64,OpenJDK,OpenJDK Runtime Environment,macos-aarch64",
                "Darwin,aarch64,OpenJDK,OpenJDK Runtime Environment,macos-aarch64",
                "Windows 11,amd64,HotSpot,Java Runtime Environment,windows-x86_64",
                "Windows 11,arm64,HotSpot,Java Runtime Environment,windows-aarch64",
                "Linux,aarch64,Dalvik,Android Runtime,android-aarch64",
                "Linux,arm64,ART,Android Runtime,android-aarch64"})
    void selectsTargetBeforeChoosingTheLoadingMechanism(String os, String arch, String vm,
                                                        String runtime, String expected) {
        assertEquals(expected, NativeLoader.classifier(os, arch, vm, runtime));
    }

    @Test
    void unsupportedPlatformsFailWithTheSelectedPlatform() {
        UnsatisfiedLinkError android = assertThrows(UnsatisfiedLinkError.class,
                () -> NativeLoader.classifier("Linux", "x86_64", "Dalvik", "Android Runtime"));
        assertTrue(android.getMessage().contains("arch=x86_64"));
        assertThrows(UnsatisfiedLinkError.class,
                () -> NativeLoader.classifier("FreeBSD", "amd64", "OpenJDK", "OpenJDK"));
        assertThrows(UnsatisfiedLinkError.class,
                () -> NativeLoader.classifier("Mac OS X", "x86_64", "OpenJDK", "OpenJDK"));
    }

    @Test
    void androidUsesItsPackagedLibraryWithoutResourceExtraction() {
        RecordingLinker linker = new RecordingLinker();
        NativeLoader.loadLibrary(null, "android-aarch64", linker);
        assertEquals(List.of("library:boson_quiche"), linker.calls);
    }

    @Test
    void explicitOverridePrecedesPlatformSelection() {
        RecordingLinker linker = new RecordingLinker();
        NativeLoader.loadLibrary("custom-native-library", null, linker);
        assertEquals(List.of("path:" + new File("custom-native-library").getAbsolutePath()), linker.calls);
    }

    @Test
    void desktopResourceIsExtractedToAnIsolatedDirectory() {
        String platform = NativeLoader.classifier(System.getProperty("os.name"), System.getProperty("os.arch"),
                System.getProperty("java.vm.name"), System.getProperty("java.runtime.name"));
        RecordingLinker linker = new RecordingLinker();
        NativeLoader.loadLibrary(null, platform, linker);
        assertEquals(1, linker.calls.size());
        Path library = Path.of(linker.calls.get(0).substring("path:".length()));
        assertTrue(Files.isRegularFile(library));
        assertEquals(System.mapLibraryName("boson_quiche"), library.getFileName().toString());
        assertTrue(library.getParent().getFileName().toString().startsWith("boson-quiche-"));
    }

    @ParameterizedTest
    @CsvSource({"abi,Binding ABI mismatch", "version,Binding version mismatch",
                "upstream,Binding requires quiche", "legacy,has no binding ABI metadata"})
    void staleNativeArtifactsFailBeforeNormalApiCalls(String fixture, String message) throws Exception {
        Path directory = Path.of(System.getProperty("boson.quiche.test.libraries"));
        Path library = directory.resolve(System.mapLibraryName("loader_" + fixture));
        assertTrue(Files.isRegularFile(library), "Missing loader fixture " + library);
        probe(message, library);
    }

    @Test
    void matchingArtifactsLoadInAFreshJvm() throws Exception {
        probe("success", null);
    }

    @Test
    void matchingArtifactsLoadThroughAnExplicitPath() throws Exception {
        String platform = NativeLoader.classifier(System.getProperty("os.name"), System.getProperty("os.arch"),
                System.getProperty("java.vm.name"), System.getProperty("java.runtime.name"));
        Path library = Path.of(NativeLoader.class.getResource(
                "/native/" + platform + "/" + System.mapLibraryName("boson_quiche")).toURI());
        probe("success", library);
    }

    private static void probe(String expected, Path library) throws Exception {
        List<String> command = new ArrayList<>();
        command.add(Path.of(System.getProperty("java.home"), "bin", "java").toString());
        command.add("-Xcheck:jni");
        if (library != null)
            command.add("-Dboson.quiche.library=" + library.toAbsolutePath());

        command.add("-cp");
        command.add(System.getProperty("java.class.path"));
        command.add(NativeLoadProbe.class.getName());
        command.add(expected);
        Process process = new ProcessBuilder(command).redirectErrorStream(true).start();
        if (!process.waitFor(30, TimeUnit.SECONDS)) {
            process.destroyForcibly();
            fail("Native loader probe timed out");
        }

        String output = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        assertEquals(0, process.exitValue(), output);
    }

    private static final class RecordingLinker implements NativeLoader.Linker {
        private final List<String> calls = new ArrayList<>();

        @Override
        public void load(String path) {
            calls.add("path:" + path);
        }

        @Override
        public void loadLibrary(String name) {
            calls.add("library:" + name);
        }
    }
}

