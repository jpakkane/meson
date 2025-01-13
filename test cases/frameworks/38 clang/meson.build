# SPDX-License-Identifier: Apache-2.0
# Copyright © 2024 Intel Corporation

# C and C++ for are needed for cmake always
project('clangtest', 'c', 'cpp', default_options : ['c_std=c99', 'cpp_std=c++17'])

method = get_option('method')
static = get_option('link-static')
language = get_option('language')

test_file = files('test.cpp')

if language == 'c'
  dep_clang_c = dependency('clang', method : method, static : static, language : 'c', required : false)
  if not dep_clang_c.found()
    error('MESON_SKIP_TEST Could not find Clang for C language')
  endif
  exe = executable('parser', 'main.c', dependencies : dep_clang_c)
  test('C API', exe, args : [test_file])
else
  modules_to_find = [
    'clangAST',
    'clangASTMatchers',
    'clangAnalysis',
    'clangBasic',
    'clangDriver',
    'clangEdit',
    'clangFrontend',
    'clangLex',
    'clangParse',
    'clangSema',
    'clangSerialization',
    'clangSupport',
  ]

  dep_llvm = dependency('llvm', method : method == 'system' ? 'config-tool' : 'cmake', required : false)
  if not dep_llvm.found()
    error('MESON_SKIP_TEST Could not find LLVM, which is required for C++ test')
  endif
  if dep_llvm.version().version_compare('>= 18')
    modules_to_find += ['clangAPINotes']
  endif

  dep_clang_cpp = dependency('clang', modules : modules_to_find, method : method, static : static, language : 'cpp', required : false)
  if not dep_clang_cpp.found()
    error('MESON_SKIP_TEST Could not find Clang for C++ language')
  endif
  exe = executable('cpp-parser', 'main.cpp', dependencies : dep_clang_cpp)
  test('C++ API', exe, args : [test_file])
endif
