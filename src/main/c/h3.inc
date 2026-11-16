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
/* HTTP/3 JNI functions, included after the common QUIC marshalling helpers. */

JNIEXPORT jlong JNICALL JN(h3ConfigNew)(JNIEnv *env, jclass cls) {
    quiche_h3_config *config = quiche_h3_config_new();
    if (!config) oom(env);
    return (jlong) (uintptr_t) config;
}
JNIEXPORT void JNICALL JN(h3ConfigSet)(JNIEnv *env, jclass cls, jlong handle, jint option, jlong value) {
    quiche_h3_config *config = PTR(quiche_h3_config, handle);
    switch (option) {
        case 0: quiche_h3_config_set_max_field_section_size(config, (uint64_t) value); break;
        case 1: quiche_h3_config_set_qpack_max_table_capacity(config, (uint64_t) value); break;
        case 2: quiche_h3_config_set_qpack_blocked_streams(config, (uint64_t) value); break;
        case 3: quiche_h3_config_enable_extended_connect(config, value != 0); break;
        case 4: quiche_h3_config_set_max_priority_update_size(config, (uint64_t) value); break;
        default: invalid(env, "Unknown HTTP/3 config option");
    }
}
JNIEXPORT jlong JNICALL JN(h3New)(JNIEnv *env, jclass cls, jlong transport, jlong config) {
    quiche_h3_conn *conn = quiche_h3_conn_new_with_transport(PTR(quiche_conn, transport), PTR(quiche_h3_config, config));
    if (!conn) fail(env, "java/lang/IllegalStateException", "Could not initialize HTTP/3; establish QUIC and configure at least three unidirectional streams");
    return (jlong) (uintptr_t) conn;
}
typedef struct {
    JNIEnv *env;
    quiche_h3_header *headers;
    size_t count;
    size_t capacity;
} header_collection;
static int collect_header(uint8_t *name, size_t name_len, uint8_t *value, size_t value_len, void *arg) {
    header_collection *collection = arg;
    if (!reserve(collection->env, (void **) &collection->headers, &collection->capacity, collection->count, sizeof(quiche_h3_header))) return QUICHE_H3_ERR_INTERNAL_ERROR;
    collection->headers[collection->count++] = (quiche_h3_header) { name, name_len, value, value_len };
    return 0;
}
JNIEXPORT jobject JNICALL JN(h3Poll)(JNIEnv *env, jclass cls, jlong handle, jlong transport) {
    quiche_h3_event *event = NULL;
    int64_t id = quiche_h3_conn_poll(PTR(quiche_h3_conn, handle), PTR(quiche_conn, transport), &event);
    if (id == QUICHE_H3_ERR_DONE) return NULL;
    if (id < 0) { h3_error(env, id); return NULL; }
    enum quiche_h3_event_type type = quiche_h3_event_type(event);
    header_collection collection = { env, NULL, 0, 0 };
    bool more = false;
    if (type == QUICHE_H3_EVENT_HEADERS) {
        int result = quiche_h3_event_for_each_header(event, collect_header, &collection);
        if (result < 0) h3_error(env, result);
        more = quiche_h3_event_headers_has_more_frames(event);
    }
    jobject result = NULL; jobjectArray headers = NULL; jclass header_type = NULL;
    if (!(*env)->ExceptionCheck(env)) header_type = (*env)->FindClass(env, PACKAGE "H3Header");
    if (header_type) {
        headers = (*env)->NewObjectArray(env, (jsize) collection.count, header_type, NULL);
        (*env)->DeleteLocalRef(env, header_type);
    }
    for (size_t i = 0; headers && i < collection.count; i++) {
        quiche_h3_header *header = &collection.headers[i];
        jbyteArray name = bytes(env, header->name, header->name_len);
        jbyteArray value = (*env)->ExceptionCheck(env) ? NULL : bytes(env, header->value, header->value_len);
        jobject item = construct(env, "H3Header", "([B[B)V", name, value);
        (*env)->DeleteLocalRef(env, name); (*env)->DeleteLocalRef(env, value);
        if (!item) break;
        (*env)->SetObjectArrayElement(env, headers, (jsize) i, item); (*env)->DeleteLocalRef(env, item);
        if ((*env)->ExceptionCheck(env)) break;
    }
    if (headers) result = construct(env, "H3Event", "(JI[L" PACKAGE "H3Header;Z)V", (jlong) id, (jint) type, headers, (jboolean) more);
    (*env)->DeleteLocalRef(env, headers); free(collection.headers); quiche_h3_event_free(event);
    return result;
}
static void free_headers(quiche_h3_header *headers, size_t length) {
    if (!headers) return;
    for (size_t i = 0; i < length; i++) { free((void *) headers[i].name); free((void *) headers[i].value); }
    free(headers);
}
JNIEXPORT jlong JNICALL JN(h3Headers)(JNIEnv *env, jclass cls, jlong handle, jlong transport, jint option, jlong stream,
                                     jobjectArray names, jobjectArray values, jboolean fin, jint urgency, jboolean incremental, jboolean trailer) {
    size_t length = (size_t) (*env)->GetArrayLength(env, names);
    if ((size_t) (*env)->GetArrayLength(env, values) != length) { invalid(env, "Header array length mismatch"); return -1; }
    quiche_h3_header *headers = calloc(length ? length : 1, sizeof(*headers));
    if (!headers) { oom(env); return -1; }
    for (size_t i = 0; i < length; i++) {
        jbyteArray name = (*env)->GetObjectArrayElement(env, names, (jsize) i);
        if ((*env)->ExceptionCheck(env)) break;
        jbyteArray value = (*env)->GetObjectArrayElement(env, values, (jsize) i);
        if ((*env)->ExceptionCheck(env)) { (*env)->DeleteLocalRef(env, name); break; }
        byte_slice n = copy_bytes(env, name), v = { NULL, 0 };
        if (!(*env)->ExceptionCheck(env)) v = copy_bytes(env, value);
        headers[i] = (quiche_h3_header) { n.data, n.length, v.data, v.length };
        (*env)->DeleteLocalRef(env, name); (*env)->DeleteLocalRef(env, value);
        if ((*env)->ExceptionCheck(env)) break;
    }
    int64_t result = -1;
    if (!(*env)->ExceptionCheck(env)) {
        quiche_h3_conn *conn = PTR(quiche_h3_conn, handle); quiche_conn *quic = PTR(quiche_conn, transport);
        quiche_h3_priority priority = { (uint8_t) urgency, incremental };
        switch (option) {
            case 0: result = quiche_h3_send_request(conn, quic, headers, length, fin); break;
            case 1: result = quiche_h3_send_response(conn, quic, (uint64_t) stream, headers, length, fin); break;
            case 2: result = quiche_h3_send_response_with_priority(conn, quic, (uint64_t) stream, headers, length, &priority, fin); break;
            case 3: result = quiche_h3_send_additional_headers(conn, quic, (uint64_t) stream, headers, length, trailer, fin); break;
            default: invalid(env, "Unknown HTTP/3 header operation");
        }
    }
    free_headers(headers, length); h3_error(env, result); return (jlong) result;
}
JNIEXPORT jint JNICALL JN(h3Body)(JNIEnv *env, jclass cls, jlong handle, jlong transport, jlong stream,
                                 jobject input, jint offset, jint length, jboolean send, jboolean fin) {
    uint8_t *data = buffer(env, input, offset, length); if (!data) return -1;
    ssize_t result = send ? quiche_h3_send_body(PTR(quiche_h3_conn, handle), PTR(quiche_conn, transport), (uint64_t) stream, data, (size_t) length, fin)
                          : quiche_h3_recv_body(PTR(quiche_h3_conn, handle), PTR(quiche_conn, transport), (uint64_t) stream, data, (size_t) length);
    if (result != QUICHE_H3_ERR_DONE) h3_error(env, result);
    return (jint) result;
}
JNIEXPORT void JNICALL JN(h3Action)(JNIEnv *env, jclass cls, jlong handle, jlong transport, jint option, jlong stream, jint urgency, jboolean incremental) {
    int result;
    if (option == 0) result = quiche_h3_send_goaway(PTR(quiche_h3_conn, handle), PTR(quiche_conn, transport), (uint64_t) stream);
    else if (option == 1) {
        quiche_h3_priority priority = { (uint8_t) urgency, incremental };
        result = quiche_h3_send_priority_update_for_request(PTR(quiche_h3_conn, handle), PTR(quiche_conn, transport), (uint64_t) stream, &priority);
    } else { invalid(env, "Unknown HTTP/3 action"); return; }
    h3_error(env, result);
}
JNIEXPORT jboolean JNICALL JN(h3Enabled)(JNIEnv *env, jclass cls, jlong handle, jlong transport, jboolean datagram) {
    return datagram ? quiche_h3_dgram_enabled_by_peer(PTR(quiche_h3_conn, handle), PTR(quiche_conn, transport))
                    : quiche_h3_extended_connect_enabled_by_peer(PTR(quiche_h3_conn, handle));
}
typedef struct { JNIEnv *env; jlong *values; size_t count, capacity; } settings_collection;
static int collect_setting(uint64_t id, uint64_t value, void *arg) {
    settings_collection *collection = arg;
    if (!reserve(collection->env, (void **) &collection->values, &collection->capacity, collection->count + 1, sizeof(jlong))) return QUICHE_H3_ERR_INTERNAL_ERROR;
    collection->values[collection->count++] = (jlong) id;
    collection->values[collection->count++] = (jlong) value;
    return 0;
}
JNIEXPORT jlongArray JNICALL JN(h3Settings)(JNIEnv *env, jclass cls, jlong handle) {
    settings_collection collection = { env, NULL, 0, 0 };
    int result = quiche_h3_for_each_setting(PTR(quiche_h3_conn, handle), collect_setting, &collection);
    h3_error(env, result);
    jlongArray values = (*env)->ExceptionCheck(env) ? NULL : longs(env, collection.values, collection.count);
    free(collection.values); return values;
}
JNIEXPORT jobject JNICALL JN(h3ParsePriority)(JNIEnv *env, jclass cls, jbyteArray input) {
    byte_slice data = copy_bytes(env, input); if (!data.data) return NULL;
    quiche_h3_priority priority;
    int result = quiche_h3_parse_extensible_priority(data.data, data.length, &priority);
    free(data.data); h3_error(env, result);
    if ((*env)->ExceptionCheck(env)) return NULL;
    return construct(env, "H3Priority", "(IZ)V", (jint) priority.urgency, (jboolean) priority.incremental);
}
typedef struct { JNIEnv *env; jbyteArray result; } priority_collection;
static int collect_priority(uint8_t *data, uint64_t length, void *arg) {
    priority_collection *collection = arg;
    collection->result = bytes(collection->env, data, (size_t) length);
    return collection->result ? 0 : QUICHE_H3_ERR_INTERNAL_ERROR;
}
JNIEXPORT jbyteArray JNICALL JN(h3TakePriority)(JNIEnv *env, jclass cls, jlong handle, jlong stream) {
    priority_collection collection = { env, NULL };
    int result = quiche_h3_take_last_priority_update(PTR(quiche_h3_conn, handle), (uint64_t) stream, collect_priority, &collection);
    if (result != QUICHE_H3_ERR_DONE) h3_error(env, result);
    return collection.result;
}
