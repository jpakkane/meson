project('zigtest-polyglot', 'c', 'zig')

lib = library('hello', 'src/hello.c')
executable('zigtest-polyglot', 'src/main.zig',
    link_with: lib
)
