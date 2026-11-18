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

/**
 * A copied QUIC packet-header snapshot. Parsing does not consume the input buffer. Connection IDs
 * and tokens are returned as defensive byte-array copies.
 *
 * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Header.html">
 *         quiche 0.30.1 upstream API</a>
 */
public final class PacketHeader {
    /**
     * The unsigned 32-bit QUIC wire version; zero denotes version negotiation.
     */
    public final long version;

    /**
     * The parsed QUIC packet type.
     */
    public final PacketType type;
    private final byte[] sourceId;
    private final byte[] destinationId;
    private final byte[] token;

    PacketHeader(long version, int type, byte[] sourceId, byte[] destinationId, byte[] token) {
        this.version = version;
        this.type = PacketType.fromCode(type);
        this.sourceId = sourceId.clone();
        this.destinationId = destinationId.clone();
        this.token = token.clone();
    }

    /**
     * Returns a defensive copy of the source connection ID.
     *
     * @return the copied bytes, empty when unavailable where documented above
     */
    public byte[] sourceId() {
        return sourceId.clone();
    }

    /**
     * Returns a defensive copy of the destination connection ID.
     *
     * @return the copied bytes, empty when unavailable where documented above
     */
    public byte[] destinationId() {
        return destinationId.clone();
    }

    /**
     * Returns a defensive copy of the Retry/address-validation token.
     *
     * @return the copied bytes, empty when unavailable where documented above
     */
    public byte[] token() {
        return token.clone();
    }
}
