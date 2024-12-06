---
title: Release 1.6.0
short-description: Release notes for 1.6.0
...

# New features

Meson 1.6.0 was released on 20 October 2024
## Support for OpenXL compiler in AIX.

The OpenXL compiler is now supported from Meson 1.6.0 onwards.
So currently, in AIX Operating system we support GCC and openXL compilers for Meson build system.

Both the compilers will archive shared libraries and generate a shared object
for a shared module while using Meson in AIX.

## `alias_target` of `both_libraries`

Previously, when passing a [[@both_libs]] object to [[alias_target]], the alias
would only point to the shared library. It now points to both the static and the
shared library.

## Default to printing deprecations when no minimum version is specified.

For a long time, the [[project]] function has supported specifying the minimum
`meson_version:` needed by a project. When this is used, deprecated features
from before that version produce warnings, as do features which aren't
available in all supported versions.

When no minimum version was specified, meson didn't warn you even about
deprecated functionality that might go away in an upcoming semver major release
of meson.

Now, meson will treat an unspecified minimum version following semver:

- For new features introduced in the current meson semver major cycle
  (currently: all features added since 1.0) a warning is printed. Features that
  have been available since the initial 1.0 release are assumed to be widely
  available.

- For features that have been deprecated by any version of meson, a warning is
  printed. Since no minimum version was specified, it is assumed that the
  project wishes to follow the latest and greatest functionality.

These warnings will overlap for functionality that was both deprecated and
replaced with an alternative in the current release cycle. The combination
means that projects without a minimum version specified are assumed to want
broad compatibility with the current release cycle (1.x).

Projects that specify a minimum `meson_version:` will continue to only receive
actionable warnings based on their current minimum version.

## Cargo subprojects is experimental

Cargo subprojects was intended to be experimental with no stability guarantees.
That notice was unfortunately missing from documentation. Meson will now start
warning about usage of experimental features and future releases might do breaking
changes.

This is aligned with our general policy regarding [mixing build systems](Mixing-build-systems.md).

## Dependencies from CMake subprojects now use only PUBLIC link flags

Any [[@dep]] obtained from a CMake subproject (or `.wrap` with `method = cmake`)
now only includes link flags marked in CMake as `PUBLIC` or `INTERFACE`.
Flags marked as `PRIVATE` are now only applied when building the subproject
library and not when using it as a dependency. This better matches how CMake
handles link flags and fixes link errors when using some CMake projects as
subprojects.

## New built-in option for default both_libraries

`both_libraries` targets used to be considered as a shared library by default.
There is now the `default_both_libraries` option to change this default.

When `default_both_libraries` is 'auto', [[both_libraries]] with dependencies
that are [[@both_libs]] themselves will link with the same kind of library.
For example, if `libA` is a [[@both_libs]] and `libB` is a [[@both_libs]]
linked with `libA` (or with an internal dependency on `libA`),
the static lib of `libB` will link with the static lib of `libA`, and the
shared lib of `libA` will link with the shared lib of `libB`.

## New `as_static` and `as_shared` methods on internal dependencies

[[@dep]] object returned by [[declare_dependency]] now has `.as_static()` and
`.as_shared()` methods, to convert to a dependency that prefers the `static`
or the `shared` version of the linked [[@both_libs]] target.

When the same dependency is used without those methods, the
`default_both_libraries` option determines which version is used.

## Support for DIA SDK

Added support for Windows Debug Interface Access SDK (DIA SDK) dependency. It allows reading with MSVC debugging information (.PDB format). This dependency can only be used on Windows, with msvc, clang or clang-cl compiler.

## Support for LLVM-based flang compiler

Added basic handling for the [flang](https://flang.llvm.org/docs/) compiler
that's now part of LLVM. It is the successor of another compiler named
[flang](https://github.com/flang-compiler/flang) by largely the same
group of developers, who now refer to the latter as "classic flang".

Meson already supports classic flang, and the LLVM-based flang now
uses the compiler-id `'llvm-flang'`.

## nvc and nvc++ now support setting std

The following standards are available for nvc: c89, c90, c99, c11,
c17, c18, gnu90, gnu89, gnu99, gnu11, gnu17, gnu18. For nvc++: 
c++98, c++03, c++11, c++14, c++17, c++20, c++23, gnu++98, gnu++03,
gnu++11, gnu++14, gnu++17, gnu++20

## Tools can be selected when calling `has_tools()` on the Qt modules

When checking for the presence of Qt tools, you can now explictly ask Meson
which tools you need. This is particularly useful when you do not need
`lrelease` because you are not shipping any translations. For example:

```meson
qt6_mod = import('qt6')
qt6_mod.has_tools(required: true, tools: ['moc', 'uic', 'rcc'])
```

valid tools are `moc`, `uic`, `rcc` and `lrelease`.

## Simple tool to test build reproducibility

Meson now ships with a command for testing whether your project can be
[built reproducibly](https://reproducible-builds.org/). It can be used
by running a command like the following in the source root of your
project:

    meson reprotest --intermediaries -- --buildtype=debugoptimized

All command line options after the `--` are passed to the build
invocations directly.

This tool is not meant to be exhaustive, but instead easy and
convenient to run. It will detect some but definitely not all
reproducibility issues.

## Support for variable in system dependencies

System Dependency method `get_variable()` now supports `system` variable.

## test() and benchmark() functions accept new types

`test` and `benchmark` now accept ExternalPrograms (as returned by
`find_program`) in the `args` list.  This can be useful where the test
executable is a wrapper which invokes another program given as an
argument.

```meson
test('some_test', find_program('sudo'), args : [ find_program('sh'), 'script.sh' ])
```

## Zig 0.11 can be used as a C/C++ compiler frontend

Zig offers
[a C/C++ frontend](https://andrewkelley.me/post/zig-cc-powerful-drop-in-replacement-gcc-clang.html) as a drop-in replacement for Clang. It worked fine with Meson up to Zig 0.10. Since 0.11, Zig's
dynamic linker reports itself as `zig ld`, which wasn't known to Meson. Meson now correctly handles
Zig's linker.

You can use Zig's frontend via a [machine file](Machine-files.md):

```ini
[binaries]
c = ['zig', 'cc']
cpp = ['zig', 'c++']
ar = ['zig', 'ar']
ranlib = ['zig', 'ranlib']
lib = ['zig', 'lib']
dlltool = ['zig', 'dlltool']
```

