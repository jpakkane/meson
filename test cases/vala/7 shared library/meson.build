project('shared library', 'vala', 'c', default_options: ['b_legal_code=false'])

valadeps = [dependency('glib-2.0'), dependency('gobject-2.0')]

libinc = include_directories('lib')

subdir('lib')
subdir('prog')

test('valasharedtest', e)
