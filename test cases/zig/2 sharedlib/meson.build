project('zigtest-shared-lib', 'zig')

lib = shared_library('hello', 'src/hello.zig',
    version: '1.0.0',
    install: true
)
executable('zigtest-shared-lib', 'src/main.zig',
    link_with: lib,
    install: true
)
