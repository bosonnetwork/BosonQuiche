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
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.locks.LockSupport;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import static org.junit.jupiter.api.Assertions.*;

@Timeout(20)
class ConnectionTest {
    @ParameterizedTest
    @ValueSource(strings = {"127.0.0.1", "::1"})
    void verifiedHandshakeAndBidirectionalStreams(String host) {
        try (Pair pair = new Pair(host, "boson-test", true)) {
            pair.handshake();
            assertFalse(pair.client.isServer());
            assertTrue(pair.server.isServer());
            assertArrayEquals("boson-test".getBytes(StandardCharsets.US_ASCII), pair.client.applicationProto());
            assertArrayEquals("localhost".getBytes(StandardCharsets.US_ASCII), pair.server.serverName());
            assertTrue(pair.client.peerCert().length > 0);
            assertFalse(pair.client.isResumed());
            assertFalse(pair.client.isInEarlyData());
            assertNull(pair.client.peerError());
            assertEquals(pair.clientAddress, pair.client.pathStats(0).localAddress);
            assertEquals(pair.serverAddress, pair.client.pathStats(0).peerAddress);
            byte[] payload = new byte[32768];
            Arrays.fill(payload, (byte) 0x8a);
            ByteBuffer input = Pair.data(payload);
            int accepted = pair.client.streamSend(0, input, true);
            assertTrue(accepted > 0 && accepted < payload.length, "Exercise an actual partial native stream write");
            pair.client.streamPriority(0, 2, true);
            pair.pump();
            while (input.hasRemaining()) {
                int before = input.position();
                pair.client.streamSend(0, input, true);
                pair.pump();
                assertTrue(input.position() > before, "Stream must progress after peer ACKs");
            }

            assertTrue(pair.server.streamReadable(0));
            assertTrue(pair.server.isReadable());
            assertTrue(Arrays.stream(pair.server.readable()).anyMatch(id -> id == 0));
            ByteBuffer received = ByteBuffer.allocateDirect(payload.length);
            StreamResult result = pair.server.streamRecv(0, received);
            assertNotNull(result);
            assertTrue(result.fin);
            assertArrayEquals(payload, Pair.take(received));
            assertTrue(pair.server.streamFinished(0));
            pair.server.streamSend(0, Pair.data(new byte[]{9, 8, 7}), true);
            pair.pump();
            received.clear();
            result = pair.client.streamRecv(0, received);
            assertNotNull(result);
            assertTrue(result.fin);
            assertArrayEquals(new byte[]{9, 8, 7}, Pair.take(received));
            assertEquals(QuicheError.INVALID_STREAM_STATE,
                    assertThrows(QuicheException.class, () -> pair.client.streamRecv(0, received.clear())).error());
            assertTrue(pair.client.stats().sent > 0);
            assertTrue(pair.client.stats().recv > 0);
            assertTrue(pair.client.stats().sentBytes > 0);
            assertEquals(20, pair.client.peerTransportParams().peerInitialMaxStreamsBidi);
            assertTrue(pair.client.pathStats(0).rtt > 0);
            assertTrue(pair.client.timeoutAsNanos() > 0);
            assertTrue(pair.client.maxSendUdpPayloadSize() >= 1200);
            assertTrue(pair.client.sendQuantum() > 0);
            assertTrue(pair.client.peerStreamsLeftBidi() > 0);
            assertTrue(pair.client.peerStreamsLeftUni() > 0);
            assertTrue(pair.client.traceId().length > 0);
            assertTrue(pair.client.sourceId().length > 0);
            assertTrue(pair.client.destinationId().length > 0);
            assertTrue(pair.client.sourceIds().length > 0);
            assertTrue(pair.client.paths(pair.clientAddress).length > 0);
        }
    }

    @Test
    void datagramsQueuesPurgeAndCallbacks() {
        try (Pair pair = new Pair()) {
            pair.handshake();
            assertTrue(pair.client.dgramMaxWritableLen() > 0);
            assertEquals(-1, pair.server.dgramRecv(ByteBuffer.allocateDirect(128)));
            pair.client.dgramSend(Pair.data(new byte[]{1}));
            pair.client.dgramSend(Pair.data(new byte[]{2}));
            assertEquals(2, pair.client.dgramSendQueueLen());
            pair.client.dgramPurgeOutgoing(data -> data[0] == 1);
            assertEquals(1, pair.client.dgramSendQueueLen());
            assertThrows(IllegalStateException.class, () -> pair.client.dgramPurgeOutgoing(data -> {
                pair.client.close();

                return false;
            }));
            assertFalse(pair.client.isDisposed());
            RuntimeException error = new RuntimeException("predicate failed");
            assertSame(error, assertThrows(RuntimeException.class, () -> pair.client.dgramPurgeOutgoing(data -> {
                throw error;
            })));
            pair.pump();
            assertEquals(1, pair.server.dgramRecvQueueLen());
            assertEquals(1, pair.server.dgramRecvFrontLen());
            ByteBuffer out = ByteBuffer.allocateDirect(128);
            assertEquals(1, pair.server.dgramRecv(out));
            assertArrayEquals(new byte[]{2}, Pair.take(out));
            assertEquals(0, pair.server.dgramRecvQueueByteSize());
            assertEquals(0, pair.client.dgramSendQueueByteSize());
            assertFalse(pair.client.isDgramSendQueueFull());
            assertFalse(pair.server.isDgramRecvQueueFull());
        }
    }

    @Test
    void rejectsUntrustedCertificate() {
        try (Pair pair = new Pair("127.0.0.1", "boson-test", false)) {
            QuicheException error = assertThrows(QuicheException.class, pair::pump);
            assertEquals(QuicheError.TLS_FAIL, error.error());
            assertFalse(pair.client.isEstablished());
        }
    }

    @Test
    void closeErrorsAndStreamReset() {
        try (Pair pair = new Pair()) {
            pair.handshake();
            pair.client.streamSend(0, Pair.data(new byte[]{1, 2}), false);
            pair.pump();
            pair.client.streamShutdown(0, Shutdown.WRITE, 42);
            pair.pump();
            QuicheException error = assertThrows(QuicheException.class,
                    () -> pair.server.streamRecv(0, ByteBuffer.allocateDirect(32)));
            assertEquals(QuicheError.STREAM_RESET, error.error());
            assertEquals(42, error.streamErrorCode());
            pair.client.close(true, 123, new byte[]{4, 5});
            pair.pump();
            assertNotNull(pair.client.localError());
            assertNotNull(pair.server.peerError());
            assertTrue(pair.server.peerError().application);
            assertEquals(123, pair.server.peerError().code);
            assertArrayEquals(new byte[]{4, 5}, pair.server.peerError().reason());
            assertTrue(pair.server.isDraining());
        }
    }

    @Test
    void timerDrivesRecoveryAfterLostInitial() {
        try (Config config = Pair.config("boson-test");
                Connection client = Connection.connect("localhost", Pair.cid(), new java.net.InetSocketAddress(
                        "127.0.0.1", 10000), new java.net.InetSocketAddress("127.0.0.1", 10001), config)) {
            ByteBuffer packet = ByteBuffer.allocateDirect(1350);
            assertNotNull(client.send(packet));
            while (client.send(packet.clear()) != null) {
                /* Drop all handshake datagrams. */
            }

            long timeout = client.timeoutAsNanos();
            assertTrue(timeout > 0);
            LockSupport.parkNanos(timeout + 5_000_000);
            client.onTimeout();
            assertNotNull(client.send(packet.clear()));
        }
    }

    @Test
    void idleTimeoutAndConcurrentDispose() throws InterruptedException {
        try (Config config = Pair.config("boson-test");
                Connection client = Connection.connect("localhost", Pair.cid(), new java.net.InetSocketAddress(
                        "127.0.0.1", 10000), new java.net.InetSocketAddress("127.0.0.1", 10001), config)) {
            client.setMaxIdleTimeout(5);
            ByteBuffer packet = ByteBuffer.allocateDirect(1350);
            while (client.send(packet.clear()) != null) {
                /* Drop packets to exercise idle expiry. */
            }

            long deadline = System.nanoTime() + 5_000_000_000L;
            while (!client.isClosed() && System.nanoTime() < deadline) {
                LockSupport.parkNanos(client.timeoutAsNanos() + 5_000_000);
                client.onTimeout();
            }

            assertTrue(client.isClosed());
            assertTrue(client.isTimedOut());
        }

        try (Pair pair = new Pair()) {
            pair.handshake();
            AtomicReference<Throwable> failure = new AtomicReference<>();
            CountDownLatch started = new CountDownLatch(1);
            Thread reader = new Thread(() -> {
                started.countDown();

                try {
                    for (int i = 0; i < 10000; i++)
                        pair.client.stats();
                } catch (IllegalStateException expected) {
                    /* Disposal raced with a query. */
                } catch (Throwable unexpected) {
                    failure.set(unexpected);
                }
            });
            reader.start();
            started.await();
            pair.client.close();
            reader.join();
            assertNull(failure.get());
            assertThrows(IllegalStateException.class, pair.client::stats);
        }
    }

    @Test
    void buffersAndAddressesAreCheckedBeforeNativeCalls() {
        try (Pair pair = new Pair()) {
            assertThrows(IllegalArgumentException.class, () -> pair.client.recv(ByteBuffer.allocateDirect(100)
                    .asReadOnlyBuffer(), new RecvInfo(pair.serverAddress, pair.clientAddress)));
            assertThrows(IllegalArgumentException.class, () -> pair.client.send(ByteBuffer.allocate(100)));
            assertThrows(IllegalArgumentException.class,
                    () -> new RecvInfo(java.net.InetSocketAddress.createUnresolved("invalid.test", 10),
                            pair.clientAddress));
            assertThrows(IllegalArgumentException.class, () -> pair.client.newScid(new byte[21], new byte[16], false));
            ByteBuffer tooSmall = ByteBuffer.allocateDirect(20);
            assertNull(pair.server.send(tooSmall));
            assertEquals(0, tooSmall.position());
        }
    }
}
