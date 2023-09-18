project('mixed cpp', 'cpp', 'swift')

swiftc = meson.get_compiler('swift')

# Testing C++ and Swift interoperability requires Swift 5.9
if not swiftc.version().version_compare('>= 5.9')
  error('MESON_SKIP_TEST Test requires Swift 5.9')
endif

lib = static_library('mylib', 'mylib.cpp')
exe = executable('prog', 'main.swift', 'mylib.h', link_with: lib)
test('cpp interface', exe)
