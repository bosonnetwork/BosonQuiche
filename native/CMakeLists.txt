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

cmake_minimum_required(VERSION 3.22)
project(boson_quiche LANGUAGES C)

foreach(input BOSON_SOURCE QUICHE_INCLUDE QUICHE_ARCHIVE JNI_INCLUDE)
    if(NOT EXISTS "${${input}}")
        message(FATAL_ERROR "Missing native build input ${input}: ${${input}}")
    endif()
endforeach()

add_library(boson_quiche SHARED "${BOSON_SOURCE}/boson_quiche.c")
set_target_properties(boson_quiche PROPERTIES
    C_STANDARD 11 C_STANDARD_REQUIRED YES C_VISIBILITY_PRESET hidden)
target_include_directories(boson_quiche PRIVATE
    "${QUICHE_INCLUDE}" "${JNI_INCLUDE}" "${JNI_PLATFORM_INCLUDE}")
target_link_libraries(boson_quiche PRIVATE "${QUICHE_ARCHIVE}")

if(MSVC)
    set_property(TARGET boson_quiche PROPERTY MSVC_RUNTIME_LIBRARY MultiThreaded)
    target_compile_options(boson_quiche PRIVATE /W4 /WX /wd4100)
    file(GLOB import_libraries "${LINK_SUPPORT}/*.lib")
    target_link_libraries(boson_quiche PRIVATE ${import_libraries}
        advapi32 legacy_stdio_definitions kernel32 ntdll userenv ws2_32 dbghelp)
else()
    target_compile_options(boson_quiche PRIVATE
        -Wall -Wextra -Werror -Wno-unused-parameter)
    if(APPLE)
        file(READ "${BOSON_SOURCE}/../java/io/bosonnetwork/quiche/Native.java" native_java)
        string(REGEX MATCHALL "static native [^ \n]+ [A-Za-z0-9_]+\\(" methods "${native_java}")
        set(exports "_JNI_OnLoad\n_JNI_OnUnload\n")
        foreach(method ${methods})
            string(REGEX REPLACE ".* ([A-Za-z0-9_]+)\\(" "\\1" name "${method}")
            string(APPEND exports "_Java_io_bosonnetwork_quiche_Native_${name}\n")
        endforeach()
        file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/jni.exports" "${exports}")
        target_link_options(boson_quiche PRIVATE
            "-Wl,-exported_symbols_list,${CMAKE_CURRENT_BINARY_DIR}/jni.exports")
        set_target_properties(boson_quiche PROPERTIES INSTALL_NAME_DIR "@rpath" BUILD_WITH_INSTALL_NAME_DIR YES)
        target_link_libraries(boson_quiche PRIVATE
            "-framework Security" "-framework CoreFoundation" resolv c++)
    else()
        file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/jni.exports"
            "{ global: JNI_OnLoad; JNI_OnUnload; Java_io_bosonnetwork_quiche_Native_*; local: *; };\n")
        target_link_options(boson_quiche PRIVATE
            "-Wl,--version-script=${CMAKE_CURRENT_BINARY_DIR}/jni.exports" "-Wl,-z,defs")
        if(ANDROID)
            target_link_libraries(boson_quiche PRIVATE c++_static c++abi log dl m)
            target_link_options(boson_quiche PRIVATE "-Wl,-z,max-page-size=16384")
        else()
            target_link_libraries(boson_quiche PRIVATE pthread dl m)
            target_link_options(boson_quiche PRIVATE -static-libgcc -static-libstdc++)
            # Rust's archive contains C++ objects; resolve them with the static
            # C++ runtime from the selected GCC toolchain.
            target_link_libraries(boson_quiche PRIVATE "-Wl,-Bstatic" stdc++ "-Wl,-Bdynamic")
        endif()
    endif()
endif()

