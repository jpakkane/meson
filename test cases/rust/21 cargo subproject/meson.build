project('cargo subproject', 'c')

foo_dep = dependency('foo-rs', native : true)
exe = executable('app_native', 'main.c',
  dependencies: foo_dep,
  native : true,
)

foo_dep = dependency('foo-rs')
exe = executable('app', 'main.c',
  dependencies: foo_dep,
)
test('cargo-test', exe)
