project('pathjoin', meson_version: '>= 1.5.0')

# Test string-args form since that is the canonical way
assert(join_paths('foo')               == 'foo', 'Single argument join is broken')
assert(join_paths('foo', 'bar')        == 'foo/bar', 'Path joining is broken')
assert(join_paths('foo', 'bar', 'baz') == 'foo/bar/baz', 'Path joining is broken')
assert(join_paths('/foo', 'bar')       == '/foo/bar', 'Path joining is broken')
assert(join_paths('foo', '/bar')       == '/bar', 'Absolute path joining is broken')
assert(join_paths('/foo', '/bar')      == '/bar', 'Absolute path joining is broken')
assert(join_paths('/foo', '')          == '/foo/', 'Trailing / on path')
assert(join_paths('')                  == '', 'Empty path joining is broken')

# Test array form since people are using that too
assert(join_paths(['foo'])               == 'foo', 'Single argument join is broken')
assert(join_paths(['foo', 'bar'])        == 'foo/bar', 'Path joining is broken')
assert(join_paths(['foo', 'bar', 'baz']) == 'foo/bar/baz', 'Path joining is broken')
assert(join_paths(['/foo', 'bar'])       == '/foo/bar', 'Path joining is broken')
assert(join_paths(['foo', '/bar'])       == '/bar', 'Absolute path joining is broken')
assert(join_paths(['/foo', '/bar'])      == '/bar', 'Absolute path joining is broken')
assert(join_paths(['/foo', ''])          == '/foo/', 'Trailing / on path')

# Division operator should do the same as join_paths
assert('foo' / 'bar'       == 'foo/bar',     'Path division is broken')
assert('foo' /'bar' /'baz' == 'foo/bar/baz', 'Path division is broken')
assert('/foo' / 'bar'      == '/foo/bar',    'Path division is broken')
assert('foo' / '/bar'      == '/bar',        'Absolute path division is broken')
assert('/foo' / '/bar'     == '/bar',        'Absolute path division is broken')
assert('/foo' / ''         == '/foo/',       'Trailing / on path')


# flavor keyword (since 1.5.0)
assert(join_paths('/foo/bar', '/builddir', '', flavor: 'meson') == '/builddir/', 'Default meson path joining is broken')
if build_machine.system() == 'windows'
    assert(join_paths('C:\\foo\\bar', 'D:\\builddir', '', flavor: 'meson') == 'D:/builddir/', 'Default meson path joining is broken')
else
    assert(join_paths('C:\\foo\\bar', 'D:\\builddir', '', flavor: 'meson') == 'C:/foo/bar/D:/builddir/', 'Default meson path joining is broken')
endif

assert(join_paths('/foo/bar', '/builddir', '', flavor: 'posix') == '/builddir/', 'Posix path joining is broken')
assert(join_paths('C:\\foo\\bar', 'D:\\builddir', '', flavor: 'posix') == 'C:\\foo\\bar/D:\\builddir/', 'Posix path joining is broken')

assert(join_paths('/foo/bar', '/builddir', '', flavor: 'windows') == '\\builddir\\', 'Windows path joining is broken')
assert(join_paths('C:\\foo\\bar', 'D:\\builddir', '', flavor: 'windows') == 'D:\\builddir\\', 'Windows path joining is broken')

if build_machine.system() == 'windows'
    assert(join_paths('/foo/bar', '/builddir', '', flavor: 'native') == '\\builddir\\', 'Native path joining on Windows is broken')
    assert(join_paths('C:\\foo\\bar', 'D:\\builddir', '', flavor: 'native') == 'D:\\builddir\\', 'Native path joining on Windows is broken')
else
    assert(join_paths('/foo/bar', '/builddir', '', flavor: 'posix') == '/builddir/', 'Native path joining on Posix system is broken')
    assert(join_paths('C:\\foo\\bar', 'D:\\builddir', '', flavor: 'native') == 'C:\\foo\\bar/D:\\builddir/', 'Native path joining on Posix system is broken')
endif

foreach flavor : ['posix', 'windows', 'native']
    assert(join_paths('', flavor: flavor) == '', f'Empty path joining is broken (flavor: @flavor@)')
endforeach

# mode keyword (since 1.5.0)
assert(join_paths('/foo/bar', '/builddir', '', mode: 'absolute') == '/foo/bar/builddir/', 'Absolute mode (meson) is broken')
assert(join_paths('/foo/bar', '/builddir', '', flavor: 'posix', mode: 'absolute') == '/foo/bar/builddir/', 'Absolute mode (posix) is broken')
assert(join_paths('/foo/bar', '/builddir', '', flavor: 'windows', mode: 'absolute') == '\\foo\\bar\\builddir\\', 'Absolute mode (windows) is broken')

if build_machine.system() == 'windows'
    assert(join_paths('C:\\foo\\bar', 'D:\\builddir', '', mode: 'absolute') == 'C:/foo/bar/builddir/', 'Absolute mode (meson) is broken')
else
    assert(join_paths('C:\\foo\\bar', 'D:\\builddir', '', mode: 'absolute') == 'C:/foo/bar/D:/builddir/', 'Absolute mode (meson) is broken')
endif
assert(join_paths('C:\\foo\\bar', 'D:\\builddir', '', flavor: 'posix', mode: 'absolute') == 'C:\\foo\\bar/D:\\builddir/', 'Absolute mode (posix) is broken')
assert(join_paths('C:\\foo\\bar', 'D:\\builddir', '', flavor: 'windows', mode: 'absolute') == 'C:\\foo\\bar\\builddir\\', 'Absolute mode (windows) is broken')
