project('install objects', 'c')


if host_machine.system() == 'cygwin'
  error('MESON_SKIP_TEST linuxlike soversions not supported on Cygwin.')
endif

#TODO: install
subdir_done()

inst_objs_2_lib = compiled_objects('objs_lib', ['a.c', 'b.c', 'c.c'], install: true)

inst_objs_2_lib_objs = compiled_objects('objs_lib_ojbs',
    ['d.c', 'e.c', 'f.c'],
    install_dir: get_option('libdir') / 'objs',
    install: true
)
