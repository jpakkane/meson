project('cmake_code_gen', ['c', 'cpp'])

if meson.is_cross_build()
    error('MESON_SKIP_TEST: See https://github.com/mesonbuild/meson/pull/10607#issuecomment-1188117276 for an explanation.')
else
    cm = import('cmake')

    # Subproject with the "code generator"
    sub_pro = cm.subproject('cmMod')
    sub_final = sub_pro.dependency('final', include_type: 'system')

    # Build the exe
    exe = executable('main', ['main.cpp'], dependencies: [sub_final])

    test('test', exe)

endif
