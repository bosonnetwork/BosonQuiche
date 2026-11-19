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

import java.io.PrintWriter;
import java.io.InputStream;
import java.io.OutputStream;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.Properties;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.provider.ValueSource;
import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;
import org.junit.platform.launcher.listeners.SummaryGeneratingListener;

/** Runs the same native regressions on container JVMs and Android ART. */
public final class NativeSuite {
    private NativeSuite() {
    }

    public static void main(String[] args) throws Exception {
        if (args.length == 1 && args[0].equals("android")) {
            android();
            return;
        }

        SummaryGeneratingListener listener = new SummaryGeneratingListener();
        LauncherFactory.create().execute(LauncherDiscoveryRequestBuilder.request()
                .selectors(DiscoverySelectors.selectPackage("io.bosonnetwork.quiche")).build(), listener);
        listener.getSummary().printTo(new PrintWriter(System.out, true));
        listener.getSummary().printFailuresTo(new PrintWriter(System.out, true));
        if (listener.getSummary().getTestsFoundCount() != 47 || listener.getSummary().getTestsSucceededCount() != 47
                || listener.getSummary().getTestsFailedCount() != 0
                || listener.getSummary().getTestsSkippedCount() != 0)
            throw new AssertionError("Native suite did not pass all 47 tests");

        if (args.length == 2 && args[0].equals("--report")) {
            Properties report = new Properties();
            report.setProperty("status", "passed");
            report.setProperty("tests", "47");
            report.setProperty("java_os", System.getProperty("os.name"));
            report.setProperty("java_arch", System.getProperty("os.arch"));
            report.setProperty("java_version", System.getProperty("java.runtime.version"));
            report.setProperty("binding_version", Native.bindingVersion());
            report.setProperty("binding_abi", Integer.toString(Native.bindingAbi()));
            String classifier = NativeLoader.classifier(System.getProperty("os.name"), System.getProperty("os.arch"),
                    System.getProperty("java.vm.name"), System.getProperty("java.runtime.name"));
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            try (InputStream input = NativeLoader.class.getResourceAsStream(
                    "/native/" + classifier + "/" + System.mapLibraryName("boson_quiche"))) {
                if (input == null)
                    throw new AssertionError("Missing packaged native resource");

                byte[] buffer = new byte[8192];
                int count;
                while ((count = input.read(buffer)) != -1)
                    digest.update(buffer, 0, count);
            }

            StringBuilder checksum = new StringBuilder();
            for (byte value : digest.digest())
                checksum.append(String.format("%02x", value & 0xff));

            report.setProperty("native_sha256", checksum.toString());
            try (OutputStream output = Files.newOutputStream(Path.of(args[1]))) {
                report.storeToXML(output, "BosonQuiche JNI runtime evidence", "UTF-8");
            }
        }
    }

    private static void android() throws Exception {
        // ART has no child desktop JVM executable. Run all transport regressions
        // directly, including every ValueSource case; forked loader fixtures run
        // on desktop JVMs. Their Android loadLibrary branch is checked separately.
        Class<?>[] classes = {QuicheTest.class, ConnectionTest.class, PathAndTlsTest.class,
                              H3Test.class, DirectBufferTest.class, NativePortabilityTest.class};
        int passed = 0;
        for (Class<?> type : classes) {
            Object instance = type.getDeclaredConstructor().newInstance();
            for (Method method : type.getDeclaredMethods()) {
                if (method.isAnnotationPresent(Test.class)) {
                    invoke(instance, method);
                    passed++;
                } else {
                    ValueSource values = method.getAnnotation(ValueSource.class);
                    if (values == null)
                        continue;

                    for (long value : values.longs()) {
                        invoke(instance, method, value);
                        passed++;
                    }
                    for (String value : values.strings()) {
                        invoke(instance, method, value);
                        passed++;
                    }
                }
            }
        }

        new NativeLoaderTest().androidUsesItsPackagedLibraryWithoutResourceExtraction();
        if (passed != 29)
            throw new AssertionError("Expected 29 Android transport cases, ran " + passed);

        System.out.println("Passed 29 Android JNI transport cases and the loadLibrary branch check");
    }

    private static void invoke(Object instance, Method method, Object... arguments) throws Exception {
        try {
            method.invoke(instance, arguments);
            System.out.println("Passed " + method.getName());
        } catch (InvocationTargetException error) {
            throw new AssertionError("Failed " + method.getName(), error.getCause());
        }
    }
}

