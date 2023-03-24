project('fs module test')

is_windows = build_machine.system() == 'windows'

fs = import('fs')

f = files('meson.build')

assert(fs.exists('meson.build'), 'Existing file reported as missing.')
assert(not fs.exists('nonexisting'), 'Nonexisting file was found.')

if not is_windows and build_machine.system() != 'cygwin'
  # Symlinks on Windows have specific requirements including:
  # * Meson running under Python >= 3.8
  # * Windows user permissions to create symlinks, and/or Windows in Developer mode
  # so at this time the symlink test is skipped for Windows.
  symlink = meson.current_build_dir() / 'a_symlink'
  run_command('ln', '-s', '-f', meson.current_source_dir() / 'meson.build', symlink, check: true)
  assert(fs.is_symlink(symlink), 'Symlink not detected.')
  assert(not fs.is_symlink('meson.build'), 'Regular file detected as symlink.')
  assert(not fs.is_symlink(f[0]), 'Regular file detected as symlink.')
endif

assert(fs.is_file('meson.build'), 'File not detected as a file.')
assert(not fs.is_file('subprojects'), 'Directory detected as a file.')
assert(not fs.is_file('nonexisting'), 'Bad path detected as a file.')

assert(fs.is_dir('subprojects'), 'Dir not detected correctly.')
assert(not fs.is_dir('meson.build'), 'File detected as a dir.')
assert(not fs.is_dir('nonexisting'), 'Bad path detected as a dir.')

assert(fs.is_dir('~'), 'home directory not detected')
assert(not fs.is_file('~'), 'home directory detected as file')

# -- expanduser
assert(fs.expanduser('~') != '~','expanduser failed')
assert(fs.expanduser('~/foo').endswith('foo'), 'expanduser with tail failed')

# -- as_posix
assert(fs.as_posix('/') == '/', 'as_posix idempotent')
assert(fs.as_posix('\\') == '/', 'as_posix simple')
assert(fs.as_posix('\\\\') == '/', 'as_posix simple')
assert(fs.as_posix('foo\\bar/baz') == 'foo/bar/baz', 'as_posix mixed slash')

# -- is_absolute
winabs = 'q:/foo'
unixabs = '/foo'
if is_windows
  assert(fs.is_absolute(winabs), 'is_absolute windows not detected')
  assert(not fs.is_absolute(unixabs), 'is_absolute unix false positive')
else
  assert(fs.is_absolute(unixabs), 'is_absolute unix not detected')
  assert(not fs.is_absolute(winabs), 'is_absolute windows false positive')
endif

# -- replace_suffix

original = 'foo'
assert(fs.replace_suffix(original, '') == original, 'replace_suffix idempotent')
assert(fs.replace_suffix(f[0], '') == 'meson', 'replace_suffix trim')

original = 'foo.txt'
new = fs.replace_suffix(original, '.ini')
assert(new == 'foo.ini', 'replace_suffix failed')

new = fs.replace_suffix(f[0], '.ini')
assert(new == 'meson.ini', 'replace_suffix failed')

original = 'foo'
new = fs.replace_suffix(original, '.ini')
assert(new == 'foo.ini', 'replace_suffix did not add suffix to suffixless file')

original = 'foo.dll.a'
new = fs.replace_suffix(original, '.so')
assert(new == 'foo.dll.so', 'replace_suffix did not only modify last suffix')

original = 'foo.dll'
new = fs.replace_suffix(original, '')
assert(new == 'foo',  'replace_suffix did not only delete last suffix')

# `/` on windows is interpreted like `.drive` which in general may not be `c:/`
# the files need not exist for fs.replace_suffix()
original = is_windows ? 'j:/foo/bar.txt' : '/foo/bar.txt'
new_check = is_windows ? 'j:\\foo\\bar.ini' : '/foo/bar.ini'

new = fs.replace_suffix(original, '.ini')
assert(new == new_check, 'absolute path replace_suffix failed')

# -- hash

md5 = fs.hash('subdir/subdirfile.txt', 'md5')
sha256 = fs.hash('subdir/subdirfile.txt', 'sha256')
assert(md5 == 'd0795db41614d25affdd548314b30b3b', 'md5sum did not match')
assert(sha256 == 'be2170b0dae535b73f6775694fffa3fd726a43b5fabea11b7342f0605917a42a', 'sha256sum did not match')

f = files('subdir/subdirfile.txt')
md5 = fs.hash(f[0], 'md5')
assert(md5 == 'd0795db41614d25affdd548314b30b3b', 'md5sum did not match')
sha256 = fs.hash(f[0], 'sha256')
assert(sha256 == 'be2170b0dae535b73f6775694fffa3fd726a43b5fabea11b7342f0605917a42a', 'sha256sum did not match')

# -- size

size = fs.size('subdir/subdirfile.txt')
assert(size == 19, 'file size not found correctly')

size = fs.size(f[0])
assert(size == 19, 'file size not found correctly')

# -- are filenames referring to the same file?
f1 = 'meson.build'
f2 = 'subdir/../meson.build'
assert(fs.is_samepath(f1, f2), 'is_samepath not detecting same files')
assert(fs.is_samepath(meson.source_root(), 'subdir/..'), 'is_samepath not detecting same directory')
assert(fs.is_samepath(meson.project_source_root(), 'subdir/..'), 'is_samepath not detecting same directory')
assert(fs.is_samepath(meson.project_build_root(), meson.current_build_dir() / 'subdir/..'), 'is_samepath not detecting same directory')
assert(fs.is_samepath(meson.global_source_root(), meson.current_source_dir()), 'is_samepath not detecting same directory')
assert(fs.is_samepath(meson.global_build_root(), meson.current_build_dir()), 'is_samepath not detecting same directory')
assert(not fs.is_samepath(f1, 'subdir/subdirfile.txt'), 'is_samepath known bad comparison')
assert(not fs.is_samepath('not-a-path', f2), 'is_samepath should not error if path(s) do not exist')

f = files('meson.build', 'subdir/../meson.build')
assert(fs.is_samepath(f[0], f[1]), 'is_samepath not detercting same files')

if not is_windows and build_machine.system() != 'cygwin'
  assert(fs.is_samepath(symlink, 'meson.build'), 'symlink is_samepath fail')
endif

# parts of path
assert(fs.parent('foo/bar') == 'foo', 'failed to get dirname')
if not is_windows
assert(fs.parent(f[1]) == 'subdir/..', 'failed to get dirname')
else
assert(fs.parent(f[1]) == 'subdir\..', 'failed to get dirname')
endif
assert(fs.name('foo/bar') == 'bar', 'failed to get basename')
assert(fs.name(f[1]) == 'meson.build', 'failed to get basename')
assert(fs.name('foo/bar/baz.dll.a') == 'baz.dll.a', 'failed to get basename with compound suffix')
assert(fs.stem('foo/bar/baz.dll') == 'baz', 'failed to get stem with suffix')
assert(fs.stem('foo/bar/baz.dll.a') == 'baz.dll', 'failed to get stem with compound suffix')

subdir('subdir')

subproject('subbie')

if is_windows
  assert(fs.join_absolute('C:\\foo', 'D:\\bar') == 'C:\\foo\\bar')
  assert(fs.join_absolute('C:\\foo', '\\\\Server\\Volume\\file.txt') == 'C:\\foo\\file.txt')
  # /bar is considered absolute by os.path.isabs() but not by PurePath.is_absolute().
  # Meson has always used the former to validate --prefix value, so it has to work.
  assert(fs.join_absolute('C:\\foo', '/bar') == 'C:\\foo\\bar')
else
  assert(fs.join_absolute('/foo', '/bar') == '/foo/bar')
endif
