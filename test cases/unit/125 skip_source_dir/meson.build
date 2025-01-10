project('skip_source_dir',
  meson_version: '>=1.7.0',
)

summary({
  'no args': run_command(find_program('executable.py'), capture: true, check: true).stdout(),
  'skip_source_dir: true': run_command(find_program('executable.py', skip_source_dir: false), capture: true, check: true).stdout(),
  'skip_source_dir: false': run_command(find_program('executable.py', skip_source_dir: true), capture: true, check: true).stdout(),
}, section: 'output')
