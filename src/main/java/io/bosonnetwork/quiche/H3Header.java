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

import java.nio.charset.StandardCharsets;
import java.util.Objects;

/**
 * A copied HTTP/3 header name/value pair. Use byte-array accessors for lossless values; string
 * helpers decode UTF-8. Applications remain responsible for validating pseudo-headers and header
 * fields.
 *
 * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Header.html">
 *         quiche 0.30.1 upstream API</a>
 */
public final class H3Header {
    private final byte[] name;
    private final byte[] value;

    /**
     * Creates a header by copying the supplied name/value bytes, or by UTF-8 encoding the supplied
     * strings.
     *
     * @param name the header name bytes or UTF-8 string
     * @param value the header value bytes or UTF-8 string
     */
    public H3Header(byte[] name, byte[] value) {
        this.name = Objects.requireNonNull(name, "name").clone();
        this.value = Objects.requireNonNull(value, "value").clone();
    }

    /**
     * Creates a header by copying the supplied name/value bytes, or by UTF-8 encoding the supplied
     * strings.
     *
     * @param name the header name bytes or UTF-8 string
     * @param value the header value bytes or UTF-8 string
     */
    public H3Header(String name, String value) {
        this(name.getBytes(StandardCharsets.UTF_8), value.getBytes(StandardCharsets.UTF_8));
    }

    /**
     * Returns a defensive copy of the header name bytes.
     *
     * @return the copied bytes, empty when unavailable where documented above
     */
    public byte[] name() {
        return name.clone();
    }

    /**
     * Returns a defensive copy of the header value bytes.
     *
     * @return the copied bytes, empty when unavailable where documented above
     */
    public byte[] value() {
        return value.clone();
    }

    /**
     * Decodes the header name as UTF-8.
     *
     * @return the count or limit described above
     */
    public String nameAsString() {
        return new String(name, StandardCharsets.UTF_8);
    }

    /**
     * Decodes the header value as UTF-8.
     *
     * @return the count or limit described above
     */
    public String valueAsString() {
        return new String(value, StandardCharsets.UTF_8);
    }
}
