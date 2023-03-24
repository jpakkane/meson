## fs.join_absolute(path1, path2)

Join a path with an absolute path. Unlike [join_paths](Reference-manual_functions.md#join_paths),
this makes the second path relative to its root before joining them. For example
on Unix joining `/foo` and `/bar` gives `/foo/bar`. On Windows joining
`C:\foo` and `D:\bar` gives `C:\foo\bar`.
