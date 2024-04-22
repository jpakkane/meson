project('cmakeSubTest', ['c', 'cpp'])

cm = import('cmake')
sub_pro = cm.subproject('cmMod')

# TODO: CMake add_dependency does not work with INTERFACE targets
# This ensure that the library is built
tgt_internal = sub_pro.target('cmModLib_internal')

# use the library through a config file
sub_config = sub_pro.dependency('cmModLib++', include_type: 'system')
exe1 = executable('main', ['main.cpp'], dependencies: [sub_config], link_depends: [tgt_internal])
test('test1', exe1)
