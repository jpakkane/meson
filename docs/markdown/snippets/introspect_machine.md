## "machine" entry in target introspection data

The JSON data returned by `meson introspect --targets` now has a `machine`
entry in each `target_sources` block.  The new entry can be one of `build`
or `host` for compiler-built targets, or absent for `custom_target` targets.
