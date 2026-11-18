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
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;

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
        if (listener.getSummary().getTestsFoundCount() != 47 || listener.getSummary().getTestsFailedCount() != 0
                || listener.getSummary().getTestsSkippedCount() != 0)
            throw new AssertionError("Native suite did not pass all 47 tests");
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

