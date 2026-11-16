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

import java.nio.ByteBuffer;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;

/**
 * quiche's HTTP/3 application layer over an existing QUIC connection.
 * <p>
 * Configure ALPN as <code>h3</code> and permit at least three unidirectional streams before the
 * QUIC handshake. The HTTP/3 role is inferred from the transport. Packet I/O and timer processing
 * remain on the transport; poll HTTP/3 events after delivering packets. Read a DATA event's body
 * until DONE before expecting the event to be re-armed.
 * <p>
 * This object owns native HTTP/3 state and must be closed explicitly. It shares the transport's
 * operation/disposal lock; disposing it does not dispose the transport. Operations fail with
 * <code>IllegalStateException</code> if either required owner was disposed. Body buffers are
 * direct, use position/limit, and incur no additional JNI payload copy.
 *
 * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Connection.html">
 *         quiche 0.30.1 upstream API</a>
 */
public final class H3Connection extends NativeResource {
    private final Connection transport;

    private H3Connection(long handle, Connection transport) {
        super(handle, 3, transport.lock);
        this.transport = transport;
    }

    /**
     * Creates HTTP/3 state using the provided open QUIC connection, inferring the client/server
     * role. It opens control/QPACK streams and queues local settings. Configure ALPN h3 and at
     * least three unidirectional streams first. If native initialization fails, such as when
     * stream limits prevent control-stream creation, this binding throws IllegalStateException
     * rather than returning a Rust Result. The caller owns and must separately close both the
     * HTTP/3 and transport owners.
     *
     * @param transport the open underlying QUIC connection
     * @param config the open native configuration owner
     * @return the new native owner, which the caller must close
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Connection.html#method.with_transport">
     *         quiche 0.30.1 upstream API</a>
     */
    public static H3Connection withTransport(Connection transport, H3Config config) {
        Objects.requireNonNull(transport, "transport");
        Objects.requireNonNull(config, "config");

        synchronized (transport.lock) {
            synchronized (config.lock) {
                return new H3Connection(Native.h3New(transport.pointer(), config.pointer()), transport);
            }
        }
    }

    /**
     * Processes received HTTP/3 data and returns the next copied event, or null for DONE. For
     * DATA, call recvBody() repeatedly until -1 so that the event can be re-armed. HEADERS contain
     * copied name/value pairs that the application must validate. Native HTTP/3 and propagated
     * transport errors throw H3Exception. The Rust reset-event payload is not available through
     * this C-backed snapshot.
     *
     * @return the result, or {@code null} for DONE
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Connection.html#method.poll">
     *         quiche 0.30.1 upstream API</a>
     */
    public H3Event poll() {
        synchronized (lock) {
            return Native.h3Poll(pointer(), transport.pointer());
        }
    }

    private long headers(int operation, long stream, H3Header[] headers, boolean fin, H3Priority priority,
            boolean trailer) {
        Objects.requireNonNull(headers, "headers");
        byte[][] names = new byte[headers.length][];
        byte[][] values = new byte[headers.length][];
        for (int i = 0; i < headers.length; i++) {
            names[i] = Objects.requireNonNull(headers[i], "header").name();
            values[i] = headers[i].value();
        }

        synchronized (lock) {
            return Native.h3Headers(pointer(), transport.pointer(), operation, stream, names, values, fin,
                    priority == null ? 3 : priority.urgency, priority != null && priority.incremental, trailer);
        }
    }

    /**
     * Queues request headers and returns the new stream ID. fin ends the request body direction if
     * no body follows. Drain the underlying QUIC send() to transmit it. STREAM_BLOCKED is reported
     * as H3Exception; retry after transport capacity becomes available without assuming a request
     * was queued.
     *
     * @param headers the ordered HTTP/3 header fields
     * @param fin whether this write ends the stream direction once fully accepted
     * @return the new request stream ID
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Connection.html#method.send_request">
     *         quiche 0.30.1 upstream API</a>
     */
    public long sendRequest(H3Header[] headers, boolean fin) {
        return headers(0, 0, headers, fin, null, false);
    }

    /**
     * Queues response headers on the request stream with default priority. fin ends the response
     * direction when no body follows. Drain the underlying QUIC output after queuing. HTTP/3
     * failures throw H3Exception.
     *
     * @param stream the nonnegative QUIC stream ID
     * @param headers the ordered HTTP/3 header fields
     * @param fin whether this write ends the stream direction once fully accepted
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Connection.html#method.send_response">
     *         quiche 0.30.1 upstream API</a>
     */
    public void sendResponse(long stream, H3Header[] headers, boolean fin) {
        Checks.nonnegative(stream);
        headers(1, stream, headers, fin, null, false);
    }

    /**
     * Queues response headers using the supplied Extensible Priority parameters. fin ends the
     * response direction if no body follows. Drain the underlying QUIC connection to transmit
     * queued frames.
     *
     * @param stream the nonnegative QUIC stream ID
     * @param headers the ordered HTTP/3 header fields
     * @param priority the HTTP Extensible Priority parameters
     * @param fin whether this write ends the stream direction once fully accepted
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Connection.html#method.send_response_with_priority">
     *         quiche 0.30.1 upstream API</a>
     */
    public void sendResponseWithPriority(long stream, H3Header[] headers, H3Priority priority, boolean fin) {
        Checks.nonnegative(stream);
        headers(2, stream, headers, fin, Objects.requireNonNull(priority, "priority"), false);
    }

    /**
     * Queues additional headers, such as informational response headers or a trailer section. Set
     * trailer for trailers, and fin when this section ends the stream direction. The application
     * must supply a valid HTTP/3 header sequence.
     *
     * @param stream the nonnegative QUIC stream ID
     * @param headers the ordered HTTP/3 header fields
     * @param trailer whether this is a trailer section
     * @param fin whether this write ends the stream direction once fully accepted
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Connection.html#method.send_additional_headers">
     *         quiche 0.30.1 upstream API</a>
     */
    public void sendAdditionalHeaders(long stream, H3Header[] headers, boolean trailer, boolean fin) {
        Checks.nonnegative(stream);
        headers(3, stream, headers, fin, null, trailer);
    }

    private int body(long stream, ByteBuffer buffer, boolean send, boolean fin) {
        Checks.nonnegative(stream);
        Checks.buffer(buffer, !send);

        synchronized (lock) {
            int written = Native.h3Body(pointer(), transport.pointer(), stream, buffer, buffer.position(),
                    buffer.remaining(), send, fin);
            if (written >= 0)
                buffer.position(buffer.position() + written);

            return written;
        }
    }

    /**
     * Queues a body chunk from the current direct-buffer range. Partial writes advance only by the
     * accepted prefix; retry the remainder when writable. fin ends the body only when all supplied
     * data is accepted. Returns -1 for upstream DONE, otherwise the accepted byte count. Read-only
     * direct input is supported; JNI adds no payload staging copy. Drain the underlying QUIC
     * output afterwards.
     *
     * @param stream the nonnegative QUIC stream ID
     * @param body the direct body buffer range
     * @param fin whether this write ends the stream direction once fully accepted
     * @return the successful byte count, or {@code -1} for DONE
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Connection.html#method.send_body">
     *         quiche 0.30.1 upstream API</a>
     */
    public int sendBody(long stream, ByteBuffer body, boolean fin) {
        return body(stream, body, true, fin);
    }

    /**
     * Reads buffered request/response body bytes into the current writable direct-buffer range.
     * Returns -1 for DONE, otherwise advances the buffer by the copied byte count. After DATA,
     * call repeatedly until -1 before waiting for another DATA event. Drain transport output for
     * any resulting flow-control updates.
     *
     * @param stream the nonnegative QUIC stream ID
     * @param out the writable direct output buffer, using position and limit
     * @return the successful byte count, or {@code -1} for DONE
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Connection.html#method.recv_body">
     *         quiche 0.30.1 upstream API</a>
     */
    public int recvBody(long stream, ByteBuffer out) {
        return body(stream, out, false, false);
    }

    /**
     * Sends a GOAWAY frame to initiate graceful connection closure.
     * <p>
     * When quiche is used in the server role, the <code>id</code> parameter is the stream ID of
     * the highest processed request. This can be any valid ID between 0 and 2^62-4. However, the
     * ID cannot be increased. Failure to satisfy these conditions will return an error.
     * <p>
     * This method does not close the QUIC connection. Applications are required to call
     * <code>close()</code> themselves.
     *
     * @param id the identifier or sequence number
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Connection.html#method.send_goaway">
     *         quiche 0.30.1 upstream API</a>
     */
    public void sendGoaway(long id) {
        Checks.nonnegative(id);

        synchronized (lock) {
            Native.h3Action(pointer(), transport.pointer(), 0, id, 0, false);
        }
    }

    /**
     * Queues a PRIORITY_UPDATE for a request stream on the HTTP/3 control stream. A blocked
     * control stream is reported through H3Exception; retry when capacity is available. Drain the
     * QUIC output to transmit it. Updates for closed streams may be ignored by the peer.
     *
     * @param stream the nonnegative QUIC stream ID
     * @param priority the HTTP Extensible Priority parameters
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Connection.html#method.send_priority_update_for_request">
     *         quiche 0.30.1 upstream API</a>
     */
    public void sendPriorityUpdateForRequest(long stream, H3Priority priority) {
        Checks.nonnegative(stream);
        Objects.requireNonNull(priority, "priority");

        synchronized (lock) {
            Native.h3Action(pointer(), transport.pointer(), 1, stream, priority.urgency, priority.incremental);
        }
    }

    /**
     * Takes and removes the latest serialized PRIORITY_UPDATE value for the stream, or returns
     * null for DONE when none is pending. quiche emits one update event per stream until this
     * value is taken; process all currently pending events before taking it when coalescing
     * updates.
     *
     * @param stream the nonnegative QUIC stream ID
     * @return the copied field value, or {@code null} when none is pending
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Connection.html#method.take_last_priority_update">
     *         quiche 0.30.1 upstream API</a>
     */
    public byte[] takeLastPriorityUpdate(long stream) {
        Checks.nonnegative(stream);

        synchronized (lock) {
            transport.pointer();

            return Native.h3TakePriority(pointer(), stream);
        }
    }

    /**
     * Returns whether the peer enabled extended CONNECT support.
     * <p>
     * Support is signalled by the peer's SETTINGS, so this method always returns false until they
     * have been processed using the <code>poll()</code> method.
     *
     * @return whether the condition described above holds
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Connection.html#method.extended_connect_enabled_by_peer">
     *         quiche 0.30.1 upstream API</a>
     */
    public boolean extendedConnectEnabledByPeer() {
        synchronized (lock) {
            return Native.h3Enabled(pointer(), transport.pointer(), false);
        }
    }

    /**
     * Returns whether the peer enabled HTTP/3 DATAGRAM frame support.
     * <p>
     * Support is signalled by the peer's SETTINGS, so this method always returns false until they
     * have been processed using the <code>poll()</code> method.
     *
     * @return whether the condition described above holds
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Connection.html#method.dgram_enabled_by_peer">
     *         quiche 0.30.1 upstream API</a>
     */
    public boolean dgramEnabledByPeer() {
        synchronized (lock) {
            return Native.h3Enabled(pointer(), transport.pointer(), true);
        }
    }

    /**
     * Returns an immutable Java map of the peer HTTP/3 settings as identifier/value pairs. The
     * values are copied from native state; no native iterator or callback remains live after
     * return.
     *
     * @return the copied values described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Connection.html#method.peer_settings_raw">
     *         quiche 0.30.1 upstream API</a>
     */
    public Map<Long, Long> peerSettings() {
        synchronized (lock) {
            transport.pointer();
            long[] values = Native.h3Settings(pointer());
            Map<Long, Long> settings = new LinkedHashMap<>();
            for (int i = 0; i < values.length; i += 2)
                settings.put(values[i], values[i + 1]);

            return Collections.unmodifiableMap(settings);
        }
    }

    /**
     * Collects and returns statistics about the connection.
     *
     * @return the copied statistics snapshot
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/h3/struct.Connection.html#method.stats">
     *         quiche 0.30.1 upstream API</a>
     */
    public H3Stats stats() {
        synchronized (lock) {
            transport.pointer();

            return Native.h3Stats(pointer());
        }
    }
}
