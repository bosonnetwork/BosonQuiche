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

import java.io.IOException;
import java.io.InputStream;
import java.net.Inet6Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.UnknownHostException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.Locale;

/** JNI entry points. Native handles and ABI-dependent layouts stay internal. */
final class Native {
    private static final ThreadLocal<Boolean> CALLBACK = ThreadLocal.withInitial(() -> false);
    static {
        load();
    }

    private Native() {
    }

    static void checkCallback() {
        if (CALLBACK.get())
            throw new IllegalStateException("Native callbacks must not re-enter or dispose native resources");
    }

    static <T> T callback(java.util.function.Supplier<T> callback) {
        boolean previous = CALLBACK.get();
        CALLBACK.set(true);

        try {
            return callback.get();
        } finally {
            CALLBACK.set(previous);
        }
    }

    private static void load() {
        String explicit = System.getProperty("boson.quiche.library");
        if (explicit != null) {
            System.load(Path.of(explicit).toAbsolutePath().toString());
            checkVersion();

            return;
        }

        String os = System.getProperty("os.name").toLowerCase(Locale.ROOT);
        os = os.contains("mac") ? "macos" : os.contains("linux") ? "linux" : os.contains("win") ? "windows" : os;
        String arch = System.getProperty("os.arch").toLowerCase(Locale.ROOT);
        if (arch.equals("arm64"))
            arch = "aarch64";

        if (arch.equals("amd64"))
            arch = "x86_64";

        String name = System.mapLibraryName("boson_quiche");
        String resource = "/native/" + os + "-" + arch + "/" + name;

        try (InputStream input = Native.class.getResourceAsStream(resource)) {
            if (input == null)
                throw new UnsatisfiedLinkError("No bundled native library " + resource
                        + "; set -Dboson.quiche.library=/absolute/path/to/library");

            Path directory = Files.createTempDirectory("boson-quiche-");
            Path library = directory.resolve(name);
            directory.toFile().deleteOnExit();
            library.toFile().deleteOnExit();
            Files.copy(input, library, StandardCopyOption.REPLACE_EXISTING);
            System.load(library.toAbsolutePath().toString());
        } catch (IOException error) {
            throw new ExceptionInInitializerError(error);
        }

        checkVersion();
    }

    private static void checkVersion() {
        if (!version().equals("0.30.1"))
            throw new UnsatisfiedLinkError("Binding requires quiche 0.30.1, found " + version());
    }

    static byte[] utf8(String text) {
        if (text.indexOf('\0') >= 0)
            throw new IllegalArgumentException("Embedded NUL in native string");

        return text.getBytes(StandardCharsets.UTF_8);
    }

    static byte[] address(InetSocketAddress address) {
        Checks.address(address);
        byte[] ip = address.getAddress().getAddress();
        ByteBuffer encoded = ByteBuffer.allocate(1 + ip.length + 6);
        encoded.put((byte) ip.length).put(ip).putShort((short) address.getPort());
        encoded.putInt(address.getAddress() instanceof Inet6Address ? ((Inet6Address) address.getAddress())
                .getScopeId() : 0);

        return encoded.array();
    }

    static InetSocketAddress socketAddress(byte[] bytes, int port, int scope) {
        try {
            InetAddress ip = bytes.length == 16 ? Inet6Address.getByAddress(null, bytes, scope) : InetAddress
                    .getByAddress(bytes);

            return new InetSocketAddress(ip, port);
        } catch (UnknownHostException impossible) {
            throw new IllegalArgumentException(impossible);
        }
    }

    static native String version();

    static native boolean versionIsSupported(int version);

    static native int[] enumValues();

    static native void free(long handle, int type);

    static native long configNew(int version);

    static native void configSet(long handle, int option, long value);

    static native void configText(long handle, int option, byte[] text);

    static native void configBytes(long handle, int option, byte[] data);

    static native void configFlag(long handle, int option);

    static native void configDgram(long handle, boolean enabled, int receiveQueue, int sendQueue);

    static native PacketHeader headerInfo(ByteBuffer data, int offset, int length, int dcidLength);

    static native int negotiateVersion(byte[] sourceId, byte[] destinationId, ByteBuffer out, int offset, int length);

    static native int retry(byte[] sourceId, byte[] destinationId, byte[] newSourceId, byte[] token, int version,
            ByteBuffer out, int offset, int length);

    static native long connect(long config, byte[] serverName, byte[] sourceId, byte[] originalId, byte[] local,
            byte[] peer, boolean server);

    static native int recv(long handle, ByteBuffer data, int offset, int length, byte[] from, byte[] to);

    static native SendInfo send(long handle, ByteBuffer data, int offset, int length, byte[] from, byte[] to);

    static native StreamResult streamRecv(long handle, long stream, ByteBuffer out, int offset, int length);

    static native int streamSend(long handle, long stream, ByteBuffer data, int offset, int length, boolean fin);

    static native long connGet(long handle, int option, long argument);

    static native void connAction(long handle, int option, long argument);

    static native int streamWritable(long handle, long stream, long length);

    static native void streamPriority(long handle, long stream, int urgency, boolean incremental);

    static native void streamShutdown(long handle, long stream, int direction, long error);

    static native long[] streams(long handle, boolean writable);

    static native byte[] connBytes(long handle, int option);

    static native boolean connText(long handle, int option, byte[] text, byte[] extra, byte[] extra2);

    static native void setSession(long handle, byte[] data);

    static native void closeConnection(long handle, boolean application, long error, byte[] reason);

    static native ConnectionError connectionError(long handle, boolean peer);

    static native Stats stats(long handle);

    static native TransportParams transportParams(long handle);

    static native PathStats pathStats(long handle, int index);

    static native int datagram(long handle, boolean send, ByteBuffer data, int offset, int length);

    static native void purgeDatagrams(long handle, java.util.function.Predicate<byte[]> predicate);

    static native byte[][] connectionIds(long handle, boolean retired);

    static native long newScid(long handle, byte[] id, byte[] token, boolean retire);

    static native long pathAction(long handle, int option, byte[] local, byte[] peer);

    static native PathEvent pathEvent(long handle);

    static native InetSocketAddress[] paths(long handle, byte[] local);

    static native int putVarint(ByteBuffer out, int offset, int length, long value);

    static native long[] getVarint(ByteBuffer data, int offset, int length);

    static native void debugLogging(java.util.function.Consumer<String> logger);

    static native long h3ConfigNew();

    static native void h3ConfigSet(long handle, int option, long value);

    static native long h3New(long connection, long config);

    static native H3Event h3Poll(long handle, long transport);

    static native long h3Headers(long handle, long transport, int option, long stream, byte[][] names, byte[][] values,
            boolean fin, int urgency, boolean incremental, boolean trailer);

    static native int h3Body(long handle, long transport, long stream, ByteBuffer buffer, int offset, int length,
            boolean send, boolean fin);

    static native void h3Action(long handle, long transport, int option, long stream, int urgency, boolean incremental);

    static native boolean h3Enabled(long handle, long transport, boolean datagram);

    static native long[] h3Settings(long handle);

    static native H3Priority h3ParsePriority(byte[] data);

    static native byte[] h3TakePriority(long handle, long stream);

    static native H3Stats h3Stats(long handle);
}
