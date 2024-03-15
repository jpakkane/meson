add_library(
  ${PROJECT_NAME}-libinnercalc
  STATIC
  
  innercalc.f90
  collections.F90
  )

target_include_directories(
  ${PROJECT_NAME}-libinnercalc
  INTERFACE "${CMAKE_CURRENT_BINARY_DIR}")
