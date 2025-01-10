project('include dirs type tests', 'cpp', meson_version: '>=1.3.0' )

fs = import('fs')

# Copy src header, with a modification, to build dir so we can test finding it though
# 'src-relative', 'build-relative', and 'src-and-build-relative' use types.
configure_file( input: 'whereareyoufindingme.h',
  output: 'whereareyoufindingme.h',
  configuration: {'SRC_DIR': 'build dir'}
  )

# Test that src-relative uses the unadulerated src header
exe_src = executable(
  'prog_src',
  'src/main.cpp',
  implicit_include_directories: false,
  include_directories: include_directories('.', build: false, source: true))
test('src-relative', exe_src, args: ['Hello from @SRC_DIR@'])

fs = import('fs')

# Test that build-relative uses the tweaked header, copied to the build dir.
exe_build = executable(
  'prog_build',
  'src/main.cpp',
  implicit_include_directories: false,
  include_directories: include_directories('.', build: true, source: false))
test('build-relative', exe_build, args: ['Hello from build dir'])

# Check 'src-and-build-relative' by including one header that's only found under the src and one that only found under the build dir.
subdir('moreheaders')
exe_both = executable(
  'prog_both',
  'src/main2.cpp',
  implicit_include_directories: false,
  include_directories: include_directories('moreheaders', build: true, source: true),
  dependencies: build_only_h_dep,
  )
test('both', exe_both, args: ['Src-only','Build-only'])

# Finally check the same but through ensuring that unspecified 'build' and 'source' defaults to both true
exe_both_default = executable(
  'prog_both_default',
  'src/main2.cpp',
  implicit_include_directories: false,
  include_directories: include_directories('moreheaders'),
  dependencies: build_only_h_dep,
  )
test('both default', exe_both_default, args: ['Src-only','Build-only'])
