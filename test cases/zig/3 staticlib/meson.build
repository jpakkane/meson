project('zigtest-static-lib', 'zig')

lib = static_library('hello', 'src/hello.zig')
executable('zigtest-static-lib', 'src/main.zig',
    link_with: lib
)
