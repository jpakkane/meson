snippets = import('snippets')

lib_incdir = include_directories('..')
lib_args = ['-DMY_LIB_COMPILATION']
lib_static_args = ['-DMY_LIB_STATIC_COMPILATION']

# Typically would be:
#
# h = snippets.symbol_visibility_header('apiconfig.h',
#  static_only: get_option('default_library') == 'static',
# )
# library('mylib', ...)
#
# But for the unit test we want to test all cases regardless of default_library
# option. Also on Windows default_library=both is not supported because c_args
# are different, so we build shared and static separately.

h = snippets.symbol_visibility_header('apiconfig.h')
install_headers(h, 'lib.h', subdir: 'mylib')
libsta = static_library('mylib', 'lib.c',
  include_directories: lib_incdir,
  gnu_symbol_visibility: 'hidden',
  c_args: lib_args + lib_static_args,
  install: true)
libsha = shared_library('mylib', 'lib.c',
  include_directories: lib_incdir,
  gnu_symbol_visibility: 'hidden',
  c_args: lib_args,
  install: true)
mylib_sta_dep = declare_dependency(link_with: libsta,
  include_directories: lib_incdir,
  compile_args: lib_static_args)
mylib_sha_dep = declare_dependency(link_with: libsha,
  include_directories: lib_incdir)
meson.override_dependency('mylib-sta', mylib_sta_dep)
meson.override_dependency('mylib-sha', mylib_sha_dep)
pkg.generate(libsta,
  extra_cflags: lib_static_args,
)

# When using static_only, we don't need lib_static_args because
# MY_LIB_STATIC_COMPILATION gets defined in the generated header.
h = snippets.symbol_visibility_header('apiconfig-static-only.h',
  static_only: true)
install_headers(h, 'lib-static-only.h', subdir: 'mylib')
libstaticonly = static_library('static-only', 'lib-static-only.c',
  include_directories: lib_incdir,
  gnu_symbol_visibility: 'hidden',
  c_args: lib_args,
  install: true)
static_only_dep = declare_dependency(link_with: libstaticonly,
  include_directories: lib_incdir)
meson.override_dependency('static-only', static_only_dep)
pkg.generate(libstaticonly)
