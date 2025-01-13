project(libc CXX)
add_library(libc src/libc.cc)
target_link_libraries(libc libb)
target_include_directories(libc INTERFACE ${CMAKE_CURRENT_SOURCE_DIR}/src)
