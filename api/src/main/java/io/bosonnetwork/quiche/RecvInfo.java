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

/**
 * Source and destination metadata for one received UDP datagram. Addresses must be resolved and
 * describe the observed path; this object owns no socket.
 *
 * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.RecvInfo.html">
 *         quiche 0.30.1 upstream API</a>
 */
public final class RecvInfo {
    /**
     * The remote address the packet was received from.
     */
    public final InetSocketAddress from;

    /**
     * The local address the packet was received on.
     */
    public final InetSocketAddress to;

    /**
     * Creates resolved source/destination metadata for a received datagram.
     *
     * @param from the resolved source address, or null for automatic send-path selection
     * @param to the resolved destination address, or null for automatic send-path selection
     */
    public RecvInfo(InetSocketAddress from, InetSocketAddress to) {
        this.from = Checks.address(from);
        this.to = Checks.address(to);
    }
}
