# This test uses zlib to verify static and dynamic linkages.
# A C program is used to call a single zlib function (zlibVersion).
# The nm utility is then used to check for the existence of this symbol
# in the resulting binary.

project('static dynamic', 'c')

s = get_option('static')

if s and host_machine.system() == 'sunos'
  error('MESON_SKIP_TEST: static zlib linkage is not supported on SunOS by default')
endif

cc = meson.get_compiler('c')

z = cc.find_library('z', static: s)

exe = executable('print_zlib_version', 'main.c', dependencies: [z])

# first step: the executable should compile and work
test('test zlib', exe)

# to check the zlib static/dynamic symbols in the resulting binary
find_program('nm')

# second step: static linkage
test('verify static zlib linking', find_program('verify_zlib_linkage.py'),
  args: ['--platform=' + host_machine.system(), '--static', exe.full_path()],
  depends: [exe], should_fail: not s)

# third step: dynamic linkage
test('verify dynamic zlib linking', find_program('verify_zlib_linkage.py'),
  args: ['--platform=' + host_machine.system(), exe.full_path()],
  depends: [exe], should_fail: s)
