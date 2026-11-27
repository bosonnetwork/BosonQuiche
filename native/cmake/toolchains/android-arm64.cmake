# Copyright (c) 2026 bosonnetwork.io
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# Cross-compilation for Android arm64.
#
# This file describes how to use the NDK for this product's target: the ABI, the
# static C++ runtime and the API level are compatibility promises that belong in
# version control. Locating the NDK stays a provisioning concern, so the path
# comes from ANDROID_NDK_HOME and is never hard-coded here.

if(NOT DEFINED ENV{ANDROID_NDK_HOME})
    message(FATAL_ERROR "ANDROID_NDK_HOME must point at the pinned NDK")
endif()
set(android_toolchain "$ENV{ANDROID_NDK_HOME}/build/cmake/android.toolchain.cmake")
if(NOT EXISTS "${android_toolchain}")
    message(FATAL_ERROR "Missing NDK CMake toolchain: ${android_toolchain}")
endif()
# boring-sys configures BoringSSL with its own CMake invocation, which only
# inherits this file, never the outer cache. Keep every value here.
if(NOT ANDROID_PLATFORM)
    set(ANDROID_PLATFORM android-33)
endif()

set(ANDROID_ABI arm64-v8a)
set(ANDROID_STL c++_static)
include("${android_toolchain}")
