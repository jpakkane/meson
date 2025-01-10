project(
    'skip test',
    meson_version: '>=1.5',
)

py = find_program('python3')
foo = find_program('not_a_program', required: false)

test(
    'skip',
    py,
    args: ['-c', 'raise SystemExit(1)'],
    skip: true,
)

test(
    'dont skip',
    py,
    args: ['-c', 'raise SystemExit(1)'],
    skip: false,
    should_fail: true,
)

test(
    'not found',
    foo,
    skip: not foo.found(),
)
