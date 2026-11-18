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
 * An HTTP/3 operation failure, including transport errors propagated through the HTTP/3 C API.
 * code() always preserves the numeric value; error() resolves the corresponding mapped enum.
 */
public final class H3Exception extends RuntimeException {
    private static final long serialVersionUID = 1L;

    /** @serial The native HTTP/3 error code, including propagated transport errors. */
    private final int code;

    /**
     * Creates an HTTP/3 error that retains the native numeric code.
     *
     * @param code the upstream numeric code
     */
    public H3Exception(int code) {
        super("quiche HTTP/3 error " + code);
        this.code = code;
    }

    /**
     * Returns the upstream numeric enum/error code.
     *
     * @return the upstream numeric code
     */
    public int code() {
        return code;
    }

    /**
     * Returns the mapped upstream error enum.
     *
     * @return the count or limit described above
     */
    public H3Error error() {
        return H3Error.fromCode(code);
    }
}
