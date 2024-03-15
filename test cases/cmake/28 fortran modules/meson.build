# While this top-level project is all C, what we really want to test for is
# correct handling of the cmake-based fortran subproject, and to be able to
# create "wrapping" libraries and executables in the main project.
project('fortran modules')

if not add_languages('c', required: false)
  error('MESON_SKIP_TEST: C language not available.')
endif
if not add_languages('fortran', required: false)
  error('MESON_SKIP_TEST: Fortran language not available.')
endif

cm = import('cmake')

sub_pro = cm.subproject('fortproj')
sub_sta = sub_pro.dependency('fortproj')

# 1. build exe linked with static library.
lib_sta = static_library(
    'stalib',
    'mylib.c',
    dependencies: [sub_sta],
    install: true,
)
exe_sta = executable('exe_sta', files('main.c', 'mylib.h'), link_with: lib_sta)
test('test_sta', exe_sta)

# 2. build exe linked with dynamic library.
# Use workaround with intermediate static lib from https://github.com/mesonbuild/meson/issues/10764
intermediate_static_lib = static_library(
    'fortproj_intermediate',
    'empty.c',
    dependencies: sub_sta,
    pic: true,
    install: false
)
intermediate_dependency = declare_dependency(
    link_with: intermediate_static_lib,
    include_directories: sub_pro.include_directories('fortproj')
)
lib_dyn = shared_library(
    'dynlib',
    'mylib.c',
    name_prefix: '',  # to avoid battling meson's test framework too hard
    dependencies: [intermediate_dependency],
    install: true,
)
exe_dyn = executable('exe_dyn', files('main.c', 'mylib.h'), link_with: lib_dyn)
test('test_dyn', exe_dyn)
