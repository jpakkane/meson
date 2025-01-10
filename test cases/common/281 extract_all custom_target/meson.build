project('extract all custom', 'c')
fs = import('fs')

copy = find_program('copy.py')
meson.override_find_program('copy', copy)
gen = generator(copy,
    output : 'gen_@PLAINNAME@',
    arguments: ['@INPUT@', '@OUTPUT@'])
src_gen = gen.process('gen1.c', 'sub/gen2.c')

i = 0
src_custom = []
foreach f : ['custom1.c', 'sub/custom2.c']
    i += 1
    src_custom += [custom_target('custom' + i.to_string(),
        input : f,
        output : 'gen_' + fs.name(f),
        command : [copy, '@INPUT@', '@OUTPUT@'])
    ]
endforeach

s1 = subproject('s1')
sub_a = s1.get_variable('sub_a')
sub_b = s1.get_variable('sub_b')
subsub_a = s1.get_variable('s2').get_variable('subsub_a')

# Use objects from subproject and subsubproject
a = static_library('a',
    sources : [src_gen, src_custom],
    objects : [sub_a.extract_all_objects(recursive: true), subsub_a.extract_all_objects(recursive: true)]
)
e1= executable('e1',
    sources: ['main.c'],
    link_with : a
)

# link with lib that uses objects from subproject of subproject
e2 = executable('e2',
    sources : ['main.c', src_gen, src_custom],
    link_with : [sub_b]
)
test('test_e1', e1)
test('test_e2', e2)
