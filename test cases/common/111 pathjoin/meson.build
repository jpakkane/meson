project('pathjoin')

# Test string-args form since that is the canonical way
assert(join_paths('foo')               == 'foo', 'Single argument join is broken')
assert(join_paths('foo', 'bar')        == 'foo/bar', 'Path joining is broken')
assert(join_paths('foo', 'bar', 'baz') == 'foo/bar/baz', 'Path joining is broken')
assert(join_paths('/foo', 'bar')       == '/foo/bar', 'Path joining is broken')
assert(join_paths('foo', '/bar')       == '/bar', 'Absolute path joining is broken')
assert(join_paths('/foo', '/bar')      == '/bar', 'Absolute path joining is broken')
assert(join_paths('/foo', '')          == '/foo/', 'Trailing / on path')
assert(join_paths('foo/', 'bar/')      == 'foo/bar/', 'Trailing / on path')

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

# Empty paths
assert(join_paths('')               == '', 'Empty path')
assert(join_paths('', '')           == '', 'Multiple empty paths')
assert(join_paths('foo', '', 'bar') == 'foo/bar', 'Empty path in the middle')


# Windows paths
if build_machine.system() == 'windows'
    assert(join_paths('C:\\foo', 'D:\\bar') == 'D:/bar', 'Windows-like paths joining on Windows is broken')
    assert('C:\\foo' / 'D:\\bar'            == 'D:/bar', 'Windows-like paths joining on Windows is broken')
else
    # : and \ are valid chars in posix paths
    assert(join_paths('C:\\foo', 'D:\\bar') == 'C:\\foo/D:\\bar', 'Windows-like paths joining on posix is broken')
    assert('C:\\foo' / 'D:\\bar'            == 'C:\\foo/D:\\bar', 'Windows-like paths joining on posix is broken')
endif
