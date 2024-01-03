## compiler object now have `get_crt()` method

The [[!compiler]] object now has a `get_crt()` method to get the deduced
C runtime, when `b_vscrt` option is set to `from_buildtype` or
`static_from_buildtype`, or the explicitly set runtime in other cases.
