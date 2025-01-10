## Added a new `build` and 'source' args to `include_directories(...)`

The previous behaviour of `include_directories(...)` is that it ends up adding
both source-relative and build-relative include search paths to the compile
options or, if using absolute paths, then simply duplicating the same absolute
include search path.  Even if the user wants _either_ a build-relative _or_
src-relative path only, they're forced to use both, which could cause problems
as well as just adding unnecessary compile options.

New `build` and `source` bool arguments are added to `include_directories(...)`.
If unspecified, both `build` and `source` default to True.
It is invalid for both to be False.
It is invalid to use absolute paths with _only_ 'build' set to True, since a
user asking for build-relative absolute include directories is meaningless or
at least suggests a misunderstanding.

Absolute include search paths are allowed if `source` is `true`.  If `build`
is also `true`, any absolute paths will only be added once.
