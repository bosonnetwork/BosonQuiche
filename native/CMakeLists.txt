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

# ---------------------------------------------------------------------------
# Inputs.
#
# Always required: BOSON_BINDING_ABI, BOSON_BINDING_VERSION, JNI_INCLUDE.
# Required for a self-contained build: RUST_TARGET, one of the triples in
# native/platforms.json. Required for the install layout used by Maven:
# BOSON_TARGET and BOSON_CLASSIFIER.
#
# Quiche comes from exactly one of QUICHE_SOURCE (a checkout), QUICHE_ARCHIVE
# (a prebuilt static archive, used by the cross-compile driver) or, when
# neither is given, the pinned tarball in native/quiche.json fetched into
# BOSON_CACHE_DIR.
# ---------------------------------------------------------------------------
set(BOSON_PLATFORMS_FILE "${CMAKE_CURRENT_SOURCE_DIR}/platforms.json"
    CACHE FILEPATH "Platform matrix shared with the Maven build")
set(BOSON_UPSTREAM_FILE "${CMAKE_CURRENT_SOURCE_DIR}/quiche.json"
    CACHE FILEPATH "Pinned upstream quiche inputs")
set(BOSON_CACHE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../.build"
    CACHE PATH "Shared download and source cache")
set(BOSON_SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/src/main/c"
    CACHE PATH "JNI C sources")
set(BOSON_CARGO_SUBCOMMAND ""
    CACHE STRING "Extra Cargo subcommand, for example xwin for MSVC cross builds")

if(NOT BOSON_BINDING_ABI MATCHES "^[1-9][0-9]*$" OR NOT BOSON_BINDING_VERSION)
    message(FATAL_ERROR "Binding ABI and version are required")
endif()
if(NOT JNI_INCLUDE AND DEFINED ENV{JAVA_HOME})
    set(JNI_INCLUDE "$ENV{JAVA_HOME}/include")
endif()
if(NOT JNI_INCLUDE AND APPLE)
    execute_process(COMMAND /usr/libexec/java_home
        OUTPUT_VARIABLE boson_java_home OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET RESULT_VARIABLE boson_java_result)
    if(boson_java_result EQUAL 0)
        set(JNI_INCLUDE "${boson_java_home}/include")
    endif()
endif()
if(NOT JNI_INCLUDE OR NOT EXISTS "${JNI_INCLUDE}")
    message(FATAL_ERROR "A JDK include directory is required; "
                        "pass -DJNI_INCLUDE=<jdk>/include or set JAVA_HOME")
endif()
if(NOT EXISTS "${BOSON_SOURCE}/boson_quiche.c")
    message(FATAL_ERROR "Missing JNI sources in ${BOSON_SOURCE}")
endif()
foreach(input BOSON_PLATFORMS_FILE BOSON_UPSTREAM_FILE)
    if(NOT EXISTS "${${input}}")
        message(FATAL_ERROR "Missing native build input ${input}: ${${input}}")
    endif()
endforeach()

if(NOT BOSON_JNI_PLATFORM)
    if(APPLE)
        set(BOSON_JNI_PLATFORM darwin)
    elseif(ANDROID)
        set(BOSON_JNI_PLATFORM android)
    elseif(WIN32)
        set(BOSON_JNI_PLATFORM win32)
    else()
        set(BOSON_JNI_PLATFORM linux)
    endif()
endif()
if(NOT JNI_PLATFORM_INCLUDE)
    set(JNI_PLATFORM_INCLUDE "${JNI_INCLUDE}/${BOSON_JNI_PLATFORM}")
endif()

file(READ "${BOSON_UPSTREAM_FILE}" boson_upstream)
string(JSON boson_tag GET "${boson_upstream}" tag)
string(JSON boson_archive_sha256 GET "${boson_upstream}" archive_sha256)
string(JSON boson_header_sha256 GET "${boson_upstream}" header_sha256)
string(JSON boson_feature_count LENGTH "${boson_upstream}" features)
set(boson_features_toml "")
if(boson_feature_count GREATER 0)
    math(EXPR boson_feature_last "${boson_feature_count} - 1")
    foreach(index RANGE ${boson_feature_last})
        string(JSON boson_feature GET "${boson_upstream}" features ${index})
        if(boson_features_toml)
            string(APPEND boson_features_toml ", ")
        endif()
        string(APPEND boson_features_toml "\"${boson_feature}\"")
    endforeach()
endif()

# ---------------------------------------------------------------------------
# Pinned upstream source or prebuilt archive.
# ---------------------------------------------------------------------------
if(QUICHE_ARCHIVE)
    if(NOT EXISTS "${QUICHE_ARCHIVE}")
        message(FATAL_ERROR "Missing prebuilt quiche archive: ${QUICHE_ARCHIVE}")
    endif()
else()
    if(NOT QUICHE_SOURCE)
        set(boson_download "${BOSON_CACHE_DIR}/downloads/quiche-${boson_tag}.tar.gz")
        set(boson_source_dir "${BOSON_CACHE_DIR}/sources/quiche-${boson_tag}")
        file(MAKE_DIRECTORY "${BOSON_CACHE_DIR}/downloads")
        if(NOT EXISTS "${boson_download}")
            message(STATUS "Downloading quiche ${boson_tag}")
            file(DOWNLOAD
                "https://github.com/cloudflare/quiche/archive/refs/tags/${boson_tag}.tar.gz"
                "${boson_download}" EXPECTED_HASH SHA256=${boson_archive_sha256}
                TLS_VERIFY ON STATUS boson_status)
            list(GET boson_status 0 boson_code)
            list(GET boson_status 1 boson_reason)
            if(NOT boson_code EQUAL 0)
                file(REMOVE "${boson_download}")
                message(FATAL_ERROR "Could not download quiche ${boson_tag}: ${boson_reason}")
            endif()
        endif()
        if(NOT EXISTS "${boson_source_dir}/quiche/include/quiche.h")
            set(boson_extracting "${boson_source_dir}.extracting")
            file(REMOVE_RECURSE "${boson_extracting}")
            file(ARCHIVE_EXTRACT INPUT "${boson_download}" DESTINATION "${boson_extracting}")
            file(MAKE_DIRECTORY "${BOSON_CACHE_DIR}/sources")
            file(RENAME "${boson_extracting}/quiche-${boson_tag}" "${boson_source_dir}")
            file(REMOVE_RECURSE "${boson_extracting}")
        endif()
        set(QUICHE_SOURCE "${boson_source_dir}")
    endif()
    if(NOT EXISTS "${QUICHE_SOURCE}/quiche/include/quiche.h")
        message(FATAL_ERROR "QUICHE_SOURCE is not a quiche checkout: ${QUICHE_SOURCE}")
    endif()
    file(SHA256 "${QUICHE_SOURCE}/quiche/include/quiche.h" boson_header_actual)
    if(NOT boson_header_actual STREQUAL boson_header_sha256)
        message(FATAL_ERROR "quiche.h differs from the pinned header in quiche.json")
    endif()
endif()
if(NOT QUICHE_INCLUDE)
    set(QUICHE_INCLUDE "${QUICHE_SOURCE}/quiche/include")
endif()

# ---------------------------------------------------------------------------
# Driver crate for the pinned dependency graph. The notice collection and any
# Cargo build share this manifest, so it is generated even when the archive is
# prebuilt.
# ---------------------------------------------------------------------------
set(boson_driver "${CMAKE_BINARY_DIR}/driver")
file(MAKE_DIRECTORY "${boson_driver}/src")
configure_file("${CMAKE_CURRENT_SOURCE_DIR}/cmake/Cargo.toml.in"
               "${boson_driver}/Cargo.toml" @ONLY)
configure_file("${CMAKE_CURRENT_SOURCE_DIR}/Cargo.lock"
               "${boson_driver}/Cargo.lock" COPYONLY)
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/copyright-header.txt" boson_copyright)
set(boson_lib_rs "${boson_copyright}// Generated by CMake; do not edit.\n\npub use quiche::*;\n")
set(boson_lib_rs_current "")
if(EXISTS "${boson_driver}/src/lib.rs")
    file(READ "${boson_driver}/src/lib.rs" boson_lib_rs_current)
endif()
if(NOT boson_lib_rs_current STREQUAL boson_lib_rs)
    file(WRITE "${boson_driver}/src/lib.rs" "${boson_lib_rs}")
endif()

# ---------------------------------------------------------------------------
# Rust: the pinned quiche static archive, built by Cargo.
#
# Cargo is driven from CMake because the archive is a native build product.
# The custom target always runs and lets Cargo decide what is stale; tracking
# the archive timestamp here as well would give two competing freshness models.
# ---------------------------------------------------------------------------
if(NOT QUICHE_ARCHIVE)
    if(NOT RUST_TARGET)
        message(FATAL_ERROR "RUST_TARGET is required to build the quiche archive; "
                            "see native/platforms.json")
    endif()
    find_program(CARGO_EXECUTABLE NAMES cargo REQUIRED)

    if(WIN32)
        set(boson_rust_archive "${CMAKE_BINARY_DIR}/rust/${RUST_TARGET}/release/boson_quiche_build.lib")
    else()
        set(boson_rust_archive "${CMAKE_BINARY_DIR}/rust/${RUST_TARGET}/release/libboson_quiche_build.a")
    endif()

    # boring-sys runs its own CMake for BoringSSL, so the toolchain, sysroot and
    # deployment target must be forwarded through the environment, not inherited
    # from this invocation.
    set(boson_cargo_env "CARGO_TARGET_DIR=${CMAKE_BINARY_DIR}/rust")
    if(DEFINED ENV{CARGO_HOME})
        list(APPEND boson_cargo_env "CARGO_HOME=$ENV{CARGO_HOME}")
    endif()
    if(CMAKE_OSX_DEPLOYMENT_TARGET)
        list(APPEND boson_cargo_env "MACOSX_DEPLOYMENT_TARGET=${CMAKE_OSX_DEPLOYMENT_TARGET}")
    endif()
    set(boson_toolchain_file "${CMAKE_TOOLCHAIN_FILE}")
    if(NOT boson_toolchain_file)
        set(boson_toolchain_file "$ENV{CMAKE_TOOLCHAIN_FILE}")
    endif()
    if(boson_toolchain_file)
        get_filename_component(boson_toolchain_file "${boson_toolchain_file}" ABSOLUTE)
        list(APPEND boson_cargo_env "CMAKE_TOOLCHAIN_FILE=${boson_toolchain_file}")
    endif()
    if(DEFINED ENV{CMAKE_BUILD_PARALLEL_LEVEL})
        list(APPEND boson_cargo_env "CARGO_BUILD_JOBS=$ENV{CMAKE_BUILD_PARALLEL_LEVEL}")
    endif()

    add_custom_target(quiche_ffi ALL
        COMMAND "${CMAKE_COMMAND}" -E env ${boson_cargo_env}
                "${CARGO_EXECUTABLE}" ${BOSON_CARGO_SUBCOMMAND} rustc --release --locked --target "${RUST_TARGET}"
                --manifest-path "${boson_driver}/Cargo.toml" -- --print=native-static-libs
        BYPRODUCTS "${boson_rust_archive}"
        WORKING_DIRECTORY "${CMAKE_BINARY_DIR}"
        COMMENT "Building the pinned quiche archive for ${RUST_TARGET}"
        VERBATIM)
endif()

# ---------------------------------------------------------------------------
# JNI library.
# ---------------------------------------------------------------------------
add_library(boson_quiche SHARED "${BOSON_SOURCE}/boson_quiche.c")
set_target_properties(boson_quiche PROPERTIES
    C_STANDARD 11 C_STANDARD_REQUIRED YES C_VISIBILITY_PRESET hidden)
target_include_directories(boson_quiche PRIVATE
    "${QUICHE_INCLUDE}" "${JNI_INCLUDE}" "${JNI_PLATFORM_INCLUDE}")

# Link the pinned archive directly and before the platform and C++ runtime
# libraries. With a static libstdc++ the archive must precede -lstdc++, or the
# C++ symbols it pulls in stay unresolved.
if(QUICHE_ARCHIVE)
    target_link_libraries(boson_quiche PRIVATE "${QUICHE_ARCHIVE}")
else()
    add_dependencies(boson_quiche quiche_ffi)
    target_link_libraries(boson_quiche PRIVATE "${boson_rust_archive}")
endif()
target_compile_definitions(boson_quiche PRIVATE
    BOSON_BINDING_ABI=${BOSON_BINDING_ABI} BOSON_BINDING_VERSION="${BOSON_BINDING_VERSION}")

if(MSVC)
    set_property(TARGET boson_quiche PROPERTY MSVC_RUNTIME_LIBRARY MultiThreaded)
    target_compile_options(boson_quiche PRIVATE /W4 /WX /wd4100)
    if(LINK_SUPPORT)
        file(GLOB boson_import_libraries "${LINK_SUPPORT}/*.lib")
        target_link_libraries(boson_quiche PRIVATE ${boson_import_libraries})
    endif()
    target_link_libraries(boson_quiche PRIVATE
        advapi32 legacy_stdio_definitions kernel32 ntdll userenv ws2_32 dbghelp)
else()
    target_compile_options(boson_quiche PRIVATE
        -Wall -Wextra -Werror -Wno-unused-parameter)
    if(APPLE)
        # Export exactly the JNI entry points. The list comes from the C sources
        # compiled here, never from the Java declarations.
        file(GLOB boson_jni_sources "${BOSON_SOURCE}/*.c" "${BOSON_SOURCE}/*.inc")
        set(boson_exports "_JNI_OnLoad" "_JNI_OnUnload")
        foreach(source IN LISTS boson_jni_sources)
            file(READ "${source}" boson_text)
            string(REGEX MATCHALL "JNICALL JN\\([A-Za-z0-9_]+\\)" boson_names "${boson_text}")
            foreach(name IN LISTS boson_names)
                string(REGEX REPLACE "^JNICALL JN\\(([A-Za-z0-9_]+)\\)$" "\\1" boson_method "${name}")
                list(APPEND boson_exports "_Java_io_bosonnetwork_quiche_Native_${boson_method}")
            endforeach()
        endforeach()
        list(REMOVE_DUPLICATES boson_exports)
        list(SORT boson_exports)
        set(boson_exports_text "")
        foreach(export IN LISTS boson_exports)
            string(APPEND boson_exports_text "${export}\n")
        endforeach()
        file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/jni.exports" "${boson_exports_text}")
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

option(BOSON_TEST_NATIVES "Build isolated native loader fixtures" OFF)
if(BOSON_TEST_NATIVES)
    add_subdirectory(src/test/c)
endif()

# ---------------------------------------------------------------------------
# Maven install layout. Maven decides where packaged files go; CMake decides
# what they are. Only a target with a known classifier produces an install
# tree, so the cross-compile driver keeps working without one.
# ---------------------------------------------------------------------------
if(BOSON_TARGET)
    if(NOT BOSON_CLASSIFIER)
        message(FATAL_ERROR "BOSON_CLASSIFIER is required with BOSON_TARGET; "
                            "see native/platforms.json")
    endif()
    install(TARGETS boson_quiche
        LIBRARY DESTINATION "native/${BOSON_CLASSIFIER}"
        RUNTIME DESTINATION "native/${BOSON_CLASSIFIER}")
    if(BOSON_TEST_NATIVES)
        install(DIRECTORY "${CMAKE_BINARY_DIR}/test-libraries/"
            DESTINATION "test-libraries")
    endif()
    configure_file("${CMAKE_CURRENT_SOURCE_DIR}/cmake/build-info.json.in"
                   "${CMAKE_CURRENT_BINARY_DIR}/build-info.json" @ONLY)
    install(FILES "${CMAKE_CURRENT_BINARY_DIR}/build-info.json"
        DESTINATION "native/${BOSON_CLASSIFIER}")
endif()
