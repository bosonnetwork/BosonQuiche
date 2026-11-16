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
import java.nio.ByteBuffer;
import java.util.Objects;
import java.util.function.Predicate;

/**
 * A socket-independent QUIC connection, backed by quiche and BoringSSL.
 * <p>
 * The application supplies packet I/O, source/destination addresses, pacing and timers. Drain
 * <code>send()</code> after receiving packets, writing or reading application data, shutting down
 * a stream, or processing a timeout. Continue driving timers even without incoming traffic. Stream
 * counts and flow-control limits are configured on <code>Config</code>.
 * <p>
 * Bulk I/O requires direct <code>ByteBuffer</code> instances. Methods use the current position and
 * limit, and advance the position on success. There is no JNI payload staging copy; quiche may
 * copy data internally for buffering and retransmission. <code>recv()</code> decrypts packets in
 * place. Native code retains no reference to a supplied buffer after return.
 * <p>
 * Close this owner explicitly to free native memory. The overloaded protocol <code>close</code>
 * method only queues CONNECTION_CLOSE; drain outgoing packets before disposing. Calls are
 * serialized with disposal, but callers must protect shared buffers. Disposed owners reject
 * further operations with <code>IllegalStateException</code>. Native uint64 values retain their
 * bit pattern in Java <code>long</code> values.
 *
 * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html">
 *         quiche 0.30.1 upstream API</a>
 */
public final class Connection extends NativeResource {
    private Connection(long handle) {
        super(handle, 1);
    }

    /**
     * Creates a client connection using the supplied source connection ID and resolved local/peer
     * addresses. serverName is the TLS server name used for SNI and certificate name verification,
     * not an instruction to open a socket. A null name omits SNI/name checking; configure peer
     * authentication deliberately. No packet is transmitted until the application drains send().
     *
     * @param serverName the TLS server name, or null to omit it
     * @param sourceId the source connection ID, at most 20 bytes
     * @param local the resolved local path address
     * @param peer the resolved peer path address
     * @param config the open native configuration owner
     * @return the new native owner, which the caller must close
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/fn.connect.html">
     *         quiche 0.30.1 upstream API</a>
     */
    public static Connection connect(String serverName, byte[] sourceId, InetSocketAddress local,
            InetSocketAddress peer, Config config) {
        return create(serverName, sourceId, null, local, peer, config, false);
    }

    /**
     * Creates a server connection. sourceId is the server source connection ID;
     * originalDestinationId is the client destination ID before Retry, or null when Retry was not
     * used. Supply the actual received local/peer path. No socket is opened.
     *
     * @param sourceId the source connection ID, at most 20 bytes
     * @param originalDestinationId the pre-Retry destination ID, or null without Retry
     * @param local the resolved local path address
     * @param peer the resolved peer path address
     * @param config the open native configuration owner
     * @return the new native owner, which the caller must close
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/fn.accept.html">
     *         quiche 0.30.1 upstream API</a>
     */
    public static Connection accept(byte[] sourceId, byte[] originalDestinationId, InetSocketAddress local,
            InetSocketAddress peer, Config config) {
        return create(null, sourceId, originalDestinationId, local, peer, config, true);
    }

    private static Connection create(String name, byte[] sourceId, byte[] originalId, InetSocketAddress local,
            InetSocketAddress peer, Config config, boolean server) {
        Checks.cid(sourceId);
        if (originalId != null)
            Checks.cid(originalId);

        Objects.requireNonNull(config, "config");
        byte[] localBytes = Native.address(local);
        byte[] peerBytes = Native.address(peer);
        byte[] serverName = name == null ? null : Native.utf8(name);

        synchronized (config.lock) {
            return new Connection(Native.connect(config.pointer(), serverName, sourceId, originalId, localBytes,
                    peerBytes, server));
        }
    }

    /**
     * Processes one received UDP datagram from the current buffer range, decrypting its contents
     * in place. Provide the observed remote source and local destination in info. Advance
     * application processing and drain send() afterwards. Returns -1 for upstream DONE, otherwise
     * the consumed byte count. Other native errors throw QuicheException; the buffer position
     * advances only on success.
     *
     * @param packet the direct packet buffer range; receive requires writable memory
     * @param info the observed source/destination metadata
     * @return the successful byte count, or {@code -1} for DONE
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.recv">
     *         quiche 0.30.1 upstream API</a>
     */
    public int recv(ByteBuffer packet, RecvInfo info) {
        Checks.buffer(packet, true);
        Objects.requireNonNull(info, "info");

        synchronized (lock) {
            int read = Native.recv(pointer(), packet, packet.position(), packet.remaining(), Native.address(info.from),
                    Native.address(info.to));
            if (read >= 0)
                packet.position(packet.position() + read);

            return read;
        }
    }

    /**
     * Produces one outgoing UDP datagram and its path/pacing metadata. Call repeatedly until null
     * (DONE), using a writable direct buffer large enough for the configured packet size. Drain
     * after recv(), onTimeout(), stream writes/shutdown and application reads that can generate
     * flow-control updates. Once draining, no further packets need be produced. The buffer
     * position advances by SendInfo.bytes; transmit those bytes before reusing their storage.
     *
     * @param out the writable direct output buffer, using position and limit
     * @return the result, or {@code null} for DONE
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.send">
     *         quiche 0.30.1 upstream API</a>
     */
    public SendInfo send(ByteBuffer out) {
        return sendOnPath(out, null, null);
    }

    /**
     * Produces one outgoing datagram on the requested path. A null source or destination lets
     * quiche select that part of the path. Returns null for DONE and otherwise the same buffer and
     * pacing contract as send(). This selects a QUIC path; the application is still responsible
     * for actual UDP/ICE transmission.
     *
     * @param out the writable direct output buffer, using position and limit
     * @param from the resolved source address, or null for automatic send-path selection
     * @param to the resolved destination address, or null for automatic send-path selection
     * @return the result, or {@code null} for DONE
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.send_on_path">
     *         quiche 0.30.1 upstream API</a>
     */
    public SendInfo sendOnPath(ByteBuffer out, InetSocketAddress from, InetSocketAddress to) {
        Checks.buffer(out, true);

        synchronized (lock) {
            SendInfo info = Native.send(pointer(), out, out.position(), out.remaining(),
                    from == null ? null : Native.address(from), to == null ? null : Native.address(to));
            if (info != null)
                out.position(out.position() + info.bytes);

            return info;
        }
    }

    /**
     * Reads contiguous stream data into the current writable direct-buffer range. Returns a
     * StreamResult containing bytes and FIN, or null for DONE when no data is available. Reading
     * can queue flow-control updates, so drain send() afterwards. STREAM_RESET/STREAM_STOPPED
     * failures throw QuicheException with the application error code. A fully consumed and
     * reclaimed stream can instead report INVALID_STREAM_STATE.
     *
     * @param stream the nonnegative QUIC stream ID
     * @param out the writable direct output buffer, using position and limit
     * @return the result, or {@code null} for DONE
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.stream_recv">
     *         quiche 0.30.1 upstream API</a>
     */
    public StreamResult streamRecv(long stream, ByteBuffer out) {
        Checks.nonnegative(stream);
        Checks.buffer(out, true);

        synchronized (lock) {
            StreamResult result = Native.streamRecv(pointer(), stream, out, out.position(), out.remaining());
            if (result != null)
                out.position(out.position() + result.bytes);

            return result;
        }
    }

    /**
     * Queues data from the current direct-buffer range on a stream, opening it if permitted by
     * stream limits. Partial writes are normal: only the accepted prefix advances the buffer
     * position. Retry the remaining range when writable, and drain send() to produce network
     * packets. FIN is committed only when the requested data is accepted. Returns -1 for
     * DONE/backpressure; native reset/stop errors preserve the application error code. Read-only
     * direct input is supported. quiche can copy the accepted data for retransmission; JNI does
     * not stage it.
     *
     * @param stream the nonnegative QUIC stream ID
     * @param data the direct input buffer, using position and limit
     * @param fin whether this write ends the stream direction once fully accepted
     * @return the successful byte count, or {@code -1} for DONE
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.stream_send">
     *         quiche 0.30.1 upstream API</a>
     */
    public int streamSend(long stream, ByteBuffer data, boolean fin) {
        Checks.nonnegative(stream);
        Checks.buffer(data, false);

        synchronized (lock) {
            int written = Native.streamSend(pointer(), stream, data, data.position(), data.remaining(), fin);
            if (written >= 0)
                data.position(data.position() + written);

            return written;
        }
    }

    /**
     * Sets the priority for a stream.
     * <p>
     * A stream's priority determines the order in which stream data is sent on the wire (streams
     * with lower priority are sent first). Streams are created with a default priority of
     * <code>127</code>.
     * <p>
     * The target stream is created if it did not exist before calling this method.
     *
     * @param stream the nonnegative QUIC stream ID
     * @param urgency the priority urgency
     * @param incremental whether delivery is incremental
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.stream_priority">
     *         quiche 0.30.1 upstream API</a>
     */
    public void streamPriority(long stream, int urgency, boolean incremental) {
        Checks.nonnegative(stream);
        if (urgency < 0 || urgency > 255)
            throw new IllegalArgumentException("Invalid urgency");

        synchronized (lock) {
            Native.streamPriority(pointer(), stream, urgency, incremental);
        }
    }

    /**
     * Shuts down reading or writing from/to the specified stream.
     * <p>
     * When the <code>direction</code> argument is set to <code>Shutdown.READ</code>, outstanding
     * data in the stream's receive buffer is dropped, and no additional data is added to it. Data
     * received after calling this method is still validated and acked but not stored, and
     * <code>streamRecv()</code> will not return it to the application. In addition, a
     * <code>STOP_SENDING</code> frame will be sent to the peer to signal it to stop sending data.
     * <p>
     * When the <code>direction</code> argument is set to <code>Shutdown.WRITE</code>, outstanding
     * data in the stream's send buffer is dropped, and no additional data is added to it. Data
     * passed to <code>streamSend()</code> after calling this method will be ignored. In addition,
     * a <code>RESET_STREAM</code> frame will be sent to the peer to signal the reset, unless all
     * outgoing data has already been acked by the peer (up to the <code>fin</code> offset).
     * <p>
     * Locally-initiated unidirectional streams can only be closed in the
     * <code>Shutdown.WRITE</code> direction. Remotely-initiated unidirectional streams can only be
     * closed in the <code>Shutdown.READ</code> direction. Using an incorrect direction will return
     * <code>InvalidStreamState</code>.
     *
     * @param stream the nonnegative QUIC stream ID
     * @param direction the stream direction to stop
     * @param error the unsigned application or transport error-code bit pattern
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.stream_shutdown">
     *         quiche 0.30.1 upstream API</a>
     */
    public void streamShutdown(long stream, Shutdown direction, long error) {
        Checks.nonnegative(stream);
        Objects.requireNonNull(direction, "direction");

        synchronized (lock) {
            Native.streamShutdown(pointer(), stream, direction.code(), error);
        }
    }

    private long get(int option, long argument) {
        synchronized (lock) {
            return Native.connGet(pointer(), option, argument);
        }
    }

    /**
     * Returns true if the connection handshake is complete.
     *
     * @return whether the condition described above holds
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.is_established">
     *         quiche 0.30.1 upstream API</a>
     */
    public boolean isEstablished() {
        return get(0, 0) != 0;
    }

    /**
     * Returns true if the connection is resumed.
     *
     * @return whether the condition described above holds
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.is_resumed">
     *         quiche 0.30.1 upstream API</a>
     */
    public boolean isResumed() {
        return get(1, 0) != 0;
    }

    /**
     * Returns true if the connection has a pending handshake that has progressed enough to send or
     * receive early data.
     *
     * @return whether the condition described above holds
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.is_in_early_data">
     *         quiche 0.30.1 upstream API</a>
     */
    public boolean isInEarlyData() {
        return get(2, 0) != 0;
    }

    /**
     * Returns whether there is stream or DATAGRAM data available to read.
     *
     * @return whether the condition described above holds
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.is_readable">
     *         quiche 0.30.1 upstream API</a>
     */
    public boolean isReadable() {
        return get(3, 0) != 0;
    }

    /**
     * Returns true if the connection is draining.
     * <p>
     * If this returns <code>true</code>, the connection object cannot yet be dropped, but no new
     * application data can be sent or received. An application should continue calling the
     * <code>recv()</code>, <code>timeout()</code>, and <code>onTimeout()</code> methods as normal,
     * until the <code>isClosed()</code> method returns <code>true</code>.
     * <p>
     * In contrast, once <code>isDraining()</code> returns <code>true</code>, calling
     * <code>send()</code> is not required because no new outgoing packets will be generated.
     *
     * @return whether the condition described above holds
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.is_draining">
     *         quiche 0.30.1 upstream API</a>
     */
    public boolean isDraining() {
        return get(4, 0) != 0;
    }

    /**
     * Returns true if the connection is closed.
     * <p>
     * If this returns true, the connection object can be dropped.
     *
     * @return whether the condition described above holds
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.is_closed">
     *         quiche 0.30.1 upstream API</a>
     */
    public boolean isClosed() {
        return get(5, 0) != 0;
    }

    /**
     * Returns true if the connection was closed due to the idle timeout.
     *
     * @return whether the condition described above holds
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.is_timed_out">
     *         quiche 0.30.1 upstream API</a>
     */
    public boolean isTimedOut() {
        return get(6, 0) != 0;
    }

    /**
     * Returns whether or not this is a server-side connection.
     *
     * @return whether the condition described above holds
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.is_server">
     *         quiche 0.30.1 upstream API</a>
     */
    public boolean isServer() {
        return get(7, 0) != 0;
    }

    /**
     * Returns the number of bidirectional streams that can be created before the peer's stream
     * count limit is reached.
     * <p>
     * This can be useful to know if it's possible to create a bidirectional stream without trying
     * it first.
     *
     * @return the count or limit described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.peer_streams_left_bidi">
     *         quiche 0.30.1 upstream API</a>
     */
    public long peerStreamsLeftBidi() {
        return get(8, 0);
    }

    /**
     * Returns the number of unidirectional streams that can be created before the peer's stream
     * count limit is reached.
     * <p>
     * This can be useful to know if it's possible to create a unidirectional stream without trying
     * it first.
     *
     * @return the count or limit described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.peer_streams_left_uni">
     *         quiche 0.30.1 upstream API</a>
     */
    public long peerStreamsLeftUni() {
        return get(9, 0);
    }

    /**
     * Returns the relative nanoseconds until the next connection timer, or -1 when no timer is
     * armed. Schedule onTimeout() after this delay, then drain send() and recompute the timeout.
     * Zero means the timer is already due; it is not the disarmed sentinel.
     *
     * @return the relative delay in the named unit, or {@code -1} when disarmed
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.timeout">
     *         quiche 0.30.1 upstream API</a>
     */
    public long timeoutAsNanos() {
        return get(10, 0);
    }

    /**
     * Returns the relative milliseconds until the next connection timer, or -1 when no timer is
     * armed. Sub-millisecond delays may round down to zero. Prefer timeoutAsNanos() when
     * fine-grained scheduling is available.
     *
     * @return the relative delay in the named unit, or {@code -1} when disarmed
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.timeout">
     *         quiche 0.30.1 upstream API</a>
     */
    public long timeoutAsMillis() {
        return get(11, 0);
    }

    /**
     * Returns the maximum possible size of egress UDP payloads.
     * <p>
     * This is the maximum size of UDP payloads that can be sent, and depends on both the
     * configured maximum send payload size of the local endpoint (as configured with
     * <code>setMaxSendUdpPayloadSize()</code>), as well as the transport parameter advertised by
     * the remote peer.
     * <p>
     * Note that this value can change during the lifetime of the connection, but should remain
     * stable across consecutive calls to <code>send()</code>.
     * struct.Config.html#method.set_max_send_udp_payload_size
     *
     * @return the count or limit described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.max_send_udp_payload_size">
     *         quiche 0.30.1 upstream API</a>
     */
    public long maxSendUdpPayloadSize() {
        return get(12, 0);
    }

    /**
     * Returns the size of the send quantum, in bytes.
     * <p>
     * This represents the maximum size of a packet burst as determined by the congestion control
     * algorithm in use.
     * <p>
     * Applications can, for example, use it in conjunction with segmentation offloading mechanisms
     * as the maximum limit for outgoing aggregates of multiple packets.
     *
     * @return the count or limit described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.send_quantum">
     *         quiche 0.30.1 upstream API</a>
     */
    public long sendQuantum() {
        return get(13, 0);
    }

    /**
     * Returns the maximum currently writable DATAGRAM payload size, accounting for peer support,
     * path MTU and protocol overhead, or -1 for upstream DONE if the size is unavailable. This
     * limit does not guarantee room in the outgoing queue.
     *
     * @return the count or limit described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.dgram_max_writable_len">
     *         quiche 0.30.1 upstream API</a>
     */
    public long dgramMaxWritableLen() {
        return get(14, 0);
    }

    /**
     * Returns the first queued incoming DATAGRAM length in bytes, or -1 when the queue is empty.
     * Zero is a valid empty-datagram length.
     *
     * @return the count or limit described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.dgram_recv_front_len">
     *         quiche 0.30.1 upstream API</a>
     */
    public long dgramRecvFrontLen() {
        return get(15, 0);
    }

    /**
     * Returns the number of items in the DATAGRAM receive queue.
     *
     * @return the count or limit described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.dgram_recv_queue_len">
     *         quiche 0.30.1 upstream API</a>
     */
    public long dgramRecvQueueLen() {
        return get(16, 0);
    }

    /**
     * Returns the total size of all items in the DATAGRAM receive queue.
     *
     * @return the count or limit described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.dgram_recv_queue_byte_size">
     *         quiche 0.30.1 upstream API</a>
     */
    public long dgramRecvQueueByteSize() {
        return get(17, 0);
    }

    /**
     * Returns the number of items in the DATAGRAM send queue.
     *
     * @return the count or limit described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.dgram_send_queue_len">
     *         quiche 0.30.1 upstream API</a>
     */
    public long dgramSendQueueLen() {
        return get(18, 0);
    }

    /**
     * Returns the total size of all items in the DATAGRAM send queue.
     *
     * @return the count or limit described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.dgram_send_queue_byte_size">
     *         quiche 0.30.1 upstream API</a>
     */
    public long dgramSendQueueByteSize() {
        return get(19, 0);
    }

    /**
     * Returns whether or not the DATAGRAM send queue is full.
     *
     * @return whether the condition described above holds
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.is_dgram_send_queue_full">
     *         quiche 0.30.1 upstream API</a>
     */
    public boolean isDgramSendQueueFull() {
        return get(20, 0) != 0;
    }

    /**
     * Returns whether or not the DATAGRAM recv queue is full.
     *
     * @return whether the condition described above holds
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.is_dgram_recv_queue_full">
     *         quiche 0.30.1 upstream API</a>
     */
    public boolean isDgramRecvQueueFull() {
        return get(21, 0) != 0;
    }

    /**
     * Returns the number of source Connection IDs that are retired.
     *
     * @return the count or limit described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.retired_scids">
     *         quiche 0.30.1 upstream API</a>
     */
    public long retiredScids() {
        return get(22, 0);
    }

    /**
     * Returns the number of spare Destination Connection IDs, i.e., Destination Connection IDs
     * that are still unused.
     * <p>
     * Note that this function returns 0 if the host uses zero length Destination Connection IDs.
     *
     * @return the count or limit described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.available_dcids">
     *         quiche 0.30.1 upstream API</a>
     */
    public long availableDcids() {
        return get(23, 0);
    }

    /**
     * Returns the number of additional source Connection IDs that can be provided to the peer
     * without exceeding the limit it advertised.
     * <p>
     * The limit is the minimum of the locally configured active connection ID limit and the one
     * sent by the peer.
     * <p>
     * Returns <code>0</code> when the peer's limit is already reached or temporarily exceeded
     * (e.g. during a SCID rotation where a retirement is in flight and <code>activeScids()</code>
     * transiently exceeds the advertised limit).
     * <p>
     * To obtain the maximum possible value allowed by the peer an application can instead inspect
     * the <code>peer_active_conn_id_limit</code> value.
     *
     * @return the count or limit described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.scids_left">
     *         quiche 0.30.1 upstream API</a>
     */
    public long scidsLeft() {
        return get(24, 0);
    }

    /**
     * Returns the number of source Connection IDs that are active. This is only meaningful if the
     * host uses non-zero length Source Connection IDs.
     *
     * @return the count or limit described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.active_scids">
     *         quiche 0.30.1 upstream API</a>
     */
    public long activeScids() {
        return get(25, 0);
    }

    /**
     * Returns current send capacity for a stream in bytes, or -1 for upstream DONE. Missing,
     * stopped or reset streams can throw QuicheException; readiness/capacity can change after
     * other operations.
     *
     * @param stream the nonnegative QUIC stream ID
     * @return the count or limit described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.stream_capacity">
     *         quiche 0.30.1 upstream API</a>
     */
    public long streamCapacity(long stream) {
        Checks.nonnegative(stream);

        return get(26, stream);
    }

    /**
     * Returns true if the stream has data that can be read.
     *
     * @param stream the nonnegative QUIC stream ID
     * @return whether the condition described above holds
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.stream_readable">
     *         quiche 0.30.1 upstream API</a>
     */
    public boolean streamReadable(long stream) {
        Checks.nonnegative(stream);

        return get(27, stream) != 0;
    }

    /**
     * Returns true if all the data has been read from the specified stream.
     * <p>
     * This instructs the application that all the data received from the peer on the stream has
     * been read, and there won't be anymore in the future.
     * <p>
     * Basically this returns true when the peer either set the <code>fin</code> flag for the
     * stream, or sent <code>RESET_STREAM</code>.
     *
     * @param stream the nonnegative QUIC stream ID
     * @return whether the condition described above holds
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.stream_finished">
     *         quiche 0.30.1 upstream API</a>
     */
    public boolean streamFinished(long stream) {
        Checks.nonnegative(stream);

        return get(28, stream) != 0;
    }

    /**
     * Returns the next stream ID with buffered readable data, or -1 when no stream is readable.
     * This query does not consume stream data.
     *
     * @return the stream ID, or {@code -1} when none is ready
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.stream_readable_next">
     *         quiche 0.30.1 upstream API</a>
     */
    public long streamReadableNext() {
        return get(29, 0);
    }

    /**
     * Returns the next writable stream ID, or -1 when no stream is writable. This query does not
     * reserve send capacity.
     *
     * @return the stream ID, or {@code -1} when none is ready
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.stream_writable_next">
     *         quiche 0.30.1 upstream API</a>
     */
    public long streamWritableNext() {
        return get(30, 0);
    }

    /**
     * Returns whether the stream can buffer at least length more bytes. If flow control prevents
     * that write, quiche notifies the peer and records a low send watermark; streamWritableNext()
     * will not report the stream again until that capacity is available. A missing or completed
     * stream throws QuicheException with INVALID_STREAM_STATE; STOP_SENDING is reported as
     * STREAM_STOPPED.
     *
     * @param stream the nonnegative QUIC stream ID
     * @param length the required number of writable bytes
     * @return whether the condition described above holds
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.stream_writable">
     *         quiche 0.30.1 upstream API</a>
     */
    public boolean streamWritable(long stream, long length) {
        Checks.nonnegative(stream);
        Checks.nonnegative(length);

        synchronized (lock) {
            return Native.streamWritable(pointer(), stream, length) != 0;
        }
    }

    /**
     * Returns a copied snapshot of readable stream IDs. The native iterator is consumed and freed
     * inside JNI. Reading can change readiness, so obtain a fresh snapshot after processing data.
     *
     * @return the copied values described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.readable">
     *         quiche 0.30.1 upstream API</a>
     */
    public long[] readable() {
        synchronized (lock) {
            return Native.streams(pointer(), false);
        }
    }

    /**
     * Returns a copied snapshot of writable stream IDs. A stream can still accept only a prefix of
     * a later write; this is a readiness snapshot, not reserved capacity.
     *
     * @return the copied values described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.writable">
     *         quiche 0.30.1 upstream API</a>
     */
    public long[] writable() {
        synchronized (lock) {
            return Native.streams(pointer(), true);
        }
    }

    /**
     * Processes a timeout event.
     * <p>
     * If no timeout has occurred it does nothing.
     *
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.on_timeout">
     *         quiche 0.30.1 upstream API</a>
     */
    public void onTimeout() {
        synchronized (lock) {
            Native.connAction(pointer(), 0, 0);
        }
    }

    /**
     * Schedule an ack-eliciting packet on the active path.
     * <p>
     * QUIC packets might not contain ack-eliciting frames during normal operating conditions. If
     * the packet would already contain ack-eliciting frames, this method does not change any
     * behavior. However, if the packet would not ordinarily contain ack-eliciting frames, this
     * method ensures that a PING frame sent.
     * <p>
     * Calling this method multiple times before <code>send()</code> has no effect.
     *
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.send_ack_eliciting">
     *         quiche 0.30.1 upstream API</a>
     */
    public void sendAckEliciting() {
        synchronized (lock) {
            Native.connAction(pointer(), 1, 0);
        }
    }

    /**
     * Requests the retirement of the destination Connection ID used by the host to reach its peer.
     * <p>
     * This triggers sending RETIRE_CONNECTION_ID frames.
     * <p>
     * If the application tries to retire a non-existing Destination Connection ID sequence number,
     * or if it uses zero-length Destination Connection ID, this method returns an
     * <code>InvalidState</code>.
     * <p>
     * At any time, the host must have at least one Destination ID. If the application tries to
     * retire the last one, or if the caller tries to retire the destination Connection ID used by
     * the current active path while having neither spare Destination Connection IDs nor validated
     * network paths, this method returns an <code>OutOfIdentifiers</code>. This behavior prevents
     * the caller from stalling the connection due to the lack of validated path to send
     * non-probing packets.
     *
     * @param sequence the destination connection-ID sequence number
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.retire_dcid">
     *         quiche 0.30.1 upstream API</a>
     */
    public void retireDcid(long sequence) {
        synchronized (lock) {
            Native.connAction(pointer(), 2, sequence);
        }
    }

    private byte[] bytes(int option) {
        synchronized (lock) {
            return Native.connBytes(pointer(), option);
        }
    }

    /**
     * Returns a copy of the connection trace identifier encoded as bytes. It is intended for
     * correlation and diagnostics.
     *
     * @return the copied bytes, empty when unavailable where documented above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.trace_id">
     *         quiche 0.30.1 upstream API</a>
     */
    public byte[] traceId() {
        return bytes(0);
    }

    /**
     * Returns a copy of the current source connection ID.
     *
     * @return the copied bytes, empty when unavailable where documented above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.source_id">
     *         quiche 0.30.1 upstream API</a>
     */
    public byte[] sourceId() {
        return bytes(1);
    }

    /**
     * Returns a copy of the current destination connection ID.
     *
     * @return the copied bytes, empty when unavailable where documented above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.destination_id">
     *         quiche 0.30.1 upstream API</a>
     */
    public byte[] destinationId() {
        return bytes(2);
    }

    /**
     * Returns a copy of the negotiated ALPN protocol bytes, or an empty array before negotiation.
     * No character decoding is imposed.
     *
     * @return the copied bytes, empty when unavailable where documented above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.application_proto">
     *         quiche 0.30.1 upstream API</a>
     */
    public byte[] applicationProto() {
        return bytes(3);
    }

    /**
     * Returns a copy of the peer leaf certificate in DER format, or an empty array when
     * unavailable. This C API does not expose the entire Rust certificate-chain API. A server that
     * requires a client certificate must check that one was presented.
     *
     * @return the copied bytes, empty when unavailable where documented above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.peer_cert">
     *         quiche 0.30.1 upstream API</a>
     */
    public byte[] peerCert() {
        return bytes(4);
    }

    /**
     * Returns a copy of the serialized TLS session for resumption, or an empty array when no
     * session is available yet. Treat the serialization as opaque and pass it to setSession() on a
     * new connection.
     *
     * @return the copied bytes, empty when unavailable where documented above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.session">
     *         quiche 0.30.1 upstream API</a>
     */
    public byte[] session() {
        return bytes(5);
    }

    /**
     * Returns a copy of the TLS server-name bytes, or an empty array when no name is available.
     *
     * @return the copied bytes, empty when unavailable where documented above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.server_name">
     *         quiche 0.30.1 upstream API</a>
     */
    public byte[] serverName() {
        return bytes(6);
    }

    /**
     * Configures opaque session-resumption data from a previous connection. Call on a new
     * connection before sending or receiving packets. Invalid serialization throws
     * QuicheException; enabling early data is a separate configuration choice.
     *
     * @param session the opaque serialized TLS session
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.set_session">
     *         quiche 0.30.1 upstream API</a>
     */
    public void setSession(byte[] session) {
        Objects.requireNonNull(session, "session");

        synchronized (lock) {
            Native.setSession(pointer(), session);
        }
    }

    /**
     * Enables TLS secret logging to the specified filesystem path. Returns whether the log file
     * was opened successfully. Configure logging before processing the handshake; protect these
     * secrets because they permit traffic decryption.
     *
     * @param path the filesystem path
     * @return whether the condition described above holds
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.set_keylog">
     *         quiche 0.30.1 upstream API</a>
     */
    public boolean setKeylogPath(String path) {
        synchronized (lock) {
            return Native.connText(pointer(), 0, Native.utf8(path), null, null);
        }
    }

    /**
     * Enables qlog output at the specified filesystem path, with title and description metadata.
     * Returns whether the file could be opened. Configure it before processing the connection
     * events to be recorded.
     *
     * @param path the filesystem path
     * @param title the qlog title
     * @param description the qlog description
     * @return whether the condition described above holds
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.set_qlog">
     *         quiche 0.30.1 upstream API</a>
     */
    public boolean setQlogPath(String path, String title, String description) {
        synchronized (lock) {
            return Native.connText(pointer(), 1, Native.utf8(path), Native.utf8(title), Native.utf8(description));
        }
    }

    /**
     * Sets the <code>max_idle_timeout</code> transport parameter, in milliseconds.
     * <p>
     * This must only be called immediately after creating a connection, that is, before any packet
     * is sent or received.
     * <p>
     * The default value is infinite, that is, no timeout is used unless already configured when
     * creating the connection.
     *
     * @param millis the idle timeout in milliseconds
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.set_max_idle_timeout">
     *         quiche 0.30.1 upstream API</a>
     */
    public void setMaxIdleTimeout(long millis) {
        Checks.nonnegative(millis);

        synchronized (lock) {
            Native.connAction(pointer(), 3, millis);
        }
    }

    /**
     * Queues an application or transport CONNECTION_CLOSE error and a reason. Drain send() to
     * transmit the close, and continue timer processing while closing. This overload does not free
     * native memory; the no-argument AutoCloseable close() disposes it. Repeated upstream DONE
     * closes are ignored.
     *
     * @param application true for an application error, false for a transport error
     * @param error the unsigned application or transport error-code bit pattern
     * @param reason the opaque close-reason bytes
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.close">
     *         quiche 0.30.1 upstream API</a>
     */
    public void close(boolean application, long error, byte[] reason) {
        Objects.requireNonNull(reason, "reason");

        synchronized (lock) {
            Native.closeConnection(pointer(), application, error, reason);
        }
    }

    /**
     * Returns the peer CONNECTION_CLOSE error, or null when none has been received. The reason
     * bytes are copied before returning.
     *
     * @return the copied snapshot, or {@code null} when unavailable
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.peer_error">
     *         quiche 0.30.1 upstream API</a>
     */
    public ConnectionError peerError() {
        synchronized (lock) {
            return Native.connectionError(pointer(), true);
        }
    }

    /**
     * Returns the locally queued or sent CONNECTION_CLOSE error, or null when none exists. This
     * does not itself queue a close or free memory.
     *
     * @return the copied snapshot, or {@code null} when unavailable
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.local_error">
     *         quiche 0.30.1 upstream API</a>
     */
    public ConnectionError localError() {
        synchronized (lock) {
            return Native.connectionError(pointer(), false);
        }
    }

    /**
     * Collects and returns statistics about the connection.
     *
     * @return the copied statistics snapshot
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.stats">
     *         quiche 0.30.1 upstream API</a>
     */
    public Stats stats() {
        synchronized (lock) {
            return Native.stats(pointer());
        }
    }

    /**
     * Returns a copied peer transport-parameter snapshot, or null before the peer parameters have
     * been processed. C-API durations retain their documented milliseconds units.
     *
     * @return the copied snapshot, or {@code null} when unavailable
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.peer_transport_params">
     *         quiche 0.30.1 upstream API</a>
     */
    public TransportParams peerTransportParams() {
        synchronized (lock) {
            return Native.transportParams(pointer());
        }
    }

    /**
     * Collects and returns statistics about each known path for the connection.
     *
     * @param index the nonnegative path index
     * @return the copied statistics snapshot
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.path_stats">
     *         quiche 0.30.1 upstream API</a>
     */
    public PathStats pathStats(int index) {
        Checks.nonnegative(index);

        synchronized (lock) {
            return Native.pathStats(pointer(), index);
        }
    }

    /**
     * Reads the first buffered unreliable DATAGRAM into the current writable direct-buffer range.
     * Returns -1 for DONE, otherwise advances by the datagram length. The buffer must fit the
     * whole datagram; BUFFER_TOO_SHORT leaves it queued. Stream flow control does not apply to
     * DATAGRAM frames.
     *
     * @param out the writable direct output buffer, using position and limit
     * @return the successful byte count, or {@code -1} for DONE
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.dgram_recv">
     *         quiche 0.30.1 upstream API</a>
     */
    public int dgramRecv(ByteBuffer out) {
        return datagram(out, false);
    }

    /**
     * Queues one unreliable DATAGRAM from the current direct-buffer range. Returns its accepted
     * byte count or -1 for DONE when blocked by the outgoing queue. A payload larger than
     * dgramMaxWritableLen() fails with BUFFER_TOO_SHORT. Delivery is not acknowledged or
     * retransmitted. Drain send() to produce packets; read-only direct input is supported.
     *
     * @param data the direct input buffer, using position and limit
     * @return the successful byte count, or {@code -1} for DONE
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.dgram_send">
     *         quiche 0.30.1 upstream API</a>
     */
    public int dgramSend(ByteBuffer data) {
        return datagram(data, true);
    }

    private int datagram(ByteBuffer buffer, boolean send) {
        Checks.buffer(buffer, !send);

        synchronized (lock) {
            int result = Native.datagram(pointer(), send, buffer, buffer.position(), buffer.remaining());
            if (result >= 0)
                buffer.position(buffer.position() + result);

            return result;
        }
    }

    /**
     * Removes queued outgoing DATAGRAMs for which the predicate returns true. The predicate
     * receives a Java-owned copy; this explicit control API does not expose borrowed native
     * memory. It must not re-enter or dispose native owners. Predicate exceptions propagate after
     * quiche returns.
     *
     * @param predicate the non-reentrant predicate selecting datagrams to remove
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.dgram_purge_outgoing">
     *         quiche 0.30.1 upstream API</a>
     */
    public void dgramPurgeOutgoing(Predicate<byte[]> predicate) {
        Objects.requireNonNull(predicate, "predicate");

        synchronized (lock) {
            Native.purgeDatagrams(pointer(), data -> Native.callback(() -> predicate.test(data)));
        }
    }

    /**
     * Returns copies of all active source connection IDs. Native iterator memory is released
     * before this method returns.
     *
     * @return the copied values described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.source_ids">
     *         quiche 0.30.1 upstream API</a>
     */
    public byte[][] sourceIds() {
        synchronized (lock) {
            return Native.connectionIds(pointer(), false);
        }
    }

    /**
     * Drains all currently retired source connection IDs into Java-owned byte arrays and frees the
     * native iterator. Unlike sourceIds(), this operation consumes pending retired-ID
     * notifications.
     *
     * @return the copied values described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.retired_scid_next">
     *         quiche 0.30.1 upstream API</a>
     */
    public byte[][] retiredSourceIds() {
        synchronized (lock) {
            return Native.connectionIds(pointer(), true);
        }
    }

    /**
     * Provides additional source Connection IDs that the peer can use to reach this host.
     * <p>
     * This triggers sending NEW_CONNECTION_ID frames if the provided Source Connection ID is not
     * already present. In the case the caller tries to reuse a Connection ID with a different
     * reset token, this raises an <code>InvalidState</code>.
     * <p>
     * At any time, the peer cannot have more Destination Connection IDs than the maximum number of
     * active Connection IDs it negotiated. In such case (i.e., when <code>scidsLeft()</code>
     * returns 0), if the host agrees to request the removal of previous connection IDs, it sets
     * the <code>retireIfNeeded</code> parameter. Otherwise, an <code>IdLimit</code> is returned.
     * <p>
     * Note that setting <code>retireIfNeeded</code> does not prevent this function from returning
     * an <code>IdLimit</code> in the case the caller wants to retire still unannounced Connection
     * IDs.
     * <p>
     * The caller is responsible for ensuring that the provided <code>id</code> is not repeated
     * several times over the connection. quiche ensures that as long as the provided Connection ID
     * is still in use (i.e., not retired), it does not assign a different sequence number.
     * <p>
     * Note that if the host uses zero-length Source Connection IDs, it cannot advertise Source
     * Connection IDs and calling this method returns an <code>InvalidState</code>.
     * <p>
     * Returns the sequence number associated to the provided Connection ID.
     *
     * @param id the identifier or sequence number
     * @param resetToken the 16-byte stateless reset token
     * @param retireIfNeeded whether quiche may retire an older source ID to make room
     * @return the associated connection-ID sequence number
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.new_scid">
     *         quiche 0.30.1 upstream API</a>
     */
    public long newScid(byte[] id, byte[] resetToken, boolean retireIfNeeded) {
        Checks.cid(id);
        if (Objects.requireNonNull(resetToken, "resetToken").length != 16)
            throw new IllegalArgumentException("Reset token must be 16 bytes");

        synchronized (lock) {
            return Native.newScid(pointer(), id, resetToken, retireIfNeeded);
        }
    }

    private long path(int action, InetSocketAddress local, InetSocketAddress peer) {
        synchronized (lock) {
            return Native.pathAction(pointer(), action, Native.address(local),
                    peer == null ? null : Native.address(peer));
        }
    }

    /**
     * Requests the stack to perform path validation of the proposed 4-tuple.
     * <p>
     * Probing new paths requires spare Connection IDs at both the host and the peer sides. If it
     * is not the case, it raises an <code>OutOfIdentifiers</code>.
     * <p>
     * The probing of new addresses can only be done by the client. The server can only probe
     * network paths that were previously advertised by <code>PathEventType.NEW</code>. If the
     * server tries to probe such an unseen network path, this call raises an
     * <code>InvalidState</code>.
     * <p>
     * The caller might also want to probe an existing path. In such case, it triggers a
     * PATH_CHALLENGE frame, but it does not require spare CIDs.
     * <p>
     * A server always probes a new path it observes. Calling this method is hence not required to
     * validate a new path. However, a server can still request an additional path validation of
     * the proposed 4-tuple.
     * <p>
     * Calling this method several times before calling <code>send()</code> or
     * <code>sendOnPath()</code> results in a single probe being generated. An application wanting
     * to send multiple in-flight probes must call this method again after having sent packets.
     * <p>
     * Returns the Destination Connection ID sequence number associated to that path.
     *
     * @param local the resolved local path address
     * @param peer the resolved peer path address
     * @return the associated connection-ID sequence number
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.probe_path">
     *         quiche 0.30.1 upstream API</a>
     */
    public long probePath(InetSocketAddress local, InetSocketAddress peer) {
        return path(0, local, Objects.requireNonNull(peer, "peer"));
    }

    /**
     * Migrates the connection to a new local address <code>local</code>.
     * <p>
     * The behavior is similar to <code>migrate()</code>, with the nuance that the connection only
     * changes the local address, but not the peer one.
     * <p>
     * See <code>migrate()</code> for the full specification of this method.
     *
     * @param local the resolved local path address
     * @return the associated connection-ID sequence number
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.migrate_source">
     *         quiche 0.30.1 upstream API</a>
     */
    public long migrateSource(InetSocketAddress local) {
        return path(1, local, null);
    }

    /**
     * Migrates the connection over the given network path between <code>local</code> and
     * <code>peer</code>.
     * <p>
     * Connection migration can only be initiated by the client. Calling this method as a server
     * throws QuicheException with INVALID_STATE.
     * <p>
     * To initiate voluntary migration, there should be enough Connection IDs at both sides. If
     * this requirement is not satisfied, this call returns <code>OutOfIdentifiers</code>.
     * <p>
     * Returns the Destination Connection ID associated to that migrated path.
     *
     * @param local the resolved local path address
     * @param peer the resolved peer path address
     * @return the associated connection-ID sequence number
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.migrate">
     *         quiche 0.30.1 upstream API</a>
     */
    public long migrate(InetSocketAddress local, InetSocketAddress peer) {
        return path(2, local, Objects.requireNonNull(peer, "peer"));
    }

    /**
     * Returns whether the network path with local address <code>from</code> and remote address
     * <code>peer</code> has been validated.
     * <p>
     * If the 4-tuple does not exist over the connection, returns an <code>InvalidState</code>.
     *
     * @param local the resolved local path address
     * @param peer the resolved peer path address
     * @return whether the condition described above holds
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.is_path_validated">
     *         quiche 0.30.1 upstream API</a>
     */
    public boolean isPathValidated(InetSocketAddress local, InetSocketAddress peer) {
        return path(3, local, Objects.requireNonNull(peer, "peer")) != 0;
    }

    /**
     * Schedule an ack-eliciting packet on the specified path.
     * <p>
     * See <code>sendAckEliciting()</code> for more detail. <code>InvalidState</code> is returned
     * if there is no record of the path.
     *
     * @param local the resolved local path address
     * @param peer the resolved peer path address
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.send_ack_eliciting_on_path">
     *         quiche 0.30.1 upstream API</a>
     */
    public void sendAckElicitingOnPath(InetSocketAddress local, InetSocketAddress peer) {
        path(4, local, Objects.requireNonNull(peer, "peer"));
    }

    /**
     * Returns the size of the send quantum over the given 4-tuple, in bytes.
     * <p>
     * This represents the maximum size of a packet burst as determined by the congestion control
     * algorithm in use.
     * <p>
     * Applications can, for example, use it in conjunction with segmentation offloading mechanisms
     * as the maximum limit for outgoing aggregates of multiple packets.
     * <p>
     * If the (<code>local</code>, peer_addr`) 4-tuple relates to a non-existing path, this method
     * returns 0.
     *
     * @param local the resolved local path address
     * @param peer the resolved peer path address
     * @return the count or limit described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.send_quantum_on_path">
     *         quiche 0.30.1 upstream API</a>
     */
    public long sendQuantumOnPath(InetSocketAddress local, InetSocketAddress peer) {
        return path(5, local, Objects.requireNonNull(peer, "peer"));
    }

    /**
     * Returns the next copied path event, or null when no event is pending. The native event is
     * freed before return; inspect the type before using variant-specific fields.
     *
     * @return the result, or {@code null} for DONE
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.path_event_next">
     *         quiche 0.30.1 upstream API</a>
     */
    public PathEvent pathEventNext() {
        synchronized (lock) {
            return Native.pathEvent(pointer());
        }
    }

    /**
     * Returns a copied snapshot of peer addresses that form known sendable QUIC paths with the
     * supplied local address. The native address iterator is freed before return.
     *
     * @param local the resolved local path address
     * @return the copied values described above
     * @see <a href="https://docs.rs/quiche/0.30.1/quiche/struct.Connection.html#method.paths_iter">
     *         quiche 0.30.1 upstream API</a>
     */
    public InetSocketAddress[] paths(InetSocketAddress local) {
        synchronized (lock) {
            return Native.paths(pointer(), Native.address(local));
        }
    }
}
