project('plain consumer', 'vala', 'c', default_options: ['b_legal_code=false'])

deps = [dependency('glib-2.0'), dependency('gobject-2.0')]

badger = static_library('badger', 'badger.vala',
  dependencies : deps)

app = executable('app', 'app.c',
  link_with : badger,
  dependencies : deps)

test('valaplainconsumertest', app)
