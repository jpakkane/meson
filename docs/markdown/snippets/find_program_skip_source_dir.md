## `find_program()` can optionally skip searching the source directory

When given an executable name without any overrides, the `find_program()`
function searches the source directory for the executable before scanning
through `PATH`. This can now be skipped by passing `skip_source_dir: true` to
`find_program()` so that only `PATH` will be searched.
