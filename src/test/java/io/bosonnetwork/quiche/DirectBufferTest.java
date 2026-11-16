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
import java.util.Arrays;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class DirectBufferTest {
    @Test
    void packetDecryptionMutatesTheOriginalDirectSliceAndRespectsItsBounds() {
        try (Pair pair = new Pair()) {
            pair.handshake();
            byte[] payload = new byte[512];
            Arrays.fill(payload, (byte) 0xa7);
            ByteBuffer source = Pair.data(payload).asReadOnlyBuffer();
            assertEquals(payload.length, pair.client.streamSend(0, source, true));
            ByteBuffer backing = ByteBuffer.allocateDirect(1400);
            for (int i = 0; i < backing.capacity(); i++)
                backing.put(i, (byte) 0x5a);

            backing.position(13).limit(1380);
            ByteBuffer packet = backing.slice();
            packet.position(7).limit(1357);
            SendInfo info = pair.client.send(packet);
            assertNotNull(info);
            packet.limit(packet.position()).position(7);
            byte[] encrypted = new byte[packet.remaining()];
            packet.duplicate().get(encrypted);
            assertEquals(info.bytes, pair.server.recv(packet, new RecvInfo(info.from, info.to)));
            byte[] decrypted = new byte[info.bytes];
            packet.duplicate().position(7).get(decrypted);
            assertFalse(Arrays.equals(encrypted, decrypted),
                    "quiche must decrypt the original direct memory, not a staging copy");
            backing.clear();
            for (int i = 0; i < 20; i++)
                assertEquals((byte) 0x5a, backing.get(i));

            for (int i = 20 + info.bytes; i < backing.capacity(); i++)
                assertEquals((byte) 0x5a, backing.get(i));

            ByteBuffer out = ByteBuffer.allocateDirect(1024);
            for (int i = 0; i < out.capacity(); i++)
                out.put(i, (byte) 0x33);

            out.position(23).limit(23 + payload.length);
            StreamResult result = pair.server.streamRecv(0, out);
            assertNotNull(result);
            assertTrue(result.fin);
            assertEquals(23 + payload.length, out.position());
            out.position(23);
            byte[] received = new byte[payload.length];
            out.get(received);
            assertArrayEquals(payload, received);
            out.clear();
            assertEquals((byte) 0x33, out.get(22));
            assertEquals((byte) 0x33, out.get(23 + payload.length));
        }
    }
}
