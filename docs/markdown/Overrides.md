# Overriding project options for subprojects

_This feature is available in Meson version 0.59.0 and later._

Configuring a project with build options is straightforward for a
single project. Things get more compilicated when you have multiple
subprojects that need different settings. As an example you might want
to build the project using the `C11` C language standard but you have
a dependency library that must be built with the `gnu99` dialect of C.
As the number of subprojects grows, the number of options to change
gets bigger and bigger and eventually becomes unusable. Meson provides
a mechanism called an _override file_ to solve this problem.

An override is nothing more than a file like cross and native files
that can be used to specify the option values you need. The override
file is itself specified with a Meson build option, either during
setup or later with configure:

     meson -Doverride_file=myoverrides.txt <srcdir> <builddir>

As an example a file that disables compiler warnings on subproject
`sub1` and to build `sub2` as `gnu99` would look like this:

```
[options_sub1]
warning_level = '0'

[options_sub2]
c_std = 'gnu99'
```

This approach allows users to configure builds to their specific needs
without needing to manually edit the build files of subprojects.

## Overriding options for all subprojects

A common need during regular development is to build all your
dependencies with optimizations enabled but so that the master project
is not optimized. The override file has a special syntax for
specifying an option for all subprojcts.

```
[options_subprojects]
buildtype = 'debugoptimized`
```

If the `buildtype` is set to `debug` the end result is as expected. It
is even possible to disable generating debug information, which is
usually slow:

```
[options_subprojects]
optimization = '2'
debug = false
```

This may speed up builds and reduce disk space usage, but the downside
is that debugging issues in subprojects becomes infeasible. If the
dependencies are of sufficiently high quality that you don't need to
debug issues in them, then this may be a worthwhile tradeoff.

Individual overrides have preference over the general subprojects one:

```
[options_subprojects]
warning_level = '2'

[options_sub1]
warning_level = '1'
```

In this case the subproject `sub1` would have warning level 1, all
other subprojects would have warning level `1` and the top level
project would have whatever warning level has been set in the global
`warning_level` option.
