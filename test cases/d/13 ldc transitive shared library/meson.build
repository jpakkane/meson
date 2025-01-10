project('D Ldc Transitive Shared Library', 'd')

dc = meson.get_compiler('d')
if dc.get_id() == 'gcc'
  if dc.version().version_compare('< 8')
    error('MESON_SKIP_TEST: GDC < 8.0 can not build shared libraries')
  endif
endif

lib_two = shared_library('two', 'libtwo.d')
lib_one = shared_library('one', 'libone.d', link_with: lib_two)

ed = executable('app_d', 'app.d', link_with : lib_one)
test('linktest_dyn', ed)
