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

import java.net.InetSocketAddress;
import java.nio.ByteBuffer;
import java.util.Objects;

final class Checks {
    private Checks() {
    }

    static int u32(long value) {
        if (value < 0 || value > 0xffffffffL)
            throw new IllegalArgumentException("Value is not uint32");

        return (int) value;
    }

    static void nonnegative(long value) {
        if (value < 0)
            throw new IllegalArgumentException("Negative length or index");
    }

    static byte[] cid(byte[] id) {
        if (Objects.requireNonNull(id, "connectionId").length > Quiche.MAX_CONN_ID_LEN)
            throw new IllegalArgumentException("Connection ID exceeds 20 bytes");

        return id;
    }

    static void buffer(ByteBuffer buffer, boolean writable) {
        Objects.requireNonNull(buffer, "buffer");
        if (!buffer.isDirect())
            throw new IllegalArgumentException("A direct ByteBuffer is required");

        if (writable && buffer.isReadOnly())
            throw new IllegalArgumentException("A writable ByteBuffer is required");
    }

    static InetSocketAddress address(InetSocketAddress address) {
        if (Objects.requireNonNull(address, "address").isUnresolved())
            throw new IllegalArgumentException("Socket address must be resolved");

        return address;
    }
}
