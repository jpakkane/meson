project('subproj', 'c')

fs = import('fs')
copy = find_program('copy')

gen = generator(copy,
    output : 'gen_@PLAINNAME@',
    arguments: ['@INPUT@', '@OUTPUT@'])
src_gen = gen.process('gen5.c', 'sub/gen6.c')

subsub_a = static_library('subsub_a', sources : [src_gen])