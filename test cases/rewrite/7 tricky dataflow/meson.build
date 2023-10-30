project('rewrite tricky dataflow', 'c')

# Adding a file to `begin` will add this file to the sources of `tgt1`, but
# not to any other target. But a buggy rewriter might think that adding a file
# to `begin` will also add this file to `end` and will refuse to add a file to
# `begin`.
begin = ['foo.c']
tgt1 = library('tgt1', begin)
distraction = executable('distraction', link_with: tgt1)


tgt2_srcs = ['foo.c']
if meson.host_machine().system() == 'windows' # Some condition that cannot be known statically
    tgt2_srcs += ['bar.c']
endif
executable('tgt2', tgt2_srcs)


tgt34_srcs = ['foo.c']
executable('tgt3', tgt34_srcs)
if meson.host_machine().system() == 'windows'
    tgt34_srcs += ['bar.c']
endif
executable('tgt4', tgt34_srcs)


dont_add_here_5 = ['foo.c']
ct = custom_target('ct', output: 'out.c', input: dont_add_here_5, command: ['placeholder', '@INPUT@', '@OUTPUT@'])
executable('tgt5', ct)


dont_add_here_6 = ['foo.c']
gen = generator(find_program('cp'), output: '@BASENAME@_copy.c', arguments: ['@INPUT@', '@OUTPUT@'])
generated = gen.process(dont_add_here_6)
executable('tgt6', generated)
