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
 
#define _POSIX_C_SOURCE 200809L
#include <jni.h>
#include <quiche.h>
#include <arpa/inet.h>
#include <limits.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define JN(name) Java_io_bosonnetwork_quiche_Native_##name
#define PTR(type, handle) ((type *) (uintptr_t) (handle))
#define PACKAGE "io/bosonnetwork/quiche/"

static void fail(JNIEnv *env, const char *type, const char *message) {
    if ((*env)->ExceptionCheck(env)) return;
    jclass cls = (*env)->FindClass(env, type);
    if (cls) { (*env)->ThrowNew(env, cls, message); (*env)->DeleteLocalRef(env, cls); }
}

static void invalid(JNIEnv *env, const char *message) { fail(env, "java/lang/IllegalArgumentException", message); }
static void oom(JNIEnv *env) { fail(env, "java/lang/OutOfMemoryError", "Native allocation failed"); }

static jobject construct(JNIEnv *env, const char *type, const char *signature, ...) {
    if ((*env)->ExceptionCheck(env)) return NULL;
    char name[160];
    snprintf(name, sizeof(name), PACKAGE "%s", type);
    jclass cls = (*env)->FindClass(env, name);
    if (!cls) return NULL;
    jmethodID constructor = (*env)->GetMethodID(env, cls, "<init>", signature);
    jobject object = NULL;
    if (constructor) {
        va_list args; va_start(args, signature);
        object = (*env)->NewObjectV(env, cls, constructor, args);
        va_end(args);
    }
    (*env)->DeleteLocalRef(env, cls);
    return object;
}

static void quic_error(JNIEnv *env, int result, uint64_t stream_error) {
    if ((*env)->ExceptionCheck(env)) return;
    jobject error = construct(env, "QuicheException", "(IJ)V", (jint) result, (jlong) stream_error);
    if (error) { (*env)->Throw(env, error); (*env)->DeleteLocalRef(env, error); }
}

static int64_t check(JNIEnv *env, int64_t result) {
    if (result < 0) quic_error(env, (int) result, 0);
    return result;
}

static int64_t io_result(JNIEnv *env, int64_t result) {
    if (result < 0 && result != QUICHE_ERR_DONE) quic_error(env, (int) result, 0);
    return result;
}

static void h3_error(JNIEnv *env, int64_t result) {
    if (result >= 0 || (*env)->ExceptionCheck(env)) return;
    jobject error = construct(env, "H3Exception", "(I)V", (jint) result);
    if (error) { (*env)->Throw(env, error); (*env)->DeleteLocalRef(env, error); }
}

static jbyteArray bytes(JNIEnv *env, const uint8_t *data, size_t length) {
    if ((*env)->ExceptionCheck(env)) return NULL;
    if (length > INT_MAX) { oom(env); return NULL; }
    jbyteArray result = (*env)->NewByteArray(env, (jsize) length);
    if (result && length) (*env)->SetByteArrayRegion(env, result, 0, (jsize) length, (const jbyte *) data);
    return result;
}

static jlongArray longs(JNIEnv *env, const jlong *data, size_t length) {
    if ((*env)->ExceptionCheck(env)) return NULL;
    if (length > INT_MAX) { oom(env); return NULL; }
    jlongArray result = (*env)->NewLongArray(env, (jsize) length);
    if (result && length) (*env)->SetLongArrayRegion(env, result, 0, (jsize) length, data);
    return result;
}

typedef struct { uint8_t *data; size_t length; } byte_slice;

static byte_slice copy_bytes(JNIEnv *env, jbyteArray input) {
    byte_slice result = { NULL, 0 };
    if ((*env)->ExceptionCheck(env)) return result;
    if (!input) { invalid(env, "Null native byte array"); return result; }
    result.length = (size_t) (*env)->GetArrayLength(env, input);
    result.data = calloc(result.length + 1, 1);
    if (!result.data) { oom(env); return result; }
    if (result.length) (*env)->GetByteArrayRegion(env, input, 0, (jsize) result.length, (jbyte *) result.data);
    if ((*env)->ExceptionCheck(env)) { free(result.data); result.data = NULL; }
    return result;
}

static uint8_t *buffer(JNIEnv *env, jobject input, jint offset, jint length) {
    jlong capacity = (*env)->GetDirectBufferCapacity(env, input);
    void *address = (*env)->GetDirectBufferAddress(env, input);
    if (capacity < 0 || !address || offset < 0 || length < 0 || offset > capacity || length > capacity - offset) {
        invalid(env, "Invalid direct buffer range"); return NULL;
    }
    return ((uint8_t *) address) + offset;
}

static bool address(JNIEnv *env, jbyteArray input, struct sockaddr_storage *out, socklen_t *length) {
    if (!input) { invalid(env, "Missing socket address"); return false; }
    jsize count = (*env)->GetArrayLength(env, input);
    if (count != 11 && count != 23) { invalid(env, "Invalid socket address"); return false; }
    uint8_t data[23];
    (*env)->GetByteArrayRegion(env, input, 0, count, (jbyte *) data);
    if ((*env)->ExceptionCheck(env)) return false;
    int ip_length = data[0];
    if ((ip_length != 4 && ip_length != 16) || count != ip_length + 7) { invalid(env, "Invalid IP length"); return false; }
    uint16_t port = ((uint16_t) data[ip_length + 1] << 8) | data[ip_length + 2];
    memset(out, 0, sizeof(*out));
    if (ip_length == 4) {
        struct sockaddr_in *v4 = (struct sockaddr_in *) out;
        v4->sin_family = AF_INET; v4->sin_port = htons(port);
        memcpy(&v4->sin_addr, data + 1, 4); *length = sizeof(*v4);
#ifdef __APPLE__
        v4->sin_len = sizeof(*v4);
#endif
    } else {
        struct sockaddr_in6 *v6 = (struct sockaddr_in6 *) out;
        v6->sin6_family = AF_INET6; v6->sin6_port = htons(port);
        memcpy(&v6->sin6_addr, data + 1, 16);
        size_t i = (size_t) ip_length + 3;
        v6->sin6_scope_id = ((uint32_t) data[i] << 24) | ((uint32_t) data[i+1] << 16) | ((uint32_t) data[i+2] << 8) | data[i+3];
        *length = sizeof(*v6);
#ifdef __APPLE__
        v6->sin6_len = sizeof(*v6);
#endif
    }
    return true;
}

static jobject java_address(JNIEnv *env, const struct sockaddr *input) {
    if ((*env)->ExceptionCheck(env)) return NULL;
    const uint8_t *ip; int length, port, scope = 0;
    if (input->sa_family == AF_INET) {
        const struct sockaddr_in *v4 = (const struct sockaddr_in *) input;
        ip = (const uint8_t *) &v4->sin_addr; length = 4; port = ntohs(v4->sin_port);
    } else if (input->sa_family == AF_INET6) {
        const struct sockaddr_in6 *v6 = (const struct sockaddr_in6 *) input;
        ip = (const uint8_t *) &v6->sin6_addr; length = 16; port = ntohs(v6->sin6_port); scope = (int) v6->sin6_scope_id;
    } else { invalid(env, "Unknown native address family"); return NULL; }
    jbyteArray data = bytes(env, ip, (size_t) length);
    if (!data) return NULL;
    jclass cls = (*env)->FindClass(env, PACKAGE "Native");
    if (!cls) { (*env)->DeleteLocalRef(env, data); return NULL; }
    jmethodID method = (*env)->GetStaticMethodID(env, cls, "socketAddress", "([BII)Ljava/net/InetSocketAddress;");
    jobject result = NULL;
    if (method) {
        result = (*env)->CallStaticObjectMethod(env, cls, method, data, (jint) port, (jint) scope);
        if ((*env)->ExceptionCheck(env)) result = NULL;
    }
    (*env)->DeleteLocalRef(env, cls); (*env)->DeleteLocalRef(env, data);
    return result;
}

JNIEXPORT jstring JNICALL JN(version)(JNIEnv *env, jclass cls) {
    return (*env)->NewStringUTF(env, quiche_version());
}

JNIEXPORT jboolean JNICALL JN(versionIsSupported)(JNIEnv *env, jclass cls, jint version) {
    return quiche_version_is_supported((uint32_t) version); 
}

JNIEXPORT void JNICALL JN(free)(JNIEnv *env, jclass cls, jlong handle, jint type) {
    switch (type) {
        case 0: quiche_config_free(PTR(quiche_config, handle)); break;
        case 1: quiche_conn_free(PTR(quiche_conn, handle)); break;
        case 2: quiche_h3_config_free(PTR(quiche_h3_config, handle)); break;
        case 3: quiche_h3_conn_free(PTR(quiche_h3_conn, handle)); break;
        default: invalid(env, "Unknown native owner type");
    }
}

JNIEXPORT jlong JNICALL JN(configNew)(JNIEnv *env, jclass cls, jint version) {
    quiche_config *config = quiche_config_new((uint32_t) version);
    if (!config) quic_error(env, QUICHE_ERR_UNKNOWN_VERSION, 0);
    return (jlong) (uintptr_t) config;
}

JNIEXPORT void JNICALL JN(configText)(JNIEnv *env, jclass cls, jlong handle, jint option, jbyteArray text) {
    byte_slice value = copy_bytes(env, text); if (!value.data) return;
    quiche_config *config = PTR(quiche_config, handle); int result = 0;
    switch (option) {
        case 0: result = quiche_config_load_cert_chain_from_pem_file(config, (char *) value.data); break;
        case 1: result = quiche_config_load_priv_key_from_pem_file(config, (char *) value.data); break;
        case 2: result = quiche_config_load_verify_locations_from_file(config, (char *) value.data); break;
        case 3: result = quiche_config_load_verify_locations_from_directory(config, (char *) value.data); break;
        case 4: result = quiche_config_set_curves_list(config, (char *) value.data); break;
        case 5: result = quiche_config_set_cc_algorithm_name(config, (char *) value.data); break;
        default: invalid(env, "Unknown config text option");
    }
    free(value.data); check(env, result);
}

JNIEXPORT void JNICALL JN(configBytes)(JNIEnv *env, jclass cls, jlong handle, jint option, jbyteArray data) {
    byte_slice value = copy_bytes(env, data); if (!value.data) return;
    quiche_config *config = PTR(quiche_config, handle); int result = 0;
    switch (option) {
        case 0: result = quiche_config_set_application_protos(config, value.data, value.length); break;
        case 1:
            if (value.length != 16) invalid(env, "Reset token must contain 16 bytes");
            else quiche_config_set_stateless_reset_token(config, value.data);
            break;
        case 2: result = quiche_config_set_ticket_key(config, value.data, value.length); break;
        default: invalid(env, "Unknown config bytes option");
    }
    free(value.data); check(env, result);
}

JNIEXPORT void JNICALL JN(configFlag)(JNIEnv *env, jclass cls, jlong handle, jint option) {
    if (option == 0) quiche_config_log_keys(PTR(quiche_config, handle));
    else if (option == 1) quiche_config_enable_early_data(PTR(quiche_config, handle));
    else invalid(env, "Unknown config flag");
}

JNIEXPORT void JNICALL JN(configDgram)(JNIEnv *env, jclass cls, jlong handle, jboolean enabled, jint receive, jint send) {
    if (receive < 0 || send < 0) { invalid(env, "Negative queue size"); return; }
    quiche_config_enable_dgram(PTR(quiche_config, handle), enabled, (size_t) receive, (size_t) send);
}

JNIEXPORT jobject JNICALL JN(headerInfo)(JNIEnv *env, jclass cls, jobject data, jint offset, jint length, jint dcid_length) {
    uint8_t *input = buffer(env, data, offset, length); if (!input) return NULL;
    uint8_t scid[20], dcid[20], type; uint32_t version;
    size_t scid_length = 20, dcid_len = 20, token_length = (size_t) length;
    uint8_t *token = malloc(token_length ? token_length : 1); if (!token) { oom(env); return NULL; }
    int result = quiche_header_info(input, (size_t) length, (size_t) dcid_length, &version, &type,
                                   scid, &scid_length, dcid, &dcid_len, token, &token_length);
    if (check(env, result) < 0) { free(token); return NULL; }
    jbyteArray source = bytes(env, scid, scid_length), destination = bytes(env, dcid, dcid_len), tok = bytes(env, token, token_length);
    free(token);
    jobject out = construct(env, "PacketHeader", "(JI[B[B[B)V", (jlong) version, (jint) type, source, destination, tok);
    (*env)->DeleteLocalRef(env, source); (*env)->DeleteLocalRef(env, destination); (*env)->DeleteLocalRef(env, tok);
    return out;
}

JNIEXPORT jint JNICALL JN(negotiateVersion)(JNIEnv *env, jclass cls, jbyteArray source, jbyteArray destination, jobject out, jint offset, jint length) {
    uint8_t *output = buffer(env, out, offset, length); if (!output) return -1;
    byte_slice scid = copy_bytes(env, source), dcid = copy_bytes(env, destination);
    ssize_t result = -1;
    if (scid.data && dcid.data) result = quiche_negotiate_version(scid.data, scid.length, dcid.data, dcid.length, output, (size_t) length);
    free(scid.data); free(dcid.data); return (jint) check(env, result);
}

JNIEXPORT jint JNICALL JN(retry)(JNIEnv *env, jclass cls, jbyteArray source, jbyteArray destination, jbyteArray new_source, jbyteArray tok, jint version, jobject out, jint offset, jint length) {
    uint8_t *output = buffer(env, out, offset, length); if (!output) return -1;
    byte_slice scid = copy_bytes(env, source), dcid = copy_bytes(env, destination), new_scid = copy_bytes(env, new_source), token = copy_bytes(env, tok);
    ssize_t result = -1;
    if (scid.data && dcid.data && new_scid.data && token.data)
        result = quiche_retry(scid.data, scid.length, dcid.data, dcid.length, new_scid.data, new_scid.length, token.data, token.length, (uint32_t) version, output, (size_t) length);
    free(scid.data); free(dcid.data); free(new_scid.data); free(token.data); return (jint) check(env, result);
}

JNIEXPORT jlong JNICALL JN(connect)(JNIEnv *env, jclass cls, jlong config, jbyteArray name, jbyteArray source, jbyteArray original, jbyteArray local, jbyteArray peer, jboolean server) {
    struct sockaddr_storage from, to; socklen_t from_len, to_len;
    if (!address(env, local, &from, &from_len) || !address(env, peer, &to, &to_len)) return 0;
    byte_slice scid = copy_bytes(env, source), odcid = { NULL, 0 }, hostname = { NULL, 0 };
    if (original) odcid = copy_bytes(env, original);
    if (name) hostname = copy_bytes(env, name);
    quiche_conn *conn = NULL;
    if (!(*env)->ExceptionCheck(env) && scid.data) {
        if (server) conn = quiche_accept(scid.data, scid.length, odcid.data, odcid.length,
                (struct sockaddr *) &from, from_len, (struct sockaddr *) &to, to_len, PTR(quiche_config, config));
        else conn = quiche_connect((char *) hostname.data, scid.data, scid.length,
                (struct sockaddr *) &from, from_len, (struct sockaddr *) &to, to_len, PTR(quiche_config, config));
    }
    free(scid.data); free(odcid.data); free(hostname.data);
    if (!conn && !(*env)->ExceptionCheck(env)) quic_error(env, QUICHE_ERR_TLS_FAIL, 0);
    return (jlong) (uintptr_t) conn;
}

JNIEXPORT jint JNICALL JN(recv)(JNIEnv *env, jclass cls, jlong handle, jobject input, jint offset, jint length, jbyteArray from, jbyteArray to) {
    uint8_t *data = buffer(env, input, offset, length); if (!data) return -1;
    struct sockaddr_storage source, destination; socklen_t source_len, destination_len;
    if (!address(env, from, &source, &source_len) || !address(env, to, &destination, &destination_len)) return -1;
    quiche_recv_info info = { (struct sockaddr *) &source, source_len, (struct sockaddr *) &destination, destination_len };
    return (jint) io_result(env, quiche_conn_recv(PTR(quiche_conn, handle), data, (size_t) length, &info));
}

JNIEXPORT jobject JNICALL JN(send)(JNIEnv *env, jclass cls, jlong handle, jobject output, jint offset, jint length, jbyteArray from, jbyteArray to) {
    uint8_t *data = buffer(env, output, offset, length); if (!data) return NULL;
    quiche_send_info info; ssize_t result;
    if (from || to) {
        struct sockaddr_storage source, destination; socklen_t source_len = 0, destination_len = 0;
        if (from && !address(env, from, &source, &source_len)) return NULL;
        if (to && !address(env, to, &destination, &destination_len)) return NULL;
        result = quiche_conn_send_on_path(PTR(quiche_conn, handle), data, (size_t) length,
            from ? (struct sockaddr *) &source : NULL, source_len,
            to ? (struct sockaddr *) &destination : NULL, destination_len, &info);
    } else result = quiche_conn_send(PTR(quiche_conn, handle), data, (size_t) length, &info);
    if (io_result(env, result) < 0) return NULL;
    jobject source = java_address(env, (struct sockaddr *) &info.from);
    if ((*env)->ExceptionCheck(env)) return NULL;
    jobject destination = java_address(env, (struct sockaddr *) &info.to);
    jobject time = construct(env, "Timespec", "(JJ)V", (jlong) info.at.tv_sec, (jlong) info.at.tv_nsec);
    jlong delay = 0;
    if (info.at.tv_sec != 0 || info.at.tv_nsec != 0) {
        struct timespec now;
        if (clock_gettime(CLOCK_MONOTONIC, &now) == 0) {
            delay = ((jlong) info.at.tv_sec - (jlong) now.tv_sec) * 1000000000LL + info.at.tv_nsec - now.tv_nsec;
            if (delay < 0) delay = 0;
        }
    }
    jobject out = construct(env, "SendInfo", "(ILjava/net/InetSocketAddress;Ljava/net/InetSocketAddress;L" PACKAGE "Timespec;J)V",
                            (jint) result, source, destination, time, delay);
    (*env)->DeleteLocalRef(env, source); (*env)->DeleteLocalRef(env, destination); (*env)->DeleteLocalRef(env, time);
    return out;
}

JNIEXPORT jobject JNICALL JN(streamRecv)(JNIEnv *env, jclass cls, jlong handle, jlong stream, jobject output, jint offset, jint length) {
    uint8_t *data = buffer(env, output, offset, length); if (!data) return NULL;
    bool fin = false; uint64_t code = 0;
    ssize_t result = quiche_conn_stream_recv(PTR(quiche_conn, handle), (uint64_t) stream, data, (size_t) length, &fin, &code);
    if (result == QUICHE_ERR_DONE) return NULL;
    if (result < 0) { quic_error(env, (int) result, code); return NULL; }
    return construct(env, "StreamResult", "(IZ)V", (jint) result, (jboolean) fin);
}

JNIEXPORT jint JNICALL JN(streamSend)(JNIEnv *env, jclass cls, jlong handle, jlong stream, jobject input, jint offset, jint length, jboolean fin) {
    uint8_t *data = buffer(env, input, offset, length); if (!data) return -1;
    uint64_t code = 0;
    ssize_t result = quiche_conn_stream_send(PTR(quiche_conn, handle), (uint64_t) stream, data, (size_t) length, fin, &code);
    if (result < 0 && result != QUICHE_ERR_DONE) quic_error(env, (int) result, code);
    return (jint) result;
}

JNIEXPORT jlong JNICALL JN(connGet)(JNIEnv *env, jclass cls, jlong handle, jint option, jlong argument) {
    quiche_conn *conn = PTR(quiche_conn, handle);
    switch (option) {
        case 0: return quiche_conn_is_established(conn);
        case 1: return quiche_conn_is_resumed(conn);
        case 2: return quiche_conn_is_in_early_data(conn);
        case 3: return quiche_conn_is_readable(conn);
        case 4: return quiche_conn_is_draining(conn);
        case 5: return quiche_conn_is_closed(conn);
        case 6: return quiche_conn_is_timed_out(conn);
        case 7: return quiche_conn_is_server(conn);
        case 8: return (jlong) quiche_conn_peer_streams_left_bidi(conn);
        case 9: return (jlong) quiche_conn_peer_streams_left_uni(conn);
        case 10: return (jlong) quiche_conn_timeout_as_nanos(conn);
        case 11: return (jlong) quiche_conn_timeout_as_millis(conn);
        case 12: return (jlong) quiche_conn_max_send_udp_payload_size(conn);
        case 13: return (jlong) quiche_conn_send_quantum(conn);
        case 14: return io_result(env, quiche_conn_dgram_max_writable_len(conn));
        case 15: return io_result(env, quiche_conn_dgram_recv_front_len(conn));
        case 16: return quiche_conn_dgram_recv_queue_len(conn);
        case 17: return quiche_conn_dgram_recv_queue_byte_size(conn);
        case 18: return quiche_conn_dgram_send_queue_len(conn);
        case 19: return quiche_conn_dgram_send_queue_byte_size(conn);
        case 20: return quiche_conn_is_dgram_send_queue_full(conn);
        case 21: return quiche_conn_is_dgram_recv_queue_full(conn);
        case 22: return (jlong) quiche_conn_retired_scids(conn);
        case 23: return (jlong) quiche_conn_available_dcids(conn);
        case 24: return (jlong) quiche_conn_scids_left(conn);
        case 25: return (jlong) quiche_conn_active_scids(conn);
        case 26: return io_result(env, quiche_conn_stream_capacity(conn, (uint64_t) argument));
        case 27: return quiche_conn_stream_readable(conn, (uint64_t) argument);
        case 28: return quiche_conn_stream_finished(conn, (uint64_t) argument);
        case 29: return quiche_conn_stream_readable_next(conn);
        case 30: return quiche_conn_stream_writable_next(conn);
        default: invalid(env, "Unknown connection query"); return -1;
    }
}

JNIEXPORT void JNICALL JN(connAction)(JNIEnv *env, jclass cls, jlong handle, jint option, jlong argument) {
    quiche_conn *conn = PTR(quiche_conn, handle);
    switch (option) {
        case 0: quiche_conn_on_timeout(conn); break;
        case 1: io_result(env, quiche_conn_send_ack_eliciting(conn)); break;
        case 2: check(env, quiche_conn_retire_dcid(conn, (uint64_t) argument)); break;
        case 3: check(env, quiche_conn_set_max_idle_timeout(conn, (uint64_t) argument)); break;
        default: invalid(env, "Unknown connection action");
    }
}

JNIEXPORT jint JNICALL JN(streamWritable)(JNIEnv *env, jclass cls, jlong handle, jlong stream, jlong length) {
    return (jint) check(env, quiche_conn_stream_writable(PTR(quiche_conn, handle), (uint64_t) stream, (size_t) length));
}

JNIEXPORT void JNICALL JN(streamPriority)(JNIEnv *env, jclass cls, jlong handle, jlong stream, jint urgency, jboolean incremental) {
    check(env, quiche_conn_stream_priority(PTR(quiche_conn, handle), (uint64_t) stream, (uint8_t) urgency, incremental));
}

JNIEXPORT void JNICALL JN(streamShutdown)(JNIEnv *env, jclass cls, jlong handle, jlong stream, jint direction, jlong error) {
    check(env, quiche_conn_stream_shutdown(PTR(quiche_conn, handle), (uint64_t) stream, (enum quiche_shutdown) direction, (uint64_t) error));
}

static bool reserve(JNIEnv *env, void **data, size_t *capacity, size_t count, size_t width) {
    if (count < *capacity) return true;
    size_t next = *capacity ? *capacity * 2 : 16;
    if (next <= count || next > (size_t) INT_MAX || next > SIZE_MAX / width) { oom(env); return false; }
    void *allocation = realloc(*data, next * width);
    if (!allocation) { oom(env); return false; }
    *data = allocation; *capacity = next; return true;

}
JNIEXPORT jlongArray JNICALL JN(streams)(JNIEnv *env, jclass cls, jlong handle, jboolean writable) {
    quiche_stream_iter *iter = writable ? quiche_conn_writable(PTR(quiche_conn, handle)) : quiche_conn_readable(PTR(quiche_conn, handle));
    if (!iter) { oom(env); return NULL; }
    jlong *data = NULL; size_t count = 0, capacity = 0; uint64_t stream;
    while (quiche_stream_iter_next(iter, &stream)) {
        if (!reserve(env, (void **) &data, &capacity, count, sizeof(*data))) break;
        data[count++] = (jlong) stream;
    }
    quiche_stream_iter_free(iter);
    jlongArray result = (*env)->ExceptionCheck(env) ? NULL : longs(env, data, count);
    free(data); return result;
}

JNIEXPORT jbyteArray JNICALL JN(connBytes)(JNIEnv *env, jclass cls, jlong handle, jint option) {
    const uint8_t *data = NULL; size_t length = 0; quiche_conn *conn = PTR(quiche_conn, handle);
    switch (option) {
        case 0: quiche_conn_trace_id(conn, &data, &length); break;
        case 1: quiche_conn_source_id(conn, &data, &length); break;
        case 2: quiche_conn_destination_id(conn, &data, &length); break;
        case 3: quiche_conn_application_proto(conn, &data, &length); break;
        case 4: quiche_conn_peer_cert(conn, &data, &length); break;
        case 5: quiche_conn_session(conn, &data, &length); break;
        case 6: quiche_conn_server_name(conn, &data, &length); break;
        default: invalid(env, "Unknown bytes query"); return NULL;
    }
    return bytes(env, data, length);
}

JNIEXPORT jboolean JNICALL JN(connText)(JNIEnv *env, jclass cls, jlong handle, jint option, jbyteArray text, jbyteArray extra, jbyteArray extra2) {
    byte_slice value = copy_bytes(env, text), title = { NULL, 0 }, description = { NULL, 0 };
    if (extra) title = copy_bytes(env, extra);
    if (extra2) description = copy_bytes(env, extra2);
    bool result = false;
    if (!(*env)->ExceptionCheck(env)) {
        if (option == 0) result = quiche_conn_set_keylog_path(PTR(quiche_conn, handle), (char *) value.data);
        else if (option == 1) result = quiche_conn_set_qlog_path(PTR(quiche_conn, handle), (char *) value.data, (char *) title.data, (char *) description.data);
        else invalid(env, "Unknown connection text option");
    }
    free(value.data); free(title.data); free(description.data); return result;
}

JNIEXPORT void JNICALL JN(setSession)(JNIEnv *env, jclass cls, jlong handle, jbyteArray input) {
    byte_slice data = copy_bytes(env, input); if (!data.data) return;
    int result = quiche_conn_set_session(PTR(quiche_conn, handle), data.data, data.length);
    free(data.data); check(env, result);
}

JNIEXPORT void JNICALL JN(closeConnection)(JNIEnv *env, jclass cls, jlong handle, jboolean application, jlong error, jbyteArray input) {
    byte_slice data = copy_bytes(env, input); if (!data.data) return;
    int result = quiche_conn_close(PTR(quiche_conn, handle), application, (uint64_t) error, data.data, data.length);
    free(data.data); io_result(env, result);
}

JNIEXPORT jobject JNICALL JN(connectionError)(JNIEnv *env, jclass cls, jlong handle, jboolean peer) {
    bool application; uint64_t code; const uint8_t *reason; size_t length;
    bool has_error = peer ? quiche_conn_peer_error(PTR(quiche_conn, handle), &application, &code, &reason, &length)
        : quiche_conn_local_error(PTR(quiche_conn, handle), &application, &code, &reason, &length);
    if (!has_error) return NULL;
    jbyteArray copied = bytes(env, reason, length);
    jobject result = construct(env, "ConnectionError", "(ZJ[B)V", (jboolean) application, (jlong) code, copied);
    (*env)->DeleteLocalRef(env, copied); return result;
}

JNIEXPORT jint JNICALL JN(datagram)(JNIEnv *env, jclass cls, jlong handle, jboolean send, jobject input, jint offset, jint length) {
    uint8_t *data = buffer(env, input, offset, length); if (!data) return -1;
    return (jint) io_result(env, send ? quiche_conn_dgram_send(PTR(quiche_conn, handle), data, (size_t) length)
                                     : quiche_conn_dgram_recv(PTR(quiche_conn, handle), data, (size_t) length));
}

typedef struct { JNIEnv *env; jobject predicate; jmethodID method; } purge_context;
static _Thread_local purge_context *current_purge;

static bool purge_callback(uint8_t *data, size_t length) {
    purge_context *context = current_purge; JNIEnv *env = context->env;
    if ((*env)->ExceptionCheck(env)) return false;
    jbyteArray copy = bytes(env, data, length); if (!copy) return false;
    jboolean result = (*env)->CallBooleanMethod(env, context->predicate, context->method, copy);
    bool failed = (*env)->ExceptionCheck(env);
    (*env)->DeleteLocalRef(env, copy); return !failed && result;
}

JNIEXPORT void JNICALL JN(purgeDatagrams)(JNIEnv *env, jclass cls, jlong handle, jobject predicate) {
    jclass type = (*env)->GetObjectClass(env, predicate);
    if (!type) return;
    jmethodID method = (*env)->GetMethodID(env, type, "test", "(Ljava/lang/Object;)Z");
    (*env)->DeleteLocalRef(env, type); if (!method) return;
    purge_context context = { env, predicate, method }, *previous = current_purge;
    current_purge = &context;
    quiche_conn_dgram_purge_outgoing(PTR(quiche_conn, handle), purge_callback);
    current_purge = previous;
}

typedef struct { uint8_t id[20]; size_t length; } copied_cid;

JNIEXPORT jobjectArray JNICALL JN(connectionIds)(JNIEnv *env, jclass cls, jlong handle, jboolean retired) {
    quiche_connection_id_iter *iter = retired ? quiche_conn_retired_scid_iter(PTR(quiche_conn, handle)) : quiche_conn_source_ids(PTR(quiche_conn, handle));
    if (!iter) { oom(env); return NULL; }
    copied_cid *data = NULL; size_t count = 0, capacity = 0; const uint8_t *id; size_t length;
    while (quiche_connection_id_iter_next(iter, &id, &length)) {
        if (length > 20) { invalid(env, "Invalid native connection ID"); break; }
        if (!reserve(env, (void **) &data, &capacity, count, sizeof(*data))) break;
        memcpy(data[count].id, id, length); data[count++].length = length;
    }
    quiche_connection_id_iter_free(iter);
    if ((*env)->ExceptionCheck(env)) { free(data); return NULL; }
    jclass type = (*env)->FindClass(env, "[B");
    jobjectArray result = type ? (*env)->NewObjectArray(env, (jsize) count, type, NULL) : NULL;
    if (type) (*env)->DeleteLocalRef(env, type);
    for (size_t i = 0; result && i < count; i++) {
        jbyteArray value = bytes(env, data[i].id, data[i].length); if (!value) break;
        (*env)->SetObjectArrayElement(env, result, (jsize) i, value); (*env)->DeleteLocalRef(env, value);
        if ((*env)->ExceptionCheck(env)) break;
    }
    free(data); return result;
}

JNIEXPORT jlong JNICALL JN(newScid)(JNIEnv *env, jclass cls, jlong handle, jbyteArray input, jbyteArray reset_token, jboolean retire) {
    byte_slice id = copy_bytes(env, input), token = copy_bytes(env, reset_token); uint64_t sequence = 0;
    int result = -1;
    if (id.data && token.data) {
        if (token.length != 16 || id.length > 20) invalid(env, "Invalid CID or reset token length");
        else result = quiche_conn_new_scid(PTR(quiche_conn, handle), id.data, id.length, token.data, retire, &sequence);
    }
    free(id.data); free(token.data); check(env, result); return (jlong) sequence;
}

JNIEXPORT jlong JNICALL JN(pathAction)(JNIEnv *env, jclass cls, jlong handle, jint option, jbyteArray local, jbyteArray peer) {
    struct sockaddr_storage source, destination; socklen_t source_len, destination_len = 0;
    if (!address(env, local, &source, &source_len) || (peer && !address(env, peer, &destination, &destination_len))) return -1;
    quiche_conn *conn = PTR(quiche_conn, handle); uint64_t sequence = 0; int result = 0;
    switch (option) {
        case 0: result = quiche_conn_probe_path(conn, (struct sockaddr *) &source, source_len, (struct sockaddr *) &destination, destination_len, &sequence); break;
        case 1: result = quiche_conn_migrate_source(conn, (struct sockaddr *) &source, source_len, &sequence); break;
        case 2: result = quiche_conn_migrate(conn, (struct sockaddr *) &source, source_len, (struct sockaddr *) &destination, destination_len, &sequence); break;
        case 3: return check(env, quiche_conn_is_path_validated(conn, (struct sockaddr *) &source, source_len, (struct sockaddr *) &destination, destination_len));
        case 4: return io_result(env, quiche_conn_send_ack_eliciting_on_path(conn, (struct sockaddr *) &source, source_len, (struct sockaddr *) &destination, destination_len));
        case 5: return (jlong) quiche_conn_send_quantum_on_path(conn, (struct sockaddr *) &source, source_len, (struct sockaddr *) &destination, destination_len);
        default: invalid(env, "Unknown path action"); return -1;
    }
    check(env, result); return (jlong) sequence;
}

JNIEXPORT jobject JNICALL JN(pathEvent)(JNIEnv *env, jclass cls, jlong handle) {
    quiche_path_event *event = quiche_conn_path_event_next(PTR(quiche_conn, handle)); if (!event) return NULL;
    enum quiche_path_event_type type = quiche_path_event_type(event);
    struct sockaddr_storage local, peer, old_local, old_peer;
    socklen_t local_len = sizeof(local), peer_len = sizeof(peer), old_local_len = sizeof(old_local), old_peer_len = sizeof(old_peer);
    uint64_t id = 0; size_t pmtu = 0;
    switch (type) {
        case QUICHE_PATH_EVENT_NEW: quiche_path_event_new(event, &local, &local_len, &peer, &peer_len); break;
        case QUICHE_PATH_EVENT_VALIDATED: quiche_path_event_validated(event, &local, &local_len, &peer, &peer_len); break;
        case QUICHE_PATH_EVENT_FAILED_VALIDATION: quiche_path_event_failed_validation(event, &local, &local_len, &peer, &peer_len); break;
        case QUICHE_PATH_EVENT_CLOSED: quiche_path_event_closed(event, &local, &local_len, &peer, &peer_len); break;
        case QUICHE_PATH_EVENT_PEER_MIGRATED: quiche_path_event_peer_migrated(event, &local, &local_len, &peer, &peer_len); break;
        case QUICHE_PATH_EVENT_PMTU_UPDATED: quiche_path_event_pmtu_updated(event, &local, &local_len, &peer, &peer_len, &pmtu); break;
        case QUICHE_PATH_EVENT_REUSED_SOURCE_CONNECTION_ID:
            quiche_path_event_reused_source_connection_id(event, &id, &old_local, &old_local_len, &old_peer, &old_peer_len, &local, &local_len, &peer, &peer_len); break;
        default: quiche_path_event_free(event); invalid(env, "Unknown native path event"); return NULL;
    }
    jobject from = java_address(env, (struct sockaddr *) &local);
    jobject to = (*env)->ExceptionCheck(env) ? NULL : java_address(env, (struct sockaddr *) &peer);
    jobject old_from = NULL, old_to = NULL;
    if (type == QUICHE_PATH_EVENT_REUSED_SOURCE_CONNECTION_ID && !(*env)->ExceptionCheck(env)) {
        old_from = java_address(env, (struct sockaddr *) &old_local);
        if (!(*env)->ExceptionCheck(env)) old_to = java_address(env, (struct sockaddr *) &old_peer);
    }
    quiche_path_event_free(event);
    jobject result = construct(env, "PathEvent", "(ILjava/net/InetSocketAddress;Ljava/net/InetSocketAddress;Ljava/net/InetSocketAddress;Ljava/net/InetSocketAddress;JJ)V",
                               (jint) type, from, to, old_from, old_to, (jlong) id, (jlong) pmtu);
    (*env)->DeleteLocalRef(env, from); (*env)->DeleteLocalRef(env, to); (*env)->DeleteLocalRef(env, old_from); (*env)->DeleteLocalRef(env, old_to);
    return result;
}

JNIEXPORT jobjectArray JNICALL JN(paths)(JNIEnv *env, jclass cls, jlong handle, jbyteArray local) {
    struct sockaddr_storage source; socklen_t source_len;
    if (!address(env, local, &source, &source_len)) return NULL;
    quiche_socket_addr_iter *iter = quiche_conn_paths_iter(PTR(quiche_conn, handle), (struct sockaddr *) &source, source_len);
    if (!iter) { oom(env); return NULL; }
    struct sockaddr_storage *data = NULL, peer; size_t count = 0, capacity = 0, length = sizeof(peer);
    while (quiche_socket_addr_iter_next(iter, &peer, &length)) {
        if (!reserve(env, (void **) &data, &capacity, count, sizeof(*data))) break;
        data[count++] = peer; length = sizeof(peer);
    }
    quiche_socket_addr_iter_free(iter);
    if ((*env)->ExceptionCheck(env)) { free(data); return NULL; }
    jclass type = (*env)->FindClass(env, "java/net/InetSocketAddress");
    jobjectArray result = type ? (*env)->NewObjectArray(env, (jsize) count, type, NULL) : NULL;
    if (type) (*env)->DeleteLocalRef(env, type);
    for (size_t i = 0; result && i < count; i++) {
        jobject value = java_address(env, (struct sockaddr *) &data[i]); if (!value) break;
        (*env)->SetObjectArrayElement(env, result, (jsize) i, value); (*env)->DeleteLocalRef(env, value);
        if ((*env)->ExceptionCheck(env)) break;
    }
    free(data); return result;
}

JNIEXPORT jint JNICALL JN(putVarint)(JNIEnv *env, jclass cls, jobject output, jint offset, jint length, jlong value) {
    uint8_t *data = buffer(env, output, offset, length); if (!data) return -1;
    int result = quiche_put_varint(data, (size_t) length, (uint64_t) value);
    if (check(env, result) < 0) return -1;
    return value < 64 ? 1 : value < 16384 ? 2 : value < 1073741824LL ? 4 : 8;
}

JNIEXPORT jlongArray JNICALL JN(getVarint)(JNIEnv *env, jclass cls, jobject input, jint offset, jint length) {
    uint8_t *data = buffer(env, input, offset, length); if (!data) return NULL;
    uint64_t value = 0; ssize_t result = quiche_get_varint(data, (size_t) length, &value);
    if (check(env, result) < 0) return NULL;
    jlong values[] = { (jlong) value, (jlong) result }; return longs(env, values, 2);
}

#include "h3.inc"
#include "logging.inc"
#include "generated.inc"
