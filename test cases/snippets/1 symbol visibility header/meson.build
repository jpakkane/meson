project('symbol visibility header', 'c')

sta_dep = dependency('mylib-sta', fallback: 'sub')
exe = executable('exe-sta', 'main.c', dependencies: sta_dep)
test('test-sta', exe)

sha_dep = dependency('mylib-sha', fallback: 'sub')
exe = executable('exe-sha', 'main.c', dependencies: sha_dep)
test('test-sha', exe)

static_only_dep = dependency('static-only', fallback: 'sub')
exe = executable('exe-static-only', 'main-static-only.c', dependencies: static_only_dep)
test('test-static-only', exe)
