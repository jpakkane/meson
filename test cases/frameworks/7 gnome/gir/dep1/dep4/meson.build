dep4_inc = include_directories('.')
dep4_dep = declare_dependency(
  dependencies : gobj,
  include_directories : [dep4_inc],
)

# Manually run g-ir-compiler
g_ir_compiler = find_program('g-ir-compiler')
custom_target(
  'dep4_typelib',
  build_by_default: true,
  command: [g_ir_compiler, '--output', '@OUTPUT@', '@INPUT@'],
  input: 'MesonDep4-1.0.gir',
  output: 'MesonDep4-1.0.typelib',
  install: false,
)
