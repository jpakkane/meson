project('ignoring args for checks', 'c',
    version : '0.1',
    default_options : 'werror=true',
)

test_program = '''
#ifdef @0@
#error FAIL FAIL FAIL
FAIL FAIL FAIL
#endif
'''

add_project_arguments('-DMESON_CC_CHECKS_SHOULDNT_SEE_ME__FUNC=1', language: 'c')

cc = meson.get_compiler('c')

define_to_check = get_option('define_to_check')
define_expected = true

if define_to_check == ''
  add_project_arguments('-DMESON_CC_CHECKS_SHOULDNT_SEE_ME__FUNC=1', language: 'c')
  define_to_check = 'MESON_CC_CHECKS_SHOULDNT_SEE_ME__FUNC'
  define_expected = false
endif


if define_expected
  if cc.get_define(define_to_check) == ''
    error('Compiler argument has no effect on compiler check (compiler.get_define) but should!')
  endif

  if cc.compiles(test_program.format(define_to_check))
    error('Compiler argument has no effect on compiler check (compiler.compiles) but should!')
  endif
else
  if cc.get_define(define_to_check) != ''
    error('Compiler argument has effect on compiler check (compiler.get_define) but should not!')
  endif

  if not cc.compiles(test_program.format(define_to_check))
    error('Compiler argument has effect on compiler check (compiler.compiles) but should not!')
  endif
endif
