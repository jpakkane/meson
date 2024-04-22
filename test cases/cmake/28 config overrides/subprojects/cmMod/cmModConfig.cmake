# Check if meson correctly sets the build type and resolves the correct entry
add_library(cmMod::cmModLib++ STATIC IMPORTED)

# Construct the name of the library that was built
# (cmake in meson does not support TARGET_FILE generator expression unless the target is imported)
get_target_property(CMMOD_LIB_DIR cmModLib_internal BINARY_DIR)
get_target_property(CMMOD_LIB_NAME cmModLib_internal NAME)

# meson Windows static library naming scheme
if(MSVC)
  set(CMMOD_LIB_PREFIX lib)
  set(CMMOD_LIB_SUFFIX .a)
else()
  set(CMMOD_LIB_PREFIX ${CMAKE_STATIC_LIBRARY_PREFIX})
  set(CMMOD_LIB_SUFFIX ${CMAKE_STATIC_LIBRARY_SUFFIX})
endif()

set(CMMOD_STATIC_LIB "${CMMOD_LIB_DIR}/../${CMMOD_LIB_PREFIX}${CMMOD_LIB_NAME}${CMMOD_LIB_SUFFIX}")

# Map both RELEASE and DEBUG to IMPORTED_SPECIAL
set_property(TARGET cmMod::cmModLib++ PROPERTY MAP_IMPORTED_CONFIG_RELEASE IMPORTED_SPECIAL)
set_property(TARGET cmMod::cmModLib++ PROPERTY MAP_IMPORTED_CONFIG_DEBUG IMPORTED_SPECIAL)

# Do not take this
set_property(TARGET cmMod::cmModLib++ PROPERTY IMPORTED_LOCATION ${CMAKE_BINARY_DIR}/invalid.a)

# Take this
set_property(TARGET cmMod::cmModLib++ PROPERTY IMPORTED_LOCATION_IMPORTED_SPECIAL ${CMMOD_STATIC_LIB})
