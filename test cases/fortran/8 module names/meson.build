# SPDX-License-Identifier: Apache-2.0
# Copyright © 2024 Intel Corporation

project('mod_name_case', 'fortran')

sources = ['test.f90', 'mod1.f90', 'mod2.f90']

l = static_library('s1', 'mod1.f90')
l2 = static_library('s2', 'mod2.f90', link_whole : l)
if get_option('unittest')
  sh = static_library('library', 'lib.f90', link_with : l2)
else
  exe = executable('mod_name_case', 'test.f90', link_with : l2)
  test('mod_name_case', exe)
endif
