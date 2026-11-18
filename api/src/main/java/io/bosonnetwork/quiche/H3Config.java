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
 * Owned HTTP/3 settings with upstream defaults. Close explicitly; initialized HTTP/3 connections
 * do not borrow this Java owner.
 *
 * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Config.html">
 *         quiche 0.30.1 upstream API</a>
 */
public final class H3Config extends NativeResource {
    /**
     * Creates an HTTP/3 configuration with upstream default settings. Close the owner explicitly.
     */
    public H3Config() {
        super(Native.h3ConfigNew(), 2);
    }

    private H3Config set(int option, long value) {
        Checks.nonnegative(value);

        synchronized (lock) {
            Native.h3ConfigSet(pointer(), option, value);
        }

        return this;
    }

    /**
     * Sets the <code>SETTINGS_MAX_FIELD_SECTION_SIZE</code> setting.
     * <p>
     * The default is <code>32768 bytes</code>. The value is measured in units of bytes, it is used
     * as a limit when parsing frames that contain encoded HTTP headers when <code>poll()</code> is
     * called. A first check is applied when handling HEADERS and PUSH_PROMISE frames themselves,
     * with some margin allowed on top of the provided size. A second check is applied when
     * decoding QPACK, implementing the rules described in <a
     * href="https://datatracker.ietf.org/doc/html/rfc9114#section-4.2.2">https://datatracker.ietf.org/doc/html/rfc9114#section-4.2.2</a>.
     * <p>
     * When headers exceed the limit set by the application, the call to the <code>poll()</code>
     * method will return the <code>H3Error.EXCESSIVE_LOAD</code> error, and the connection will be
     * closed.
     *
     * @param value the configuration value, in the units described above
     * @return this configuration
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Config.html#method.set_max_field_section_size">
     *         quiche 0.30.1 upstream API</a>
     */
    public H3Config setMaxFieldSectionSize(long value) {
        return set(0, value);
    }

    /**
     * Sets the <code>SETTINGS_QPACK_MAX_TABLE_CAPACITY</code> setting.
     * <p>
     * The default value is <code>0</code>.
     *
     * @param value the configuration value, in the units described above
     * @return this configuration
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Config.html#method.set_qpack_max_table_capacity">
     *         quiche 0.30.1 upstream API</a>
     */
    public H3Config setQpackMaxTableCapacity(long value) {
        return set(1, value);
    }

    /**
     * Sets the <code>SETTINGS_QPACK_BLOCKED_STREAMS</code> setting.
     * <p>
     * The default value is <code>0</code>.
     *
     * @param value the configuration value, in the units described above
     * @return this configuration
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Config.html#method.set_qpack_blocked_streams">
     *         quiche 0.30.1 upstream API</a>
     */
    public H3Config setQpackBlockedStreams(long value) {
        return set(2, value);
    }

    /**
     * Sets or omits the <code>SETTINGS_ENABLE_CONNECT_PROTOCOL</code> setting.
     * <p>
     * The default value is <code>false</code>.
     *
     * @param value whether this feature is enabled
     * @return this configuration
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Config.html#method.enable_extended_connect">
     *         quiche 0.30.1 upstream API</a>
     */
    public H3Config enableExtendedConnect(boolean value) {
        return set(3, value ? 1 : 0);
    }

    /**
     * Sets the maximum size for the payload of PRIORITY_UPDATE frames.
     * <p>
     * The default is <code>256 bytes</code>. The value uses units of bytes.
     * <p>
     * When a PRIORITY_UPDATE frame exceeds the limit set by the application, the call to the
     * <code>poll()</code> method will return the <code>H3Error.EXCESSIVE_LOAD</code> error, and
     * the connection will be closed.
     *
     * @param value the configuration value, in the units described above
     * @return this configuration
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Config.html#method.set_max_priority_update_size">
     *         quiche 0.30.1 upstream API</a>
     */
    public H3Config setMaxPriorityUpdateSize(long value) {
        return set(4, value);
    }
}
