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
 * Owns a native allocation. All native calls and disposal share a monitor. Close owners
 * explicitly; further native operations on a disposed owner throw IllegalStateException.
 */
abstract class NativeResource implements AutoCloseable {
    final Object lock;
    private long handle;
    private final int type;

    NativeResource(long handle, int type) {
        this(handle, type, new Object());
    }

    NativeResource(long handle, int type, Object lock) {
        if (handle == 0)
            throw new IllegalStateException("Could not create native resource");

        this.handle = handle;
        this.type = type;
        this.lock = lock;
    }

    final long pointer() {
        Native.checkCallback();
        if (handle == 0)
            throw new IllegalStateException("Native resource is closed");

        return handle;
    }

    /**
     * Returns whether native memory has been released. This is different from the QUIC protocol
     * closed state.
     *
     * @return whether the condition described above holds
     */
    public final boolean isDisposed() {
        synchronized (lock) {
            return handle == 0;
        }
    }

    /**
     * Idempotently frees the native allocation. This no-argument method does not initiate a
     * graceful protocol close; queue a protocol close and drain output first if required.
     */
    @Override
    public final void close() {
        synchronized (lock) {
            Native.checkCallback();
            if (handle != 0) {
                Native.free(handle, type);
                handle = 0;
            }
        }
    }
}
