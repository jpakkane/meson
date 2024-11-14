# Features module

## Overview

Dealing with a numerous of CPU features within C and C++ compilers poses intricate challenges,
particularly when endeavoring to support an extensive set of CPU features across diverse
architectures and multiple compilers. Furthermore, the conundrum of accommodating
both fundamental features and supplementary features dispatched at runtime
further complicates matters.

In addition, the task of streamlining generic interface implementations often leads to the necessity
of intricate solutions, which can obscure code readability and hinder debugging and maintenance.
Nested namespaces, recursive sources, complex precompiled macros, or intricate meta templates
are commonly employed but can result in convoluted code structures.

Enter the proposed module, which offers a simple pragmatic multi-target solution to
facilitate the management of CPU features with heightened ease and reliability.

In essence, this module introduces the following core principle:

```C
// Include header files for enabled CPU features
#ifdef HAVE_SSE
    #include <xmmintrin.h>
#endif
#ifdef HAVE_SSE2
    #include <emmintrin.h>
#endif
#ifdef HAVE_SSE3
    #include <pmmintrin.h>
#endif
#ifdef HAVE_SSSE3
    #include <tmmintrin.h>
#endif
#ifdef HAVE_SSE41
    #include <smmintrin.h>
#endif
#ifdef HAVE_NEON
    #include <arm_neon.h>
#endif
// ... (similar blocks for other features)

// MTARGETS_CURRENT defined as compiler argument via `features.multi_targets()`
#ifdef MTARGETS_CURRENT
    #define TARGET_SFX(X) X##_##MTARGETS_CURRENT
#else
    // baseline or when building source without this module.
    #define TARGET_SFX(X) X
#endif

// Core function utilizing feature-specific implementations
void TARGET_SFX(my_kernal)(const float *src, float *dst)
{
// Feature-based branching
#if defined(HAVE_SSE41)
    // Definitions for implied features always present,
    // regardless of the compiler used.
    #ifndef HAVE_SSSE3
        #error "Alawys defined"
    #endif
#elif defined(HAVE_SSE2)
    #ifndef HAVE_SSE2
        #error "Alawys defined"
    #endif
#elif defined(HAVE_ASIMDHP)
    #if !defined(HAVE_NEON) || !defined(HAVE_ASIMD)
        #error "Alawys defined"
    #endif
#elif defined(HAVE_ASIMD)
    #ifndef HAVE_NEON_VFPV4
        #error "Alawys defined"
    #endif
#elif defined(HAVE_NEON_F16)
    #ifndef HAVE_NEON
        #error "Alawys defined"
    #endif
#else
    // fallback to C scalar
#endif
}
```

Key Takeaways from the Code:

- The code employs feature-centric definitions, enhancing readability
  and flexibility while sidestepping the need for feature grouping.

- Notably, compiler-built definitions are circumvented, thereby affording
  seamless management of enabled/disabled features and accommodating diverse compilers and feature sets.
  Notably, this accommodates compilers like MSVC, which might lack definitions for specific CPU features.

- The code remains agnostic about its build process, granting it remarkable versatility
  in managing generated objects. This empowers the ability to elevate baseline features at will,
  adjust additional dispatched features, and effect changes without necessitating code modifications.

- The architecture permits the construction of a singular source, which can be compiled multiple times.
  This strategic approach simplifies the implementation of generic interfaces, streamlining the development process.


## Usage
To use this module, just do: **`features = import('features')`**. The
following functions will then be available as methods on the object
with the name `features`. You can, of course, replace the name `features`
with anything else.

### features.new()

**Signature**
```meson
FeatureObject features.new(
  # Positional arguments:
  str,
  int,
  # Keyword arguments:
  implies      : FeatureOject | list[FeatureObject] = [],
  group        : str | list[str] = [],
  args         : str | dict[str] | list[str | dict[str]] = [],
  detect       : str | dict[str] | list[str | dict[str]] = [],
  test_code    : str | File = '',
  extra_tests  : dict[str | file] = {},
  disable      : str = ''
)
```

The `features.new()` function plays a pivotal role within the Features Module.
It creates a fresh mutable instance of FeatureObject, an essential component
for facilitating the functionality of other methods within the module.

This function requires two positional arguments. The first argument pertains to the feature's name,
while the second one involves the interest level of the feature. This interest level governs sorting
operations and aids in resolving conflicts among arguments with differing priorities.

Additional keyword arguments are elaborated as follows:

* `implies` **FeatureOject | list[FeatureObject]**:
  An optional single feature object or an array of feature objects
  representing predecessor features. It is noteworthy that two features can imply each other.
  Such mutual implication can prove beneficial in addressing compatibility concerns with compilers or hardware.
  For instance, while some compilers might require enabling both `AVX2` and `FMA3` simultaneously,
  others may permit independent activation.

* `group` **str | list[str]**:
  An optional single feature name or an array of additional feature names. These names are appended as
  supplementary definitions that can be passed to the source.

* `args` **str | dict[str] | list[str | dict[str]] = []**:
  An optional single compiler argument or an array of compiler arguments that must be enabled for
  the corresponding feature. Each argument can be a string or a dictionary containing four elements.
  These elements handle conflicts arising from arguments of implied features or when concatenating two features:
  - `val` **str**:
    The compiler argument.
  - `match` **str | empty**:
    A regular expression to match arguments of implied features that necessitate filtering or removal.
  - `mfilter` **str | empty**:
    A regular expression to identify specific strings from matched arguments.
    These strings are combined with `val`. If `mfilter` is empty or undefined,
    matched arguments from `match` will not be combined with `val`.
  - `mjoin` **str | empty**:
    A separator used to join all filtered arguments.
    If undefined or empty, filtered arguments are joined without a separator.

* `detect` **str | dict[str] | list[str | dict[str]] = [] = []**:
  An optional single feature name or an array of feature names to be detected at runtime.
  If no feature names are specified, the values from the `group` will be used.
  If the `group` doesn't provide values, the feature's name is employed instead.
  Similar to args, each feature name can be a string or a dictionary with four
  elements to manage conflicts of implied feature names.
  Refer to `features.multi_targets()` or `features.test()` for further clarity.

* `test_code` **str | File = ''**:
  An optional block of C/C++ code or the path to a source file for testing against the compiler.
  Successful compilation indicates feature support.

* `extra_tests` **dict[str | file] = {}**:
  An optional dictionary containing extra tests. The keys represent test names,
  and the associated values are C/C++ code or paths to source files.
  Successful tests lead to compiler definitions based on the test names.

* `disable` **str = ''**:
  An optional string to mark a feature as disabled.
  If the string is empty or undefined, the feature is considered not disabled.

The function returns a new instance of `FeatureObject`.

Example:

```Meson
cpu = host_machine.cpu_family()
features = import('features')

ASIMD = features.new(
  'ASIMD', 1, group: ['NEON', 'NEON_VFPV4', 'NEON_VFPV4'],
  args: cpu == 'aarch64' ? '' : [
    '-mfpu=neon-fp-armv8',
    '-march=armv8-a+simd'
  ],
  disable: cpu in ['arm', 'aarch64'] ? '' : 'Not supported by ' + cpu
)
# ARMv8.2 half-precision & vector arithm
ASIMDHP = features.new(
  'ASIMDHP', 2, implies: ASIMD,
  args: {
    'val': '-march=armv8.2-a+fp16',
    # search for any argument starts with `-match=`
    'match': '-march=',
    # gets any string starts with `+` and apended to the value of `val`
    'mfilter': '\+.*'
  }
)
## ARMv8.2 dot product
ASIMDDP = features.new(
  'ASIMDDP', 3, implies: ASIMD,
  args: {'val': '-march=armv8.2-a+dotprod', 'match': '-march=.*', 'mfilter': '\+.*'}
)
## ARMv8.2 Single & half-precision Multiply
ASIMDFHM = features.new(
  'ASIMDFHM', 4, implies: ASIMDHP,
  args: {'val': '-march=armv8.2-a+fp16fml', 'match': '-march=.*', 'mfilter': '\+.*'}
)
```
### features.test()
**Signature**
```meson
[bool, Dict] features.test(
  # Positional arguments:
  FeatureObject...
  # Keyword arguments:
  anyfet      : bool = false,
  force_args  : str | list[str] | empty = empty,
  compiler    : Compiler | empty = empty,
  cached      : bool = true
)
```

Test one or a list of features against the compiler and retrieve a dictionary containing
essential information required for compiling a source that depends on these features.

A feature is deemed supported if it fulfills the following criteria:

 - It is not marked as disabled.
 - The compiler accommodates the features arguments.
 - Successful compilation of the designated test file or code.
 - The implied features are supported by the compiler, aligning with
   the criteria mentioned above.

This function requires at least one feature object as positional argument,
and additional keyword arguments are elaborated as follows:

- `anyfet` **bool = false**:
  If set to true, the returned dictionary will encompass information regarding
  the maximum features available that are supported by the compiler.
  This extends beyond the specified features and includes their implied features.
- `force_args` **str | list[str] | empty = empty**:
  An optional single compiler argument or an array of compiler arguments to be
  employed instead of the designated features' arguments when testing the
  test code against the compiler.  This can be useful for detecting host features.
- `compiler` **Compiler | empty = empty**:
  A Compiler object to be tested against. If not defined,
  the function will default to the standard C or C++ compiler.
- `cached`: **bool = true**:
  Enable or disable the cache. By default, the cache is enabled,
  enhancing efficiency by storing previous results.

This function returns a list of two items. The first item is a boolean value,
set to true if the compiler supports the feature and false if it does not.
The second item is a dictionary that encapsulates the test results, outlined as follows:

**structure**
```meson
{
    'target_name'        : str,
    'prevalent_features' : list[str],
    'features'           : list[str],
    'args'               : list[str],
    'detect'             : list[str],
    'defines'            : list[str],
    'undefines'          : list[str],
    'is_supported'       : bool,
    'is_disabled'        : bool,
    'fail_reason'        : str
}
```

### features.multi_targets()
**Signature**
```meson
TargetsObject features.multi_targets(
  # Positional arguments:
  str,
  (
    str | File | CustomTarget | CustomTargetIndex |
    GeneratedList | StructuredSources | ExtractedObjects |
    BuildTarget
  )...,
  # Keyword arguments:
  dispatch    : FeatureObject | list[FeatureObject] = [],
  baseline    : empty | list[FeatureObject] = empty,
  prefix      : str = '',
  keep_sort   : bool = false,
  compiler    : empty | compiler = empty,
  cached      : bool = True,
  **known_stlib_kwargs
)
```

### features.sort()
**Signature**
```meson
```

### features.implicit()
**Signature**
```meson
```

### features.implicit_c()
**Signature**
```meson
```

