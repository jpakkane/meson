project(libb CXX)
add_library(libb src/libb.cc)
target_include_directories(libb INTERFACE ${CMAKE_CURRENT_SOURCE_DIR}/src)
