project('isystem includes', 'c', default_options : 'werror=true')

cc = meson.get_compiler('c')

# Canary warning to check suppression in system headers. Chosen randomly from GCC docs.
incwarg = '-Wsizeof-array-div'

add_project_dependencies(
  declare_dependency(
    include_directories: include_directories('global_include', is_system: true),
  ),
  language: ['c'],
)

local_inc_dep1 = declare_dependency(
  include_directories: 'local_include1',
).as_system().partial_dependency(includes : true)

if cc.has_argument(incwarg)
  executable('main', 'main.c', c_args: incwarg, dependencies: local_inc_dep1)
else
  error('MESON_SKIP_TEST compiler does not support emitting canary warning.')
endif
