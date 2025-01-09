project('android usecase', 'c')
fs = import('fs')

e = executable('executable', 'usecase.c',
  android_usecase : 'executable')
a = executable('application', 'usecase.c',
  android_usecase : 'application')

if fs.name(e.full_path()).contains('.')
  error('Executable with usecase `executable` did have expected filename')
endif

if not fs.name(a.full_path()).startswith('lib') or not fs.name(a.full_path()).endswith('.so')
  error('Executable with usecase `application` did not have expected filename')
endif
