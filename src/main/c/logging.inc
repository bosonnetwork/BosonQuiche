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
/* quiche's logger is process-global and is installed once. */
static JavaVM *java_vm;
static jobject log_consumer;
static jmethodID log_accept;
static jstring log_string(JNIEnv *env, const char *line) {
    /* quiche emits UTF-8, whereas NewStringUTF expects JNI modified UTF-8. */
    jbyteArray encoded = bytes(env, (const uint8_t *) line, strlen(line));
    if (!encoded) return NULL;
    jclass type = (*env)->FindClass(env, "java/lang/String");
    if (!type) { (*env)->DeleteLocalRef(env, encoded); return NULL; }
    jmethodID constructor = (*env)->GetMethodID(env, type, "<init>", "([BLjava/lang/String;)V");
    jstring encoding = constructor ? (*env)->NewStringUTF(env, "UTF-8") : NULL;
    jstring result = encoding ? (*env)->NewObject(env, type, constructor, encoded, encoding) : NULL;
    (*env)->DeleteLocalRef(env, encoding); (*env)->DeleteLocalRef(env, type); (*env)->DeleteLocalRef(env, encoded);
    return result;
}
static void log_callback(const char *line, void *argument) {
    JNIEnv *env = NULL; bool attached = false;
    jint status = (*java_vm)->GetEnv(java_vm, (void **) &env, JNI_VERSION_1_6);
    if (status == JNI_EDETACHED) {
#ifdef __ANDROID__
        if ((*java_vm)->AttachCurrentThread(java_vm, &env, NULL) != JNI_OK) return;
#else
        if ((*java_vm)->AttachCurrentThread(java_vm, (void **) &env, NULL) != JNI_OK) return;
#endif
        attached = true;
    } else if (status != JNI_OK) return;
    /* Do not replace an exception already being propagated by a JNI call. */
    if (!(*env)->ExceptionCheck(env)) {
        jstring text = log_string(env, line);
        if (text) {
            (*env)->CallVoidMethod(env, log_consumer, log_accept, text);
            if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
            (*env)->DeleteLocalRef(env, text);
        } else if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
    }
    if (attached) (*java_vm)->DetachCurrentThread(java_vm);
}
JNIEXPORT void JNICALL JN(debugLogging)(JNIEnv *env, jclass cls, jobject consumer) {
    if (log_consumer) { fail(env, "java/lang/IllegalStateException", "Debug logging has already been installed"); return; }
    jclass type = (*env)->GetObjectClass(env, consumer); if (!type) return;
    jmethodID accept = (*env)->GetMethodID(env, type, "accept", "(Ljava/lang/Object;)V");
    (*env)->DeleteLocalRef(env, type); if (!accept) return;
    jobject global = (*env)->NewGlobalRef(env, consumer); if (!global) return;
    log_consumer = global; log_accept = accept;
    int result = quiche_enable_debug_logging(log_callback, NULL);
    if (result != 0) {
        log_consumer = NULL; (*env)->DeleteGlobalRef(env, global);
        fail(env, "java/lang/IllegalStateException", "Upstream quiche logger is already initialized");
    }
}
JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM *vm, void *reserved) { java_vm = vm; return JNI_VERSION_1_6; }
JNIEXPORT void JNICALL JNI_OnUnload(JavaVM *vm, void *reserved) {
    JNIEnv *env = NULL;
    if (log_consumer && (*vm)->GetEnv(vm, (void **) &env, JNI_VERSION_1_6) == JNI_OK) {
        (*env)->DeleteGlobalRef(env, log_consumer); log_consumer = NULL;
    }
}
