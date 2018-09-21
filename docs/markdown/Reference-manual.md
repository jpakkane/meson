# Reference manual

## Functions

The following functions are available in build files. Click on each to
see the description and usage. The objects returned by them are [list
afterwards](#returned-objects).


### add_global_arguments()

``` meson
  void add_global_arguments(arg1, arg2, ...)
```

Adds the positional arguments to the compiler command line. This
function has two keyword arguments:

- `language` specifies the language(s) that the arguments should be
applied to. If a list of languages is given, the arguments are added
to each of the corresponding compiler command lines. Note that there
is no way to remove an argument set in this way. If you have an
argument that is only used in a subset of targets, you have to specify
it in per-target flags.

- `native` is a boolean specifying whether the arguments should be
  applied to the native or cross compilation. If `true` the arguments
  will only be used for native compilations. If `false` the arguments
  will only be used in cross compilations. If omitted, the flags are
  added to native compilations if compiling natively and cross
  compilations (only) when cross compiling. Available since 0.48.0

The arguments are used in all compiler invocations with the exception
of compile tests, because you might need to run a compile test with
and without the argument in question. For this reason only the
arguments explicitly specified are used during compile tests.

**Note:** Usually you should use `add_project_arguments` instead,
  because that works even when you project is used as a subproject.

**Note:** You must pass always arguments individually `arg1, arg2,
  ...` rather than as a string `'arg1 arg2', ...`

### add_global_link_arguments()

``` meson
    void add_global_link_arguments(*arg1*, *arg2*, ...)
```

Like `add_global_arguments` but the arguments are passed to the linker.

### add_languages()

``` meson
  add_languages(*langs*)
```

Add support for new programming languages. Equivalent to having them
in the `project` declaration. This function is usually used to add
languages that are only used on some platforms like this:

```meson
project('foobar', 'c')
if compiling_for_osx
  add_languages('objc')
endif
```

Takes one keyword argument, `required`. It defaults to `true`, which
means that if any of the languages specified is not found, Meson will
halt. Returns true if all languages specified were found and false
otherwise. Since *0.47.0* the value of a
[`feature`](Build-options.md#features) option can also be passed to
the `required` keyword argument.

### add_project_arguments()

``` meson
  void add_project_arguments(arg1, arg2, ...)
```

This function behaves in the same way as `add_global_arguments` except
that the arguments are only used for the current project, they won't
be used in any other subproject.

### add_project_link_arguments()

``` meson
  void add_project_link_arguments(*arg1*, *arg2*, ...)
```

Like `add_project_arguments` but the arguments are passed to the linker.

### add_test_setup()

``` meson
  void add_test_setup(*name*, ...)
```

Add a custom test setup that can be used to run the tests with a
custom setup, for example under Valgrind. The keyword arguments are
the following:

- `env` an [environment object](#environment-object) to use a custom environment
- `exe_wrapper` a list containing the wrapper command or script followed by the arguments to it
- `gdb` if `true`, the tests are also run under `gdb`
- `timeout_multiplier` a number to multiply the test timeout with

To use the test setup, run `meson test --setup=*name*` inside the build dir.

Note that all these options are also available while running the
`meson test` script for running tests instead of `ninja test` or
`msbuild RUN_TESTS.vcxproj`, etc depending on the backend.

### benchmark()

``` meson
    void benchmark(name, executable, ...)
```

Creates a benchmark item that will be run when the benchmark target is
run. The behavior of this function is identical to `test` with the
exception that there is no `is_parallel` keyword, because benchmarks
are never run in parallel.

### both_libraries()

``` meson
    buildtarget both_libraries(library_name, list_of_sources, ...)
```

Builds both a static and shared library with the given
sources. Positional and keyword arguments are otherwise the same as
for [`library`](#library). Source files will be compiled only once and
object files will be reused to build both shared and static libraries,
unless `b_staticpic` user option or `pic` argument are set to false in
which case sources will be compiled twice.

The returned [buildtarget](#build-target-object) always represents the shared
library. In addition it supports the following extra methods:

- `get_shared_lib()` returns the shared library build target
- `get_static_lib()` returns the static library build target

*Added 0.46.0*

### build_target()

Creates a build target whose type can be set dynamically with the
`target_type` keyword argument. This declaration:

```meson
executable(<arguments and keyword arguments>)
```

is equivalent to this:

```meson
build_target(<arguments and keyword arguments>, target_type : 'executable')
```

The object returned by `build_target` and all convenience wrappers for
`build_target` such as [`executable`](#executable) and
[`library`](#library) has methods that are documented in the [object
methods section](#build-target-object) below.

### configuration_data()

``` meson
    configuration_data_object = configuration_data()
```

Creates an empty configuration object. You should add your
configuration with [its method calls](#configuration-data-object) and
finally use it in a call to `configure_file`.

### configure_file()

``` meson
    generated_file = configure_file(...)
```

This function can run in three modes depending on the keyword arguments
passed to it.

When a [`configuration_data()`](#configuration_data) object is passed
to the `configuration:` keyword argument, it takes a template file as
the `input:` (optional) and produces the `output:` (required) by
substituting values from the configuration data as detailed in [the
configuration file documentation](Configuration.md).

When a list of strings is passed to the `command:` keyword argument,
it takes any source or configured file as the `input:` and assumes
that the `output:` is produced when the specified command is run.

Since *0.47.0*, when the `copy:` keyword argument is set to `true`,
this function will copy the file provided in `input:` to a file in the
build directory with the name `output:` in the current directory.

These are all the supported keyword arguments:

- `capture` when this argument is set to true, Meson captures `stdout`
  of the `command` and writes it to the target file specified as
  `output`. Available since v0.41.0.
- `command` as explained above, if specified, Meson does not create
  the file itself but rather runs the specified command, which allows
  you to do fully custom file generation.
- `copy` *(added 0.47.0)* as explained above, if specified Meson only
  copies the file from input to output.
- `format` *(added 0.46.0)* the format of defines. It defaults to `meson`, and so substitutes
`#mesondefine` statements and variables surrounded by `@` characters, you can also use `cmake`
to replace `#cmakedefine` statements and variables with the `${variable}` syntax. Finally you can use
`cmake@` in which case substitutions will apply on `#cmakedefine` statements and variables with
the `@variable@` syntax.
- `input` the input file name. If it's not specified in configuration
  mode, all the variables in the `configuration:` object (see above)
  are written to the `output:` file.
- `install_dir` the subdirectory to install the generated file to
  (e.g. `share/myproject`), if omitted or given the value of empty
  string, the file is not installed.
- `install_mode` *(added 0.47.0)* specify the file mode in symbolic format
  and optionally the owner/uid and group/gid for the installed files.
- `output` the output file name (since v0.41.0, may contain
  `@PLAINNAME@` or `@BASENAME@` substitutions). In configuration mode,
  the permissions of the input file (if it is specified) are copied to
  the output file.
- `output_format` *(added 0.47.0)* the format of the output to generate when no input
  was specified. It defaults to `c`, in which case preprocessor directives
  will be prefixed with `#`, you can also use `nasm`, in which case the
  prefix will be `%`.
- `encoding` *(added v0.47.0)* set the file encoding for the input and output file,
  defaults to utf-8. The supported encodings are those of python3, see
  [standard-encodings](https://docs.python.org/3/library/codecs.html#standard-encodings).

### custom_target()

``` meson
    customtarget custom_target(*name*, ...)
```

Create a custom top level build target. The only positional argument
is the name of this target and the keyword arguments are the
following.

- `build_by_default` *(added 0.38.0)* causes, when set to true, to
  have this target be built by default, that is, when invoking plain
  `ninja`; the default value is false
- `build_always` (deprecated) if `true` this target is always considered out of
  date and is rebuilt every time.  Equivalent to setting both
  `build_always_stale` and `build_by_default` to true.
- `build_always_stale` if `true` the target is always considered out of date.
  Useful for things such as build timestamps or revision control tags.
  The associated command is run even if the outputs are up to date.
- `capture`, there are some compilers that can't be told to write
  their output to a file but instead write it to standard output. When
  this argument is set to true, Meson captures `stdout` and writes it
  to the target file. Note that your command argument list may not
  contain `@OUTPUT@` when capture mode is active.
- `console` keyword argument conflicts with `capture`, and is meant
  for commands that are resource-intensive and take a long time to
  finish. With the Ninja backend, setting this will add this target
  to [Ninja's `console` pool](https://ninja-build.org/manual.html#_the_literal_console_literal_pool),
  which has special properties such as not buffering stdout and
  serializing all targets in this pool.
- `command` command to run to create outputs from inputs. The command
  may be strings or the return value of functions that return file-like
  objects such as [`find_program()`](#find_program),
  [`executable()`](#executable), [`configure_file()`](#configure_file),
  [`files()`](#files), [`custom_target()`](#custom_target), etc.
  Meson will automatically insert the appropriate dependencies on
  targets and files listed in this keyword argument.
  Note: always specify commands in array form `['commandname',
  '-arg1', '-arg2']` rather than as a string `'commandname -arg1
  -arg2'` as the latter will *not* work.
- `depend_files` files ([`string`](#string-object),
  [`files()`](#files), or [`configure_file()`](#configure_file)) that
  this target depends on but are not listed in the `command` keyword
  argument. Useful for adding regen dependencies.
- `depends` specifies that this target depends on the specified
  target(s), even though it does not take any of them as a command
  line argument. This is meant for cases where you have a tool that
  e.g. does globbing internally. Usually you should just put the
  generated sources as inputs and Meson will set up all dependencies
  automatically.
- `depfile` is a dependency file that the command can write listing
  all the additional files this target depends on, for example a C
  compiler would list all the header files it included, and a change
  in any one of these files triggers a recompilation
- `input` list of source files. As of 0.41.0 the list will be flattened.
- `install` when true, this target is installed during the install step
- `install_dir` directory to install to
- `install_mode` *(added 0.47.0)* the file mode and optionally the
  owner/uid and group/gid
- `output` list of output files

The list of strings passed to the `command` keyword argument accept
the following special string substitutions:

- `@INPUT@` the full path to the input passed to `input`. If more than
  one input is specified, all of them will be substituted as separate
  arguments only if the command uses `'@INPUT@'` as a
  standalone-argument. For instance, this would not work: `command :
  ['cp', './@INPUT@']`, but this would: `command : ['cp', '@INPUT@']`.
- `@OUTPUT@` the full path to the output passed to `output`. If more
  than one outputs are specified, the behavior is the same as
  `@INPUT@`.
- `@INPUT0@` `@INPUT1@` `...` the full path to the input with the specified array index in `input`
- `@OUTPUT0@` `@OUTPUT1@` `...` the full path to the output with the specified array index in `output`
- `@OUTDIR@` the full path to the directory where the output(s) must be written
- `@DEPFILE@` the full path to the dependency file passed to `depfile`
- `@PLAINNAME@`: the input filename, without a path
- `@BASENAME@`: the input filename, with extension removed

The `depfile` keyword argument also accepts the `@BASENAME@` and `@PLAINNAME@`
substitutions. *(since 0.47)*

The returned object also has methods that are documented in the
[object methods section](#custom-target-object) below.

### declare_dependency()

``` meson
    dependency_object declare_dependency(...)
```

This function returns a [dependency object](#dependency-object) that
behaves like the return value of [`dependency`](#dependency) but is
internal to the current build. The main use case for this is in
subprojects. This allows a subproject to easily specify how it should
be used. This makes it interchangeable with the same dependency that
is provided externally by the system. This function has the following
keyword arguments.

  - `compile_args`, compile arguments to use
  - `dependencies`, other dependencies needed to use this dependency
  - `include_directories`, the directories to add to header search path
  - `link_args`, link arguments to use
  - `link_with`, libraries to link against
  - `link_whole`, libraries to link fully, same as [`executable`](#executable)
    Since 0.46.0
  - `sources`, sources to add to targets (or generated header files
    that should be built before sources including them are built)
  - `version`, the version of this dependency, such as `1.2.3`

### dependency()

``` meson
    dependency_object dependency(*dependency_name*, ...)
```

Finds an external dependency (usually a library installed on your
system) with the given name with `pkg-config` if possible, as a
framework (OSX only), and with
[library-specific fallback detection logic](Dependencies.md#dependencies-with-custom-lookup-functionality)
otherwise. This function supports the following keyword arguments:

- `default_options` *(added 0.37.0)* an array of default option values
  that override those set in the subproject's `meson_options.txt`
  (like `default_options` in [`project()`](#project), they only have
  effect when Meson is run for the first time, and command line
  arguments override any default options in build files)
- `fallback` specifies a subproject fallback to use in case the
  dependency is not found in the system. The value is an array
  `['subproj_name', 'subproj_dep']` where the first value is the name
  of the subproject and the second is the variable name in that
  subproject that contains a dependency object such as the return
  value of [`declare_dependency`](#declare_dependency) or
  [`dependency()`](#dependency), etc. Note that this means the
  fallback dependency may be a not-found dependency, in which
  case the value of the `required:` kwarg will be obeyed.
- `language` *(added 0.42.0)* defines what language-specific
  dependency to find if it's available for multiple languages.
- `method` defines the way the dependency is detected, the default is
  `auto` but can be overridden to be e.g. `qmake` for Qt development,
  and [different dependencies support different values](
  Dependencies.md#dependencies-with-custom-lookup-functionality)
  for this (though `auto` will work on all of them)
- `native` if set to `true`, causes Meson to find the dependency on
  the build machine system rather than the host system (i.e. where the
  cross compiled binary will run on), usually only needed if you build
  a tool to be used during compilation.
- `required`, when set to false, Meson will proceed with the build
  even if the dependency is not found. Since *0.47.0* the value of a
  [`feature`](Build-options.md#features) option can also be passed.
- `static` tells the dependency provider to try to get static
  libraries instead of dynamic ones (note that this is not supported
  by all dependency backends)
- `version` specifies the required version, a string containing a
  comparison operator followed by the version string, examples include
  `>1.0.0`, `<=2.3.5` or `3.1.4` for exact matching. (*Added 0.37.0*)
  You can also specify multiple restrictions by passing a list to this
  keyword argument, such as: `['>=3.14.0', '<=4.1.0']`.
  These requirements are never met if the version is unknown.
- other
[library-specific](Dependencies.md#dependencies-with-custom-lookup-functionality)
keywords may also be accepted (e.g. `modules` specifies submodules to use for
dependencies such as Qt5 or Boost. )

If dependency_name is `''`, the dependency is always not found.  So with
`required: false`, this always returns a dependency object for which the
`found()` method returns `false`, and which can be passed like any other
dependency to the `dependencies:` keyword argument of a `build_target`.  This
can be used to implement a dependency which is sometimes not required e.g. in
some branches of a conditional.

The returned object also has methods that are documented in the
[object methods section](#dependency-object) below.

### disabler()

Returns a [disabler object](#disabler-object). Added in 0.44.0.

### error()

``` meson
    void error(message)
```

Print the argument string and halts the build process.

### environment()

``` meson
    environment_object environment()
```

Returns an empty [environment variable object](#environment-object).

### executable()

``` meson
    buildtarget executable(*exe_name*, *sources*, ...)
```

Creates a new executable. The first argument specifies its name and
the remaining positional arguments define the input files to use. They
can be of the following types:

- Strings relative to the current source directory
- [`files()`](#files) objects defined in any preceding build file
- The return value of configure-time generators such as [`configure_file()`](#configure_file)
- The return value of build-time generators such as
  [`custom_target()`](#custom_target) or
  [`generator.process()`](#generator-object)

These input files can be sources, objects, libraries, or any other
file. Meson will automatically categorize them based on the extension
and use them accordingly. For instance, sources (`.c`, `.cpp`,
`.vala`, `.rs`, etc) will be compiled and objects (`.o`, `.obj`) and
libraries (`.so`, `.dll`, etc) will be linked.

With the Ninja backend, Meson will create a build-time [order-only
dependency](https://ninja-build.org/manual.html#ref_dependencies) on
all generated input files, including unknown files. For all input
files (generated and non-generated), Meson uses the [dependency
file](https://ninja-build.org/manual.html#ref_headers) generated by
your compiler to determine when to rebuild sources. The behavior is
similar for other backends.

Executable supports the following keyword arguments. Note that just
like the positional arguments above, these keyword arguments can also
be passed to [shared and static libraries](#library).

- `<languagename>_pch` precompiled header file to use for the given language
- `<languagename>_args` compiler flags to use for the given language;
  eg: `cpp_args` for C++
- `build_by_default` causes, when set to true, to have this target be
  built by default, that is, when invoking plain `ninja`, the default
  value is true for all built target types, since 0.38.0
- `build_rpath` a string to add to target's rpath definition in the
  build dir, but which will be removed on install
- `dependencies` one or more objects created with
  [`dependency`](#dependency) or [`find_library`](#compiler-object)
  (for external deps) or [`declare_dependency`](#declare_dependency)
  (for deps built by the project)
- `extra_files` are not used for the build itself but are shown as
  source files in IDEs that group files by targets (such as Visual
  Studio)
- `gui_app` when set to true flags this target as a GUI application on
  platforms where this makes a difference (e.g. Windows)
- `link_args` flags to use during linking. You can use UNIX-style
  flags here for all platforms.
- `link_depends` strings, files, or custom targets the link step
  depends on such as a symbol visibility map. The purpose is to
  automatically trigger a re-link (but not a re-compile) of the target
  when this file changes.
- `link_whole` links all contents of the given static libraries
  whether they are used by not, equivalent to the
  `-Wl,--whole-archive` argument flag of GCC, available since
  0.40.0. As of 0.41.0 if passed a list that list will be flattened.
- `link_with`, one or more shared or static libraries (built by this
  project) that this target should be linked with, If passed a list
  this list will be flattened as of 0.41.0.
- `export_dynamic` when set to true causes the target's symbols to be
  dynamically exported, allowing modules built using the
  [`shared_module`](#shared_module) function to refer to functions,
  variables and other symbols defined in the executable itself. Implies
  the `implib` argument.  Since 0.45.0
- `implib` when set to true, an import library is generated for the
  executable (the name of the import library is based on *exe_name*).
  Alternatively, when set to a string, that gives the base name for
  the import library.  The import library is used when the returned
  build target object appears in `link_with:` elsewhere.  Only has any
  effect on platforms where that is meaningful (e.g. Windows). Implies
  the `export_dynamic` argument.  Since 0.42.0
- `implicit_include_directories` is a boolean telling whether Meson
  adds the current source and build directories to the include path,
  defaults to `true`, since 0.42.0
- `include_directories` one or more objects created with the
  `include_directories` function
- `install`, when set to true, this executable should be installed
- `install_dir` override install directory for this file. The value is
  relative to the `prefix` specified. F.ex, if you want to install
  plugins into a subdir, you'd use something like this: `install_dir :
  join_paths(get_option('libdir'), 'projectname-1.0'`).
- `install_mode` *(added 0.47.0)* specify the file mode in symbolic format
  and optionally the owner/uid and group/gid for the installed files.
- `install_rpath` a string to set the target's rpath to after install
  (but *not* before that)
- `objects` list of prebuilt object files (usually for third party
  products you don't have source to) that should be linked in this
  target, **never** use this for object files that you build yourself.
- `name_suffix` the string that will be used as the extension for the
  target by overriding the default. By default on Windows this is
  `exe` and on other platforms it is omitted. Set this to `[]`, or omit
  the keyword argument for the default behaviour.
- `override_options` takes an array of strings in the same format as
  `project`'s `default_options` overriding the values of these options
  for this target only, since 0.40.0
- `gnu_symbol_visibility` specifies how symbols should be exported, see
  e.g [the GCC Wiki](https://gcc.gnu.org/wiki/Visibility) for more
  information. This value can either be an empty string or one of
  `default`, `internal`, `hidden`, `protected` or `inlineshidden`, which
  is the same as `hidden` but also includes things like C++ implicit
  constructors as specified in the GCC manual. Ignored on compilers that
  do not support GNU visibility arguments. Available since 0.48.0.
- `d_import_dirs` list of directories to look in for string imports used
  in the D programming language
- `d_unittest`, when set to true, the D modules are compiled in debug mode
- `d_module_versions` list of module versions set when compiling D sources
- `build_dir` provides a subdirectory to place the built
  target. Useful when building multiple targets with the same base filename.

The list of `sources`, `objects`, and `dependencies` is always
flattened, which means you can freely nest and add lists while
creating the final list.

The returned object also has methods that are documented in the
[object methods section](#build-target-object) below.

### find_library()

This function is deprecated and in the 0.31.0 release it was moved to
[the compiler object](#compiler-object) as obtained from
`meson.get_compiler(lang)`.

### find_program()

``` meson
    program find_program(program_name1, program_name2, ...)
```

`program_name1` here is a string that can be an executable or script
to be searched for in `PATH`, or a script in the current source
directory.

`program_name2` and later positional arguments are used as fallback
strings to search for. This is meant to be used for cases where the
program may have many alternative names, such as `foo` and
`foo.py`. The function will check for the arguments one by one and the
first one that is found is returned. Meson versions earlier than
0.37.0 only accept one argument.

Keyword arguments are the following:

- `required` By default, `required` is set to `true` and Meson will
  abort if no program can be found. If `required` is set to `false`,
  Meson continue even if none of the programs can be found. You can
  then use the `.found()` method on the returned object to check
  whether it was found or not. Since *0.47.0*  the value of a
  [`feature`](Build-options.md#features) option can also be passed to the
  `required` keyword argument.

- `native` *(since 0.43)* defines how this executable should be searched. By default
  it is set to `false`, which causes Meson to first look for the
  executable in the cross file (when cross building) and if it is not
  defined there, then from the system. If set to `true`, the cross
  file is ignored and the program is only searched from the system.

Meson will also autodetect scripts with a shebang line and run them
with the executable/interpreter specified in it both on Windows
(because the command invocator will reject the command otherwise) and
Unixes (if the script file does not have the executable bit
set). Hence, you *must not* manually add the interpreter while using
this script as part of a list of commands.

If you need to check for a program in a non-standard location, you can
just pass an absolute path to `find_program`, e.g.  ``` setcap =
find_program('setcap', '/usr/sbin/setcap', '/sbin/setcap', required :
false) ```

It is also possible to pass an array to `find_program` in case you
need to construct the set of paths to search on the fly:

```
setcap = find_program(['setcap', '/usr/sbin/setcap', '/sbin/setcap'], required : false)
```

The returned object also has methods that are documented in the
[object methods section](#external-program-object) below.

### files()

``` meson
    file_array files(list_of_filenames)
```

This command takes the strings given to it in arguments and returns
corresponding File objects that you can use as sources for build
targets. The difference is that file objects remember the subdirectory
they were defined in and can be used anywhere in the source tree. As
an example suppose you have source file `foo.cpp` in subdirectory
`bar1` and you would like to use it in a build target that is defined
in `bar2`. To make this happen you first create the object in `bar1`
like this:

```meson
    foofile = files('foo.cpp')
```

Then you can use it in `bar2` like this:

```meson
    executable('myprog', 'myprog.cpp', foofile, ...)
```

Meson will then do the right thing.

### generator()

``` meson
    generator_object generator(*executable*, ...)
```

See also: [`custom_target`](#custom_target)

This function creates a [generator object](#generator-object) that can
be used to run custom compilation commands. The only positional
argument is the executable to use. It can either be a self-built
executable or one returned by find_program. Keyword arguments are the
following:

- `arguments` a list of template strings that will be the command line
  arguments passed to the executable
- `depfile` is a template string pointing to a dependency file that a
  generator can write listing all the additional files this target
  depends on, for example a C compiler would list all the header files
  it included, and a change in any one of these files triggers a
  recompilation
- `output` a template string (or list of template strings) defining
  how an output file name is (or multiple output names are) generated
  from a single source file name
- `capture` when this argument is set to true, Meson captures `stdout`
  of the `executable` and writes it to the target file specified as
  `output`. Available since v0.43.0.

The returned object also has methods that are documented in the
[object methods section](#generator-object) below.

The template strings passed to all the above keyword arguments accept
the following special substitutions:

- `@PLAINNAME@`: the complete input file name, e.g: `foo.c` becomes `foo.c` (unchanged)
- `@BASENAME@`: the base of the input filename, e.g.: `foo.c.y` becomes `foo.c` (extension is removed)

Each string passed to the `output` keyword argument *must* be
constructed using one or both of these two substitutions.

In addition to the above substitutions, the `arguments` keyword
argument also accepts the following:

- `@OUTPUT@`: the full path to the output file
- `@INPUT@`: the full path to the input file
- `@SOURCE_DIR@`: the full path to the root of the source tree
- `@CURRENT_SOURCE_DIR@`: this is the directory where the currently processed meson.build is located in
- `@BUILD_DIR@`: the full path to the root of the build dir where the output will be placed

NOTE: Generators should only be used for outputs that will ***only***
be used as inputs for a [build target](#build_target) or a [custom
target](#custom_target). When you use the processed output of a
generator in multiple targets, the generator will be run multiple
times to create outputs for each target. Each output will be created
in a target-private directory `@BUILD_DIR@`.

If you want to generate files for general purposes such as for
generating headers to be used by several sources, or data that will be
installed, and so on, use a [`custom_target`](#custom_target) instead.

### get_option()

``` meson
    value get_option(option_name)
```

Obtains the value of the [project build option](Build-options.md)
specified in the positional argument.

Note that the value returned for built-in options that end in `dir`
such as `bindir` and `libdir` is always a path relative to (and
inside) the `prefix`.

The only exceptions are: `sysconfdir`, `localstatedir`, and
`sharedstatedir` which will return the value passed during
configuration as-is, which may be absolute, or relative to `prefix`.
[`install_dir` arguments](Installing.md) handles that as expected, but
if you need the absolute path to one of these e.g. to use in a define
etc., you should use `join_paths(get_option('prefix'),
get_option('localstatedir'))`

For options of type `feature` a special object is returned instead of
a string.  See [`feature` options](Build-options.md#features)
documentation for more details.

### get_variable()

``` meson
    value get_variable(variable_name, fallback)
```

This function can be used to dynamically obtain a variable. `res =
get_variable(varname, fallback)` takes the value of `varname` (which
must be a string) and stores the variable of that name into `res`. If
the variable does not exist, the variable `fallback` is stored to
`res`instead. If a fallback is not specified, then attempting to read
a non-existing variable will cause a fatal error.

### import()

``` meson
    module_object import(module_name)
```

Imports the given extension module. Returns an opaque object that can
be used to call the methods of the module. Here's an example for a
hypothetical `testmod` module.

```meson
    tmod = import('testmod')
    tmod.do_something()
```

### include_directories()

``` meson
    include_object include_directories(directory_names, ...)
```

Returns an opaque object which contains the directories (relative to
the current directory) given in the positional arguments. The result
can then be passed to the `include_directories:` keyword argument when
building executables or libraries. You can use the returned object in
any subdirectory you want, Meson will make the paths work
automatically.

Note that this function call itself does not add the directories into
the search path, since there is no global search path. For something
like that, see [`add_project_arguments()`](#add_project_arguments).

See also `implicit_include_directories` parameter of
[executable()](#executable), which adds current source and build
directories to include path.

Each directory given is converted to two include paths: one that is
relative to the source root and one relative to the build root.

For example, with the following source tree layout in
`/home/user/project.git`:

`meson.build`:
```meson
project(...)

subdir('include')
subdir('src')

...
```

`include/meson.build`:
```meson
inc = include_directories('.')

...
```

`src/meson.build`:
```meson
sources = [...]

executable('some-tool', sources,
  include_directories : inc,
  ...)

...
```

If the build tree is `/tmp/build-tree`, the following include paths
will be added to the `executable()` call: `-I/tmp/build-tree/include
-I/home/user/project.git/include`.

This function has one keyword argument `is_system` which, if set,
flags the specified directories as system directories. This means that
they will be used with the `-isystem` compiler argument rather than
`-I` on compilers that support this flag (in practice everything
except Visual Studio).

### install_data()

``` meson
    void install_data(list_of_files, ...)
```

Installs files from the source tree that are listed as positional
arguments. The following keyword arguments are supported:

- `install_dir` the absolute or relative path to the installation
  directory. If this is a relative path, it is assumed to be relative
  to the prefix.

  If omitted, the directory defaults to `{datadir}/{projectname}` *(added 0.45.0)*.

- `install_mode` specify the file mode in symbolic format and
  optionally the owner/uid and group/gid for the installed files. For
  example:

  `install_mode: 'rw-r--r--'` for just the file mode

  `install_mode: ['rw-r--r--', 'nobody', 'nobody']` for the file mode and the user/group

  `install_mode: ['rw-r-----', 0, 0]` for the file mode and uid/gid

 To leave any of these three as the default, specify `false`.

- `rename` if specified renames each source file into corresponding
  file from `rename` list. Nested paths are allowed and they are
  joined with `install_dir`. Length of `rename` list must be equal to
  the number of sources.  *(added 0.46.0)*

See [Installing](Installing.md) for more examples.

### install_headers()

``` meson
    void install_headers(list_of_headers, ...)
```

Installs the specified header files from the source tree into the
system header directory (usually `/{prefix}/include`) during the
install step. This directory can be overridden by specifying it with
the `install_dir` keyword argument. If you just want to install into a
subdirectory of the system header directory, then use the `subdir`
argument. As an example if this has the value `myproj` then the
headers would be installed to `/{prefix}/include/myproj`.

For example, this will install `common.h` and `kola.h` into
`/{prefix}/include`:

```meson
install_headers('common.h', 'proj/kola.h')
```

This will install `common.h` and `kola.h` into `/{prefix}/include/myproj`:

```meson
install_headers('common.h', 'proj/kola.h', subdir : 'myproj')
```

This will install `common.h` and `kola.h` into `/{prefix}/cust/myproj`:

```meson
install_headers('common.h', 'proj/kola.h', install_dir : 'cust', subdir : 'myproj')
```

The `install_mode` argument can be used to specify the file mode in symbolic
format and optionally the owner/uid and group/gid for the installed files.
An example value could be `['rwxr-sr-x', 'root', 'root']`.
*(Added 0.47.0)*.

### install_man()

``` meson
    void install_man(list_of_manpages, ...)
```

Installs the specified man files from the source tree into system's
man directory during the install step. This directory can be
overridden by specifying it with the `install_dir` keyword
argument. All man pages are compressed during installation and
installed with a `.gz` suffix.

The `install_mode` argument can be used to specify the file mode in symbolic
format and optionally the owner/uid and group/gid for the installed files.
An example value could be `['rwxr-sr-x', 'root', 'root']`.
*(Added 0.47.0)*.

### install_subdir()

``` meson
    void install_subdir(subdir_name, install_dir : ..., exclude_files : ..., exclude_directories : ..., strip_directory : ...)
```

Installs the entire given subdirectory and its contents from the
source tree to the location specified by the keyword argument
`install_dir`.

The following keyword arguments are supported:

- `exclude_files`: a list of file names that should not be installed.
  Names are interpreted as paths relative to the `subdir_name` location.
- `exclude_directories`: a list of directory names that should not be installed.
  Names are interpreted as paths relative to the `subdir_name` location.
- `install_dir`: the location to place the installed subdirectory.
- `install_mode`: the file mode in symbolic format and optionally
  the owner/uid and group/gid for the installed files. *(Added 0.47.0)*
- `strip_directory`: install directory contents. `strip_directory=false` by default.
  If `strip_directory=false` only last component of source path is used.
  Since 0.45.0

For a given directory `foo`:
```text
foo/
  bar/
    file1
  file2
```
`install_subdir('foo', install_dir : 'share', strip_directory : false)` creates
```text
share/
  foo/
    bar/
      file1
    file2
```

`install_subdir('foo', install_dir : 'share', strip_directory : true)` creates
```text
share/
  bar/
    file1
  file2
```

`install_subdir('foo/bar', install_dir : 'share', strip_directory : false)` creates
```text
share/
  bar/
    file1
```

`install_subdir('foo/bar', install_dir : 'share', strip_directory : true)` creates
```text
share/
  file1
```

### is_variable()

``` meson
    bool is_variable(varname)
```

Returns true if a variable of the given name exists and false otherwise.

### jar()

```meson
   jar_object jar(name, list_of_sources, ...)
```

Build a jar from the specified Java source files. Keyword arguments
are the same as [`executable`](#executable)'s, with the addition of
`main_class` which specifies the main class to execute when running
the jar with `java -jar file.jar`.

### join_paths()

``` meson
   string join_paths(string1, string2, ...)
```

Joins the given strings into a file system path segment. For example
`join_paths('foo', 'bar')` results in `foo/bar`. If any one of the
individual segments is an absolute path, all segments before it are
dropped. That means that `join_paths('foo', '/bar')` returns `/bar`.

*Added 0.36.0*

### library()

``` meson
    buildtarget library(library_name, list_of_sources, ...)
```

Builds a library that is either static, shared or both depending on
the value of `default_library` user option. You should use this
instead of [`shared_library`](#shared_library),
[`static_library`](#static_library) or
[`both_libraries`](#both_libraries) most of the time. This allows you
to toggle your entire project (including subprojects) from shared to
static with only one option.

The keyword arguments for this are the same as for
[`executable`](#executable) with the following additions:

- `name_prefix` the string that will be used as the prefix for the
  target output filename by overriding the default (only used for
  libraries). By default this is `lib` on all platforms and compilers
  except with MSVC shared libraries where it is omitted to follow
  convention.
- `name_suffix` the string that will be used as the suffix for the
  target output filename by overriding the default (see also:
  [executable()](#executable)). By default, for shared libraries this
  is `dylib` on macOS, `dll` on Windows, and `so` everywhere else.
  For static libraries, it is `a` everywhere. By convention MSVC
  static libraries use the `lib` suffix, but we use `a` to avoid a
  potential name clash with shared libraries which also generate
  `xxx.lib` import files.
- `rust_crate_type` specifies the crate type for Rust
  libraries. Defaults to `dylib` for shared libraries and `rlib` for
  static libraries.

`static_library`, `shared_library` and `both_libraries` also accept
these keyword arguments.

Note: You can set `name_prefix` and `name_suffix` to `[]`, or omit
them for the default behaviour for each platform.

### message()

``` meson
    void message(text)
```

This function prints its argument to stdout.

### warning()

``` meson
    void warning(text)
```

This function prints its argument to stdout prefixed with WARNING:.

*Added 0.44.0*

### project()

``` meson
    void project(project_name, list_of_languages, ...)
```

The first argument to this function must be a string defining the name
of this project. It is followed by programming languages that the
project uses. Supported values for languages are `c`, `cpp` (for
`C++`), `d`, `objc`, `objcpp`, `fortran`, `java`, `cs` (for `C#`) and
`vala`. In versions before `0.40.0` you must have at least one
language listed.

The project name can be any string you want, it's not used for
anything except descriptive purposes. However since it is written to
e.g. the dependency manifest is usually makes sense to have it be the
same as the project tarball or pkg-config name. So for example you
would probably want to use the name _libfoobar_ instead of _The Foobar
Library_.

Project supports the following keyword arguments.

 - `default_options` takes an array of strings. The strings are in the
   form `key=value` and have the same format as options to
   `meson configure`. For example to set the default project type you would
   set this: `default_options : ['buildtype=debugoptimized']`. Note
   that these settings are only used when running Meson for the first
   time. Global options such as `buildtype` can only be specified in
   the master project, settings in subprojects are ignored. Project
   specific options are used normally even in subprojects.


  - `license` takes a string or array of strings describing the
    license(s) the code is under. Usually this would be something like
    `license : 'GPL2+'`, but if the code has multiple licenses you can
    specify them as an array like this: `license : ['proprietary',
    'GPL3']`. Note that the text is informal and is only written to
    the dependency manifest. Meson does not do any license validation,
    you are responsible for verifying that you abide by all licensing
    terms. You can access the value in your Meson build files with
    `meson.project_license()`.

  - `meson_version` takes a string describing which Meson version the
    project requires. Usually something like `>=0.28.0`.

  - `subproject_dir` specifies the top level directory name that holds
    Meson subprojects. This is only meant as a compatibility option
    for existing code bases that house their embedded source code in a
    custom directory. All new projects should not set this but instead
    use the default value. It should be noted that this keyword
    argument is ignored inside subprojects. There can be only one
    subproject dir and it is set in the top level Meson file.

 - `version`, which is a free form string describing the version of
   this project. You can access the value in your Meson build files
   with `meson.project_version()`.

### run_command()

``` meson
    runresult run_command(command, list_of_args, ...)
```

Runs the command specified in positional arguments.  `command` can be
a string, or the output of [`find_program()`](#find_program),
[`files()`](#files) or [`configure_file()`](#configure_file), or [a
compiler object](#compiler-object).

Returns [an opaque object](#run-result-object) containing the result
of the invocation. The command is run from an *unspecified* directory,
and Meson will set three environment variables `MESON_SOURCE_ROOT`,
`MESON_BUILD_ROOT` and `MESON_SUBDIR` that specify the source
directory, build directory and subdirectory the target was defined in,
respectively.

This function has one keyword argument.

 - `check` takes a boolean. If `true`, the exit status code of the command will
   be checked, and the configuration will fail if it is non-zero. The default is
   `false`.
   Since 0.47.0

See also [External commands](External-commands.md).

### run_target

``` meson
runtarget run_target(target_name, ...)
```

This function creates a new top-level target that runs a specified
command with the specified arguments. Like all top-level targets, this
integrates with the selected backend. For instance, with Ninja you can
run it as `ninja target_name`. Note that a run target produces no
output as far as Meson is concerned. It is only meant for tasks such
as running a code formatter or flashing an external device's firmware
with a built file.

The command is run from an *unspecified* directory, and Meson will set
three environment variables `MESON_SOURCE_ROOT`, `MESON_BUILD_ROOT`
and `MESON_SUBDIR` that specify the source directory, build directory
and subdirectory the target was defined in, respectively.

 - `command` is a list containing the command to run and the arguments
   to pass to it. Each list item may be a string or a target. For
   instance, passing the return value of [`executable()`](#executable)
   as the first item will run that executable, or passing a string as
   the first item will find that command in `PATH` and run it.
- `depends` is a list of targets that this target depends on but which
  are not listed in the command array (because, for example, the
  script does file globbing internally)

### set_variable()

``` meson
    void set_variable(variable_name, value)
```

Assigns a value to the given variable name. Calling
`set_variable('foo', bar)` is equivalent to `foo = bar`.

**Note:** Prior to v0.46.1, the `value` parameter could not be an
array type, due to flattening of the function parameters.

### shared_library()

``` meson
    buildtarget shared_library(library_name, list_of_sources, ...)
```

Builds a shared library with the given sources. Positional and keyword
arguments are the same as for [`library`](#library) with the following
extra keyword arguments.

- `soversion` a string specifying the soversion of this shared
  library, such as `0`. On Linux and Windows this is used to set the
  soversion (or equivalent) in the filename. For example, if
  `soversion` is `4`, a Windows DLL will be called `foo-4.dll` and one
  of the aliases of the Linux shared library would be
  `libfoo.so.4`. If this is not specified, the first part of `version`
  is used instead (see below). For example, if `version` is `3.6.0` and
  `soversion` is not defined, it is set to `3`.
- `version` a string specifying the version of this shared library,
  such as `1.1.0`. On Linux and OS X, this is used to set the shared
  library version in the filename, such as `libfoo.so.1.1.0` and
  `libfoo.1.1.0.dylib`. If this is not specified, `soversion` is used
  instead (see above).
- `darwin_versions` *(added 0.48)* an integer, string, or a list of
  versions to use for setting dylib `compatibility version` and
  `current version` on macOS. If a list is specified, it must be
  either zero, one, or two elements. If only one element is specified
  or if it's not a list, the specified value will be used for setting
  both compatibility version and current version. If unspecified, the
  `soversion` will be used as per the aforementioned rules.
- `vs_module_defs` a string, a File object, or Custom Target for a
  Microsoft module definition file for controlling symbol exports,
  etc., on platforms where that is possible (e.g. Windows).

### shared_module()

``` meson
    buildtarget shared_module(module_name, list_of_sources, ...)
```

Builds a shared module with the given sources. Positional and keyword
arguments are the same as for [`library`](#library).

This is useful for building modules that will be `dlopen()`ed and
hence may contain undefined symbols that will be provided by the
library that is loading it.

If you want the shared module to be able to refer to functions and
variables defined in the [`executable`](#executable) it is loaded by,
you will need to set the `export_dynamic` argument of the executable to
`true`.

**Note:** Linking to a shared module is not supported on some
platforms, notably OSX.  Consider using a
[`shared_library`](#shared_library) instead, if you need to both
`dlopen()` and link with a library.

*Added 0.37.0*

### static_library()

``` meson
    buildtarget static_library(library_name, list_of_sources, ...)
```

Builds a static library with the given sources. Positional and keyword
arguments are otherwise the same as for [`library`](#library), but it
has one argument the others don't have:

 - `pic`, (*Added 0.36.0*) builds the library as positional
   independent code (so it can be linked into a shared library). This
   option has no effect on Windows and OS X since it doesn't make
   sense on Windows and PIC cannot be disabled on OS X.

### subdir()

``` meson
    void subdir(dir_name, ...)
```

Enters the specified subdirectory and executes the `meson.build` file
in it. Once that is done, it returns and execution continues on the
line following this `subdir()` command. Variables defined in that
`meson.build` file are then available for use in later parts of the
current build file and in all subsequent build files executed with
`subdir()`.

Note that this means that each `meson.build` file in a source tree can
and must only be executed once.

This function has one keyword argument.

 - `if_found` takes one or several dependency objects and will only
   recurse in the subdir if they all return `true` when queried with
   `.found()`

### subdir_done()

``` meson
    subdir_done()
```

Stops further interpretation of the meson script file from the point of
the invocation. All steps executed up to this point are valid and will
be executed by meson. This means that all targets defined before the call
of `subdir_done` will be build.

If the current script was called by `subdir` the execution returns to the
calling directory and continues as if the script had reached the end.
If the current script is the top level script meson configures the project
as defined up to this point.

Example:
```meson
project('example exit', 'cpp')
executable('exe1', 'exe1.cpp')
subdir_done()
executable('exe2', 'exe2.cpp')
```

The executable `exe1` will be build, while the executable `exe2` is not
build.

### subproject()

``` meson
    subproject_object subproject(subproject_name, ...)
```

Takes the project specified in the positional argument and brings that
in the current build specification by returning a [subproject
object](#subproject-object). Subprojects must always be placed inside
the `subprojects` directory at the top source directory. So for
example a subproject called `foo` must be located in
`${MESON_SOURCE_ROOT}/subprojects/foo`. Supports the following keyword
arguments:

 - `default_options` *(added 0.37.0)* an array of default option values
   that override those set in the subproject's `meson_options.txt`
   (like `default_options` in `project`, they only have effect when
   Meson is run for the first time, and command line arguments override
   any default options in build files)
 - `version` keyword argument that works just like the one in
   `dependency`. It specifies what version the subproject should be,
   as an example `>=1.0.1`

Note that you can use the returned [subproject
object](#subproject-object) to access any variable in the
subproject. However, if you want to use a dependency object from
inside a subproject, an easier way is to use the `fallback:` keyword
argument to [`dependency()`](#dependency).

[See additional documentation](Subprojects.md).

### test()

``` meson
    void test(name, executable, ...)
```

Defines a test to run with the test harness. Takes two positional
arguments, the first is the name of the test and the second is the
executable to run.  The executable can be an [executable build target
object](#build-target-object) returned by
[`executable()`](#executable) or an [external program
object](#external-program-object) returned by
[`find_program()`](#find_program). The executable's exit code is used
by the test harness to record the outcome of the test, for example
exit code zero indicates success. For more on the Meson test harness
protocol read [Unit Tests](Unit-tests.md).

Keyword arguments are the following:

- `args` arguments to pass to the executable

- `env` environment variables to set, such as `['NAME1=value1',
  'NAME2=value2']`, or an [`environment()`
  object](#environment-object) which allows more sophisticated
  environment juggling

- `is_parallel` when false, specifies that no other test must be
  running at the same time as this test

- `should_fail` when true the test is considered passed if the
  executable returns a non-zero return value (i.e. reports an error)

- `suite` `'label'` (or list of labels `['label1', 'label2']`)
  attached to this test. The suite name is qualified by a (sub)project
  name resulting in `(sub)project_name:label`. In the case of a list
  of strings, the suite names will be `(sub)project_name:label1`,
  `(sub)project_name:label2`, etc.

- `timeout` the amount of seconds the test is allowed to run, a test
  that exceeds its time limit is always considered failed, defaults to
  30 seconds

- `workdir` absolute path that will be used as the working directory
  for the test

- `depends` specifies that this test depends on the specified
  target(s), even though it does not take any of them as a command
  line argument. This is meant for cases where test finds those
  targets internally, e.g. plugins or globbing. Those targets are built
  before test is executed even if they have `build_by_default : false`.
  Since 0.46.0

Defined tests can be run in a backend-agnostic way by calling
`meson test` inside the build dir, or by using backend-specific
commands, such as `ninja test` or `msbuild RUN_TESTS.vcxproj`.

### vcs_tag()

``` meson
    customtarget vcs_tag(...)
```

This command detects revision control commit information at build time
and places it in the specified output file. This file is guaranteed to
be up to date on every build. Keywords are similar to `custom_target`.

- `command` string list with the command to execute, see
  [`custom_target`](#custom_target) for details on how this command
  must be specified
- `fallback` version number to use when no revision control
  information is present, such as when building from a release tarball
  (defaults to `meson.project_version()`)
- `input` file to modify (e.g. `version.c.in`) (required)
- `output` file to write the results to (e.g. `version.c`) (required)
- `replace_string` string in the input file to substitute with the
  commit information (defaults to `@VCS_TAG@`)

Meson will read the contents of `input`, substitute the
`replace_string` with the detected revision number, and write the
result to `output`. This method returns a 
[`custom_target`](#custom_target) object that (as usual) should be
used to signal dependencies if other targets use the file outputted
by this.

For example, if you generate a header with this and want to use that in
a build target, you must add the return value to the sources of that
build target. Without that, Meson will not know the order in which to
build the targets.

If you desire more specific behavior than what this command provides,
you should use `custom_target`.

## Built-in objects

These are built-in objects that are always available.

### `meson` object

The `meson` object allows you to introspect various properties of the
system. This object is always mapped in the `meson` variable. It has
the following methods.

- `add_dist_script` causes the script given as argument to run during
  `dist` operation after the distribution source has been generated
  but before it is archived. Note that this runs the script file that
  is in the _staging_ directory, not the one in the source
  directory. If the script file can not be found in the staging
  directory, it is a hard error. This command can only invoked from
  the main project, calling it from a subproject is a hard
  error. Available since 0.48.0.

- `add_install_script(script_name, arg1, arg2, ...)` causes the script
  given as an argument to be run during the install step, this script
  will have the environment variables `MESON_SOURCE_ROOT`,
  `MESON_BUILD_ROOT`, `MESON_INSTALL_PREFIX`,
  `MESON_INSTALL_DESTDIR_PREFIX`, and `MESONINTROSPECT` set. All
  additional arguments are passed as parameters.

  Meson uses the `DESTDIR` environment variable as set by the
  inherited environment to determine the (temporary) installation
  location for files. Your install script must be aware of this while
  manipulating and installing files. The correct way to handle this is
  with the `MESON_INSTALL_DESTDIR_PREFIX` variable which is always set
  and contains `DESTDIR` (if set) and `prefix` joined together. This
  is useful because both are usually absolute paths and there are
  platform-specific edge-cases in joining two absolute paths.

  In case it is needed, `MESON_INSTALL_PREFIX` is also always set and
  has the value of the `prefix` option passed to Meson.

  `MESONINTROSPECT` contains the path to the introspect command that
  corresponds to the `meson` executable that was used to configure the
  build. (This might be a different path then the first executable
  found in `PATH`.) It can be used to query build configuration. Note
  that the value will contain many parts, f.ex., it may be `python3
  /path/to/meson.py introspect`. The user is responsible for splitting
  the string to an array if needed by splitting lexically like a UNIX
  shell would. If your script uses Python, `shlex.split()` is the
  easiest correct way to do this.

- `add_postconf_script(script_name, arg1, arg2, ...)` will run the
  executable given as an argument after all project files have been
  generated. This script will have the environment variables
  `MESON_SOURCE_ROOT` and `MESON_BUILD_ROOT` set.

- `backend()` *(added 0.37.0)* returns a string representing the
  current backend: `ninja`, `vs2010`, `vs2015`, `vs2017`, or `xcode`.

- `build_root()` returns a string with the absolute path to the build
  root directory. Note: this function will return the build root of
  the parent project if called from a subproject, which is usually
  not what you want. Try using `current_build_dir()`.

- `source_root()` returns a string with the absolute path to the
  source root directory. Note: you should use the `files()` function
  to refer to files in the root source directory instead of
  constructing paths manually with `meson.source_root()`. This
  function will return the source root of the parent project if called
  from a subproject, which is usually not what you want. Try using
  `current_source_dir()`.

- `current_build_dir()` returns a string with the absolute path to the
  current build directory.

- `current_source_dir()` returns a string to the current source
  directory. Note: **you do not need to use this function** when
  passing files from the current source directory to a function since
  that is the default. Also, you can use the `files()` function to
  refer to files in the current or any other source directory instead
  of constructing paths manually with `meson.current_source_dir()`.

- `get_cross_property(propname, fallback_value)` returns the given
  property from a cross file, the optional second argument is returned
  if not cross compiling or the given property is not found.

- `get_compiler(language)` returns [an object describing a
  compiler](#compiler-object), takes one positional argument which is
  the language to use. It also accepts one keyword argument, `native`
  which when set to true makes Meson return the compiler for the build
  machine (the "native" compiler) and when false it returns the host
  compiler (the "cross" compiler). If `native` is omitted, Meson
  returns the "cross" compiler if we're currently cross-compiling and
  the "native" compiler if we're not.

- `has_exe_wrapper()` returns true when doing a cross build if there
  is a wrapper command that can be used to execute cross built
  binaries (for example when cross compiling from Linux to Windows,
  one can use `wine` as the wrapper).

- `install_dependency_manifest(output_name)` installs a manifest file
  containing a list of all subprojects, their versions and license
  files to the file name given as the argument.

- `is_cross_build()` returns `true` if the current build is a [cross
  build](Cross-compilation.md) and `false` otherwise.

- `is_subproject()` returns `true` if the current project is being
  built as a subproject of some other project and `false` otherwise.

- `is_unity()` returns `true` when doing a [unity
  build](Unity-builds.md) (multiple sources are combined before
  compilation to reduce build time) and `false` otherwise.

- `override_find_program(progname, program)` [*(Added
  0.46.0)*](Release-notes-for-0-46-0.html#can-override-find_program)
  specifies that whenever `find_program` is used to find a program
  named `progname`, Meson should not not look it up on the system but
  instead return `program`, which may either be the result of
  `find_program`, `configure_file` or `executable`.

  If `program` is an `executable`, it cannot be used during configure.

- `project_version()` returns the version string specified in
  `project` function call.

- `project_license()` returns the array of licenses specified in
  `project` function call.

- `project_name()` returns the project name specified in the `project`
  function call.

- `version()` return a string with the version of Meson.

### `build_machine` object

Provides information about the build machine — the machine that is
doing the actual compilation. See
[Cross-compilation](Cross-compilation.md). It has the following
methods:

- `cpu_family()` returns the CPU family name. [This
  table](Reference-tables.md#cpu-families) contains all known CPU
  families. These are guaranteed to continue working.

- `cpu()` returns a more specific CPU name, such as `i686`, `amd64`,
  etc.

- `system()` returns the operating system name.  [This
  table](Reference-tables.html#operating-system-names) Lists all of
  the currently known Operating System names, these are guaranteed to
  continue working.

- `endian()` returns `big` on big-endian systems and `little` on
  little-endian systems.

Currently, these values are populated using
[`platform.system()`](https://docs.python.org/3.4/library/platform.html#platform.system)
and
[`platform.machine()`](https://docs.python.org/3.4/library/platform.html#platform.machine). If
you think the returned values for any of these are incorrect for your
system or CPU, or if your OS is not in the linked table, please file
[a bug report](https://github.com/mesonbuild/meson/issues/new) with
details and we'll look into it.

### `host_machine` object

Provides information about the host machine — the machine on which the
compiled binary will run. See
[Cross-compilation](Cross-compilation.md).

It has the same methods as [`build_machine`](#build_machine-object).

When not cross-compiling, all the methods return the same values as
`build_machine` (because the build machine is the host machine)

Note that while cross-compiling, it simply returns the values defined
in the cross-info file.

### `target_machine` object

Provides information about the target machine — the machine on which
the compiled binary's output will run. Hence, this object should only
be used while cross-compiling a compiler. See
[Cross-compilation](Cross-compilation.md).

It has the same methods as [`build_machine`](#build_machine-object).

When all compilation is 'native', all the methods return the same
values as `build_machine` (because the build machine is the host
machine and the target machine).

Note that while cross-compiling, it simply returns the values defined
in the cross-info file. If `target_machine` values are not defined in
the cross-info file, `host_machine` values are returned instead.

### `compiler` object

This object is returned by
[`meson.get_compiler(lang)`](#meson-object). It represents a compiler
for a given language and allows you to query its properties. It has
the following methods:

- `alignment(typename)` returns the alignment of the type specified in
  the positional argument, you can specify external dependencies to
  use with `dependencies` keyword argument.

- `compiles(code)` returns true if the code fragment given in the
  positional argument compiles, you can specify external dependencies
  to use with `dependencies` keyword argument, `code` can be either a
  string containing source code or a `file` object pointing to the
  source code.

- `compute_int(expr, ...')` computes the value of the given expression
  (as an example `1 + 2`). When cross compiling this is evaluated with
  an iterative algorithm, you can specify keyword arguments `low`
  (defaults to -1024), `high` (defaults to 1024) and `guess` to
  specify max and min values for the search and the value to try
  first.

- `find_library(lib_name, ...)` tries to find the library specified in
  the positional argument. The [result
  object](#external-library-object) can be used just like the return
  value of `dependency`. If the keyword argument `required` is false,
  Meson will proceed even if the library is not found. By default the
  library is searched for in the system library directory
  (e.g. /usr/lib). This can be overridden with the `dirs` keyword
  argument, which can be either a string or a list of strings.  Since
  *0.47.0* the value of a [`feature`](Build-options.md#features)
  option can also be passed to the `required` keyword argument.

- `first_supported_argument(list_of_strings)`, given a list of
  strings, returns the first argument that passes the `has_argument`
  test or an empty array if none pass.

- `first_supported_link_argument(list_of_strings)` *(added 0.46.0)*,
  given a list of strings, returns the first argument that passes the
  `has_link_argument` test or an empty array if none pass.

- `get_define(definename)` returns the given preprocessor symbol's
  value as a string or empty string if it is not defined.
  Starting with 0.47.0, this method will concatenate string literals as
  the compiler would. E.g. `"a" "b"` will become `"ab"`.

- `get_id()` returns a string identifying the compiler. For example,
  `gcc`, `msvc`, [and more](Reference-tables.html#compiler-ids).

- `get_supported_arguments(list_of_string)` *(added 0.43.0)* returns
  an array containing only the arguments supported by the compiler,
  as if `has_argument` were called on them individually.

- `get_supported_link_arguments(list_of_string)` *(added 0.46.0)* returns
  an array containing only the arguments supported by the linker,
  as if `has_link_argument` were called on them individually.

- `has_argument(argument_name)` returns true if the compiler accepts
  the specified command line argument, that is, can compile code
  without erroring out or printing a warning about an unknown flag.

- `has_link_argument(argument_name)` *(added 0.46.0)* returns true if
  the linker accepts the specified command line argument, that is, can
  compile and link code without erroring out or printing a warning
  about an unknown flag. Link arguments will be passed to the
  compiler, so should usually have the `-Wl,` prefix. On VisualStudio
  a `/link` argument will be prepended.

- `has_function(funcname)` returns true if the given function is
  provided by the standard library or a library passed in with the
  `args` keyword, you can specify external dependencies to use with
  `dependencies` keyword argument.

- `check_header` *(added 0.47.0)* returns true if the specified header is *usable* with
  the specified prefix, dependencies, and arguments.
  You can specify external dependencies to use with `dependencies`
  keyword argument and extra code to put above the header test with
  the `prefix` keyword. In order to look for headers in a specific
  directory you can use `args : '-I/extra/include/dir`, but this
  should only be used in exceptional cases for includes that can't be
  detected via pkg-config and passed via `dependencies`.

- `has_header` returns true if the specified header *exists*, and is
  faster than `check_header()` since it only does a pre-processor check.
  You can specify external dependencies to use with `dependencies`
  keyword argument and extra code to put above the header test with
  the `prefix` keyword. In order to look for headers in a specific
  directory you can use `args : '-I/extra/include/dir`, but this
  should only be used in exceptional cases for includes that can't be
  detected via pkg-config and passed via `dependencies`.

- `has_header_symbol(headername, symbolname)` allows one to detect
  whether a particular symbol (function, variable, #define, type
  definition, etc) is declared in the specified header, you can
  specify external dependencies to use with `dependencies` keyword
  argument.

- `has_member(typename, membername)` takes two arguments, type name
  and member name and returns true if the type has the specified
  member, you can specify external dependencies to use with
  `dependencies` keyword argument.

- `has_members(typename, membername1, membername2, ...)` takes at
  least two arguments, type name and one or more member names, returns
  true if the type has all the specified members, you can specify
  external dependencies to use with `dependencies` keyword argument.

- `has_multi_arguments(arg1, arg2, arg3, ...)` is the same as
  `has_argument` but takes multiple arguments and uses them all in a
  single compiler invocation, available since 0.37.0.

- `has_multi_link_arguments(arg1, arg2, arg3, ...)` *(added 0.46.0)*
  is the same as `has_link_argument` but takes multiple arguments and
  uses them all in a single compiler invocation.

- `has_type(typename)` returns true if the specified token is a type,
  you can specify external dependencies to use with `dependencies`
  keyword argument.

- `links(code)` returns true if the code fragment given in the
  positional argument compiles and links, you can specify external
  dependencies to use with `dependencies` keyword argument, `code` can
  be either a string containing source code or a `file` object
  pointing to the source code.

- `run(code)` attempts to compile and execute the given code fragment,
  returns a run result object, you can specify external dependencies
  to use with `dependencies` keyword argument, `code` can be either a
  string containing source code or a `file` object pointing to the
  source code.

- `symbols_have_underscore_prefix()` returns `true` if the C symbol
  mangling is one underscore (`_`) prefixed to the symbol, available
  since 0.37.0.

- `sizeof(typename, ...)` returns the size of the given type
  (e.g. `'int'`) or -1 if the type is unknown, to add includes set
  them in the `prefix` keyword argument, you can specify external
  dependencies to use with `dependencies` keyword argument.

- `version()` returns the compiler's version number as a string.

- `has_function_attribute(name)` *(added in 0.48.0)* returns `true` if the
  compiler supports the GNU style (`__attribute__(...)`) `name`. This is
  preferable to manual compile checks as it may be optimized for compilers that
  do not support such attributes.
  [This table](Reference-tables.html#gcc-attribute-support) Lists all of the
  supported attributes.

- `get_supported_function_attributes(list_of_names)` *(added in 0.48.0)
  returns an array containing any names that are supported GCC style
  attributes. Equivalent to `has_function_attribute` was called on each of them
  individually.

The following keyword arguments can be used:

- `args` can be used to pass a list of compiler arguments that are
  required to find the header or symbol. For example, you might need
  to pass the include path `-Isome/path/to/header` if a header is not
  in the default include path. In versions newer than 0.38.0 you
  should use the `include_directories` keyword described above. You
  may also want to pass a library name `-lfoo` for `has_function` to
  check for a function. Supported by all methods except `get_id`,
  `version`, and `find_library`.

- `include_directories` specifies extra directories for header
  searches. *(added 0.38.0)*

- `name` the name to use for printing a message about the compiler
  check. Supported by the methods `compiles()`, `links()`, and
  `run()`. If this keyword argument is not passed to those methods, no
  message will be printed about the check.

- `prefix` can be used to add #includes and other things that are
  required for the symbol to be declared. System definitions should be
  passed via compiler args (eg: `_GNU_SOURCE` is often required for
  some symbols to be exposed on Linux, and it should be passed via
  `args` keyword argument, see below). Supported by the methods
  `sizeof`, `has_type`, `has_function`, `has_member`, `has_members`,
  `check_header`, `has_header`, `has_header_symbol`.

**Note:** These compiler checks do not use compiler arguments added with 
`add_*_arguments()`, via `-Dlang_args` on the command-line, or through
`CFLAGS`/`LDFLAGS`, etc in the environment. Hence, you can trust that
the tests will be fully self-contained, and won't fail because of custom
flags added by other parts of the build file or by users.

Note that if you have a single prefix with all your dependencies, you
might find it easier to append to the environment variables
`C_INCLUDE_PATH` with GCC/Clang and `INCLUDE` with MSVC to expand the
default include path, and `LIBRARY_PATH` with GCC/Clang and `LIB` with
MSVC to expand the default library search path.

However, with GCC, these variables will be ignored when
cross-compiling. In that case you need to use a specs file. See:
<http://www.mingw.org/wiki/SpecsFileHOWTO>

### `string` object

All [strings](Syntax.md#strings) have the following methods. Strings
are immutable, all operations return their results as a new string.

- `contains(string)` returns true if string contains the string
  specified as the argument

- `endswith(string)` returns true if string ends with the string
  specified as the argument

- `format()` formats text, see the [Syntax
  manual](Syntax.md#string-formatting) for usage info

- `join(list_of_strings)` is the opposite of split, for example
  `'.'.join(['a', 'b', 'c']` yields `'a.b.c'`

- `split(split_character)` splits the string at the specified
  character (or whitespace if not set) and returns the parts in an
  array

- `startswith(string)` returns true if string starts with the string
  specified as the argument

- `strip()` removes whitespace at the beginning and end of the string
  *(added 0.43.0)* optionally can take one positional string argument,
  and all characters in that string will be stripped

- `to_int` returns the string converted to an integer (error if string
  is not a number)

- `to_lower()` creates a lower case version of the string

- `to_upper()` creates an upper case version of the string

- `underscorify()` creates a string where every non-alphabetical
  non-number character is replaced with `_`

- `version_compare(comparison_string)` does semantic version
  comparison, if `x = '1.2.3'` then `x.version_compare('>1.0.0')`
  returns `true`

### `Number` object

[Numbers](Syntax.md#numbers) support these methods:

 - `is_even()` returns true if the number is even
 - `is_odd()` returns true if the number is odd

### `boolean` object

A [boolean](Syntax.md#booleans) object has two simple methods:

- `to_int()` as above, but returns either `1` or `0`

- `to_string()` returns the string `'true'` if the boolean is true or
  `'false'` otherwise. You can also pass it two strings as positional
  arguments to specify what to return for true/false. For instance,
  `bool.to_string('yes', 'no')` will return `yes` if the boolean is
  true and `no` if it is false.

### `array` object

The following methods are defined for all [arrays](Syntax.md#arrays):

- `contains(item)`, returns `true` if the array contains the object
  given as argument, `false` otherwise

- `get(index, fallback)`, returns the object at the given index,
  negative indices count from the back of the array, indexing out of
  bounds returns the `fallback` value *(added 0.38.0)* or, if it is
  not specified, causes a fatal error

- `length()`, the size of the array

You can also iterate over arrays with the [`foreach`
statement](Syntax.md#foreach-statements).

### `dictionary` object

The following methods are defined for all [dictionaries](Syntax.md#dictionaries):

- `has_key(key)` returns `true` if the dictionary contains the key
  given as argument, `false` otherwise

- `get(key, fallback)`, returns the value for the key given as first
  argument if it is present in the dictionary, or the optional
  fallback value given as the second argument. If a single argument
  was given and the key was not found, causes a fatal error

You can also iterate over dictionaries with the [`foreach`
statement](Syntax.md#foreach-statements).

Dictionaries are available since 0.47.0.

Since 0.48.0 dictionaries can be added (e.g. `d1 = d2 + d3` and `d1 += d2`).
Values from the second dictionary overrides values from the first.

## Returned objects

These are objects returned by the [functions listed above](#functions).

### `build target` object

A build target is either an [executable](#executable),
[shared library](#shared_library), [static library](#static_library),
[both shared and static library](#both_libraries) or
[shared module](#shared_module).

- `extract_all_objects()` is same as `extract_objects` but returns all
  object files generated by this target. Since 0.46.0 keyword argument
  `recursive` must be set to `true` to also return objects passed to
  the `object` argument of this target. By default only objects built
  for this target are returned to maintain backward compatibility with
  previous versions.  The default will eventually be changed to `true`
  in a future version.

- `extract_objects()` returns an opaque value representing the
  generated object files of arguments, usually used to take single
  object files and link them to unit tests or to compile some source
  files with custom flags. To use the object file(s) in another build
  target, use the `objects:` keyword argument.

- `full_path()` returns a full path pointing to the result target file.
  NOTE: In most cases using the object itself will do the same job as
  this and will also allow Meson to setup inter-target dependencies
  correctly. Please file a bug if that doesn't work for you.

- `private_dir_include()` returns a opaque value that works like
  `include_directories` but points to the private directory of this
  target, usually only needed if an another target needs to access
  some generated internal headers of this target


### `configuration` data object

This object is returned by
[`configuration_data()`](#configuration_data) and encapsulates
configuration values to be used for generating configuration files. A
more in-depth description can be found in the [the configuration wiki
page](Configuration.md) It has three methods:

- `get(varname, default_value)` returns the value of `varname`, if the
  value has not been set returns `default_value` if it is defined
  *(added 0.38.0)* and errors out if not

- `get_unquoted(varname, default_value)` returns the value of `varname`
  but without surrounding double quotes (`"`). If the value has not been
  set returns `default_value` if it is defined and errors out if not.
  Available since 0.44.0

- `has(varname)`, returns `true` if the specified variable is set

- `merge_from(other)` takes as argument a different configuration data
  object and copies all entries from that object to the current
  object, available since 0.42.0

- `set(varname, value)`, sets a variable to a given value

- `set10(varname, boolean_value)` is the same as above but the value
  is either `true` or `false` and will be written as 1 or 0,
  respectively

- `set_quoted(varname, value)` is same as `set` but quotes the value
  in double quotes (`"`)

They all take the `description` keyword that will be written in the
result file. The replacement assumes a file with C syntax. If your
generated file is source code in some other language, you probably
don't want to add a description field because it most likely will
cause a syntax error.

### `custom target` object

This object is returned by [`custom_target`](#custom_target) and
contains a target with the following methods:

- `full_path()` returns a full path pointing to the result target file
  NOTE: In most cases using the object itself will do the same job as
  this and will also allow Meson to setup inter-target dependencies
  correctly. Please file a bug if that doesn't work for you.

- `[index]` returns an opaque object that references this target, and
  can be used as a source in other targets. When it is used as such it
  will make that target depend on this custom target, but the only
  source added will be the one that corresponds to the index of the
  custom target's output argument.

### `dependency` object

This object is returned by [`dependency()`](#dependency) and contains
an external dependency with the following methods:

 - `found()` which returns whether the dependency was found

 - `get_pkgconfig_variable(varname)` (*Added 0.36.0*) will get the
   pkg-config variable specified, or, if invoked on a non pkg-config
   dependency, error out. (*Added 0.44.0*) You can also redefine a
   variable by passing a list to the `define_variable` parameter
   that can affect the retrieved variable: `['prefix', '/'])`.
   (*Added 0.45.0*) A warning is issued if the variable is not defined,
   unless a `default` parameter is specified.

 - `get_configtool_variable(varname)` (*Added 0.44.0*) will get the
   command line argument from the config tool (with `--` prepended), or,
   if invoked on a non config-tool dependency, error out.

 - `type_name()` which returns a string describing the type of the
   dependency, the most common values are `internal` for deps created
   with `declare_dependency()` and `pkgconfig` for system dependencies
   obtained with Pkg-config.

 - `version()` is the version number as a string, for example `1.2.8`.
   `unknown` if the dependency provider doesn't support determining the
   version.

 - `partial_dependency(compile_args : false, link_args : false, links
   : false, includes : false, source : false)` (*added 0.46.0*) returns
   a new dependency object with the same name, version, found status,
   type name, and methods as the object that called it. This new
   object will only inherit other attributes from its parent as
   controlled by keyword arguments.

   If the parent has any dependencies, those will be applied to the new
   partial dependency with the same rules. So , given:

   ```meson
   dep1 = declare_dependency(compiler_args : '-Werror=foo', link_with : 'libfoo')
   dep2 = declare_dependency(compiler_args : '-Werror=bar', dependencies : dep1)
   dep3 = dep2.partial_dependency(compile_args : true)
   ```

   dep3 will add `['-Werror=foo', '-Werror=bar']` to the compiler args
   of any target it is added to, but libfoo will not be added to the
   link_args.

   The following arguments will add the following attributes:

   - compile_args: any arguments passed to the compiler
   - link_args: any arguments passed to the linker
   - links: anything passed via link_with or link_whole
   - includes: any include_directories
   - sources: any compiled or static sources the dependency has

### `disabler` object

A disabler object is an object that behaves in much the same way as
NaN numbers do in floating point math. That is when used in any
statement (function call, logical op, etc) they will cause the
statement evaluation to immediately short circuit to return a disabler
object. A disabler object has one method:

  - `found()`, always returns `false`

### `external program` object

This object is returned by [`find_program()`](#find_program) and
contains an external (i.e. not built as part of this project) program
and has the following methods:

- `found()` which returns whether the executable was found

- `path()` which returns a string pointing to the script or executable
  **NOTE:** You should not need to use this method. Passing the object
  itself should work in all cases. F.ex.: `run_command(obj, arg1, arg2)`

### `environment` object

This object is returned by [`environment()`](#environment) and stores
detailed information about how environment variables should be set
during tests. It should be passed as the `env` keyword argument to
tests. It has the following methods.

- `append(varname, value1, value2, ...)` appends the given values to
  the old value of the environment variable, e.g.  `env.append('FOO',
  'BAR', 'BAZ', separator : ';')` produces `BOB;BAR;BAZ` if `FOO` had
  the value `BOB` and plain `BAR;BAZ` if the value was not defined. If
  the separator is not specified explicitly, the default path
  separator for the host operating system will be used, i.e. ';' for
  Windows and ':' for UNIX/POSIX systems.

- `prepend(varname, value1, value2, ...)` is the same as `append` except that it
  writes to the beginning of the variable

- `set(varname, value1, value2)` sets the environment variable
  specified in the first argument to the values in the second argument
  joined by the separator, e.g.  `env.set('FOO', 'BAR'),` sets envvar
  `FOO` to value `BAR`. See `append()` above for how separators work.

**Note:** All these methods overwrite the previously-defined value(s)
if called twice with the same `varname`.

### `external library` object

This object is returned by [`find_library()`](#find_library) and
contains an external (i.e. not built as part of this project)
library. This object has the following methods:

 - `found` which returns whether the library was found.

 - `type_name()` (*added 0.48.0*) which returns a string describing
   the type of the dependency, which will be `library` in this case.

 - `partial_dependency(compile_args : false, link_args : false, links
   : false, includes : false, source : false)` (*added 0.46.0*) returns
   a new dependency object with the same name, version, found status,
   type name, and methods as the object that called it. This new
   object will only inherit other attributes from its parent as
   controlled by keyword arguments.

### `generator` object

This object is returned by [`generator()`](#generator) and contains a
generator that is used to transform files from one type to another by
an executable (e.g. `idl` files into source code and headers).

* `process(list_of_files, ...)` takes a list of files, causes them to
  be processed and returns an object containing the result which can
  then, for example, be passed into a build target definition. The
  keyword argument `extra_args`, if specified, will be used to replace
  an entry `@EXTRA_ARGS@` in the argument list. The keyword argument
  `preserve_path_from`, if given, specifies that the output files need
  to maintain their directory structure inside the target temporary
  directory. The most common value for this is
  `meson.current_source_dir()`. With this value when a file called
  `subdir/one.input` is processed it generates a file `<target private
  directory>/subdir/one.out` as opposed to `<target private
  directory>/one.out`.

### `subproject` object

This object is returned by [`subproject()`](#subproject) and is an
opaque object representing it.

- `get_variable(name)` fetches the specified variable from inside the
  subproject. This is useful to, for instance, get a [declared
  dependency](#declare_dependency) from the [subproject](Subprojects.md).

### `run result` object

This object encapsulates the result of trying to compile and run a
sample piece of code with [`compiler.run()`](#compiler-object) or
[`run_command()`](#run_command). It has the following methods:

- `compiled()` if true, the compilation succeeded, if false it did not
  and the other methods return unspecified data
- `returncode()` the return code of executing the compiled binary
- `stderr()` the standard error produced when the command was run
- `stdout()` the standard out produced when the command was run
