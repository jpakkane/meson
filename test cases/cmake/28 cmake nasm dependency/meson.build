project('cmake nasm dependency', ['c', 'cpp'])

if meson.is_cross_build()
  error('MESON_SKIP_TEST: skip this on cross builds')
endif

if get_option('backend').startswith('vs')
  error('MESON_SKIP_TEST: nasm is not supported by vs backend')
endif

if not add_languages('nasm', required: false, native: false)
  error('MESON_SKIP_TEST: nasm not found')
endif

# Using this dependency triggers CMakeToolchain.update_cmake_compiler_state(),
# and with nasm as a language, resulted in a warning
# "Failed to determine CMake compilers state" after nasm was added as a language.
sub_dep = dependency('cmTest')

exe1 = executable('exe1', ['main.c'], dependencies: [sub_dep])
test('test1', exe1)
