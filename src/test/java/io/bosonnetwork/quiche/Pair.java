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
import java.net.URISyntaxException;
import java.nio.ByteBuffer;
import java.nio.file.Path;
import java.security.SecureRandom;

import static org.junit.jupiter.api.Assertions.*;

/** Real quiche peers; only their UDP delivery is replaced by memory copies. */
final class Pair implements AutoCloseable {
    final Connection client;
    final Connection server;
    final InetSocketAddress clientAddress;
    final InetSocketAddress serverAddress;

    Pair() {
        this("127.0.0.1", "boson-test", true);
    }

    Pair(String host, String protocol, boolean trust) {
        this(host, protocol, protocol, trust, "localhost");
    }

    Pair(String host, String clientProtocol, String serverProtocol, boolean trust, String serverName) {
        clientAddress = new InetSocketAddress(host, 40000);
        serverAddress = new InetSocketAddress(host, 40001);

        try (Config clientConfig = config(clientProtocol); Config serverConfig = config(serverProtocol)) {
            serverConfig.loadCertChainFromPemFile(resource("server-cert.pem")).loadPrivKeyFromPemFile(
                    resource("server-key.pem"));
            clientConfig.verifyPeer(true);
            if (trust)
                clientConfig.loadVerifyLocationsFromFile(resource("server-cert.pem"));

            client = Connection.connect(serverName, cid(), clientAddress, serverAddress, clientConfig);
            ByteBuffer initial = ByteBuffer.allocateDirect(1350);
            SendInfo info = client.send(initial);
            assertNotNull(info);
            initial.flip();
            PacketHeader header = Quiche.headerInfo(initial, 16);
            assertEquals(PacketType.INITIAL, header.type);
            server = Connection.accept(header.destinationId(), null, serverAddress, clientAddress, serverConfig);
            server.recv(initial, new RecvInfo(info.from, info.to));
        }
    }

    static String resource(String name) {
        try {
            return Path.of(Pair.class.getResource("/" + name).toURI()).toString();
        } catch (URISyntaxException e) {
            throw new AssertionError(e);
        }
    }

    static byte[] cid() {
        byte[] id = new byte[16];
        new SecureRandom().nextBytes(id);

        return id;
    }

    static Config config(String protocol) {
        return new Config()
                .setApplicationProtos(protocol)
                .setMaxIdleTimeout(30_000)
                .setMaxRecvUdpPayloadSize(1350)
                .setMaxSendUdpPayloadSize(1350)
                .setInitialMaxData(1_000_000)
                .setInitialMaxStreamDataBidiLocal(256_000)
                .setInitialMaxStreamDataBidiRemote(256_000)
                .setInitialMaxStreamDataUni(256_000)
                .setInitialMaxStreamsBidi(20)
                .setInitialMaxStreamsUni(20)
                .setActiveConnectionIdLimit(4)
                .enablePacing(false)
                .enableDgram(true, 16, 16);
    }

    void handshake() {
        pump();
        assertTrue(client.isEstablished(), "client handshake");
        assertTrue(server.isEstablished(), "server handshake");
    }

    void pump() {
        for (int round = 0; round < 256; round++) {
            int count = transfer(client, server) + transfer(server, client);
            if (count == 0)
                return;
        }

        fail("Packet pump did not quiesce");
    }

    static int transfer(Connection from, Connection to) {
        for (int count = 0; count < 1024; count++) {
            ByteBuffer packet = ByteBuffer.allocateDirect(1350);
            SendInfo info = from.send(packet);
            if (info == null)
                return count;

            assertEquals(info.bytes, packet.position());
            assertTrue(info.bytes > 0);
            assertNotNull(info.at);
            assertTrue(info.delayNanos >= 0);
            packet.flip();
            to.recv(packet, new RecvInfo(info.from, info.to));
        }

        throw new AssertionError("Too many packets");
    }

    static ByteBuffer data(byte[] data) {
        ByteBuffer out = ByteBuffer.allocateDirect(data.length);
        out.put(data).flip();

        return out;
    }

    static byte[] take(ByteBuffer buffer) {
        buffer.flip();
        byte[] out = new byte[buffer.remaining()];
        buffer.get(out);

        return out;
    }

    @Override
    public void close() {
        server.close();
        client.close();
    }
}
