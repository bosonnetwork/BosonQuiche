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

import java.nio.ByteBuffer;
import java.util.Objects;
import java.util.function.Consumer;

/**
 * Socket-independent QUIC utilities and constants from quiche 0.30.1. Connections provide TLS,
 * streams and datagrams without creating sockets, threads or schedulers.
 */
public final class Quiche {
    /**
     * The current supported QUIC v1 wire version.
     */
    public static final long PROTOCOL_VERSION = 1;

    /**
     * The maximum connection-ID length in bytes (20).
     */
    public static final int MAX_CONN_ID_LEN = 20;

    /**
     * The minimum UDP payload for client Initial datagrams, in bytes (1200).
     */
    public static final int MIN_CLIENT_INITIAL_LEN = 1200;

    /**
     * The HTTP/3 ALPN identifier h3.
     */
    public static final String H3_APPLICATION_PROTOCOL = "h3";

    private Quiche() {
    }

    /**
     * Returns the version of the loaded native quiche library. The loader rejects a native library
     * that does not match the pinned binding version.
     *
     * @return the native quiche version string
     */
    public static String version() {
        return Native.version();
    }

    /**
     * Returns true if the given protocol version is supported.
     *
     * @param version the unsigned QUIC wire version
     * @return whether the condition described above holds
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/index.html">
     *         quiche 0.30.1 upstream API</a>
     */
    public static boolean versionIsSupported(long version) {
        return Native.versionIsSupported(Checks.u32(version));
    }

    /**
     * Parses the QUIC packet header without consuming the direct input buffer. dcidLength supplies
     * the destination connection-ID length for short-header packets. The result copies connection
     * IDs and tokens. Malformed input throws QuicheException.
     *
     * @param packet the direct packet buffer range; receive requires writable memory
     * @param dcidLength the destination ID length for short-header packets, in 0..20
     * @return the count or limit described above
     */
    public static PacketHeader headerInfo(ByteBuffer packet, int dcidLength) {
        Checks.buffer(packet, false);
        if (dcidLength < 0 || dcidLength > MAX_CONN_ID_LEN)
            throw new IllegalArgumentException("Invalid DCID length");

        return Native.headerInfo(packet, packet.position(), packet.remaining(), dcidLength);
    }

    /**
     * Builds a Version Negotiation packet from the source/destination IDs in the received packet.
     * QUIC reverses these IDs in its response header. The output must be a writable direct buffer;
     * its position advances by the encoded packet length. The application performs the actual
     * transmission.
     *
     * @param sourceId the source connection ID, at most 20 bytes
     * @param destinationId the destination connection ID, at most 20 bytes
     * @param out the writable direct output buffer, using position and limit
     * @return the encoded byte count
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/index.html">
     *         quiche 0.30.1 upstream API</a>
     */
    public static int negotiateVersion(byte[] sourceId, byte[] destinationId, ByteBuffer out) {
        Checks.buffer(out, true);
        int written = Native.negotiateVersion(Checks.cid(sourceId), Checks.cid(destinationId), out, out.position(),
                out.remaining());
        out.position(out.position() + written);

        return written;
    }

    /**
     * Builds a Retry packet into the writable direct output range. Supply the source and
     * destination IDs from the received Initial, a new server source ID and an
     * application-authenticated address-validation token. The application sends the packet and
     * validates the returned token before accepting the connection. On success the output position
     * advances by the packet length.
     *
     * @param sourceId the source connection ID, at most 20 bytes
     * @param destinationId the destination connection ID, at most 20 bytes
     * @param newSourceId the new source connection ID for Retry
     * @param token the token bytes
     * @param version the unsigned QUIC wire version
     * @param out the writable direct output buffer, using position and limit
     * @return the encoded byte count
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/index.html">
     *         quiche 0.30.1 upstream API</a>
     */
    public static int retry(byte[] sourceId, byte[] destinationId, byte[] newSourceId, byte[] token, long version,
            ByteBuffer out) {
        Checks.buffer(out, true);
        Objects.requireNonNull(token, "token");
        int written = Native.retry(Checks.cid(sourceId), Checks.cid(destinationId), Checks.cid(newSourceId), token,
                Checks.u32(version), out, out.position(), out.remaining());
        out.position(out.position() + written);

        return written;
    }

    /**
     * Encodes an unsigned QUIC variable-length integer into the current writable direct-buffer
     * range and advances the position by its wire length. Values must be in 0..2^62-1.
     * BUFFER_TOO_SHORT is reported as QuicheException.
     *
     * @param out the writable direct output buffer, using position and limit
     * @param value the unsigned value in 0..2^62-1
     * @return the encoded byte count
     */
    public static int putVarint(ByteBuffer out, long value) {
        Checks.buffer(out, true);
        if (value < 0 || value >= (1L << 62))
            throw new IllegalArgumentException("QUIC varint exceeds 62 bits");

        int written = Native.putVarint(out, out.position(), out.remaining(), value);
        out.position(out.position() + written);

        return written;
    }

    /**
     * Decodes an unsigned QUIC variable-length integer from the current direct-buffer range and
     * advances the position by its wire length. A truncated encoding throws QuicheException.
     *
     * @param input the direct encoded input buffer range
     * @return the decoded unsigned 62-bit value
     */
    public static long getVarint(ByteBuffer input) {
        Checks.buffer(input, false);
        long[] result = Native.getVarint(input, input.position(), input.remaining());
        input.position(input.position() + (int) result[1]);

        return result[0];
    }

    /**
     * Installs the process-global quiche debug logger once. Install before configuring
     * connections. Callback exceptions are dropped by native logging; callbacks must not re-enter
     * or dispose native owners. A second installation throws IllegalStateException.
     *
     * @param logger the process-global non-reentrant logging callback
     */
    public static synchronized void enableDebugLogging(Consumer<String> logger) {
        Objects.requireNonNull(logger, "logger");
        Native.debugLogging(line -> Native.callback(() -> {
            logger.accept(line);

            return null;
        }));
    }
}
