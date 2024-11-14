project('multi_targets', 'c')
subdir('init_features')

multi_targets = mod_features.multi_targets(
    'dispatch1.conf.h', 'dispatch1.c',
    dispatch: [SSSE3, ASIMD],
    baseline: [SSE3, NEON]
)

multi_targets.extend(mod_features.multi_targets(
    'dispatch2.conf.h', 'dispatch2.c',
    dispatch: [SSE41, SSSE3, ASIMD],
    baseline: [SSE3]
))

multi_targets.extend(mod_features.multi_targets(
    'dispatch3.conf.h', 'dispatch3.c',
    dispatch: []
))

exe = executable(
    'multi_targets', 'main.c',
    link_with: multi_targets.static_lib('multi_targets_lib')
)

test('multi_targets', exe)
