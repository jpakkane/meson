## Added `mode` keyword argument to `join_paths`

[[join_paths]] function now have a `mode` keyword, to specify
how it joins absolute paths.

In 'relative' mode (default), the last absolute component of the path becomes
the path starting point.

In 'absolute' mode, each subsequent parts are joined as if they were relative
to the preceding parts.
