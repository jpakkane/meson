project('Dub dependency not in dub.json')

if not add_languages('d', required: false)
  error('MESON_SKIP_TEST test requires D compiler')
endif

dub_exe = find_program('dub', required : false)
if not dub_exe.found()
    error('MESON_SKIP_TEST: Dub not found')
endif

dub_ver = dub_exe.version()
if not dub_ver.version_compare('>=1.35.0')
  error('MESON_SKIP_TEST: test requires dub >=1.35.0')
endif

dep = dependency('urld', method: 'dub') # not in dub.json
