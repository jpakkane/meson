project('pkgconfig-get', 'c')

pkgg = import('pkgconfig')

subdir('simple2')

lib = library('simple', 'simple.c', dependencies: lib_dep)
libver = '1.0'
h = install_headers('simple.h')


pkgg.generate(
  lib,
  version : libver,
  name : 'libsimple',
  filebase : 'simple',
  description : 'A simple demo library.',
  libraries: [lib_dep],
)