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
 * HTTP Extensible Priority parameters: urgency is 0 (highest) through 7 (lowest), and incremental
 * distinguishes incrementally delivered responses. Parse a serialized Priority field with
 * parse(byte[]).
 *
 * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Priority.html">
 *         quiche 0.30.1 upstream API</a>
 */
public final class H3Priority {
    /**
     * The urgency in 0..7, where zero is highest priority.
     */
    public final int urgency;

    /**
     * Whether the response can be processed incrementally.
     */
    public final boolean incremental;

    /**
     * Creates HTTP Extensible Priority parameters; urgency must be in 0..7.
     *
     * @param urgency the priority urgency
     * @param incremental whether delivery is incremental
     */
    public H3Priority(int urgency, boolean incremental) {
        if (urgency < 0 || urgency > 7)
            throw new IllegalArgumentException("HTTP/3 urgency must be 0..7");

        this.urgency = urgency;
        this.incremental = incremental;
    }

    /**
     * Parses an HTTP Extensible Priority field value using quiche Structured Fields support. The
     * returned urgency/incremental values are independent of the input bytes. Invalid input throws
     * H3Exception.
     *
     * @param field the serialized Priority field bytes
     * @return the decoded priority parameters
     */
    public static H3Priority parse(byte[] field) {
        return Native.h3ParsePriority(java.util.Objects.requireNonNull(field, "field"));
    }
}
