## Devenv support in external project module

The [external project module](External-Project-module.md) now setups `PATH` and
`LD_LIBRARY_PATH` to be able to run programs.

`@BINDIR@` is now substitued in arguments and `'--bindir=@PREFIX@/@BINDIR@'`
default argument have been added.
