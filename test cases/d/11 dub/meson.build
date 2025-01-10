project('dub-example', 'd')

dub_exe = find_program('dub', required : false)
if not dub_exe.found()
  error('MESON_SKIP_TEST: Dub not found')
endif

dub_ver = dub_exe.version()
if dub_ver.version_compare('>1.31.1') and dub_ver.version_compare('<1.35.0')
  error('MESON_SKIP_TEST: Incompatible Dub version ' + dub_ver)
endif

urld_dep = dependency('urld', method: 'dub')

test_exe = executable('test-urld', 'test.d', dependencies: urld_dep)
test('test urld', test_exe)

# If you want meson to generate/update a dub.json file
dlang = import('dlang')
dlang.generate_dub_file(meson.project_name().to_lower(), meson.build_root(),
                        authors: 'Meson Team',
                        description: 'Test executable',
                        copyright: 'Copyright © 2018, Meson Team',
                        license: 'MIT',
                        sourceFiles: 'test.d',
                        targetType: 'executable',
                        dependencies: urld_dep
)
