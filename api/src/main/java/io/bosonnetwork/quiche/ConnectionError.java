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
 * A copied local or peer CONNECTION_CLOSE error. The application flag selects application versus
 * transport error codes. The unsigned native code is represented by a Java long bit pattern.
 */
public final class ConnectionError {
    /**
     * True for an application close code, false for a transport close code.
     */
    public final boolean application;

    /**
     * The unsigned native close-code bit pattern.
     */
    public final long code;
    private final byte[] reason;

    ConnectionError(boolean application, long code, byte[] reason) {
        this.application = application;
        this.code = code;
        this.reason = reason.clone();
    }

    /**
     * Returns a defensive copy of the close-reason bytes.
     *
     * @return the copied bytes, empty when unavailable where documented above
     */
    public byte[] reason() {
        return reason.clone();
    }
}
