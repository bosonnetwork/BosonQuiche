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
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicInteger;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

import static org.junit.jupiter.api.Assertions.*;

@Timeout(20)
class PathAndTlsTest {
    @Test
    void rejectsWrongHostnameAndMismatchedAlpn() {
        try (Pair pair = new Pair("127.0.0.1", "boson-test", "boson-test", true, "wrong.invalid")) {
            assertEquals(QuicheError.TLS_FAIL, assertThrows(QuicheException.class, pair::pump).error());
        }

        try (Pair pair = new Pair("127.0.0.1", "client-protocol", "server-protocol", true, "localhost")) {
            assertEquals(QuicheError.TLS_FAIL, assertThrows(QuicheException.class, pair::pump).error());
        }
    }

    @Test
    void pathProbeEventsMigrationAndConnectionIds() {
        try (Pair pair = new Pair()) {
            pair.handshake();
            for (int i = 0; i < 2; i++) {
                assertTrue(pair.client.newScid(Pair.cid(), new byte[16], false) > 0);
                assertTrue(pair.server.newScid(Pair.cid(), new byte[16], false) > 0);
            }

            pair.pump();
            assertTrue(pair.client.availableDcids() > 0);
            assertTrue(pair.client.activeScids() > 1);
            InetSocketAddress migrated = new InetSocketAddress("127.0.0.1", 40002);
            pair.client.probePath(migrated, pair.serverAddress);
            pair.pump();
            assertTrue(pair.client.isPathValidated(migrated, pair.serverAddress));
            boolean validated = false;
            PathEvent event;
            while ((event = pair.client.pathEventNext()) != null) {
                if (event.type == PathEventType.VALIDATED) {
                    assertEquals(migrated, event.local);
                    assertEquals(pair.serverAddress, event.peer);
                    validated = true;
                }
            }

            assertTrue(validated);
            pair.client.migrate(migrated, pair.serverAddress);
            pair.client.streamSend(0, Pair.data(new byte[]{6, 7}), true);
            pair.pump();
            ByteBuffer out = ByteBuffer.allocateDirect(32);
            assertNotNull(pair.server.streamRecv(0, out));
            assertArrayEquals(new byte[]{6, 7}, Pair.take(out));
            assertTrue(pair.client.sendQuantumOnPath(migrated, pair.serverAddress) > 0);
            assertTrue(pair.client.paths(migrated).length > 0);
            pair.client.sendAckElicitingOnPath(migrated, pair.serverAddress);
            pair.pump();
            pair.client.migrateSource(pair.clientAddress);
            pair.client.sendAckEliciting();
            pair.pump();
            assertTrue(pair.client.stats().pathsCount >= 2);
            while (pair.server.pathEventNext() != null) {
                /* Exercise copied event ownership. */
            }

            assertNotNull(pair.client.retiredSourceIds());
            assertTrue(pair.client.retiredScids() >= 0);
            assertTrue(pair.client.scidsLeft() >= 0);
        }
    }

    @Test
    void keylogQlogSessionsAndNativeLogger() throws Exception {
        AtomicInteger logs = new AtomicInteger();
        Quiche.enableDebugLogging(line -> logs.incrementAndGet());
        assertThrows(IllegalStateException.class, () -> Quiche.enableDebugLogging(line -> {
        }));
        java.nio.file.Path directory = java.nio.file.Files.createTempDirectory("quiche-logs-");

        try (Pair pair = new Pair()) {
            assertTrue(pair.client.setQlogPath(directory.resolve("client.qlog").toString(), "test", "JNI test"));
            assertTrue(pair.client.setKeylogPath(directory.resolve("keys.log").toString()));
            pair.handshake();
            assertTrue(logs.get() > 0);
            assertTrue(pair.client.session().length > 0);

            try (Config config = Pair.config("boson-test");
                    Connection resumed = Connection.connect("localhost", Pair.cid(), pair.clientAddress,
                            pair.serverAddress, config)) {
                resumed.setSession(pair.client.session());
                assertNotNull(resumed.send(ByteBuffer.allocateDirect(1350)));
                assertThrows(QuicheException.class, () -> resumed.setSession(new byte[]{0}));
            }
        } finally {
            try (java.util.stream.Stream<java.nio.file.Path> files = java.nio.file.Files.list(directory)) {
                for (java.nio.file.Path file : (Iterable<java.nio.file.Path>) files::iterator)
                    java.nio.file.Files.delete(file);
            }

            java.nio.file.Files.delete(directory);
        }
    }

    @Test
    void tamperedPacketIsDroppedAndValidPacketStillWorks() {
        try (Pair pair = new Pair()) {
            pair.handshake();
            pair.client.dgramSend(Pair.data("payload".getBytes(StandardCharsets.US_ASCII)));
            ByteBuffer packet = ByteBuffer.allocateDirect(1350);
            SendInfo info = pair.client.send(packet);
            assertNotNull(info);
            packet.flip();
            ByteBuffer tampered = ByteBuffer.allocateDirect(packet.remaining());
            tampered.put(packet.duplicate()).flip();
            int last = tampered.limit() - 1;
            tampered.put(last, (byte) (tampered.get(last) ^ 1));
            pair.server.recv(tampered, new RecvInfo(info.from, info.to));
            assertEquals(-1, pair.server.dgramRecv(ByteBuffer.allocateDirect(64)));
            pair.server.recv(packet, new RecvInfo(info.from, info.to));
            ByteBuffer out = ByteBuffer.allocateDirect(64);
            assertEquals(7, pair.server.dgramRecv(out));
            assertArrayEquals("payload".getBytes(StandardCharsets.US_ASCII), Pair.take(out));
        }
    }
}
