project('shared library linking test', 'c', 'cpp')
message('prefix is ' + get_option('prefix'))
mod = shared_module('mymod', 'libfile.c')

exe = executable('prog', 'main.c', link_with : mod, install : true)