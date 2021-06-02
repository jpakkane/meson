project('mainprog', 'c')

assert(get_option('buildtype') == 'debug')
subproject('somesub')
subproject('othersub')

executable('toplevel', 'toplevel.c')
