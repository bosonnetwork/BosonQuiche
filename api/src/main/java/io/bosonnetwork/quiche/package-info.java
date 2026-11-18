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

/**
 * Socket-independent Java bindings for Cloudflare quiche 0.30.1.
 *
 * <p>Configure {@link io.bosonnetwork.quiche.Config}, create a
 * {@link io.bosonnetwork.quiche.Connection}, and exchange packets through
 * application-owned UDP or ICE transport. The binding creates no sockets,
 * threads or schedulers. TLS is supplied by quiche and its bundled BoringSSL.
 *
 * <p>Bulk I/O uses direct {@link java.nio.ByteBuffer} ranges without an extra
 * JNI payload copy. Packet receive decrypts in place; stream/body writes can
 * accept only a prefix. Nonblocking results use {@code null} or {@code -1} for
 * upstream DONE, as documented on each method. Drain outgoing packets and drive
 * connection timers after processing network and application events.
 *
 * <p>All native owners implement {@link java.lang.AutoCloseable}; use
 * try-with-resources. Snapshot values own their Java data. Durations, limits,
 * readiness and peer-authentication defaults follow the documented upstream
 * semantics, with explicit Java adaptations. In particular, client certificate
 * verification must normally be enabled and trusted certificates configured.
 *
 * <p>Optional HTTP/3 support is provided by
 * {@link io.bosonnetwork.quiche.H3Connection}. Its QUIC transport remains owned
 * and driven by the application.
 *
 * <p>Documentation is adapted from the pinned upstream Rust and C APIs under
 * BSD-2-Clause; Java-specific descriptions cover ownership and return mappings.
 *
 * @see <a href="doc-files/NOTICE.txt">Documentation provenance</a>
 * @see <a href="doc-files/LICENSE-quiche.txt">Upstream BSD-2-Clause license</a>
 * @see <a href="https://docs.rs/quiche/0.30.1/quiche/">quiche 0.30.1 Rust API</a>
 */

package io.bosonnetwork.quiche;
