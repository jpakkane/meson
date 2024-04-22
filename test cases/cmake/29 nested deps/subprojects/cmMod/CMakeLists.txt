cmake_minimum_required(VERSION 3.5)

project(cmMod)
set (CMAKE_CXX_STANDARD 14)

include_directories(${CMAKE_CURRENT_BINARY_DIR})

add_library(cmModLib1 STATIC cmMod.cpp)
add_library(cmModLib2 STATIC cmMod.cpp)
target_compile_definitions(cmModLib1 PRIVATE cmModClass=cmModClass1)
target_compile_definitions(cmModLib2 PRIVATE cmModClass=cmModClass2)
target_link_libraries(cmModLib1 PUBLIC cmModLib2)
