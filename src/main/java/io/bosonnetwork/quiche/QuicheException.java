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
 * A QUIC operation failure mapped from an upstream error code. DONE is normally represented by
 * null or -1 on nonblocking APIs. STREAM_RESET and STREAM_STOPPED preserve the peer application
 * error code.
 */
public final class QuicheException extends RuntimeException {
    private static final long serialVersionUID = 1L;

    /** @serial The mapped native QUIC error. */
    private final QuicheError error;

    /** @serial The unsigned application stream error-code bit pattern. */
    private final long streamErrorCode;

    /**
     * Creates a QUIC error with an optional stream application error code.
     *
     * @param code the upstream numeric code
     * @param streamErrorCode the unsigned application error code for a reset or stopped stream
     */
    public QuicheException(int code, long streamErrorCode) {
        super("quiche: " + QuicheError.fromCode(code) + " (" + code + ")");
        this.error = QuicheError.fromCode(code);
        this.streamErrorCode = streamErrorCode;
    }

    /**
     * Returns the mapped upstream error enum.
     *
     * @return the count or limit described above
     */
    public QuicheError error() {
        return error;
    }

    /**
     * Returns the unsigned peer application error code, meaningful for STREAM_RESET and
     * STREAM_STOPPED.
     *
     * @return the count or limit described above
     */
    public long streamErrorCode() {
        return streamErrorCode;
    }
}
