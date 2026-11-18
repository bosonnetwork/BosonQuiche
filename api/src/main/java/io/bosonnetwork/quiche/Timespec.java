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
 * A native monotonic timespec. This is not a wall-clock date or the epoch of System.nanoTime().
 * Use SendInfo.delayNanos for a relative scheduling delay. Upstream returns zero timing
 * information on macOS, iOS and Windows.
 */
public final class Timespec {
    /**
     * The native monotonic tv_sec component.
     */
    public final long seconds;

    /**
     * The tv_nsec component in 0..999,999,999.
     */
    public final long nanoseconds;

    /**
     * Creates a native monotonic timestamp value. The fractional nanoseconds component must be in
     * range.
     *
     * @param seconds the native monotonic seconds component
     * @param nanoseconds the fractional nanoseconds component in 0..999,999,999
     */
    public Timespec(long seconds, long nanoseconds) {
        if (nanoseconds < 0 || nanoseconds >= 1_000_000_000L)
            throw new IllegalArgumentException("Invalid tv_nsec");

        this.seconds = seconds;
        this.nanoseconds = nanoseconds;
    }
}
