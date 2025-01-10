# SPDX-License-Identifier: Apache-2.0
# Copyright © 2024 Intel Corporation

project('flex and bison', 'c')

# The point of this test is that one generator
# may output headers that are necessary to build
# the sources of a different generator.

# TODO: handle win_flex/win_bison

flex = find_program('reflex', 'flex', 'lex', required: false)
bison = find_program('bison', 'byacc', 'yacc', required: false)

if not flex.found()
  error('MESON_SKIP_TEST flex not found.')
endif

if not bison.found()
  error('MESON_SKIP_TEST bison not found.')
endif

codegen = import('unstable-codegen')
codegen.find_lex(implementations : ['lex', 'flex', 'reflex'])
lfiles = codegen.lex('lexer.l')
codegen.find_yacc(implementations : ['byacc', 'bison', 'yacc'])
pfiles = codegen.yacc('parser.y', header : '@BASENAME@.tab.h')

e = executable(
  'pgen',
  'prog.c', lfiles, pfiles,
  override_options : ['unity=off'],
)

test('parsertest', e,
    args: [meson.current_source_dir() / 'testfile'])
