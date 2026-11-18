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

import java.net.Inet6Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.ByteBuffer;
import java.util.Locale;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class NativePortabilityTest {
    @Test
    void nativeSocketMetadataPreservesIpv4HighPorts() throws Exception {
        checkAddresses(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), 65535),
                new InetSocketAddress(InetAddress.getByName("127.0.0.2"), 65432));
    }

    @Test
    void nativeSocketMetadataPreservesIpv6ScopesAndHighPorts() throws Exception {
        byte[] local = InetAddress.getByName("fe80::1").getAddress();
        byte[] peer = InetAddress.getByName("fe80::2").getAddress();
        checkAddresses(new InetSocketAddress(Inet6Address.getByAddress(null, local, 7), 65535),
                new InetSocketAddress(Inet6Address.getByAddress(null, peer, 9), 65432));
    }

    private static void checkAddresses(InetSocketAddress local, InetSocketAddress peer) {
        try (Config config = Pair.config("boson-test");
                Connection connection = Connection.connect("localhost", Pair.cid(), local, peer, config)) {
            SendInfo info = connection.send(ByteBuffer.allocateDirect(1350));
            assertNotNull(info);
            assertEquals(local, info.from);
            assertEquals(peer, info.to);
            if (local.getAddress() instanceof Inet6Address) {
                assertEquals(7, ((Inet6Address) info.from.getAddress()).getScopeId());
                assertEquals(9, ((Inet6Address) info.to.getAddress()).getScopeId());
            }

            String os = System.getProperty("os.name").toLowerCase(Locale.ROOT);
            if (os.contains("mac") || os.startsWith("windows")) {
                assertEquals(0, info.at.seconds);
                assertEquals(0, info.at.nanoseconds);
                assertEquals(0, info.delayNanos);
            } else {
                assertTrue(info.at.seconds > 0);
                assertTrue(info.at.nanoseconds >= 0 && info.at.nanoseconds < 1_000_000_000L);
                assertTrue(info.delayNanos >= 0);
            }
        }
    }
}

