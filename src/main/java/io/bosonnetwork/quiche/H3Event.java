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

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/**
 * A copied HTTP/3 event. Native event memory is released before poll() returns. Headers are
 * immutable Java values; DATA is consumed separately with H3Connection.recvBody().
 *
 * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Event.html">
 *         quiche 0.30.1 upstream API</a>
 */
public final class H3Event {
    /**
     * The stream ID, or the GOAWAY identifier for a GOAWAY event.
     */
    public final long id;

    /**
     * The HTTP/3 event discriminator.
     */
    public final H3EventType type;

    /**
     * Whether more frames follow this header section; meaningful only for HEADERS.
     */
    public final boolean hasMoreFrames;
    private final List<H3Header> headers;

    H3Event(long id, int type, H3Header[] headers, boolean hasMoreFrames) {
        this.id = id;
        this.type = H3EventType.fromCode(type);
        this.hasMoreFrames = hasMoreFrames;
        this.headers = Collections.unmodifiableList(Arrays.asList(headers.clone()));
    }

    /**
     * Returns the immutable list of copied header fields, populated only for a HEADERS event.
     *
     * @return the copied values described above
     */
    public List<H3Header> headers() {
        return headers;
    }
}
