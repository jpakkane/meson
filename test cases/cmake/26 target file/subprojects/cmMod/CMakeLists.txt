cmake_minimum_required(VERSION 3.7)

project(cmMod)
set(CMAKE_CXX_STANDARD 14)

add_executable(cm_exe_local local.cpp)

# I wanted to test the IMPORTED flag, so I did this:
# add_executable(cm_exe_imported IMPORTED)
# set_property(TARGET cm_exe_imported PROPERTY IMPORTED_LOCATION "/usr/bin/cp")
# But the CI test failed since /usr/bin/cp does not exist on every machine.
if(EXISTS "/usr/bin/cp")
  add_executable(cm_exe_imported IMPORTED)
  set_property(TARGET cm_exe_imported PROPERTY IMPORTED_LOCATION "/usr/bin/cp")
else()
  add_executable(cm_exe_imported fallback.cpp)
endif()


add_custom_command(OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/output1.cpp
  COMMAND $<TARGET_FILE:cm_exe_local> ${PROJECT_SOURCE_DIR}/input1.txt ${CMAKE_CURRENT_BINARY_DIR}/output1.cpp
  #COMMAND $<TARGET_FILE:cm_exe_local> ${PROJECT_SOURCE_DIR}/input1.txt ${CMAKE_CURRENT_BINARY_DIR}/output1.cpp
  DEPENDS cm_exe_local
  DEPENDS input1.txt)
add_custom_command(OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/output2.cpp
  COMMAND $<TARGET_FILE:cm_exe_imported> ${PROJECT_SOURCE_DIR}/input2.txt ${CMAKE_CURRENT_BINARY_DIR}/output2.cpp
  DEPENDS cm_exe_imported
  DEPENDS input2.txt)

add_custom_target(output1_cpp
  DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/output1.cpp")
add_custom_target(output2_cpp
  DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/output2.cpp")

add_library(final SHARED final.cpp ${CMAKE_CURRENT_BINARY_DIR}/output1.cpp ${CMAKE_CURRENT_BINARY_DIR}/output2.cpp)
add_dependencies(final output1_cpp output2_cpp)
target_include_directories(final
    PUBLIC
        ${PROJECT_SOURCE_DIR}/include
)
