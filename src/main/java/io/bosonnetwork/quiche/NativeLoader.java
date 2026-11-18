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
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.Locale;
import java.util.Properties;

/** Selects a native library and verifies its binding contract before use. */
final class NativeLoader {
    interface Linker {
        void load(String path);

        void loadLibrary(String name);
    }

    private NativeLoader() {
    }

    static void load() {
        Properties expected = metadata();
        String explicit = System.getProperty("boson.quiche.library");
        String platform = explicit == null ? classifier(System.getProperty("os.name", ""),
                System.getProperty("os.arch", ""), System.getProperty("java.vm.name", ""),
                System.getProperty("java.runtime.name", "")) : null;

        loadLibrary(explicit, platform, new Linker() {
            @Override
            public void load(String path) {
                System.load(path);
            }

            @Override
            public void loadLibrary(String name) {
                System.loadLibrary(name);
            }
        });

        int actualAbi;
        String actualVersion;
        try {
            actualAbi = Native.bindingAbi();
        } catch (UnsatisfiedLinkError error) {
            throw incompatible("Native library has no binding ABI metadata; use matching BosonQuiche artifacts", error);
        }

        int expectedAbi = Integer.parseInt(expected.getProperty("binding.abi"));
        if (actualAbi != expectedAbi)
            throw new UnsatisfiedLinkError("Binding ABI mismatch: Java requires " + expectedAbi + ", native has " + actualAbi);

        try {
            actualVersion = Native.bindingVersion();
        } catch (UnsatisfiedLinkError error) {
            throw incompatible("Native library has no binding version metadata; use matching BosonQuiche artifacts", error);
        }

        String expectedVersion = expected.getProperty("binding.version");
        if (!expectedVersion.equals(actualVersion))
            throw new UnsatisfiedLinkError("Binding version mismatch: Java requires " + expectedVersion
                    + ", native has " + actualVersion);

        String expectedQuiche = expected.getProperty("quiche.version");
        String actualQuiche = Native.version();
        if (!expectedQuiche.equals(actualQuiche))
            throw new UnsatisfiedLinkError("Binding requires quiche " + expectedQuiche + ", found " + actualQuiche);
    }

    private static UnsatisfiedLinkError incompatible(String message, UnsatisfiedLinkError cause) {
        UnsatisfiedLinkError error = new UnsatisfiedLinkError(message);
        error.initCause(cause);
        return error;
    }

    private static Properties metadata() {
        Properties properties = new Properties();
        try (InputStream input = NativeLoader.class.getResourceAsStream("/META-INF/boson-quiche.properties")) {
            if (input == null)
                throw new UnsatisfiedLinkError("Missing BosonQuiche build metadata; rebuild the Java artifact");

            properties.load(input);
            for (String key : new String[]{"binding.version", "binding.abi", "quiche.version"}) {
                String value = properties.getProperty(key);
                if (value == null || value.isEmpty() || value.contains("${"))
                    throw new UnsatisfiedLinkError("Invalid BosonQuiche build metadata: " + key);
            }

            if (Integer.parseInt(properties.getProperty("binding.abi")) < 1)
                throw new NumberFormatException("Binding ABI must be positive");
        } catch (IOException | NumberFormatException error) {
            throw new ExceptionInInitializerError(error);
        }

        return properties;
    }

    static String classifier(String os, String arch, String vm, String runtime) {
        String system = os.toLowerCase(Locale.ROOT);
        String machine = arch.toLowerCase(Locale.ROOT);
        String virtualMachine = vm.toLowerCase(Locale.ROOT);
        if (virtualMachine.contains("dalvik") || virtualMachine.equals("art")
                || runtime.toLowerCase(Locale.ROOT).contains("android"))
            system = "android";
        else if (system.contains("mac") || system.equals("darwin"))
            system = "macos";
        else if (system.contains("linux"))
            system = "linux";
        else if (system.startsWith("windows"))
            system = "windows";

        if (machine.equals("arm64"))
            machine = "aarch64";
        else if (machine.equals("amd64"))
            machine = "x86_64";

        if ((system.equals("android") || system.equals("macos")) && machine.equals("aarch64")
                || (system.equals("linux") || system.equals("windows"))
                && (machine.equals("x86_64") || machine.equals("aarch64")))
            return system + "-" + machine;

        throw new UnsatisfiedLinkError("Unsupported BosonQuiche platform: os=" + os + ", arch=" + arch
                + ", vm=" + vm + "; supported: Linux/Windows amd64 or arm64, macOS/Android arm64");
    }

    static void loadLibrary(String explicit, String platform, Linker linker) {
        if (explicit != null) {
            linker.load(new File(explicit).getAbsolutePath());
            return;
        }

        if (platform.equals("android-aarch64")) {
            linker.loadLibrary("boson_quiche");
            return;
        }

        String name = System.mapLibraryName("boson_quiche");
        String resource = "/native/" + platform + "/" + name;
        try (InputStream input = NativeLoader.class.getResourceAsStream(resource)) {
            if (input == null)
                throw new UnsatisfiedLinkError("No bundled native library " + resource
                        + "; set -Dboson.quiche.library=/absolute/path/to/library");

            Path directory = Files.createTempDirectory("boson-quiche-");
            Path library = directory.resolve(name);
            directory.toFile().deleteOnExit();
            library.toFile().deleteOnExit();
            Files.copy(input, library, StandardCopyOption.REPLACE_EXISTING);
            linker.load(library.toAbsolutePath().toString());
        } catch (IOException error) {
            throw new ExceptionInInitializerError(error);
        }
    }
}

