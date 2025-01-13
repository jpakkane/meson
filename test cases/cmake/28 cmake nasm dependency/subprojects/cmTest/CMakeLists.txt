cmake_minimum_required(VERSION ${CMAKE_VERSION})

project(cmTest)

#Detect processor
if ("${CMAKE_SYSTEM_PROCESSOR}" MATCHES "[Aa][Mm][Dd]64")
    SET(TEST_PROCESSOR "x86_64")
elseif ("${CMAKE_SYSTEM_PROCESSOR}" MATCHES "[Xx]86_64")
    SET(TEST_PROCESSOR "x86_64")
elseif ("${CMAKE_SYSTEM_PROCESSOR}" MATCHES "[Ii]386")
    SET(TEST_PROCESSOR "x86")
elseif ("${CMAKE_SYSTEM_PROCESSOR}" MATCHES "[Ii]686")
    SET(TEST_PROCESSOR "x86")
else ()
    message(FATAL_ERROR "MESON_SKIP_TEST: Unsupported Assembler Platform ${CMAKE_SYSTEM_PROCESSOR}")
endif ()

enable_language(ASM_NASM)

add_library(cmTest STATIC cmTest.c cmTestAsm.asm)
