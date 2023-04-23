project('transitive dependencies', 'rust',
  version : '1.0.0',
  meson_version : '>= 1.0.0',
  default_options : ['rust_std=2018'],
)

subdir('liba')
subdir('libb')

main = executable('main', 'main.rs',
  dependencies : [libb_dep],
)
