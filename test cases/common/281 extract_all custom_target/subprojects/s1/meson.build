project('subproj', 'c')

fs = import('fs')
copy = find_program('copy')

i = 2
src_custom = []
foreach f : ['custom3.c', 'sub/custom4.c']
    i += 1
    src_custom += [custom_target('custom' + i.to_string(),
        input : f,
        output : 'gen_' + fs.name(f),
        command : [copy, '@INPUT@', '@OUTPUT@'])
    ]
endforeach

gen = generator(copy,
    output : 'gen_@PLAINNAME@',
    arguments: ['@INPUT@', '@OUTPUT@'])
src_gen = gen.process('gen3.c', 'sub/gen4.c')

s2 = subproject('s2')
subsub_a = s2.get_variable('subsub_a')

sub_a = static_library('sub_a', sources : [src_custom, src_gen])
sub_b = static_library('sub_b', objects : [sub_a.extract_all_objects(recursive: true), subsub_a.extract_all_objects(recursive: true)])