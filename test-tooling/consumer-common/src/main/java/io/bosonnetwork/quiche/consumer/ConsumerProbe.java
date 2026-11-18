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

package io.bosonnetwork.quiche.consumer;

import java.net.InetSocketAddress;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.security.SecureRandom;
import java.util.Arrays;

import io.bosonnetwork.quiche.Config;
import io.bosonnetwork.quiche.Connection;
import io.bosonnetwork.quiche.H3Config;
import io.bosonnetwork.quiche.H3Connection;
import io.bosonnetwork.quiche.H3Event;
import io.bosonnetwork.quiche.H3EventType;
import io.bosonnetwork.quiche.H3Header;
import io.bosonnetwork.quiche.H3Priority;
import io.bosonnetwork.quiche.PacketHeader;
import io.bosonnetwork.quiche.PacketType;
import io.bosonnetwork.quiche.Quiche;
import io.bosonnetwork.quiche.QuicheError;
import io.bosonnetwork.quiche.QuicheException;
import io.bosonnetwork.quiche.RecvInfo;
import io.bosonnetwork.quiche.SendInfo;
import io.bosonnetwork.quiche.StreamResult;

/** Exercises the published API and native library with no test framework. */
public final class ConsumerProbe implements AutoCloseable {
    private final Connection client;
    private final Connection server;

    private ConsumerProbe(Path certificates) {
        InetSocketAddress local = new InetSocketAddress("127.0.0.1", 40000);
        InetSocketAddress remote = new InetSocketAddress("127.0.0.1", 40001);
        try (Config clientConfig = config(); Config serverConfig = config()) {
            String certificate = certificates.resolve("server-cert.pem").toString();
            serverConfig.loadCertChainFromPemFile(certificate)
                    .loadPrivKeyFromPemFile(certificates.resolve("server-key.pem").toString());
            clientConfig.verifyPeer(true).loadVerifyLocationsFromFile(certificate);
            byte[] id = new byte[16];
            new SecureRandom().nextBytes(id);
            client = Connection.connect("localhost", id, local, remote, clientConfig);
            ByteBuffer packet = ByteBuffer.allocateDirect(1350);
            SendInfo info = client.send(packet);
            check(info != null && info.at != null, "initial send metadata");
            packet.flip();
            PacketHeader header = Quiche.headerInfo(packet, 16);
            check(header.type == PacketType.INITIAL, "initial packet header");
            server = Connection.accept(header.destinationId(), null, remote, local, serverConfig);
            server.recv(packet, new RecvInfo(info.from, info.to));
        }
    }

    private static Config config() {
        return new Config().setApplicationProtos("h3").setMaxIdleTimeout(30_000)
                .setMaxRecvUdpPayloadSize(1350).setMaxSendUdpPayloadSize(1350)
                .setInitialMaxData(1_000_000).setInitialMaxStreamDataBidiLocal(256_000)
                .setInitialMaxStreamDataBidiRemote(256_000).setInitialMaxStreamDataUni(256_000)
                .setInitialMaxStreamsBidi(20).setInitialMaxStreamsUni(20)
                .setActiveConnectionIdLimit(4).enablePacing(false).enableDgram(true, 16, 16);
    }

    /** Verifies TLS, direct buffers, native snapshots and HTTP/3 JNI callbacks. */
    public static void run(Path certificates) {
        check("0.30.1".equals(Quiche.version()), "upstream version");
        try {
            Quiche.putVarint(ByteBuffer.allocateDirect(1), 1000);
            throw new AssertionError("Missing native exception");
        } catch (QuicheException expected) {
            check(expected.error() == QuicheError.BUFFER_TOO_SHORT, "native exception type");
        }

        ByteBuffer varint = ByteBuffer.allocateDirect(32);
        varint.position(5).limit(24);
        ByteBuffer slice = varint.slice();
        Quiche.putVarint(slice, 123456);
        slice.flip();
        check(Quiche.getVarint(slice) == 123456, "direct buffer slice");
        H3Priority priority = H3Priority.parse("u=1, i".getBytes(StandardCharsets.US_ASCII));
        check(priority.urgency == 1 && priority.incremental, "native HTTP/3 priority");

        try (ConsumerProbe peers = new ConsumerProbe(certificates)) {
            peers.pump();
            check(peers.client.isEstablished() && peers.server.isEstablished(), "TLS handshake");
            byte[] data = {1, 2, 3};
            check(peers.client.streamSend(0, data(data), true) == data.length, "stream send");
            peers.pump();
            ByteBuffer received = ByteBuffer.allocateDirect(32);
            StreamResult result = peers.server.streamRecv(0, received);
            check(result != null && result.bytes == data.length && result.fin, "stream result");
            check(Arrays.equals(data, take(received)), "stream bytes");
            check(peers.client.dgramSend(data(data)) == data.length, "datagram send");
            peers.pump();
            received.clear();
            check(peers.server.dgramRecv(received) == data.length, "datagram receive");
            check(Arrays.equals(data, take(received)), "datagram bytes");
            check(peers.client.stats().sent > 0, "native statistics");
            check(peers.client.pathStats(0).active, "native path statistics");
            check(peers.client.peerTransportParams().peerInitialMaxData > 0, "transport parameters");
        }

        try (ConsumerProbe peers = new ConsumerProbe(certificates); H3Config config = new H3Config()) {
            peers.pump();
            try (H3Connection client = H3Connection.withTransport(peers.client, config);
                    H3Connection server = H3Connection.withTransport(peers.server, config)) {
                peers.pump();
                client.poll();
                server.poll();
                long id = client.sendRequest(new H3Header[]{new H3Header(":method", "GET"),
                        new H3Header(":scheme", "https"), new H3Header(":authority", "localhost"),
                        new H3Header(":path", "/consumer")}, true);
                peers.pump();
                H3Event event = server.poll();
                check(event != null && event.id == id && event.type == H3EventType.HEADERS,
                        "native HTTP/3 event");
                check(event.headers().stream().anyMatch(h -> h.nameAsString().equals(":path")
                        && h.valueAsString().equals("/consumer")), "native HTTP/3 headers");
                check(client.stats().qpackEncoderStreamRecvBytes >= 0, "native HTTP/3 statistics");
            }
        }
    }

    private void pump() {
        for (int round = 0; round < 256; round++) {
            if (transfer(client, server) + transfer(server, client) == 0)
                return;
        }

        throw new AssertionError("Packet pump did not quiesce");
    }

    private static int transfer(Connection from, Connection to) {
        for (int count = 0; count < 1024; count++) {
            ByteBuffer packet = ByteBuffer.allocateDirect(1350);
            SendInfo info = from.send(packet);
            if (info == null)
                return count;

            check(info.bytes == packet.position() && info.at != null, "send metadata");
            packet.flip();
            to.recv(packet, new RecvInfo(info.from, info.to));
        }

        throw new AssertionError("Too many packets");
    }

    private static ByteBuffer data(byte[] data) {
        ByteBuffer buffer = ByteBuffer.allocateDirect(data.length);
        buffer.put(data).flip();
        return buffer;
    }

    private static byte[] take(ByteBuffer buffer) {
        buffer.flip();
        byte[] bytes = new byte[buffer.remaining()];
        buffer.get(bytes);
        return bytes;
    }

    private static void check(boolean condition, String operation) {
        if (!condition)
            throw new AssertionError(operation);
    }

    @Override
    public void close() {
        server.close();
        client.close();
    }

    public static void main(String[] args) {
        run(Path.of(args[0]));
        System.out.println("BosonQuiche packaged consumer PASS");
    }
}
