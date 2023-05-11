project('vapi-test', ['c', 'vala'], default_options: ['c_legal_code=false'])

gnome = import('gnome')
subdir('libfoo')
subdir('libbar')

vapiexe = executable('vapigen-test',
  'main.vala',
  dependencies: [dependency('gobject-2.0'), libfoo_vapi, libbar_vapi],
  install: true,
)

test('vapigen-test', vapiexe)
