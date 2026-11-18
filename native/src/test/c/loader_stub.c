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

#include <jni.h>

JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM *vm, void *reserved) {
    (void) vm;
    (void) reserved;
    return JNI_VERSION_1_6;
}

#ifndef STUB_legacy
JNIEXPORT jint JNICALL Java_io_bosonnetwork_quiche_Native_bindingAbi(JNIEnv *env, jclass type) {
    (void) env;
    (void) type;
#ifdef STUB_abi
    return BOSON_BINDING_ABI + 1;
#else
    return BOSON_BINDING_ABI;
#endif
}

JNIEXPORT jstring JNICALL Java_io_bosonnetwork_quiche_Native_bindingVersion(JNIEnv *env, jclass type) {
    (void) type;
#ifdef STUB_version
    return (*env)->NewStringUTF(env, "stale-binding");
#else
    return (*env)->NewStringUTF(env, BOSON_BINDING_VERSION);
#endif
}

/* Only the upstream-mismatch fixture exposes this ordinary API operation.
 * ABI/version failures must happen before the loader can reach it. */
#ifdef STUB_upstream
JNIEXPORT jstring JNICALL Java_io_bosonnetwork_quiche_Native_version(JNIEnv *env, jclass type) {
    (void) type;
    return (*env)->NewStringUTF(env, "0.0.0");
}
#endif
#endif

