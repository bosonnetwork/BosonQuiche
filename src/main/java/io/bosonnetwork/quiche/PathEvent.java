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
import java.net.InetSocketAddress;

/**
 * A copied QUIC path event. Native event memory is released before polling returns. All events
 * have current local/peer addresses; reused-CID events also have previous addresses and an ID, and
 * PMTU events have a byte limit.
 *
 * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.PathEvent.html">
 *         quiche 0.30.1 upstream API</a>
 */
public final class PathEvent {
    /**
     * The event discriminator; inspect it before variant-specific fields.
     */
    public final PathEventType type;

    /**
     * The current local path address.
     */
    public final InetSocketAddress local;

    /**
     * The current peer path address.
     */
    public final InetSocketAddress peer;

    /**
     * The previous local address for REUSED_SOURCE_CONNECTION_ID, otherwise null.
     */
    public final InetSocketAddress previousLocal;

    /**
     * The previous peer address for REUSED_SOURCE_CONNECTION_ID, otherwise null.
     */
    public final InetSocketAddress previousPeer;

    /**
     * The reused source connection-ID sequence number, meaningful only for
     * REUSED_SOURCE_CONNECTION_ID.
     */
    public final long id;

    /**
     * The validated normal-traffic PMTU in bytes, meaningful only for PMTU_UPDATED.
     */
    public final long pmtu;

    PathEvent(int type, InetSocketAddress local, InetSocketAddress peer, InetSocketAddress previousLocal,
            InetSocketAddress previousPeer, long id, long pmtu) {
        this.type = PathEventType.fromCode(type);
        this.local = local;
        this.peer = peer;
        this.previousLocal = previousLocal;
        this.previousPeer = previousPeer;
        this.id = id;
        this.pmtu = pmtu;
    }
}
