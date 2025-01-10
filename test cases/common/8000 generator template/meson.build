# SPDX-License-Identifier: Apache-2.0
# Copyright © 2024 Intel Corporation

project(
  'generator.template tests',
  meson_version : '>= 1.5',
)

gen = import('unstable-generator')

tmpl1 = gen.template(
  'tmpl1',
  command : [find_program('generator.py'), '@OUTPUT@', '@INPUT@'],
)

output = tmpl1.call(
  '123',
  output : ['123.txt'],
  input : ['data/1.txt', 'data/2.txt', 'data/3.txt'],
)

prog_test = find_program('test.py')
test('123', prog_test, args : [output, '123'])

tmpl2 = tmpl1.extend('1234', input : ['data/1.txt', 'data/2.txt'])

output = tmpl2.call(
  '1223',
  output : ['1223.txt'],
  input : ['data/2.txt', 'data/3.txt'],
)
test('1223', prog_test, args : [output, '1223'])
