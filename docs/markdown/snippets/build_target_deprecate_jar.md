## passing `target_type : 'jar'` to `build_target()` is deprecated

This never really made sense as you can't mix Java sources with non-Java
sources, but this is even more difficult to ensure that we validate the
arguments correctly given that many `jar()` arguments allow different types than
other targets do.
