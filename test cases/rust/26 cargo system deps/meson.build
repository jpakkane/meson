project('cargo system-deps', 'rust')

glib = dependency('glib-2.0', required: false)
if not glib.found()
  error('MESON_SKIP_TEST: Need glib system dependency')
endif

sub_dep = dependency('sub-1-rs')
exe = executable('main', 'main.rs', dependencies : sub_dep)
test('main', exe)

