# SPDX-License-Identifier: Apache-2.0
# Copyright © 2024 Intel Corporation

project('flex and bison', 'c')

# The point of this test is that one generator
# may output headers that are necessary to build
# the sources of a different generator.

# TODO: handle win_flex/win_bison

flex = find_program('flex', 'lex', required: false)
bison = find_program('bison', required: false)

if not flex.found()
  error('MESON_SKIP_TEST flex not found.')
endif

if not bison.found()
  error('MESON_SKIP_TEST bison not found.')
endif

codegen = import('unstable-codegen')
lfiles = codegen.lex('lexer.l')

pgen = generator(bison,
output : ['@BASENAME@.tab.c', '@BASENAME@.tab.h'],
arguments : ['@INPUT@', '--defines=@OUTPUT1@', '--output=@OUTPUT0@'])

pfiles = pgen.process('parser.y')

e = executable(
  'pgen',
  'prog.c', lfiles, pfiles,
  override_options : ['unity=off'],
)

test('parsertest', e,
    args: [meson.current_source_dir() / 'testfile'])
