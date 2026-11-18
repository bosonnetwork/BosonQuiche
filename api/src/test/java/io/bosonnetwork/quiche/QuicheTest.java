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
import java.util.ArrayList;
import java.util.List;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import static org.junit.jupiter.api.Assertions.*;

class QuicheTest {
    @Test
    void versionAndNativeEnumValuesMatch() {
        assertEquals("0.30.1", Quiche.version());
        assertTrue(Quiche.versionIsSupported(1));
        assertFalse(Quiche.versionIsSupported(0xdeadbeefL));
        List<Integer> expected = new ArrayList<>();
        for (QuicheError value : QuicheError.values())
            expected.add(value.code());

        for (CongestionControlAlgorithm value : CongestionControlAlgorithm.values())
            expected.add(value.code());

        for (Shutdown value : Shutdown.values())
            expected.add(value.code());

        for (PathEventType value : PathEventType.values())
            expected.add(value.code());

        for (H3Error value : H3Error.values())
            expected.add(value.code());

        for (H3EventType value : H3EventType.values())
            expected.add(value.code());

        assertArrayEquals(expected.stream().mapToInt(Integer::intValue).toArray(), Native.enumValues());
    }

    @ParameterizedTest
    @ValueSource(longs = {0, 63, 64, 16383, 16384, 1073741823L, 1073741824L, 4611686018427387903L})
    void varintsRespectPositionLimitAndSlices(long value) {
        ByteBuffer backing = ByteBuffer.allocateDirect(32);
        backing.position(5).limit(25);
        ByteBuffer buffer = backing.slice();
        buffer.position(3);
        int bytes = Quiche.putVarint(buffer, value);
        assertEquals(3 + bytes, buffer.position());
        buffer.limit(buffer.position()).position(3);
        assertEquals(value, Quiche.getVarint(buffer));
        assertEquals(buffer.limit(), buffer.position());
    }

    @Test
    void invalidInputsNeverReachUnsafeNativeOperations() {
        assertThrows(IllegalArgumentException.class, () -> Quiche.putVarint(ByteBuffer.allocate(8), 1));
        assertThrows(IllegalArgumentException.class,
                () -> Quiche.putVarint(ByteBuffer.allocateDirect(8).asReadOnlyBuffer(), 1));
        assertThrows(IllegalArgumentException.class, () -> Quiche.putVarint(ByteBuffer.allocateDirect(8), -1));
        ByteBuffer shortBuffer = ByteBuffer.allocateDirect(1);
        assertEquals(QuicheError.BUFFER_TOO_SHORT,
                assertThrows(QuicheException.class, () -> Quiche.putVarint(shortBuffer, 1000)).error());
        assertEquals(0, shortBuffer.position());
        assertThrows(QuicheException.class, () -> new Config(0xdeadbeefL));

        try (Config config = new Config()) {
            assertThrows(IllegalArgumentException.class, () -> config.setApplicationProtos(new byte[]{4, 1}));
            assertThrows(IllegalArgumentException.class, () -> config.setApplicationProtos(new byte[]{0}));
            assertThrows(IllegalArgumentException.class, () -> config.setStatelessResetToken(new byte[15]));
            assertThrows(IllegalArgumentException.class, () -> config.setTicketKey(new byte[47]));
            assertThrows(IllegalArgumentException.class, () -> config.setMaxIdleTimeout(-1));
            assertThrows(IllegalArgumentException.class, () -> config.loadCertChainFromPemFile("a\0b"));
            assertThrows(QuicheException.class, () -> config.loadCertChainFromPemFile("does-not-exist.pem"));
        }
    }

    @Test
    void versionNegotiationRetryAndMalformedHeader() {
        byte[] scid = Pair.cid();
        byte[] dcid = Pair.cid();
        byte[] next = Pair.cid();
        ByteBuffer packet = ByteBuffer.allocateDirect(1350);
        Quiche.negotiateVersion(scid, dcid, packet);
        packet.flip();
        PacketHeader header = Quiche.headerInfo(packet, 16);
        assertEquals(PacketType.VERSION_NEGOTIATION, header.type);
        assertEquals(0, header.version);
        assertArrayEquals(dcid, header.sourceId());
        assertArrayEquals(scid, header.destinationId());
        packet.clear();
        byte[] token = {1, 2, 3};
        Quiche.retry(scid, dcid, next, token, 1, packet);
        packet.flip();
        header = Quiche.headerInfo(packet, 16);
        assertEquals(PacketType.RETRY, header.type);
        assertArrayEquals(next, header.sourceId());
        assertArrayEquals(token, header.token());
        ByteBuffer invalid = ByteBuffer.allocateDirect(1);
        invalid.put((byte) 0xff).flip();
        assertThrows(QuicheException.class, () -> Quiche.headerInfo(invalid, 16));
    }

    @Test
    void configurationAndDisposal() {
        Config config = new Config();
        config.setCcAlgorithm(CongestionControlAlgorithm.RENO).setCcAlgorithm(CongestionControlAlgorithm.CUBIC)
                .setCcAlgorithm(CongestionControlAlgorithm.BBR2_GCONGESTION).setCcAlgorithmName("cubic")
                .setCurvesList("X25519:P-256").setInitialCongestionWindowPackets(12)
                .setUncheckedCongestionWindow(64000).setMaxOutstandingSentPackets(22000).setAckDelayExponent(3)
                .setMaxAckDelay(25).grease(false).discoverPmtu(true).setMaxAmplificationFactor(3).enableHystart(true)
                .enablePacing(true).setEnableCubicIdleRestartFix(true).setMaxPacingRate(1000000)
                .setMaxConnectionWindow(1000000).setMaxStreamWindow(100000).setDisableDcidReuse(true)
                .setDisableActiveMigration(false).setTicketKey(new byte[48]);
        config.close();
        config.close();
        assertTrue(config.isDisposed());
        assertThrows(IllegalStateException.class, () -> config.verifyPeer(false));
        assertThrows(IllegalStateException.class, () -> Connection.connect(null, Pair.cid(),
                new java.net.InetSocketAddress("127.0.0.1", 1), new java.net.InetSocketAddress("127.0.0.1", 2), config));
    }
}
