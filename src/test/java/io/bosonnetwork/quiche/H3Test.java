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

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

import static org.junit.jupiter.api.Assertions.*;

@Timeout(20)
class H3Test {
    @Test
    void requestResponseHeadersBodySettingsAndGoaway() {
        try (Pair pair = new Pair("127.0.0.1", "h3", true);
                H3Config config = new H3Config().setMaxFieldSectionSize(65536).setQpackMaxTableCapacity(4096)
                        .setQpackBlockedStreams(16).enableExtendedConnect(true).setMaxPriorityUpdateSize(1024)) {
            pair.handshake();

            try (H3Connection client = H3Connection.withTransport(pair.client, config);
                    H3Connection server = H3Connection.withTransport(pair.server, config)) {
                pair.pump();
                client.poll();
                server.poll();
                assertTrue(client.extendedConnectEnabledByPeer());
                assertTrue(server.extendedConnectEnabledByPeer());
                assertFalse(client.peerSettings().isEmpty());
                assertTrue(client.dgramEnabledByPeer());
                long id = client.sendRequest(new H3Header[]{new H3Header(":method", "POST"),
                        new H3Header(":scheme", "https"), new H3Header(":authority", "localhost"),
                        new H3Header(":path", "/test"), new H3Header("content-length", "3")}, false);
                pair.pump();
                H3Event event = server.poll();
                assertNotNull(event);
                assertEquals(H3EventType.HEADERS, event.type);
                assertEquals(id, event.id);
                assertTrue(event.hasMoreFrames);
                assertTrue(event.headers().stream()
                        .anyMatch(h -> h.nameAsString().equals(":method") && h.valueAsString().equals("POST")));
                client.sendPriorityUpdateForRequest(id, new H3Priority(1, false));
                pair.pump();
                event = server.poll();
                assertNotNull(event);
                assertEquals(H3EventType.PRIORITY_UPDATE, event.type);
                assertNotNull(server.takeLastPriorityUpdate(id));
                assertNull(server.takeLastPriorityUpdate(id));
                assertEquals(3, client.sendBody(id, Pair.data(new byte[]{1, 2, 3}), true));
                pair.pump();
                event = server.poll();
                assertNotNull(event);
                assertEquals(H3EventType.DATA, event.type);
                ByteBuffer body = ByteBuffer.allocateDirect(128);
                assertEquals(3, server.recvBody(id, body));
                assertArrayEquals(new byte[]{1, 2, 3}, Pair.take(body));
                event = server.poll();
                assertNotNull(event);
                assertEquals(H3EventType.FINISHED, event.type);
                server.sendResponseWithPriority(id, new H3Header[]{new H3Header(":status", "200"),
                        new H3Header("content-length", "2")}, new H3Priority(2, true), false);
                assertEquals(2, server.sendBody(id, Pair.data(new byte[]{4, 5}), false));
                server.sendAdditionalHeaders(id, new H3Header[]{new H3Header("x-trailer", "done")}, true, true);
                pair.pump();
                event = client.poll();
                assertNotNull(event);
                assertEquals(H3EventType.HEADERS, event.type);
                event = client.poll();
                assertNotNull(event);
                assertEquals(H3EventType.DATA, event.type);
                body.clear();
                assertEquals(2, client.recvBody(id, body));
                assertArrayEquals(new byte[]{4, 5}, Pair.take(body));
                event = client.poll();
                assertNotNull(event);
                assertEquals(H3EventType.HEADERS, event.type);
                event = client.poll();
                assertNotNull(event);
                assertEquals(H3EventType.FINISHED, event.type);
                assertTrue(client.stats().qpackEncoderStreamRecvBytes >= 0);
                server.sendGoaway(4);
                pair.pump();
                event = client.poll();
                assertNotNull(event);
                assertEquals(H3EventType.GOAWAY, event.type);
                assertEquals(4, event.id);
            }
        }
    }

    @Test
    void prioritiesAndParentDisposal() {
        H3Priority priority = H3Priority.parse("u=1, i".getBytes(StandardCharsets.US_ASCII));
        assertEquals(1, priority.urgency);
        assertTrue(priority.incremental);
        assertThrows(IllegalArgumentException.class, () -> new H3Priority(8, false));

        try (Pair pair = new Pair("127.0.0.1", "h3", true); H3Config config = new H3Config()) {
            pair.handshake();

            try (H3Connection connection = H3Connection.withTransport(pair.client, config)) {
                pair.client.close();
                assertThrows(IllegalStateException.class, connection::poll);
            }
        }
    }
}
