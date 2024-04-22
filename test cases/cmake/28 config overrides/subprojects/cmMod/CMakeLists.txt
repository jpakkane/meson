cmake_minimum_required(VERSION 3.5)

project(cmMod)
set (CMAKE_CXX_STANDARD 14)

if(NOT ${CMAKE_BUILD_TYPE} STREQUAL "Release" AND NOT ${CMAKE_BUILD_TYPE} STREQUAL "Debug")
  message(FATAL_ERROR "CMAKE_BUILD_TYPE not set")
endif()

add_library(cmModLib_internal STATIC cmMod.cpp)

add_library(cmModLib++ INTERFACE)
set(cmMod_DIR ${CMAKE_CURRENT_SOURCE_DIR})
find_package(cmMod CONFIG)
target_link_libraries(cmModLib++ INTERFACE cmMod::cmModLib++)
