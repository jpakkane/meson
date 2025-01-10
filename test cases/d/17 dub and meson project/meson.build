project('Meson integration with dub.json', 'd')

dub_exe = find_program('dub', required : false)
if not dub_exe.found()
    error('MESON_SKIP_TEST: Dub not found')
endif

dub_ver = dub_exe.version()
if not dub_ver.version_compare('>=1.35.0')
  error('MESON_SKIP_TEST: test requires dub >=1.35.0')
endif

# Multiple versions supported
urld = dependency('urld', method: 'dub', version: [ '>=3.0.0', '<3.0.1' ])

# The version we got is the one in dub.selections.json
version = urld.version()
if version != '3.0.0'
  error(f'Expected urld version to be the one selected in dub.selections.json but got @version@')
endif

# dependency calls from subdirectories respect meson.source_root()/dub.selections.json
subdir('x/y/z')

# dependencies respect their configuration selected in dub.json
run_command(dub_exe, 'build', '--deep', ':multi-configuration',
            '--compiler', meson.get_compiler('d').cmd_array()[0],
            '--arch', host_machine.cpu_family(),
            '--root', meson.source_root(),
            '--config', 'lib',
            check: true)
found = dependency('17-dub-meson-project:multi-configuration', method: 'dub')
