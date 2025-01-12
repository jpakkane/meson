project('d importC', 'd')

if meson.get_compiler('d').get_id() == 'gcc'
    error('MESON_SKIP_TEST: C preprocessor directive #include is not supported by GDC')
endif

e = executable(
  'd_importc',
  sources: [
    'file1.i',
    'file2.c',
    'dmain.d',
  ],
)

test('d_importc', e)
