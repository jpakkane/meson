cmake_minimum_required(VERSION 3.17)

project(
    FORTPROJ
    LANGUAGES Fortran
)

add_subdirectory("libinnercalc")

set(sources "fortproj.f90")
add_library(fortproj STATIC "${sources}")
target_link_libraries(fortproj PUBLIC ${PROJECT_NAME}-libinnercalc)
target_include_directories(fortproj
    PUBLIC
    "${CMAKE_CURRENT_BINARY_DIR}"
)

add_executable(test "test.f90")
target_link_libraries(test
  PRIVATE
  fortproj
)
add_test(NAME "test" COMMAND test)
