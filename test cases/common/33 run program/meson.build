project('run command', version : run_command('get-version.py', check : true).stdout().strip(), meson_version: '>=0.1.0')

if build_machine.system() == 'windows'
  c = run_command('cmd', '/c', 'echo', 'hello', check: false)
else
  c = run_command('echo', 'hello', check: false)
endif

correct = 'hello'

if c.returncode() != 0
  error('Executing echo failed.')
endif

result = c.stdout().strip()

if result != correct
  error('Getting stdout failed.')
endif

if c.stderr() != ''
  error('Extra text in stderr.')
endif

# Now the same with a script.

if build_machine.system() == 'windows'
  cs = run_command('scripts/hello.bat', check: false)
else
  cs = run_command('scripts/hello.sh', check: false)
endif

if cs.returncode() != 0
  error('Executing script failed.')
endif

if cs.stdout().strip() != correct
  error('Getting stdout failed (script).')
endif

if cs.stderr() != ''
  error('Extra text in stderr (script).')
endif

# We should be able to have files() in argument
f = files('meson.build')

if build_machine.system() == 'windows'
  c = run_command('cmd', '/c', 'echo', f, check: false)
else
  c = run_command('echo', f, check: false)
endif

if c.returncode() != 0
  error('Using files() in argument failed.')
endif

py3 = import('python3').find_python()

# No runtime output expected, not captured
ret = run_command(
    py3,
    '-c',
    'import sys; print("stdout|capture:false,console:false"); print("stderr|capture:false,console:false", file=sys.stderr)',
    check: true,
    capture: false,
    console: false,
)
assert(ret.returncode() == 0, 'failed to run python3: ' + ret.stderr())
assert(ret.stdout() == '', 'stdout is "@0@" instead of empty'.format(ret.stdout()))
assert(ret.stderr() == '', 'stderr is "@0@" instead of empty'.format(ret.stderr()))

# Expect runtime output, not captured
ret = run_command(
    py3,
    '-c',
    'import sys; print("stdout|capture:false,console:true"); print("stderr|capture:false,console:true", file=sys.stderr)',
    check: true,
    capture: false,
    console: true,
)
assert(ret.returncode() == 0, 'failed to run python3: ' + ret.stderr())
assert(ret.stdout() == '', 'stdout is "@0@" instead of empty'.format(ret.stdout()))
assert(ret.stderr() == '', 'stderr is "@0@" instead of empty'.format(ret.stderr()))

# No runtime output expected, but captured
ret = run_command(
    py3,
    '-c',
    'import sys; print("stdout|capture:true,console:false"); print("stderr|capture:true,console:false", file=sys.stderr)',
    check: true,
    capture: true,
    console: false,
)
assert(ret.returncode() == 0, 'failed to run python3: ' + ret.stderr())
assert(ret.stdout() == 'stdout|capture:true,console:false\n', 'failed to capture stdout:' + ret.stdout())
assert(ret.stderr() == 'stderr|capture:true,console:false\n', 'failed to capture stderr:' + ret.stderr())

# Expect runtime output, and captured
ret = run_command(
    py3,
    '-c',
    'import sys; print("stdout|capture:true,console:true"); print("stderr|capture:true,console:true", file=sys.stderr)',
    check: true,
    capture: true,
    console: true,
)
assert(ret.returncode() == 0, 'failed to run python3: ' + ret.stderr())
assert(ret.stdout() == 'stdout|capture:true,console:true\n', 'failed to capture stdout:' + ret.stdout())
assert(ret.stderr() == 'stderr|capture:true,console:true\n', 'failed to capture stderr:' + ret.stderr())

c_env = environment()
c_env.append('CUSTOM_ENV_VAR', 'FOOBAR')
ret = run_command(py3, '-c', 'import os; print(os.environ.get("CUSTOM_ENV_VAR"))', env: c_env, check: false)
assert(ret.returncode() == 0, 'failed to run python3: ' + ret.stderr())
assert(ret.stdout() == 'FOOBAR\n', 'stdout is "@0@" instead of FOOBAR'.format(ret.stdout()))

dd = find_program('dd', required : false)
if dd.found()
  ret = run_command(dd, 'if=/dev/urandom', 'bs=10', 'count=1', 'of=/dev/null', check: false, capture: false)
  assert(ret.returncode() == 0, 'failed to run dd: ' + ret.stderr())
  assert(ret.stdout() == '', 'stdout is "@0@" instead of empty'.format(ret.stdout()))
endif

env = environment()
env.append('MY_PATH', '1')
env.append('MY_PATH', '2')
env.prepend('MY_PATH', '0')
run_command('check-env.py', env: env, check: true)
