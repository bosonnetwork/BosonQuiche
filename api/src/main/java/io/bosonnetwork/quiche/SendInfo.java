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
 * Output metadata from one native packet-send operation. The output buffer contains
 * <code>bytes</code> bytes of one UDP datagram; the application transmits it using the indicated
 * path and pacing information.
 *
 * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.SendInfo.html">
 *         quiche 0.30.1 upstream API</a>
 */
public final class SendInfo {
    /**
     * The number of bytes written into the output buffer for this datagram.
     */
    public final int bytes;

    /**
     * The local address the packet should be sent from.
     */
    public final InetSocketAddress from;

    /**
     * The remote address the packet should be sent to.
     */
    public final InetSocketAddress to;

    /**
     * The native monotonic send time. This is not a Java nanoTime epoch or wall-clock timestamp.
     * Upstream 0.30.1 supplies zero on macOS/iOS/Windows.
     */
    public final Timespec at;

    /**
     * The nonnegative relative pacing delay, in nanoseconds, sampled natively when send returned.
     * Zero means due now or unavailable. Account for time already spent before scheduling.
     */
    public final long delayNanos;

    SendInfo(int bytes, InetSocketAddress from, InetSocketAddress to, Timespec at, long delayNanos) {
        this.bytes = bytes;
        this.from = from;
        this.to = to;
        this.at = at;
        this.delayNanos = delayNanos;
    }
}
