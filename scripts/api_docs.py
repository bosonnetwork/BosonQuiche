# Copyright (c) 2026 bosonnetwork.io
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""Render the pinned Rust documentation as JavaDoc with binding-specific semantics."""
import html
import json
from pathlib import Path
import re
import textwrap

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = json.loads((ROOT / 'native/api-docs.json').read_text())
HEADER = (ROOT / 'native/copyright-header.txt').read_text()
TYPE_MAP = {'Config': 'lib.Config', 'Connection': 'lib.Connection', 'RecvInfo': 'lib.RecvInfo',
            'SendInfo': 'lib.SendInfo', 'Stats': 'lib.Stats', 'TransportParams': 'params.TransportParams',
            'PathStats': 'path.PathStats', 'PathEvent': 'path.PathEvent', 'PathState': 'path.PathState',
            'PacketType': 'packet.Type', 'PacketHeader': 'packet.Header', 'Shutdown': 'lib.Shutdown',
            'QuicheError': 'error.Error', 'CongestionControlAlgorithm': 'recovery.CongestionControlAlgorithm',
            'H3Config': 'h3.Config', 'H3Connection': 'h3.Connection', 'H3Header': 'h3.Header',
            'H3Priority': 'h3.Priority', 'H3Event': 'h3.Event', 'H3EventType': 'h3.Event',
            'H3Error': 'h3.Error', 'H3Stats': 'h3.Stats', 'PathEventType': 'path.PathEvent'}
METHOD_MAP = {
    'Config.setApplicationProtos': 'set_application_protos',
    'Connection.timeoutAsNanos': 'timeout', 'Connection.timeoutAsMillis': 'timeout',
    'Connection.setKeylogPath': 'set_keylog', 'Connection.setQlogPath': 'set_qlog',
    'Connection.retiredSourceIds': 'retired_scid_next', 'Connection.paths': 'paths_iter',
    'Connection.peerTransportParams': 'peer_transport_params',
    'H3Connection.peerSettings': 'peer_settings_raw', 'H3Priority.parse': None,
    'Quiche.headerInfo': None, 'Quiche.putVarint': None, 'Quiche.getVarint': None,
    'Quiche.enableDebugLogging': None}


def snake(value):
    return re.sub(r'(?<!^)([A-Z])', r'_\1', value).lower()


def camel(value):
    return re.sub(r'_([a-z])', lambda match: match[1].upper(), value)


def code_name(value):
    value = value.strip('`').replace('Self::', '')
    if '::' in value:
        owner, member = value.rsplit('::', 1)
        owner = {'PathEvent': 'PathEventType', 'Error': 'H3Error' if member.startswith(('Excessive', 'StreamBlocked', 'Qpack')) else 'QuicheError',
                 'Event': 'H3EventType', 'CongestionControlAlgorithm': 'CongestionControlAlgorithm'}.get(owner, owner)
        if member.endswith('()') or '_' in member:
            return owner + '.' + camel(member)
        return owner + '.' + (member if member.isupper() else snake(member).upper())
    return camel(value) if value.endswith('()') else value


def markdown(text):
    """Translate prose and links; Rust examples remain in the linked upstream API."""
    text = re.split(r'^#{1,3} Examples?:?', text, flags=re.M)[0]
    text = re.sub(r'^\s*\[[^\]]+\]:.*(?:\n|$)', '', text, flags=re.M)
    text = re.sub(r'```.*?```', '', text, flags=re.S)
    text = re.sub(r'\[`([^`]+)`\](?:\([^)]*\))?', lambda match: '`' + code_name(match[1]) + '`', text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', lambda match: match[1] if not match[2].startswith('http') else
                  '\x01' + match[1] + '\x02' + match[2] + '\x03', text)
    text = re.sub(r'\[`([^`]+)`\]', r'`\1`', text)
    text = re.sub(r'\[([\w ]+)\]', r'\1', text)
    text = text.replace('SETTINGS_MAX_FIELD_SECTION_SIZE_DEFAULT', '32768 bytes')
    text = text.replace('PRIORITY_UPDATE_FRAME_PAYLOAD_MAX_SIZE_DEFAULT', '256 bytes')
    text = re.sub(r'<(https?://[^>]+)>', lambda match: '\x01' + match[1] + '\x02' + match[1] + '\x03', text)
    # Rust slice/Option terminology is adapted for the Java value surface.
    text = text.replace('provided slice', 'provided buffer').replace('as a tuple', 'in the result object')
    text = html.escape(text, quote=False)
    text = re.sub(r'\x01(.*?)\x02(.*?)\x03', r'<a href="\2">\1</a>', text)
    text = re.sub(r'`([^`]+)`', lambda match: '<code>' + code_name(match[1]) + '</code>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    paragraphs = re.split(r'\n\s*\n', text.strip())
    result = []
    for paragraph in paragraphs:
        if not paragraph.strip():
            continue
        if re.match(r'\s*[-*] ', paragraph):
            entries = re.split(r'\n\s*[-*] ', re.sub(r'^\s*[-*] ', '', paragraph))
            result.append('<ul>\n' + '\n'.join('<li>' + re.sub(r'\s+', ' ', entry).strip() + '</li>' for entry in entries) + '\n</ul>')
        else:
            paragraph = re.sub(r'^#+\s+', '', paragraph)
            result.append(re.sub(r'\s+', ' ', paragraph).strip())
    return '\n<p>\n'.join(result).encode('ascii', 'xmlcharrefreplace').decode()


def upstream(name, member=None):
    key = TYPE_MAP.get(name)
    if name == 'Connection' and member in ('connect', 'accept'):
        return SNAPSHOT['functions'].get('lib.' + member, {}).get('text', ''), 'https://docs.rs/quiche/0.30.1/quiche/fn.' + member + '.html'
    if name == 'Quiche':
        method = METHOD_MAP.get(name + '.' + str(member), snake(member or ''))
        return SNAPSHOT['functions'].get('lib.' + str(method), {}).get('text', ''), 'https://docs.rs/quiche/0.30.1/quiche/index.html'
    record = SNAPSHOT['types'].get(key, {})
    kind = 'enum' if name in ('QuicheError', 'H3Error', 'PacketType', 'PathState', 'Shutdown', 'CongestionControlAlgorithm', 'PathEventType', 'H3EventType') else 'struct'
    rust_name = key.split('.')[-1] if key else name
    module = 'h3/' if key and key.startswith('h3.') else ''
    url = f'https://docs.rs/quiche/0.30.1/quiche/{module}{kind}.{rust_name}.html'
    if name == 'PathState':
        url = 'https://github.com/cloudflare/quiche/blob/0.30.1/quiche/src/path.rs#L53'
    if member is None:
        return record.get('text', ''), url
    method = METHOD_MAP.get(name + '.' + member, snake(member))
    return record.get('methods', {}).get(method, {}).get('text', ''), url + '#method.' + str(method)


CLASS_DOCS = {
    'CongestionControlAlgorithm': 'Congestion-control algorithms exposed by the pinned C API. CUBIC is the default. The bundled native build also enables the gcongestion BBRv2 implementation.',
    'Config': """Configuration shared by new QUIC connections. Defaults follow quiche 0.30.1.

    ALPN, stream counts and flow-control limits must be configured for the application.
    Peer certificate verification is disabled upstream by default; clients normally enable
    `verifyPeer(true)` and configure trusted certificates. Enabling server verification
    requests a client certificate but still permits clients that supply none.

    This object owns native memory and must be closed explicitly. Connections created
    from it remain usable after it is closed. Calls are serialized with disposal;
    operations on a disposed object throw `IllegalStateException`.""",
    'Connection': """A socket-independent QUIC connection, backed by quiche and BoringSSL.

    The application supplies packet I/O, source/destination addresses, pacing and timers.
    Drain `send()` after receiving packets, writing or reading application data, shutting
    down a stream, or processing a timeout. Continue driving timers even without incoming
    traffic. Stream counts and flow-control limits are configured on `Config`.

    Bulk I/O requires direct `ByteBuffer` instances. Methods use the current position
    and limit, and advance the position on success. There is no JNI payload staging copy;
    quiche may copy data internally for buffering and retransmission. `recv()` decrypts
    packets in place. Native code retains no reference to a supplied buffer after return.

    Close this owner explicitly to free native memory. The overloaded protocol `close`
    method only queues CONNECTION_CLOSE; drain outgoing packets before disposing.
    Calls are serialized with disposal, but callers must protect shared buffers.
    Disposed owners reject further operations with `IllegalStateException`.
    Native uint64 values retain their bit pattern in Java `long` values.""",
    'H3Connection': """quiche's HTTP/3 application layer over an existing QUIC connection.

    Configure ALPN as `h3` and permit at least three unidirectional streams before the
    QUIC handshake. The HTTP/3 role is inferred from the transport. Packet I/O and
    timer processing remain on the transport; poll HTTP/3 events after delivering packets.
    Read a DATA event's body until DONE before expecting the event to be re-armed.

    This object owns native HTTP/3 state and must be closed explicitly. It shares the
    transport's operation/disposal lock; disposing it does not dispose the transport.
    Operations fail with `IllegalStateException` if either required owner was disposed.
    Body buffers are direct, use position/limit, and incur no additional JNI payload copy.""",
    'H3Config': 'Owned HTTP/3 settings with upstream defaults. Close explicitly; initialized HTTP/3 connections do not borrow this Java owner.',
    'Quiche': 'Socket-independent QUIC utilities and constants from quiche 0.30.1. Connections provide TLS, streams and datagrams without creating sockets, threads or schedulers.',
    'Stats': 'Immutable connection statistics copied from quiche. Byte counters and packet/frame counts retain native units. The active-send duration is converted to milliseconds by the C API. Native uint64 counters retain their Java long bit patterns.',
    'TransportParams': 'Immutable snapshot of the peer transport parameters exposed by the quiche C API. Parameter names are prefixed with peer. Idle and ACK delays use milliseconds; limits are bytes or counts as indicated by each field.',
    'PathStats': 'Immutable statistics for one network path. RTT fields are nanoseconds, congestion-window and PMTU fields are bytes, and delivery/bandwidth estimates are bytes per second. Addresses and values are copied from native state.',
    'H3Stats': 'Immutable HTTP/3 statistics copied from quiche. Both QPACK counters are byte counts.',
    'RecvInfo': 'Source and destination metadata for one received UDP datagram. Addresses must be resolved and describe the observed path; this object owns no socket.',
    'SendInfo': 'Output metadata from one native packet-send operation. The output buffer contains `bytes` bytes of one UDP datagram; the application transmits it using the indicated path and pacing information.',
    'Timespec': 'A native monotonic timespec. This is not a wall-clock date or the epoch of System.nanoTime(). Use SendInfo.delayNanos for a relative scheduling delay. Upstream returns zero timing information on macOS, iOS and Windows.',
    'StreamResult': 'The byte count and FIN flag returned by a successful stream receive. A FIN means the peer ended this stream direction; the reverse direction can remain open.',
    'PacketHeader': 'A copied QUIC packet-header snapshot. Parsing does not consume the input buffer. Connection IDs and tokens are returned as defensive byte-array copies.',
    'ConnectionError': 'A copied local or peer CONNECTION_CLOSE error. The application flag selects application versus transport error codes. The unsigned native code is represented by a Java long bit pattern.',
    'H3Header': 'A copied HTTP/3 header name/value pair. Use byte-array accessors for lossless values; string helpers decode UTF-8. Applications remain responsible for validating pseudo-headers and header fields.',
    'H3Priority': 'HTTP Extensible Priority parameters: urgency is 0 (highest) through 7 (lowest), and incremental distinguishes incrementally delivered responses. Parse a serialized Priority field with parse(byte[]).',
    'H3Event': 'A copied HTTP/3 event. Native event memory is released before poll() returns. Headers are immutable Java values; DATA is consumed separately with H3Connection.recvBody().',
    'PathEvent': 'A copied QUIC path event. Native event memory is released before polling returns. All events have current local/peer addresses; reused-CID events also have previous addresses and an ID, and PMTU events have a byte limit.',
    'QuicheException': 'A QUIC operation failure mapped from an upstream error code. DONE is normally represented by null or -1 on nonblocking APIs. STREAM_RESET and STREAM_STOPPED preserve the peer application error code.',
    'H3Exception': 'An HTTP/3 operation failure, including transport errors propagated through the HTTP/3 C API. code() always preserves the numeric value; error() resolves the corresponding mapped enum.',
    'NativeResource': 'Owns a native allocation. All native calls and disposal share a monitor. Close owners explicitly; further native operations on a disposed owner throw IllegalStateException.'}

# Descriptions are adapted where the C/JNI return or ownership contract differs
# from the original Rust API. The original API remains linked for protocol detail.
METHOD_DOCS = {
    'Config.setUncheckedCongestionWindow': 'Sets a fixed congestion window in bytes for an upstream build that enables congestion_window_unchecked. The default is the native size_t maximum; other controllers ignore it. The native library bundled by this project does not enable that experimental controller, so this setter has no effect on the bundled controllers. Zero or a window smaller than a datagram can stall an enabled controller.',
    'Config.setStatelessResetToken': 'Sets the initial 16-byte stateless reset token advertised by servers. Configuring it on a client has no effect. By default no token is configured. The supplied array is copied for the native call.',
    'Connection.streamWritable': 'Returns whether the stream can buffer at least length more bytes. If flow control prevents that write, quiche notifies the peer and records a low send watermark; streamWritableNext() will not report the stream again until that capacity is available. A missing or completed stream throws QuicheException with INVALID_STREAM_STATE; STOP_SENDING is reported as STREAM_STOPPED.',
    'H3Connection.withTransport': 'Creates HTTP/3 state using the provided open QUIC connection, inferring the client/server role. It opens control/QPACK streams and queues local settings. Configure ALPN h3 and at least three unidirectional streams first. If native initialization fails, such as when stream limits prevent control-stream creation, this binding throws IllegalStateException rather than returning a Rust Result. The caller owns and must separately close both the HTTP/3 and transport owners.',
    'H3Connection.sendPriorityUpdateForRequest': 'Queues a PRIORITY_UPDATE for a request stream on the HTTP/3 control stream. A blocked control stream is reported through H3Exception; retry when capacity is available. Drain the QUIC output to transmit it. Updates for closed streams may be ignored by the peer.',
    'Quiche.retry': 'Builds a Retry packet into the writable direct output range. Supply the source and destination IDs from the received Initial, a new server source ID and an application-authenticated address-validation token. The application sends the packet and validates the returned token before accepting the connection. On success the output position advances by the packet length.',
    'Quiche.negotiateVersion': 'Builds a Version Negotiation packet from the source/destination IDs in the received packet. QUIC reverses these IDs in its response header. The output must be a writable direct buffer; its position advances by the encoded packet length. The application performs the actual transmission.',
    'Connection.connect': 'Creates a client connection using the supplied source connection ID and resolved local/peer addresses. serverName is the TLS server name used for SNI and certificate name verification, not an instruction to open a socket. A null name omits SNI/name checking; configure peer authentication deliberately. No packet is transmitted until the application drains send().',
    'Connection.accept': 'Creates a server connection. sourceId is the server source connection ID; originalDestinationId is the client destination ID before Retry, or null when Retry was not used. Supply the actual received local/peer path. No socket is opened.',
    'Connection.recv': 'Processes one received UDP datagram from the current buffer range, decrypting its contents in place. Provide the observed remote source and local destination in info. Advance application processing and drain send() afterwards. Returns -1 for upstream DONE, otherwise the consumed byte count. Other native errors throw QuicheException; the buffer position advances only on success.',
    'Connection.send': 'Produces one outgoing UDP datagram and its path/pacing metadata. Call repeatedly until null (DONE), using a writable direct buffer large enough for the configured packet size. Drain after recv(), onTimeout(), stream writes/shutdown and application reads that can generate flow-control updates. Once draining, no further packets need be produced. The buffer position advances by SendInfo.bytes; transmit those bytes before reusing their storage.',
    'Connection.sendOnPath': 'Produces one outgoing datagram on the requested path. A null source or destination lets quiche select that part of the path. Returns null for DONE and otherwise the same buffer and pacing contract as send(). This selects a QUIC path; the application is still responsible for actual UDP/ICE transmission.',
    'Connection.streamRecv': 'Reads contiguous stream data into the current writable direct-buffer range. Returns a StreamResult containing bytes and FIN, or null for DONE when no data is available. Reading can queue flow-control updates, so drain send() afterwards. STREAM_RESET/STREAM_STOPPED failures throw QuicheException with the application error code. A fully consumed and reclaimed stream can instead report INVALID_STREAM_STATE.',
    'Connection.streamSend': 'Queues data from the current direct-buffer range on a stream, opening it if permitted by stream limits. Partial writes are normal: only the accepted prefix advances the buffer position. Retry the remaining range when writable, and drain send() to produce network packets. FIN is committed only when the requested data is accepted. Returns -1 for DONE/backpressure; native reset/stop errors preserve the application error code. Read-only direct input is supported. quiche can copy the accepted data for retransmission; JNI does not stage it.',
    'Connection.dgramRecv': 'Reads the first buffered unreliable DATAGRAM into the current writable direct-buffer range. Returns -1 for DONE, otherwise advances by the datagram length. The buffer must fit the whole datagram; BUFFER_TOO_SHORT leaves it queued. Stream flow control does not apply to DATAGRAM frames.',
    'Connection.dgramSend': 'Queues one unreliable DATAGRAM from the current direct-buffer range. Returns its accepted byte count or -1 for DONE when blocked by the outgoing queue. A payload larger than dgramMaxWritableLen() fails with BUFFER_TOO_SHORT. Delivery is not acknowledged or retransmitted. Drain send() to produce packets; read-only direct input is supported.',
    'Connection.dgramMaxWritableLen': 'Returns the maximum currently writable DATAGRAM payload size, accounting for peer support, path MTU and protocol overhead, or -1 for upstream DONE if the size is unavailable. This limit does not guarantee room in the outgoing queue.',
    'Connection.dgramRecvFrontLen': 'Returns the first queued incoming DATAGRAM length in bytes, or -1 when the queue is empty. Zero is a valid empty-datagram length.',
    'Connection.dgramPurgeOutgoing': 'Removes queued outgoing DATAGRAMs for which the predicate returns true. The predicate receives a Java-owned copy; this explicit control API does not expose borrowed native memory. It must not re-enter or dispose native owners. Predicate exceptions propagate after quiche returns.',
    'Connection.timeoutAsNanos': 'Returns the relative nanoseconds until the next connection timer, or -1 when no timer is armed. Schedule onTimeout() after this delay, then drain send() and recompute the timeout. Zero means the timer is already due; it is not the disarmed sentinel.',
    'Connection.timeoutAsMillis': 'Returns the relative milliseconds until the next connection timer, or -1 when no timer is armed. Sub-millisecond delays may round down to zero. Prefer timeoutAsNanos() when fine-grained scheduling is available.',
    'Connection.readable': 'Returns a copied snapshot of readable stream IDs. The native iterator is consumed and freed inside JNI. Reading can change readiness, so obtain a fresh snapshot after processing data.',
    'Connection.writable': 'Returns a copied snapshot of writable stream IDs. A stream can still accept only a prefix of a later write; this is a readiness snapshot, not reserved capacity.',
    'Connection.streamCapacity': 'Returns current send capacity for a stream in bytes, or -1 for upstream DONE. Missing, stopped or reset streams can throw QuicheException; readiness/capacity can change after other operations.',
    'Connection.streamReadableNext': 'Returns the next stream ID with buffered readable data, or -1 when no stream is readable. This query does not consume stream data.',
    'Connection.streamWritableNext': 'Returns the next writable stream ID, or -1 when no stream is writable. This query does not reserve send capacity.',
    'Connection.sourceIds': 'Returns copies of all active source connection IDs. Native iterator memory is released before this method returns.',
    'Connection.retiredSourceIds': 'Drains all currently retired source connection IDs into Java-owned byte arrays and frees the native iterator. Unlike sourceIds(), this operation consumes pending retired-ID notifications.',
    'Connection.paths': 'Returns a copied snapshot of peer addresses that form known sendable QUIC paths with the supplied local address. The native address iterator is freed before return.',
    'Connection.pathEventNext': 'Returns the next copied path event, or null when no event is pending. The native event is freed before return; inspect the type before using variant-specific fields.',
    'Connection.peerTransportParams': 'Returns a copied peer transport-parameter snapshot, or null before the peer parameters have been processed. C-API durations retain their documented milliseconds units.',
    'Connection.peerError': 'Returns the peer CONNECTION_CLOSE error, or null when none has been received. The reason bytes are copied before returning.',
    'Connection.localError': 'Returns the locally queued or sent CONNECTION_CLOSE error, or null when none exists. This does not itself queue a close or free memory.',
    'Connection.traceId': 'Returns a copy of the connection trace identifier encoded as bytes. It is intended for correlation and diagnostics.',
    'Connection.sourceId': 'Returns a copy of the current source connection ID.',
    'Connection.destinationId': 'Returns a copy of the current destination connection ID.',
    'Connection.applicationProto': 'Returns a copy of the negotiated ALPN protocol bytes, or an empty array before negotiation. No character decoding is imposed.',
    'Connection.peerCert': 'Returns a copy of the peer leaf certificate in DER format, or an empty array when unavailable. This C API does not expose the entire Rust certificate-chain API. A server that requires a client certificate must check that one was presented.',
    'Connection.serverName': 'Returns a copy of the TLS server-name bytes, or an empty array when no name is available.',
    'Connection.session': 'Returns a copy of the serialized TLS session for resumption, or an empty array when no session is available yet. Treat the serialization as opaque and pass it to setSession() on a new connection.',
    'Connection.setSession': 'Configures opaque session-resumption data from a previous connection. Call on a new connection before sending or receiving packets. Invalid serialization throws QuicheException; enabling early data is a separate configuration choice.',
    'Connection.setKeylogPath': 'Enables TLS secret logging to the specified filesystem path. Returns whether the log file was opened successfully. Configure logging before processing the handshake; protect these secrets because they permit traffic decryption.',
    'Connection.setQlogPath': 'Enables qlog output at the specified filesystem path, with title and description metadata. Returns whether the file could be opened. Configure it before processing the connection events to be recorded.',
    'Connection.close': 'Queues an application or transport CONNECTION_CLOSE error and a reason. Drain send() to transmit the close, and continue timer processing while closing. This overload does not free native memory; the no-argument AutoCloseable close() disposes it. Repeated upstream DONE closes are ignored.',
    'H3Connection.poll': 'Processes received HTTP/3 data and returns the next copied event, or null for DONE. For DATA, call recvBody() repeatedly until -1 so that the event can be re-armed. HEADERS contain copied name/value pairs that the application must validate. Native HTTP/3 and propagated transport errors throw H3Exception. The Rust reset-event payload is not available through this C-backed snapshot.',
    'H3Connection.sendRequest': 'Queues request headers and returns the new stream ID. fin ends the request body direction if no body follows. Drain the underlying QUIC send() to transmit it. STREAM_BLOCKED is reported as H3Exception; retry after transport capacity becomes available without assuming a request was queued.',
    'H3Connection.sendResponse': 'Queues response headers on the request stream with default priority. fin ends the response direction when no body follows. Drain the underlying QUIC output after queuing. HTTP/3 failures throw H3Exception.',
    'H3Connection.sendResponseWithPriority': 'Queues response headers using the supplied Extensible Priority parameters. fin ends the response direction if no body follows. Drain the underlying QUIC connection to transmit queued frames.',
    'H3Connection.sendAdditionalHeaders': 'Queues additional headers, such as informational response headers or a trailer section. Set trailer for trailers, and fin when this section ends the stream direction. The application must supply a valid HTTP/3 header sequence.',
    'H3Connection.sendBody': 'Queues a body chunk from the current direct-buffer range. Partial writes advance only by the accepted prefix; retry the remainder when writable. fin ends the body only when all supplied data is accepted. Returns -1 for upstream DONE, otherwise the accepted byte count. Read-only direct input is supported; JNI adds no payload staging copy. Drain the underlying QUIC output afterwards.',
    'H3Connection.recvBody': 'Reads buffered request/response body bytes into the current writable direct-buffer range. Returns -1 for DONE, otherwise advances the buffer by the copied byte count. After DATA, call repeatedly until -1 before waiting for another DATA event. Drain transport output for any resulting flow-control updates.',
    'H3Connection.peerSettings': 'Returns an immutable Java map of the peer HTTP/3 settings as identifier/value pairs. The values are copied from native state; no native iterator or callback remains live after return.',
    'H3Connection.takeLastPriorityUpdate': 'Takes and removes the latest serialized PRIORITY_UPDATE value for the stream, or returns null for DONE when none is pending. quiche emits one update event per stream until this value is taken; process all currently pending events before taking it when coalescing updates.',
    'H3Priority.parse': 'Parses an HTTP Extensible Priority field value using quiche Structured Fields support. The returned urgency/incremental values are independent of the input bytes. Invalid input throws H3Exception.',
    'Config.logKeys': 'Enables logging of TLS secrets. Select a keylog path on each connection before its handshake. Logged keys permit traffic decryption and require appropriate storage protection.',
    'Config.setApplicationProtos': 'Configures the application protocols offered by a client or accepted by a server during ALPN. No default is supplied; applications must configure at least one protocol. The byte-array overload accepts the wire format: nonempty 8-bit length-prefixed byte strings. The string overload encodes each protocol as UTF-8. Each protocol must contain 1..255 bytes.',
    'Config.setMaxOutstandingSentPackets': 'Limits the number of sent packets tracked for loss detection. Exceeding the limit closes the connection with PROTOCOL_VIOLATION. The default is 22,000; pass 0 to disable the limit. Choose a limit larger than the expected maximum congestion window measured in packets.',
    'Config.setTicketKey': 'Sets the 48-byte session-ticket encryption key. Servers use this for stateless resumption. Upstream otherwise generates and rotates keys internally; applications supplying their own key are responsible for rotation and any cross-server sharing.',
    'Quiche.version': 'Returns the version of the loaded native quiche library. The loader rejects a native library that does not match the pinned binding version.',
    'Quiche.headerInfo': 'Parses the QUIC packet header without consuming the direct input buffer. dcidLength supplies the destination connection-ID length for short-header packets. The result copies connection IDs and tokens. Malformed input throws QuicheException.',
    'Quiche.putVarint': 'Encodes an unsigned QUIC variable-length integer into the current writable direct-buffer range and advances the position by its wire length. Values must be in 0..2^62-1. BUFFER_TOO_SHORT is reported as QuicheException.',
    'Quiche.getVarint': 'Decodes an unsigned QUIC variable-length integer from the current direct-buffer range and advances the position by its wire length. A truncated encoding throws QuicheException.',
    'Quiche.enableDebugLogging': 'Installs the process-global quiche debug logger once. Install before configuring connections. Callback exceptions are dropped by native logging; callbacks must not re-enter or dispose native owners. A second installation throws IllegalStateException.'}

FIELD_DOCS = {
    'Stats.txBufferedInconsistent': 'Whether the native send buffer is inconsistent, potentially causing stalls or excessive buffering.',
    'PathStats.startupExitCwnd': 'The congestion window in bytes at the end of startup/slow start, or zero while still in startup.',
    'TransportParams.peerMaxDatagramFrameSize': 'The peer maximum DATAGRAM frame size in bytes, or -1 if the extension was not negotiated.',
    'SendInfo.bytes': 'The number of bytes written into the output buffer for this datagram.',
    'SendInfo.at': 'The native monotonic send time. This is not a Java nanoTime epoch or wall-clock timestamp. Upstream 0.30.1 supplies zero on macOS/iOS/Windows.',
    'SendInfo.delayNanos': 'The nonnegative relative pacing delay, in nanoseconds, sampled natively when send returned. Zero means due now or unavailable. Account for time already spent before scheduling.',
    'Timespec.seconds': 'The native monotonic tv_sec component.', 'Timespec.nanoseconds': 'The tv_nsec component in 0..999,999,999.',
    'StreamResult.bytes': 'The number of bytes read and added to the output buffer position.', 'StreamResult.fin': 'Whether the peer FIN was consumed for this stream direction.',
    'ConnectionError.application': 'True for an application close code, false for a transport close code.', 'ConnectionError.code': 'The unsigned native close-code bit pattern.',
    'PacketHeader.version': 'The unsigned 32-bit QUIC wire version; zero denotes version negotiation.', 'PacketHeader.type': 'The parsed QUIC packet type.',
    'PathEvent.type': 'The event discriminator; inspect it before variant-specific fields.', 'PathEvent.local': 'The current local path address.',
    'PathEvent.peer': 'The current peer path address.', 'PathEvent.previousLocal': 'The previous local address for REUSED_SOURCE_CONNECTION_ID, otherwise null.',
    'PathEvent.previousPeer': 'The previous peer address for REUSED_SOURCE_CONNECTION_ID, otherwise null.',
    'PathEvent.id': 'The reused source connection-ID sequence number, meaningful only for REUSED_SOURCE_CONNECTION_ID.',
    'PathEvent.pmtu': 'The validated normal-traffic PMTU in bytes, meaningful only for PMTU_UPDATED.',
    'H3Event.id': 'The stream ID, or the GOAWAY identifier for a GOAWAY event.', 'H3Event.type': 'The HTTP/3 event discriminator.',
    'H3Event.hasMoreFrames': 'Whether more frames follow this header section; meaningful only for HEADERS.',
    'H3Priority.urgency': 'The urgency in 0..7, where zero is highest priority.', 'H3Priority.incremental': 'Whether the response can be processed incrementally.',
    'PathStats.localAddress': 'The local socket address for this path.', 'PathStats.peerAddress': 'The peer socket address for this path.',
    'Quiche.PROTOCOL_VERSION': 'The current supported QUIC v1 wire version.', 'Quiche.MAX_CONN_ID_LEN': 'The maximum connection-ID length in bytes (20).',
    'Quiche.MIN_CLIENT_INITIAL_LEN': 'The minimum UDP payload for client Initial datagrams, in bytes (1200).',
    'Quiche.H3_APPLICATION_PROTOCOL': 'The HTTP/3 ALPN identifier h3.'}


def field_doc(name, field):
    if name + '.' + field in FIELD_DOCS:
        return FIELD_DOCS[name + '.' + field]
    record = SNAPSHOT['types'].get(TYPE_MAP.get(name), {})
    rust_field = snake(field)
    if name == 'TransportParams':
        rust_field = rust_field.removeprefix('peer_')
    if field == 'bytesInFlightDurationMsec':
        return 'Total time actively sending bytes or waiting for their acknowledgement, in milliseconds.'
    raw = record.get('fields', {}).get(rust_field)
    return raw or ('The ' + re.sub(r'(?<!^)([A-Z])', r' \1', field).lower() + ' value.')


def variant_doc(name, value):
    record = SNAPSHOT['types'].get(TYPE_MAP.get(name), {})
    aliases = {'ZERO_RTT': 'ZeroRTT', 'VERSION_NEGOTIATION': 'VersionNegotiation', 'GOAWAY': 'GoAway',
               'BBR2_GCONGESTION': 'Bbr2Gcongestion', 'CUBIC': 'CUBIC', 'VALIDATING_MTU': 'ValidatingMTU'}
    rust_name = aliases.get(value, ''.join(word.title() for word in value.split('_')))
    raw = record.get('variants', {}).get(rust_name, '')
    if name == 'H3EventType' and value == 'DATA':
        return 'Body data is available. Call H3Connection.recvBody() repeatedly until it returns -1 (DONE); a new DATA event is not armed until all buffered data has been read.'
    if name == 'H3EventType' and value == 'PRIORITY_UPDATE':
        return 'A PRIORITY_UPDATE is available. Take it with H3Connection.takeLastPriorityUpdate(). One event per stream is triggered until the latest value is taken; normally defer taking it until poll() returns null.'
    if name == 'H3EventType' and value == 'RESET':
        return 'The stream was reset. H3Event identifies the stream; the Rust associated reset code is not exposed by this C API.'
    if name == 'QuicheError' and value == 'INVALID_STREAM_STATE':
        return 'The stream is in an invalid state. The Rust associated stream-ID payload is not exposed by this C API.'
    if name == 'QuicheError' and value in ('STREAM_RESET', 'STREAM_STOPPED'):
        return raw.replace('provided as\nassociated data', 'available through QuicheException.streamErrorCode()')
    return raw


PARAMS = {'version': 'the unsigned QUIC wire version', 'path': 'the filesystem path', 'curves': 'the colon-separated TLS group preference list',
          'algorithm': 'the upstream congestion-control algorithm name', 'protocols': 'the ALPN protocol list in the overload-specific format',
          'token': 'the token bytes', 'key': 'the session-ticket encryption key (48 bytes)', 'enabled': 'whether the feature is enabled',
          'receiveQueueLength': 'the incoming DATAGRAM queue capacity, in messages', 'sendQueueLength': 'the outgoing DATAGRAM queue capacity, in messages',
          'value': 'the configuration value, in the units described above', 'sourceId': 'the source connection ID, at most 20 bytes',
          'destinationId': 'the destination connection ID, at most 20 bytes', 'newSourceId': 'the new source connection ID for Retry',
          'originalDestinationId': 'the pre-Retry destination ID, or null without Retry', 'local': 'the resolved local path address',
          'peer': 'the resolved peer path address', 'serverName': 'the TLS server name, or null to omit it', 'config': 'the open native configuration owner',
          'transport': 'the open underlying QUIC connection', 'out': 'the writable direct output buffer, using position and limit',
          'data': 'the direct input buffer, using position and limit', 'buffer': 'the direct buffer range to process',
          'packet': 'the direct packet buffer range; receive requires writable memory', 'info': 'the observed source/destination metadata',
          'stream': 'the nonnegative QUIC stream ID', 'fin': 'whether this write ends the stream direction once fully accepted',
          'from': 'the resolved source address, or null for automatic send-path selection', 'to': 'the resolved destination address, or null for automatic send-path selection',
          'urgency': 'the priority urgency', 'incremental': 'whether delivery is incremental', 'direction': 'the stream direction to stop',
          'error': 'the unsigned application or transport error-code bit pattern', 'length': 'the required number of writable bytes',
          'millis': 'the idle timeout in milliseconds', 'application': 'true for an application error, false for a transport error',
          'reason': 'the opaque close-reason bytes', 'index': 'the nonnegative path index', 'predicate': 'the non-reentrant predicate selecting datagrams to remove',
          'id': 'the identifier or sequence number', 'resetToken': 'the 16-byte stateless reset token', 'retireIfNeeded': 'whether quiche may retire an older source ID to make room',
          'sequence': 'the destination connection-ID sequence number', 'headers': 'the ordered HTTP/3 header fields', 'priority': 'the HTTP Extensible Priority parameters',
          'trailer': 'whether this is a trailer section', 'body': 'the direct body buffer range', 'field': 'the serialized Priority field bytes',
          'dcidLength': 'the destination ID length for short-header packets, in 0..20', 'input': 'the direct encoded input buffer range',
          'logger': 'the process-global non-reentrant logging callback', 'name': 'the header name bytes or UTF-8 string',
          'code': 'the upstream numeric code', 'streamErrorCode': 'the unsigned application error code for a reset or stopped stream',
          'seconds': 'the native monotonic seconds component', 'nanoseconds': 'the fractional nanoseconds component in 0..999,999,999',
          'session': 'the opaque serialized TLS session', 'title': 'the qlog title', 'description': 'the qlog description'}


def comment(body, indent='', tags=()):
    body = markdown(textwrap.dedent(body).strip())
    lines = []
    for line in body.splitlines():
        lines.extend(textwrap.wrap(line, width=96-len(indent), break_long_words=False, break_on_hyphens=False) or [''])
    if tags:
        lines.append('')
        for tag in tags:
            if tag.startswith('@see <a href=') and len(tag) > 96-len(indent):
                anchor, label = tag.split('>', 1)
                lines.append(anchor + '>')
                lines.extend(textwrap.wrap(label, width=96-len(indent), initial_indent='        ',
                                           subsequent_indent='        ', break_long_words=False,
                                           break_on_hyphens=False))
            else:
                lines.extend(textwrap.wrap(tag, width=96-len(indent), subsequent_indent='        ',
                                           break_long_words=False, break_on_hyphens=False))
    return indent + '/**\n' + ''.join(indent + ' *' + (' ' + line if line else '') + '\n' for line in lines) + indent + ' */\n'


def preceding_doc(source, start):
    index = source.rfind('/**', 0, start)
    if index >= 0:
        end = source.find('*/', index)
        if end >= 0 and not source[end+2:start].strip():
            return source.rfind('\n', 0, index) + 1
    return start


def document(name, source):
    """Replace public member comments without changing their implementation."""
    edits = []
    pattern = re.compile(r'^(?P<indent>    )(?P<declaration>(?:@Override\s+)?public\s+[^\n;{=]+?\([^)]*\))', re.M)
    for match in pattern.finditer(source):
        declaration = match['declaration']
        head, params = declaration.split('(', 1)
        member = head.split()[-1]
        constructor = member == name
        return_type = re.sub(r'^(?:@Override\s+)?public\s+(?:(?:static|final|synchronized)\s+)*', '', head).removesuffix(member).strip()
        raw, url = upstream(name, member)
        key = name + '.' + member
        if constructor:
            body = {'Config': 'Creates a native configuration using the specified QUIC wire version. The no-argument constructor selects Quiche.PROTOCOL_VERSION. Close the owner explicitly.',
                    'H3Config': 'Creates an HTTP/3 configuration with upstream default settings. Close the owner explicitly.',
                    'H3Header': 'Creates a header by copying the supplied name/value bytes, or by UTF-8 encoding the supplied strings.',
                    'RecvInfo': 'Creates resolved source/destination metadata for a received datagram.',
                    'Timespec': 'Creates a native monotonic timestamp value. The fractional nanoseconds component must be in range.',
                    'H3Priority': 'Creates HTTP Extensible Priority parameters; urgency must be in 0..7.',
                    'QuicheException': 'Creates a QUIC error with an optional stream application error code.',
                    'H3Exception': 'Creates an HTTP/3 error that retains the native numeric code.'}.get(name, 'Creates a ' + name + ' value.')
        elif key in METHOD_DOCS:
            body = METHOD_DOCS[key]
        elif raw:
            body = raw
            aliases = {'stream_id': 'stream', 'local_addr': 'local', 'peer_addr': 'peer',
                       'retire_if_needed': 'retireIfNeeded', 'dcid_seq': 'sequence', 'len': 'length'}
            if member == 'newScid':
                aliases.update(scid='id', reset_token='resetToken')
            for original, replacement in aliases.items():
                body = body.replace('`' + original + '`', '`' + replacement + '`')
            body = re.sub(r'(error (?:will be|is)) returned', 'error is reported through a Java exception', body)
            body = body.replace('returns [`InvalidState`]', 'throws QuicheException with INVALID_STATE')
            if name == 'Config':
                body = re.sub(r'`(?:v|verify|file|dir)`', lambda item: '`path`' if item[0] in ('`file`', '`dir`') else '`value`', body)
        elif re.search(r'^    public final [^;=]+ ' + re.escape(member) + r'\s*;', source, re.M):
            body = 'Returns ' + field_doc(name, member).removeprefix('The ').removeprefix('the ')
        else:
            body = {
                'code': 'Returns the upstream numeric enum/error code.', 'error': 'Returns the mapped upstream error enum.',
                'fromCode': 'Resolves an upstream numeric code to this enum. Unknown values throw IllegalArgumentException.',
                'streamErrorCode': 'Returns the unsigned peer application error code, meaningful for STREAM_RESET and STREAM_STOPPED.',
                'reason': 'Returns a defensive copy of the close-reason bytes.', 'sourceId': 'Returns a defensive copy of the source connection ID.',
                'destinationId': 'Returns a defensive copy of the destination connection ID.', 'token': 'Returns a defensive copy of the Retry/address-validation token.',
                'name': 'Returns a defensive copy of the header name bytes.', 'value': 'Returns a defensive copy of the header value bytes.',
                'nameAsString': 'Decodes the header name as UTF-8.', 'valueAsString': 'Decodes the header value as UTF-8.',
                'headers': 'Returns the immutable list of copied header fields, populated only for a HEADERS event.',
                'isDisposed': 'Returns whether native memory has been released. This is different from the QUIC protocol closed state.',
                'close': 'Idempotently frees the native allocation. This no-argument method does not initiate a graceful protocol close; queue a protocol close and drain output first if required.'
            }.get(member, 'Returns ' + field_doc(name, member).removeprefix('The ').removeprefix('the '))
        tags = []
        for parameter in re.split(r',\s*(?![^<]*>)', params[:-1].strip()) if params[:-1].strip() else []:
            parameter_name = parameter.split()[-1]
            parameter_type = ' '.join(parameter.split()[:-1])
            if parameter_name == 'value' and name == 'H3Header':
                description = 'the header value bytes or UTF-8 string'
            elif parameter_name == 'value' and key == 'Quiche.putVarint':
                description = 'the unsigned value in 0..2^62-1'
            elif parameter_name == 'value' and parameter_type == 'boolean':
                description = 'whether this feature is enabled'
            else:
                description = PARAMS.get(parameter_name, 'the ' + parameter_name + ' value')
            tags.append('@param ' + parameter_name + ' ' + description)
        if not constructor and return_type != 'void':
            if return_type == name and name in ('Config', 'H3Config'):
                result = 'this configuration'
            elif key in ('Connection.send', 'Connection.sendOnPath', 'Connection.streamRecv', 'Connection.pathEventNext', 'H3Connection.poll'):
                result = 'the result, or {@code null} for DONE'
            elif key in ('Connection.timeoutAsNanos', 'Connection.timeoutAsMillis'):
                result = 'the relative delay in the named unit, or {@code -1} when disarmed'
            elif return_type == 'boolean':
                result = 'whether the condition described above holds'
            elif key in ('Connection.connect', 'Connection.accept', 'H3Connection.withTransport'):
                result = 'the new native owner, which the caller must close'
            elif key in ('Connection.recv', 'Connection.streamSend', 'Connection.dgramSend', 'Connection.dgramRecv', 'H3Connection.sendBody', 'H3Connection.recvBody'):
                result = 'the successful byte count, or {@code -1} for DONE'
            elif key in ('Connection.peerTransportParams', 'Connection.peerError', 'Connection.localError'):
                result = 'the copied snapshot, or {@code null} when unavailable'
            elif key == 'H3Connection.takeLastPriorityUpdate':
                result = 'the copied field value, or {@code null} when none is pending'
            elif member in ('streamReadableNext', 'streamWritableNext'):
                result = 'the stream ID, or {@code -1} when none is ready'
            elif key == 'H3Connection.sendRequest':
                result = 'the new request stream ID'
            elif member in ('newScid', 'probePath', 'migrate', 'migrateSource'):
                result = 'the associated connection-ID sequence number'
            elif key == 'Quiche.version':
                result = 'the native quiche version string'
            elif key == 'Quiche.getVarint':
                result = 'the decoded unsigned 62-bit value'
            elif key in ('Quiche.putVarint', 'Quiche.retry', 'Quiche.negotiateVersion'):
                result = 'the encoded byte count'
            elif key == 'H3Priority.parse':
                result = 'the decoded priority parameters'
            elif member == 'fromCode':
                result = 'the corresponding enum value'
            elif member == 'code':
                result = 'the upstream numeric code'
            elif return_type == 'byte[]':
                result = 'the copied bytes, empty when unavailable where documented above'
            elif return_type.endswith('[]') or return_type.startswith(('List<', 'Map<')):
                result = 'the copied values described above'
            elif return_type in ('Stats', 'H3Stats', 'PathStats'):
                result = 'the copied statistics snapshot'
            elif re.search(r'^    public final [^;=]+ ' + re.escape(member) + r'\s*;', source, re.M):
                result = 'the {@link #' + member + '} value'
            else:
                result = 'the count or limit described above'
            tags.append('@return ' + result)
        if url and raw:
            tags.append('@see <a href="' + url + '">quiche 0.30.1 upstream API</a>')
        edits.append((preceding_doc(source, match.start()), match.start(), comment(body, match['indent'], tags)))
    for match in re.finditer(r'^(?P<indent>    )public (?:static )?final [\w.<>\[\]]+ (?P<name>\w+)\s*(?:;|=)', source, re.M):
        edits.append((preceding_doc(source, match.start()), match.start(), comment(field_doc(name, match['name']), match['indent'])))
    for start, end, replacement in sorted(edits, reverse=True):
        source = source[:start] + replacement + source[end:]
    declaration = re.search(r'^(?:public )?(?:final |abstract )?(?:class|enum) ' + re.escape(name) + r'\b', source, re.M)
    if declaration:
        raw, url = upstream(name)
        body = CLASS_DOCS.get(name, raw or 'Mapped ' + name + ' values from the quiche public API.')
        tags = ['@see <a href="' + url + '">quiche 0.30.1 upstream API</a>'] if raw else []
        start = preceding_doc(source, declaration.start())
        source = source[:start] + comment(body, tags=tags) + source[declaration.start():]
    return source


if __name__ == '__main__':
    for path in (ROOT / 'src/main/java/io/bosonnetwork/quiche').glob('*.java'):
        if re.search(r'^public (?:final )?(?:class|enum) ', path.read_text(), re.M) or path.stem == 'NativeResource':
            path.write_text(document(path.stem, path.read_text()), encoding='ascii')
