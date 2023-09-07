project('response file test', default_options: ['backend=null'])

args = ['a', 'b', 'c']
rf = response_file(
    args, 'd', 'e', 'f',
    separator: '\n',
    quote: false,
    max_args_length: get_option('max_args'),
)

py = find_program('python3')

rt = run_target(
    'rt',
    command: [py, meson.current_source_dir() / 'recordargs.py',
        meson.current_build_dir() / 'argv.txt',
        meson.current_build_dir() / 'parsed.txt',
        rf
    ],
)

rc = run_command(
    py, meson.current_source_dir() / 'recordargs.py',
    meson.current_build_dir() / 'rc_argv.txt',
    meson.current_build_dir() / 'rc_parsed.txt',
    rf
)


ct = custom_target(
    'ct',
    output: ['argv.txt', 'parsed.txt'],
    command: [py, meson.current_source_dir() / 'recordargs.py', '@OUTPUT@', rf],
)

test(
    'test-args',
    py,
    args: [
        meson.current_source_dir() / 'testargs.py',
        '--nargs', '6',
        ct[0].full_path(),
        ct[1].full_path(),
    ],
    depends: [ct],
    timeout: 0,
)


cf = configure_file(
    command: [py, meson.current_source_dir() / 'recordargs.py', '@OUTPUT@', 'cf_parsed.txt', rf],
    output: 'cf_argv.txt',
)

test(
    'test-cf-args',
    py,
    args: [
        meson.current_source_dir() / 'testargs.py',
        '--nargs', '6',
        cf,
        meson.current_build_dir() / 'cf_parsed.txt',
    ],
    timeout: 0,
)
