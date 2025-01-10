project(
  'MesonLinkBoostBug',
  ['d', 'cpp'],
  default_options : ['cpp_std=c++11'],
)

src = ['main.d', 'external.cpp']

# Since we can't play rpath tricks, just statically link boost into the exe's.
# This makes the unit tests more reliable on windows
static = false
if host_machine.system() == 'windows'
  static = true
endif

boost_dep = dependency('boost', modules : ['system', 'thread'], required : false, static : static)
if not boost_dep.found()
  message('MESON_SKIP_TEST boost is required.')
endif

app = executable('app', src, dependencies: boost_dep)

test('valid value', app, args : ['0'])
test('valid failing value', app, args : ['7'], should_fail : true)
test('invalid value', app, args : ['twenty'])
