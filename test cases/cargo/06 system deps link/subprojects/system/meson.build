project('system', 'c', version: '0.2')


system_dep = declare_dependency(link_with: library('system', 'lib.c'))
meson.override_dependency('system', system_dep)
