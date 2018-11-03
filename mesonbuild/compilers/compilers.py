# Copyright 2012-2017 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import abc, contextlib, enum, os.path, re, tempfile, shlex
import subprocess

from ..linkers import StaticLinker
from .. import coredata
from .. import mlog
from .. import mesonlib
from ..mesonlib import EnvironmentException, MesonException, OrderedSet, version_compare, Popen_safe

"""This file contains the data files of all compilers Meson knows
about. To support a new compiler, add its information below.
Also add corresponding autodetection code in environment.py."""

header_suffixes = ('h', 'hh', 'hpp', 'hxx', 'H', 'ipp', 'moc', 'vapi', 'di')
obj_suffixes = ('o', 'obj', 'res')
lib_suffixes = ('a', 'lib', 'dll', 'dylib', 'so')
# Mapping of language to suffixes of files that should always be in that language
# This means we can't include .h headers here since they could be C, C++, ObjC, etc.
lang_suffixes = {
    'c': ('c',),
    'cpp': ('cpp', 'cc', 'cxx', 'c++', 'hh', 'hpp', 'ipp', 'hxx'),
    # f90, f95, f03, f08 are for free-form fortran ('f90' recommended)
    # f, for, ftn, fpp are for fixed-form fortran ('f' or 'for' recommended)
    'fortran': ('f90', 'f95', 'f03', 'f08', 'f', 'for', 'ftn', 'fpp'),
    'd': ('d', 'di'),
    'objc': ('m',),
    'objcpp': ('mm',),
    'rust': ('rs',),
    'vala': ('vala', 'vapi', 'gs'),
    'cs': ('cs',),
    'swift': ('swift',),
    'java': ('java',),
}
all_languages = lang_suffixes.keys()
cpp_suffixes = lang_suffixes['cpp'] + ('h',)
c_suffixes = lang_suffixes['c'] + ('h',)
# List of languages that by default consume and output libraries following the
# C ABI; these can generally be used interchangebly
clib_langs = ('objcpp', 'cpp', 'objc', 'c', 'fortran',)
# List of languages that can be linked with C code directly by the linker
# used in build.py:process_compilers() and build.py:get_dynamic_linker()
# XXX: Add Rust to this?
clink_langs = ('d',) + clib_langs
clink_suffixes = ()
for _l in clink_langs + ('vala',):
    clink_suffixes += lang_suffixes[_l]
clink_suffixes += ('h', 'll', 's')

soregex = re.compile(r'.*\.so(\.[0-9]+)?(\.[0-9]+)?(\.[0-9]+)?$')

# Environment variables that each lang uses.
cflags_mapping = {'c': 'CFLAGS',
                  'cpp': 'CXXFLAGS',
                  'objc': 'OBJCFLAGS',
                  'objcpp': 'OBJCXXFLAGS',
                  'fortran': 'FFLAGS',
                  'd': 'DFLAGS',
                  'vala': 'VALAFLAGS',
                  'rust': 'RUSTFLAGS'}

# All these are only for C-linkable languages; see `clink_langs` above.

def sort_clink(lang):
    '''
    Sorting function to sort the list of languages according to
    reversed(compilers.clink_langs) and append the unknown langs in the end.
    The purpose is to prefer C over C++ for files that can be compiled by
    both such as assembly, C, etc. Also applies to ObjC, ObjC++, etc.
    '''
    if lang not in clink_langs:
        return 1
    return -clink_langs.index(lang)

def is_header(fname):
    if hasattr(fname, 'fname'):
        fname = fname.fname
    suffix = fname.split('.')[-1]
    return suffix in header_suffixes

def is_source(fname):
    if hasattr(fname, 'fname'):
        fname = fname.fname
    suffix = fname.split('.')[-1].lower()
    return suffix in clink_suffixes

def is_assembly(fname):
    if hasattr(fname, 'fname'):
        fname = fname.fname
    return fname.split('.')[-1].lower() == 's'

def is_llvm_ir(fname):
    if hasattr(fname, 'fname'):
        fname = fname.fname
    return fname.split('.')[-1] == 'll'

def is_object(fname):
    if hasattr(fname, 'fname'):
        fname = fname.fname
    suffix = fname.split('.')[-1]
    return suffix in obj_suffixes

def is_library(fname):
    if hasattr(fname, 'fname'):
        fname = fname.fname

    if soregex.match(fname):
        return True

    suffix = fname.split('.')[-1]
    return suffix in lib_suffixes

gnulike_buildtype_args = {'plain': [],
                          'debug': [],
                          'debugoptimized': [],
                          'release': [],
                          'minsize': [],
                          'custom': [],
                          }

armclang_buildtype_args = {'plain': [],
                           'debug': ['-O0', '-g'],
                           'debugoptimized': ['-O1', '-g'],
                           'release': ['-Os'],
                           'minsize': ['-Oz'],
                           'custom': [],
                           }

arm_buildtype_args = {'plain': [],
                      'debug': ['-O0', '--debug'],
                      'debugoptimized': ['-O1', '--debug'],
                      'release': ['-O3', '-Otime'],
                      'minsize': ['-O3', '-Ospace'],
                      'custom': [],
                      }

msvc_buildtype_args = {'plain': [],
                       'debug': ["/ZI", "/Ob0", "/Od", "/RTC1"],
                       'debugoptimized': ["/Zi", "/Ob1"],
                       'release': ["/Ob2", "/Gw"],
                       'minsize': ["/Zi", "/Gw"],
                       'custom': [],
                       }

apple_buildtype_linker_args = {'plain': [],
                               'debug': [],
                               'debugoptimized': [],
                               'release': [],
                               'minsize': [],
                               'custom': [],
                               }

gnulike_buildtype_linker_args = {'plain': [],
                                 'debug': [],
                                 'debugoptimized': [],
                                 'release': ['-Wl,-O1'],
                                 'minsize': [],
                                 'custom': [],
                                 }

arm_buildtype_linker_args = {'plain': [],
                             'debug': [],
                             'debugoptimized': [],
                             'release': [],
                             'minsize': [],
                             'custom': [],
                             }

msvc_buildtype_linker_args = {'plain': [],
                              'debug': [],
                              'debugoptimized': [],
                              # The otherwise implicit REF and ICF linker
                              # optimisations are disabled by /DEBUG.
                              # REF implies ICF.
                              'release': ['/OPT:REF'],
                              'minsize': ['/INCREMENTAL:NO', '/OPT:REF'],
                              'custom': [],
                              }

java_buildtype_args = {'plain': [],
                       'debug': ['-g'],
                       'debugoptimized': ['-g'],
                       'release': [],
                       'minsize': [],
                       'custom': [],
                       }

rust_buildtype_args = {'plain': [],
                       'debug': [],
                       'debugoptimized': [],
                       'release': [],
                       'minsize': [],
                       'custom': [],
                       }

d_gdc_buildtype_args = {'plain': [],
                        'debug': [],
                        'debugoptimized': ['-finline-functions'],
                        'release': ['-frelease', '-finline-functions'],
                        'minsize': [],
                        'custom': [],
                        }

d_ldc_buildtype_args = {'plain': [],
                        'debug': [],
                        'debugoptimized': ['-enable-inlining', '-Hkeep-all-bodies'],
                        'release': ['-release', '-enable-inlining', '-Hkeep-all-bodies'],
                        'minsize': [],
                        'custom': [],
                        }

d_dmd_buildtype_args = {'plain': [],
                        'debug': [],
                        'debugoptimized': ['-inline'],
                        'release': ['-release', '-inline'],
                        'minsize': [],
                        'custom': [],
                        }

mono_buildtype_args = {'plain': [],
                       'debug': [],
                       'debugoptimized': ['-optimize+'],
                       'release': ['-optimize+'],
                       'minsize': [],
                       'custom': [],
                       }

swift_buildtype_args = {'plain': [],
                        'debug': [],
                        'debugoptimized': [],
                        'release': [],
                        'minsize': [],
                        'custom': [],
                        }

gnu_winlibs = ['-lkernel32', '-luser32', '-lgdi32', '-lwinspool', '-lshell32',
               '-lole32', '-loleaut32', '-luuid', '-lcomdlg32', '-ladvapi32']

msvc_winlibs = ['kernel32.lib', 'user32.lib', 'gdi32.lib',
                'winspool.lib', 'shell32.lib', 'ole32.lib', 'oleaut32.lib',
                'uuid.lib', 'comdlg32.lib', 'advapi32.lib']

gnu_color_args = {'auto': ['-fdiagnostics-color=auto'],
                  'always': ['-fdiagnostics-color=always'],
                  'never': ['-fdiagnostics-color=never'],
                  }

clang_color_args = {'auto': ['-Xclang', '-fcolor-diagnostics'],
                    'always': ['-Xclang', '-fcolor-diagnostics'],
                    'never': ['-Xclang', '-fno-color-diagnostics'],
                    }

arm_optimization_args = {'0': ['-O0'],
                         'g': ['-g'],
                         '1': ['-O1'],
                         '2': ['-O2'],
                         '3': ['-O3'],
                         's': [],
                         }

armclang_optimization_args = {'0': ['-O0'],
                              'g': ['-g'],
                              '1': ['-O1'],
                              '2': ['-O2'],
                              '3': ['-O3'],
                              's': ['-Os']
                              }

clike_optimization_args = {'0': [],
                           'g': [],
                           '1': ['-O1'],
                           '2': ['-O2'],
                           '3': ['-O3'],
                           's': ['-Os'],
                           }

gnu_optimization_args = {'0': [],
                         'g': ['-Og'],
                         '1': ['-O1'],
                         '2': ['-O2'],
                         '3': ['-O3'],
                         's': ['-Os'],
                         }

msvc_optimization_args = {'0': [],
                          'g': ['/O0'],
                          '1': ['/O1'],
                          '2': ['/O2'],
                          '3': ['/O2'],
                          's': ['/O1'], # Implies /Os.
                          }

clike_debug_args = {False: [],
                    True: ['-g']}

msvc_debug_args = {False: [],
                   True: []} # Fixme!

base_options = {'b_pch': coredata.UserBooleanOption('b_pch', 'Use precompiled headers', True),
                'b_lto': coredata.UserBooleanOption('b_lto', 'Use link time optimization', False),
                'b_sanitize': coredata.UserComboOption('b_sanitize',
                                                       'Code sanitizer to use',
                                                       ['none', 'address', 'thread', 'undefined', 'memory', 'address,undefined'],
                                                       'none'),
                'b_lundef': coredata.UserBooleanOption('b_lundef', 'Use -Wl,--no-undefined when linking', True),
                'b_asneeded': coredata.UserBooleanOption('b_asneeded', 'Use -Wl,--as-needed when linking', True),
                'b_pgo': coredata.UserComboOption('b_pgo', 'Use profile guided optimization',
                                                  ['off', 'generate', 'use'],
                                                  'off'),
                'b_coverage': coredata.UserBooleanOption('b_coverage',
                                                         'Enable coverage tracking.',
                                                         False),
                'b_colorout': coredata.UserComboOption('b_colorout', 'Use colored output',
                                                       ['auto', 'always', 'never'],
                                                       'always'),
                'b_ndebug': coredata.UserComboOption('b_ndebug', 'Disable asserts',
                                                     ['true', 'false', 'if-release'], 'false'),
                'b_staticpic': coredata.UserBooleanOption('b_staticpic',
                                                          'Build static libraries as position independent',
                                                          True),
                'b_pie': coredata.UserBooleanOption('b_pie',
                                                    'Build executables as position independent',
                                                    False),
                'b_bitcode': coredata.UserBooleanOption('b_bitcode',
                                                        'Generate and embed bitcode (only macOS and iOS)',
                                                        False),
                'b_vscrt': coredata.UserComboOption('b_vscrt', 'VS run-time library type to use.',
                                                    ['none', 'md', 'mdd', 'mt', 'mtd', 'from_buildtype'],
                                                    'from_buildtype'),
                }

gnulike_instruction_set_args = {'mmx': ['-mmmx'],
                                'sse': ['-msse'],
                                'sse2': ['-msse2'],
                                'sse3': ['-msse3'],
                                'ssse3': ['-mssse3'],
                                'sse41': ['-msse4.1'],
                                'sse42': ['-msse4.2'],
                                'avx': ['-mavx'],
                                'avx2': ['-mavx2'],
                                'neon': ['-mfpu=neon'],
                                }

vs32_instruction_set_args = {'mmx': ['/arch:SSE'], # There does not seem to be a flag just for MMX
                             'sse': ['/arch:SSE'],
                             'sse2': ['/arch:SSE2'],
                             'sse3': ['/arch:AVX'], # VS leaped from SSE2 directly to AVX.
                             'sse41': ['/arch:AVX'],
                             'sse42': ['/arch:AVX'],
                             'avx': ['/arch:AVX'],
                             'avx2': ['/arch:AVX2'],
                             'neon': None,
                             }

# The 64 bit compiler defaults to /arch:avx.
vs64_instruction_set_args = {'mmx': ['/arch:AVX'],
                             'sse': ['/arch:AVX'],
                             'sse2': ['/arch:AVX'],
                             'sse3': ['/arch:AVX'],
                             'ssse3': ['/arch:AVX'],
                             'sse41': ['/arch:AVX'],
                             'sse42': ['/arch:AVX'],
                             'avx': ['/arch:AVX'],
                             'avx2': ['/arch:AVX2'],
                             'neon': None,
                             }

gnu_symbol_visibility_args = {'': [],
                              'default': ['-fvisibility=default'],
                              'internal': ['-fvisibility=internal'],
                              'hidden': ['-fvisibility=hidden'],
                              'protected': ['-fvisibility=protected'],
                              'inlineshidden': ['-fvisibility=hidden', '-fvisibility-inlines-hidden'],
                              }

def sanitizer_compile_args(value):
    if value == 'none':
        return []
    args = ['-fsanitize=' + value]
    if 'address' in value: # For -fsanitize=address,undefined
        args.append('-fno-omit-frame-pointer')
    return args

def sanitizer_link_args(value):
    if value == 'none':
        return []
    args = ['-fsanitize=' + value]
    return args

def option_enabled(boptions, options, option):
    try:
        if option not in boptions:
            return False
        return options[option].value
    except KeyError:
        return False

def get_base_compile_args(options, compiler):
    args = []
    try:
        if options['b_lto'].value:
            if compiler.id == 'msvc' and options['buildtype'].value == 'debug':
                raise MesonException('MSVC does not support LTO with debug buildtype.')
            args.extend(compiler.get_lto_compile_args())
    except KeyError:
        pass
    try:
        args += compiler.get_colorout_args(options['b_colorout'].value)
    except KeyError:
        pass
    try:
        args += sanitizer_compile_args(options['b_sanitize'].value)
    except KeyError:
        pass
    try:
        pgo_val = options['b_pgo'].value
        if pgo_val == 'generate':
            args.append('-fprofile-generate')
        elif pgo_val == 'use':
            args.extend(['-fprofile-use', '-fprofile-correction'])
    except KeyError:
        pass
    try:
        if options['b_coverage'].value:
            args += compiler.get_coverage_args()
    except KeyError:
        pass
    try:
        if (options['b_ndebug'].value == 'true' or
                (options['b_ndebug'].value == 'if-release' and
                 options['buildtype'].value == 'release')):
            args += ['-DNDEBUG']
    except KeyError:
        pass
    # This does not need a try...except
    if option_enabled(compiler.base_options, options, 'b_bitcode'):
        args.append('-fembed-bitcode')
    try:
        crt_val = options['b_vscrt'].value
        buildtype = options['buildtype'].value
        try:
            args += compiler.get_crt_compile_args(crt_val, buildtype)
        except AttributeError:
            pass
    except KeyError:
        pass
    return args

def get_base_link_args(options, linker, is_shared_module):
    args = []
    try:
        if options['b_lto'].value:
            args.extend(linker.get_lto_link_args())
    except KeyError:
        pass
    try:
        args += sanitizer_link_args(options['b_sanitize'].value)
    except KeyError:
        pass
    try:
        pgo_val = options['b_pgo'].value
        if pgo_val == 'generate':
            args.append('-fprofile-generate')
        elif pgo_val == 'use':
            args.extend(['-fprofile-use', '-fprofile-correction'])
    except KeyError:
        pass
    try:
        if options['b_coverage'].value:
            args += linker.get_coverage_link_args()
    except KeyError:
        pass
    # These do not need a try...except
    if not is_shared_module and option_enabled(linker.base_options, options, 'b_lundef'):
        args.append('-Wl,--no-undefined')
    as_needed = option_enabled(linker.base_options, options, 'b_asneeded')
    bitcode = option_enabled(linker.base_options, options, 'b_bitcode')
    # Shared modules cannot be built with bitcode_bundle because
    # -bitcode_bundle is incompatible with -undefined and -bundle
    if bitcode and not is_shared_module:
        args.append('-Wl,-bitcode_bundle')
    elif as_needed:
        # -Wl,-dead_strip_dylibs is incompatible with bitcode
        args.append(linker.get_asneeded_args())
    try:
        crt_val = options['b_vscrt'].value
        buildtype = options['buildtype'].value
        try:
            args += linker.get_crt_link_args(crt_val, buildtype)
        except AttributeError:
            pass
    except KeyError:
        pass
    return args

def prepare_rpaths(raw_rpaths, build_dir, from_dir):
    internal_format_rpaths = [evaluate_rpath(p, build_dir, from_dir) for p in raw_rpaths]
    ordered_rpaths = order_rpaths(internal_format_rpaths)
    return ordered_rpaths

def order_rpaths(rpath_list):
    # We want rpaths that point inside our build dir to always override
    # those pointing to other places in the file system. This is so built
    # binaries prefer our libraries to the ones that may lie somewhere
    # in the file system, such as /lib/x86_64-linux-gnu.
    #
    # The correct thing to do here would be C++'s std::stable_partition.
    # Python standard library does not have it, so replicate it with
    # sort, which is guaranteed to be stable.
    return sorted(rpath_list, key=os.path.isabs)

def evaluate_rpath(p, build_dir, from_dir):
    if p == from_dir:
        return '' # relpath errors out in this case
    elif os.path.isabs(p):
        return p # These can be outside of build dir.
    else:
        return os.path.relpath(os.path.join(build_dir, p), os.path.join(build_dir, from_dir))


class CrossNoRunException(MesonException):
    pass

class RunResult:
    def __init__(self, compiled, returncode=999, stdout='UNDEFINED', stderr='UNDEFINED'):
        self.compiled = compiled
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

class CompilerArgs(list):
    '''
    Class derived from list() that manages a list of compiler arguments. Should
    be used while constructing compiler arguments from various sources. Can be
    operated with ordinary lists, so this does not need to be used everywhere.

    All arguments must be inserted and stored in GCC-style (-lfoo, -Idir, etc)
    and can converted to the native type of each compiler by using the
    .to_native() method to which you must pass an instance of the compiler or
    the compiler class.

    New arguments added to this class (either with .append(), .extend(), or +=)
    are added in a way that ensures that they override previous arguments.
    For example:

    >>> a = ['-Lfoo', '-lbar']
    >>> a += ['-Lpho', '-lbaz']
    >>> print(a)
    ['-Lpho', '-Lfoo', '-lbar', '-lbaz']

    Arguments will also be de-duped if they can be de-duped safely.

    Note that because of all this, this class is not commutative and does not
    preserve the order of arguments if it is safe to not. For example:
    >>> ['-Ifoo', '-Ibar'] + ['-Ifez', '-Ibaz', '-Werror']
    ['-Ifez', '-Ibaz', '-Ifoo', '-Ibar', '-Werror']
    >>> ['-Ifez', '-Ibaz', '-Werror'] + ['-Ifoo', '-Ibar']
    ['-Ifoo', '-Ibar', '-Ifez', '-Ibaz', '-Werror']

    '''
    # NOTE: currently this class is only for C-like compilers, but it can be
    # extended to other languages easily. Just move the following to the
    # compiler class and initialize when self.compiler is set.

    # Arg prefixes that override by prepending instead of appending
    prepend_prefixes = ('-I', '-L')
    # Arg prefixes and args that must be de-duped by returning 2
    dedup2_prefixes = ('-I', '-L', '-D', '-U')
    dedup2_suffixes = ()
    dedup2_args = ()
    # Arg prefixes and args that must be de-duped by returning 1
    dedup1_prefixes = ('-l', '-Wl,-l')
    dedup1_suffixes = ('.lib', '.dll', '.so', '.dylib', '.a')
    # Match a .so of the form path/to/libfoo.so.0.1.0
    # Only UNIX shared libraries require this. Others have a fixed extension.
    dedup1_regex = re.compile(r'([\/\\]|\A)lib.*\.so(\.[0-9]+)?(\.[0-9]+)?(\.[0-9]+)?$')
    dedup1_args = ('-c', '-S', '-E', '-pipe', '-pthread')
    compiler = None

    def _check_args(self, args):
        cargs = []
        if len(args) > 2:
            raise TypeError("CompilerArgs() only accepts at most 2 arguments: "
                            "The compiler, and optionally an initial list")
        elif not args:
            return cargs
        elif len(args) == 1:
            if isinstance(args[0], (Compiler, StaticLinker)):
                self.compiler = args[0]
            else:
                raise TypeError("you must pass a Compiler instance as one of "
                                "the arguments")
        elif len(args) == 2:
            if isinstance(args[0], (Compiler, StaticLinker)):
                self.compiler = args[0]
                cargs = args[1]
            elif isinstance(args[1], (Compiler, StaticLinker)):
                cargs = args[0]
                self.compiler = args[1]
            else:
                raise TypeError("you must pass a Compiler instance as one of "
                                "the two arguments")
        else:
            raise AssertionError('Not reached')
        return cargs

    def __init__(self, *args):
        super().__init__(self._check_args(args))

    @classmethod
    def _can_dedup(cls, arg):
        '''
        Returns whether the argument can be safely de-duped. This is dependent
        on three things:

        a) Whether an argument can be 'overridden' by a later argument.  For
           example, -DFOO defines FOO and -UFOO undefines FOO. In this case, we
           can safely remove the previous occurrence and add a new one. The same
           is true for include paths and library paths with -I and -L. For
           these we return `2`. See `dedup2_prefixes` and `dedup2_args`.
        b) Arguments that once specified cannot be undone, such as `-c` or
           `-pipe`. New instances of these can be completely skipped. For these
           we return `1`. See `dedup1_prefixes` and `dedup1_args`.
        c) Whether it matters where or how many times on the command-line
           a particular argument is present. This can matter for symbol
           resolution in static or shared libraries, so we cannot de-dup or
           reorder them. For these we return `0`. This is the default.

        In addition to these, we handle library arguments specially.
        With GNU ld, we surround library arguments with -Wl,--start/end-group
        to recursively search for symbols in the libraries. This is not needed
        with other linkers.
        '''

        # A standalone argument must never be deduplicated because it is
        # defined by what comes _after_ it. Thus dedupping this:
        # -D FOO -D BAR
        # would yield either
        # -D FOO BAR
        # or
        # FOO -D BAR
        # both of which are invalid.
        if arg in cls.dedup2_prefixes:
            return 0
        if arg in cls.dedup2_args or \
           arg.startswith(cls.dedup2_prefixes) or \
           arg.endswith(cls.dedup2_suffixes):
            return 2
        if arg in cls.dedup1_args or \
           arg.startswith(cls.dedup1_prefixes) or \
           arg.endswith(cls.dedup1_suffixes) or \
           re.search(cls.dedup1_regex, arg):
            return 1
        return 0

    @classmethod
    def _should_prepend(cls, arg):
        if arg.startswith(cls.prepend_prefixes):
            return True
        return False

    def to_native(self, copy=False):
        # Check if we need to add --start/end-group for circular dependencies
        # between static libraries, and for recursively searching for symbols
        # needed by static libraries that are provided by object files or
        # shared libraries.
        if copy:
            new = self.copy()
        else:
            new = self
        if get_compiler_uses_gnuld(self.compiler):
            global soregex
            group_start = -1
            group_end = -1
            for i, each in enumerate(new):
                if not each.startswith(('-Wl,-l', '-l')) and not each.endswith('.a') and \
                   not soregex.match(each):
                    continue
                group_end = i
                if group_start < 0:
                    # First occurrence of a library
                    group_start = i
            if group_start >= 0:
                # Last occurrence of a library
                new.insert(group_end + 1, '-Wl,--end-group')
                new.insert(group_start, '-Wl,--start-group')
        return self.compiler.unix_args_to_native(new)

    def append_direct(self, arg):
        '''
        Append the specified argument without any reordering or de-dup
        except for absolute paths where the order of include search directories
        is not relevant
        '''
        if os.path.isabs(arg):
            self.append(arg)
        else:
            super().append(arg)

    def extend_direct(self, iterable):
        '''
        Extend using the elements in the specified iterable without any
        reordering or de-dup except for absolute paths where the order of
        include search directories is not relevant
        '''
        for elem in iterable:
            self.append_direct(elem)

    def __add__(self, args):
        new = CompilerArgs(self, self.compiler)
        new += args
        return new

    def __iadd__(self, args):
        '''
        Add two CompilerArgs while taking into account overriding of arguments
        and while preserving the order of arguments as much as possible
        '''
        pre = []
        post = []
        if not isinstance(args, list):
            raise TypeError('can only concatenate list (not "{}") to list'.format(args))
        for arg in args:
            # If the argument can be de-duped, do it either by removing the
            # previous occurrence of it and adding a new one, or not adding the
            # new occurrence.
            dedup = self._can_dedup(arg)
            if dedup == 1:
                # Argument already exists and adding a new instance is useless
                if arg in self or arg in pre or arg in post:
                    continue
            if dedup == 2:
                # Remove all previous occurrences of the arg and add it anew
                if arg in self:
                    self.remove(arg)
                if arg in pre:
                    pre.remove(arg)
                if arg in post:
                    post.remove(arg)
            if self._should_prepend(arg):
                pre.append(arg)
            else:
                post.append(arg)
        # Insert at the beginning
        self[:0] = pre
        # Append to the end
        super().__iadd__(post)
        return self

    def __radd__(self, args):
        new = CompilerArgs(args, self.compiler)
        new += self
        return new

    def __mul__(self, args):
        raise TypeError("can't multiply compiler arguments")

    def __imul__(self, args):
        raise TypeError("can't multiply compiler arguments")

    def __rmul__(self, args):
        raise TypeError("can't multiply compiler arguments")

    def append(self, arg):
        self.__iadd__([arg])

    def extend(self, args):
        self.__iadd__(args)

class Compiler:
    # Libraries to ignore in find_library() since they are provided by the
    # compiler or the C library. Currently only used for MSVC.
    ignore_libs = ()
    # Libraries that are internal compiler implementations, and must not be
    # manually searched.
    internal_libs = ()
    # Cache for the result of compiler checks which can be cached
    compiler_check_cache = {}

    def __init__(self, exelist, version, **kwargs):
        if isinstance(exelist, str):
            self.exelist = [exelist]
        elif isinstance(exelist, list):
            self.exelist = exelist
        else:
            raise TypeError('Unknown argument to Compiler')
        # In case it's been overridden by a child class already
        if not hasattr(self, 'file_suffixes'):
            self.file_suffixes = lang_suffixes[self.language]
        if not hasattr(self, 'can_compile_suffixes'):
            self.can_compile_suffixes = set(self.file_suffixes)
        self.default_suffix = self.file_suffixes[0]
        self.version = version
        if 'full_version' in kwargs:
            self.full_version = kwargs['full_version']
        else:
            self.full_version = None
        self.base_options = []

    def __repr__(self):
        repr_str = "<{0}: v{1} `{2}`>"
        return repr_str.format(self.__class__.__name__, self.version,
                               ' '.join(self.exelist))

    def can_compile(self, src):
        if hasattr(src, 'fname'):
            src = src.fname
        suffix = os.path.splitext(src)[1].lower()
        if suffix and suffix[1:] in self.can_compile_suffixes:
            return True
        return False

    def get_id(self):
        return self.id

    def get_language(self):
        return self.language

    def get_display_language(self):
        return self.language.capitalize()

    def get_default_suffix(self):
        return self.default_suffix

    def get_define(self, dname, prefix, env, extra_args, dependencies):
        raise EnvironmentException('%s does not support get_define ' % self.get_id())

    def compute_int(self, expression, low, high, guess, prefix, env, extra_args, dependencies):
        raise EnvironmentException('%s does not support compute_int ' % self.get_id())

    def has_members(self, typename, membernames, prefix, env, extra_args=None, dependencies=None):
        raise EnvironmentException('%s does not support has_member(s) ' % self.get_id())

    def has_type(self, typename, prefix, env, extra_args, dependencies=None):
        raise EnvironmentException('%s does not support has_type ' % self.get_id())

    def symbols_have_underscore_prefix(self, env):
        raise EnvironmentException('%s does not support symbols_have_underscore_prefix ' % self.get_id())

    def get_exelist(self):
        return self.exelist[:]

    def get_builtin_define(self, *args, **kwargs):
        raise EnvironmentException('%s does not support get_builtin_define.' % self.id)

    def has_builtin_define(self, *args, **kwargs):
        raise EnvironmentException('%s does not support has_builtin_define.' % self.id)

    def get_always_args(self):
        return []

    def can_linker_accept_rsp(self):
        """
        Determines whether the linker can accept arguments using the @rsp syntax.
        """
        return mesonlib.is_windows()

    def get_linker_always_args(self):
        return []

    def gen_import_library_args(self, implibname):
        """
        Used only on Windows for libraries that need an import library.
        This currently means C, C++, Fortran.
        """
        return []

    def get_preproc_flags(self):
        if self.get_language() in ('c', 'cpp', 'objc', 'objcpp'):
            return os.environ.get('CPPFLAGS', '')
        return ''

    def get_args_from_envvars(self):
        """
        Returns a tuple of (compile_flags, link_flags) for the specified language
        from the inherited environment
        """
        def log_var(var, val):
            if val:
                mlog.log('Appending {} from environment: {!r}'.format(var, val))

        lang = self.get_language()
        compiler_is_linker = False
        if hasattr(self, 'get_linker_exelist'):
            compiler_is_linker = (self.get_exelist() == self.get_linker_exelist())

        if lang not in cflags_mapping:
            return [], []

        compile_flags = os.environ.get(cflags_mapping[lang], '')
        log_var(cflags_mapping[lang], compile_flags)
        compile_flags = shlex.split(compile_flags)

        # Link flags (same for all languages)
        link_flags = os.environ.get('LDFLAGS', '')
        log_var('LDFLAGS', link_flags)
        link_flags = shlex.split(link_flags)
        if compiler_is_linker:
            # When the compiler is used as a wrapper around the linker (such as
            # with GCC and Clang), the compile flags can be needed while linking
            # too. This is also what Autotools does. However, we don't want to do
            # this when the linker is stand-alone such as with MSVC C/C++, etc.
            link_flags = compile_flags + link_flags

        # Pre-processor flags (not for fortran or D)
        preproc_flags = self.get_preproc_flags()
        log_var('CPPFLAGS', preproc_flags)
        preproc_flags = shlex.split(preproc_flags)
        compile_flags += preproc_flags

        return compile_flags, link_flags

    def get_options(self):
        opts = {} # build afresh every time

        # Take default values from env variables.
        compile_args, link_args = self.get_args_from_envvars()
        description = 'Extra arguments passed to the {}'.format(self.get_display_language())
        opts.update({
            self.language + '_args': coredata.UserArrayOption(
                self.language + '_args',
                description + ' compiler',
                compile_args, shlex_split=True, user_input=True, allow_dups=True),
            self.language + '_link_args': coredata.UserArrayOption(
                self.language + '_link_args',
                description + ' linker',
                link_args, shlex_split=True, user_input=True, allow_dups=True),
        })

        return opts

    def get_option_compile_args(self, options):
        return []

    def get_option_link_args(self, options):
        return []

    def check_header(self, *args, **kwargs):
        raise EnvironmentException('Language %s does not support header checks.' % self.get_display_language())

    def has_header(self, *args, **kwargs):
        raise EnvironmentException('Language %s does not support header checks.' % self.get_display_language())

    def has_header_symbol(self, *args, **kwargs):
        raise EnvironmentException('Language %s does not support header symbol checks.' % self.get_display_language())

    def compiles(self, *args, **kwargs):
        raise EnvironmentException('Language %s does not support compile checks.' % self.get_display_language())

    def links(self, *args, **kwargs):
        raise EnvironmentException('Language %s does not support link checks.' % self.get_display_language())

    def run(self, *args, **kwargs):
        raise EnvironmentException('Language %s does not support run checks.' % self.get_display_language())

    def sizeof(self, *args, **kwargs):
        raise EnvironmentException('Language %s does not support sizeof checks.' % self.get_display_language())

    def alignment(self, *args, **kwargs):
        raise EnvironmentException('Language %s does not support alignment checks.' % self.get_display_language())

    def has_function(self, *args, **kwargs):
        raise EnvironmentException('Language %s does not support function checks.' % self.get_display_language())

    @classmethod
    def unix_args_to_native(cls, args):
        "Always returns a copy that can be independently mutated"
        return args[:]

    def find_library(self, *args, **kwargs):
        raise EnvironmentException('Language {} does not support library finding.'.format(self.get_display_language()))

    def get_library_dirs(self, *args, **kwargs):
        return ()

    def has_multi_arguments(self, args, env):
        raise EnvironmentException(
            'Language {} does not support has_multi_arguments.'.format(
                self.get_display_language()))

    def has_multi_link_arguments(self, args, env):
        raise EnvironmentException(
            'Language {} does not support has_multi_link_arguments.'.format(
                self.get_display_language()))

    def get_cross_extra_flags(self, environment, link):
        extra_flags = []
        if self.is_cross and environment:
            if 'properties' in environment.cross_info.config:
                props = environment.cross_info.config['properties']
                lang_args_key = self.language + '_args'
                extra_flags += props.get(lang_args_key, [])
                lang_link_args_key = self.language + '_link_args'
                if link:
                    extra_flags += props.get(lang_link_args_key, [])
        return extra_flags

    def _get_compile_output(self, dirname, mode):
        # In pre-processor mode, the output is sent to stdout and discarded
        if mode == 'preprocess':
            return None
        # Extension only matters if running results; '.exe' is
        # guaranteed to be executable on every platform.
        if mode == 'link':
            suffix = 'exe'
        else:
            suffix = 'obj'
        return os.path.join(dirname, 'output.' + suffix)

    @contextlib.contextmanager
    def compile(self, code, extra_args=None, mode='link', want_output=False):
        if extra_args is None:
            textra_args = None
            extra_args = []
        else:
            textra_args = tuple(extra_args)
        key = (code, textra_args, mode)
        if not want_output:
            if key in self.compiler_check_cache:
                p = self.compiler_check_cache[key]
                mlog.debug('Using cached compile:')
                mlog.debug('Cached command line: ', ' '.join(p.commands), '\n')
                mlog.debug('Code:\n', code)
                mlog.debug('Cached compiler stdout:\n', p.stdo)
                mlog.debug('Cached compiler stderr:\n', p.stde)
                yield p
                return
        try:
            with tempfile.TemporaryDirectory() as tmpdirname:
                if isinstance(code, str):
                    srcname = os.path.join(tmpdirname,
                                           'testfile.' + self.default_suffix)
                    with open(srcname, 'w') as ofile:
                        ofile.write(code)
                elif isinstance(code, mesonlib.File):
                    srcname = code.fname

                # Construct the compiler command-line
                commands = CompilerArgs(self)
                commands.append(srcname)
                commands += self.get_always_args()
                if mode == 'compile':
                    commands += self.get_compile_only_args()
                # Preprocess mode outputs to stdout, so no output args
                if mode == 'preprocess':
                    commands += self.get_preprocess_only_args()
                else:
                    output = self._get_compile_output(tmpdirname, mode)
                    commands += self.get_output_args(output)
                # extra_args must be last because it could contain '/link' to
                # pass args to VisualStudio's linker. In that case everything
                # in the command line after '/link' is given to the linker.
                commands += extra_args
                # Generate full command-line with the exelist
                commands = self.get_exelist() + commands.to_native()
                mlog.debug('Running compile:')
                mlog.debug('Working directory: ', tmpdirname)
                mlog.debug('Command line: ', ' '.join(commands), '\n')
                mlog.debug('Code:\n', code)
                os_env = os.environ.copy()
                os_env['LC_ALL'] = 'C'
                p, p.stdo, p.stde = Popen_safe(commands, cwd=tmpdirname, env=os_env)
                mlog.debug('Compiler stdout:\n', p.stdo)
                mlog.debug('Compiler stderr:\n', p.stde)
                p.commands = commands
                p.input_name = srcname
                if want_output:
                    p.output_name = output
                else:
                    self.compiler_check_cache[key] = p
                yield p
        except (PermissionError, OSError):
            # On Windows antivirus programs and the like hold on to files so
            # they can't be deleted. There's not much to do in this case. Also,
            # catch OSError because the directory is then no longer empty.
            pass

    def get_colorout_args(self, colortype):
        return []

    # Some compilers (msvc) write debug info to a separate file.
    # These args specify where it should be written.
    def get_compile_debugfile_args(self, rel_obj, **kwargs):
        return []

    def get_link_debugfile_args(self, rel_obj):
        return []

    def get_std_shared_lib_link_args(self):
        return []

    def get_std_shared_module_link_args(self, options):
        return self.get_std_shared_lib_link_args()

    def get_link_whole_for(self, args):
        if isinstance(args, list) and not args:
            return []
        raise EnvironmentException('Language %s does not support linking whole archives.' % self.get_display_language())

    # Compiler arguments needed to enable the given instruction set.
    # May be [] meaning nothing needed or None meaning the given set
    # is not supported.
    def get_instruction_set_args(self, instruction_set):
        return None

    def build_unix_rpath_args(self, build_dir, from_dir, rpath_paths, build_rpath, install_rpath):
        if not rpath_paths and not install_rpath and not build_rpath:
            return []
        args = []
        if mesonlib.is_osx():
            # Ensure that there is enough space for install_name_tool in-place editing of large RPATHs
            args.append('-Wl,-headerpad_max_install_names')
            # @loader_path is the equivalent of $ORIGIN on macOS
            # https://stackoverflow.com/q/26280738
            origin_placeholder = '@loader_path'
        else:
            origin_placeholder = '$ORIGIN'
        # The rpaths we write must be relative if they point to the build dir,
        # because otherwise they have different length depending on the build
        # directory. This breaks reproducible builds.
        processed_rpaths = prepare_rpaths(rpath_paths, build_dir, from_dir)
        # Need to deduplicate rpaths, as macOS's install_name_tool
        # is *very* allergic to duplicate -delete_rpath arguments
        # when calling depfixer on installation.
        all_paths = OrderedSet([os.path.join(origin_placeholder, p) for p in processed_rpaths])
        # Build_rpath is used as-is (it is usually absolute).
        if build_rpath != '':
            all_paths.add(build_rpath)

        if mesonlib.is_dragonflybsd() or mesonlib.is_openbsd():
            # This argument instructs the compiler to record the value of
            # ORIGIN in the .dynamic section of the elf. On Linux this is done
            # by default, but is not on dragonfly/openbsd for some reason. Without this
            # $ORIGIN in the runtime path will be undefined and any binaries
            # linked against local libraries will fail to resolve them.
            args.append('-Wl,-z,origin')

        if mesonlib.is_osx():
            # macOS does not support colon-separated strings in LC_RPATH,
            # hence we have to pass each path component individually
            args += ['-Wl,-rpath,' + rp for rp in all_paths]
        else:
            # In order to avoid relinking for RPATH removal, the binary needs to contain just
            # enough space in the ELF header to hold the final installation RPATH.
            paths = ':'.join(all_paths)
            if len(paths) < len(install_rpath):
                padding = 'X' * (len(install_rpath) - len(paths))
                if not paths:
                    paths = padding
                else:
                    paths = paths + ':' + padding
            args.append('-Wl,-rpath,' + paths)

        if get_compiler_is_linuxlike(self):
            # Rpaths to use while linking must be absolute. These are not
            # written to the binary. Needed only with GNU ld:
            # https://sourceware.org/bugzilla/show_bug.cgi?id=16936
            # Not needed on Windows or other platforms that don't use RPATH
            # https://github.com/mesonbuild/meson/issues/1897
            lpaths = ':'.join([os.path.join(build_dir, p) for p in rpath_paths])

            # clang expands '-Wl,rpath-link,' to ['-rpath-link'] instead of ['-rpath-link','']
            # This eats the next argument, which happens to be 'ldstdc++', causing link failures.
            # We can dodge this problem by not adding any rpath_paths if the argument is empty.
            if lpaths.strip() != '':
                args += ['-Wl,-rpath-link,' + lpaths]
        return args

    def thread_flags(self, env):
        return []

    def openmp_flags(self):
        raise EnvironmentException('Language %s does not support OpenMP flags.' % self.get_display_language())

    def language_stdlib_only_link_flags(self):
        # The linker flags needed to link the standard library of the current
        # language in. This is needed in cases where you e.g. combine D and C++
        # and both of which need to link their runtime library in or otherwise
        # building fails with undefined symbols.
        return []

    def gnu_symbol_visibility_args(self, vistype):
        return []

    def get_gui_app_args(self, value):
        return []

    def has_func_attribute(self, name, env):
        raise EnvironmentException(
            'Language {} does not support function attributes.'.format(self.get_display_language()))

    def get_pic_args(self):
        m = 'Language {} does not support position-independent code'
        raise EnvironmentException(m.format(self.get_display_language()))

    def get_pie_args(self):
        m = 'Language {} does not support position-independent executable'
        raise EnvironmentException(m.format(self.get_display_language()))

    def get_pie_link_args(self):
        m = 'Language {} does not support position-independent executable'
        raise EnvironmentException(m.format(self.get_display_language()))

    def get_lto_compile_args(self):
        return []

    def get_lto_link_args(self):
        return []


@enum.unique
class CompilerType(enum.Enum):
    GCC_STANDARD = 0
    GCC_OSX = 1
    GCC_MINGW = 2
    GCC_CYGWIN = 3

    CLANG_STANDARD = 10
    CLANG_OSX = 11
    CLANG_MINGW = 12
    # Possibly clang-cl?

    ICC_STANDARD = 20
    ICC_OSX = 21
    ICC_WIN = 22

    ARM_WIN = 30

    @property
    def is_standard_compiler(self):
        return self.name in ('GCC_STANDARD', 'CLANG_STANDARD', 'ICC_STANDARD')

    @property
    def is_osx_compiler(self):
        return self.name in ('GCC_OSX', 'CLANG_OSX', 'ICC_OSX')

    @property
    def is_windows_compiler(self):
        return self.name in ('GCC_MINGW', 'GCC_CYGWIN', 'CLANG_MINGW', 'ICC_WIN', 'ARM_WIN')


def get_macos_dylib_install_name(prefix, shlib_name, suffix, soversion):
    install_name = prefix + shlib_name
    if soversion is not None:
        install_name += '.' + soversion
    install_name += '.dylib'
    return '@rpath/' + install_name

def get_gcc_soname_args(compiler_type, prefix, shlib_name, suffix, soversion, darwin_versions, is_shared_module):
    if compiler_type.is_standard_compiler:
        sostr = '' if soversion is None else '.' + soversion
        return ['-Wl,-soname,%s%s.%s%s' % (prefix, shlib_name, suffix, sostr)]
    elif compiler_type.is_windows_compiler:
        # For PE/COFF the soname argument has no effect with GNU LD
        return []
    elif compiler_type.is_osx_compiler:
        if is_shared_module:
            return []
        name = get_macos_dylib_install_name(prefix, shlib_name, suffix, soversion)
        args = ['-install_name', name]
        if darwin_versions:
            args += ['-compatibility_version', darwin_versions[0], '-current_version', darwin_versions[1]]
        return args
    else:
        raise RuntimeError('Not implemented yet.')

def get_compiler_is_linuxlike(compiler):
    compiler_type = getattr(compiler, 'compiler_type', None)
    return compiler_type and compiler_type.is_standard_compiler

def get_compiler_uses_gnuld(c):
    # FIXME: Perhaps we should detect the linker in the environment?
    # FIXME: Assumes that *BSD use GNU ld, but they might start using lld soon
    compiler_type = getattr(c, 'compiler_type', None)
    return compiler_type in (
        CompilerType.GCC_STANDARD,
        CompilerType.GCC_MINGW,
        CompilerType.GCC_CYGWIN,
        CompilerType.CLANG_STANDARD,
        CompilerType.CLANG_MINGW,
        CompilerType.ICC_STANDARD,
        CompilerType.ICC_WIN)

def get_largefile_args(compiler):
    '''
    Enable transparent large-file-support for 32-bit UNIX systems
    '''
    if get_compiler_is_linuxlike(compiler):
        # Enable large-file support unconditionally on all platforms other
        # than macOS and Windows. macOS is now 64-bit-only so it doesn't
        # need anything special, and Windows doesn't have automatic LFS.
        # You must use the 64-bit counterparts explicitly.
        # glibc, musl, and uclibc, and all BSD libcs support this. On Android,
        # support for transparent LFS is available depending on the version of
        # Bionic: https://github.com/android/platform_bionic#32-bit-abi-bugs
        # https://code.google.com/p/android/issues/detail?id=64613
        #
        # If this breaks your code, fix it! It's been 20+ years!
        return ['-D_FILE_OFFSET_BITS=64']
        # We don't enable -D_LARGEFILE64_SOURCE since that enables
        # transitionary features and must be enabled by programs that use
        # those features explicitly.
    return []

# TODO: The result from calling compiler should be cached. So that calling this
# function multiple times don't add latency.
def gnulike_default_include_dirs(compiler, lang):
    if lang == 'cpp':
        lang = 'c++'
    env = os.environ.copy()
    env["LC_ALL"] = 'C'
    cmd = compiler + ['-x{}'.format(lang), '-E', '-v', '-']
    p = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env=env
    )
    stderr = p.stderr.read().decode('utf-8', errors='replace')
    parse_state = 0
    paths = []
    for line in stderr.split('\n'):
        if parse_state == 0:
            if line == '#include "..." search starts here:':
                parse_state = 1
        elif parse_state == 1:
            if line == '#include <...> search starts here:':
                parse_state = 2
            else:
                paths.append(line[1:])
        elif parse_state == 2:
            if line == 'End of search list.':
                break
            else:
                paths.append(line[1:])
    if len(paths) == 0:
        mlog.warning('No include directory found parsing "{cmd}" output'.format(cmd=" ".join(cmd)))
    return paths


class GnuLikeCompiler(abc.ABC):
    """
    GnuLikeCompiler is a common interface to all compilers implementing
    the GNU-style commandline interface. This includes GCC, Clang
    and ICC. Certain functionality between them is different and requires
    that the actual concrete subclass define their own implementation.
    """
    def __init__(self, compiler_type):
        self.compiler_type = compiler_type
        self.base_options = ['b_pch', 'b_lto', 'b_pgo', 'b_sanitize', 'b_coverage',
                             'b_ndebug', 'b_staticpic', 'b_pie']
        if not self.compiler_type.is_osx_compiler and not self.compiler_type.is_windows_compiler:
            self.base_options.append('b_lundef')
        if not self.compiler_type.is_windows_compiler:
            self.base_options.append('b_asneeded')
        # All GCC-like backends can do assembly
        self.can_compile_suffixes.add('s')

    def get_asneeded_args(self):
        # GNU ld cannot be installed on macOS
        # https://github.com/Homebrew/homebrew-core/issues/17794#issuecomment-328174395
        # Hence, we don't need to differentiate between OS and ld
        # for the sake of adding as-needed support
        if self.compiler_type.is_osx_compiler:
            return '-Wl,-dead_strip_dylibs'
        else:
            return '-Wl,--as-needed'

    def get_pic_args(self):
        if self.compiler_type.is_osx_compiler or self.compiler_type.is_windows_compiler:
            return [] # On Window and OS X, pic is always on.
        return ['-fPIC']

    def get_pie_args(self):
        return ['-fPIE']

    def get_pie_link_args(self):
        return ['-pie']

    def get_buildtype_args(self, buildtype):
        return gnulike_buildtype_args[buildtype]

    @abc.abstractmethod
    def get_optimization_args(self, optimization_level):
        raise NotImplementedError("get_optimization_args not implemented")

    def get_debug_args(self, is_debug):
        return clike_debug_args[is_debug]

    def get_buildtype_linker_args(self, buildtype):
        if self.compiler_type.is_osx_compiler:
            return apple_buildtype_linker_args[buildtype]
        return gnulike_buildtype_linker_args[buildtype]

    @abc.abstractmethod
    def get_pch_suffix(self):
        raise NotImplementedError("get_pch_suffix not implemented")

    def split_shlib_to_parts(self, fname):
        return os.path.dirname(fname), fname

    def get_soname_args(self, *args):
        return get_gcc_soname_args(self.compiler_type, *args)

    def get_std_shared_lib_link_args(self):
        return ['-shared']

    def get_std_shared_module_link_args(self, options):
        if self.compiler_type.is_osx_compiler:
            return ['-bundle', '-Wl,-undefined,dynamic_lookup']
        return ['-shared']

    def get_link_whole_for(self, args):
        if self.compiler_type.is_osx_compiler:
            result = []
            for a in args:
                result += ['-Wl,-force_load', a]
            return result
        return ['-Wl,--whole-archive'] + args + ['-Wl,--no-whole-archive']

    def get_instruction_set_args(self, instruction_set):
        return gnulike_instruction_set_args.get(instruction_set, None)

    def get_default_include_dirs(self):
        return gnulike_default_include_dirs(self.exelist, self.language)

    @abc.abstractmethod
    def openmp_flags(self):
        raise NotImplementedError("openmp_flags not implemented")

    def gnu_symbol_visibility_args(self, vistype):
        return gnu_symbol_visibility_args[vistype]

    def gen_vs_module_defs_args(self, defsfile):
        if not isinstance(defsfile, str):
            raise RuntimeError('Module definitions file should be str')
        # On Windows targets, .def files may be specified on the linker command
        # line like an object file.
        if self.compiler_type.is_windows_compiler:
            return [defsfile]
        # For other targets, discard the .def file.
        return []

    def get_lto_compile_args(self):
        return ['-flto']

    def get_lto_link_args(self):
        return ['-flto']


class GnuCompiler(GnuLikeCompiler):
    """
    GnuCompiler represents an actual GCC in its many incarnations.
    Compilers imitating GCC (Clang/Intel) should use the GnuLikeCompiler ABC.
    """
    def __init__(self, compiler_type, defines):
        super().__init__(compiler_type)
        self.id = 'gcc'
        self.defines = defines or {}
        self.base_options.append('b_colorout')

    def get_colorout_args(self, colortype):
        if mesonlib.version_compare(self.version, '>=4.9.0'):
            return gnu_color_args[colortype][:]
        return []

    def get_warn_args(self, level):
        args = super().get_warn_args(level)
        if mesonlib.version_compare(self.version, '<4.8.0') and '-Wpedantic' in args:
            # -Wpedantic was added in 4.8.0
            # https://gcc.gnu.org/gcc-4.8/changes.html
            args[args.index('-Wpedantic')] = '-pedantic'
        return args

    def has_builtin_define(self, define):
        return define in self.defines

    def get_builtin_define(self, define):
        if define in self.defines:
            return self.defines[define]

    def get_optimization_args(self, optimization_level):
        return gnu_optimization_args[optimization_level]

    def get_pch_suffix(self):
        return 'gch'

    def get_gui_app_args(self, value):
        if self.compiler_type.is_windows_compiler and value:
            return ['-mwindows']
        return []

    def openmp_flags(self):
        return ['-fopenmp']


class ElbrusCompiler(GnuCompiler):
    # Elbrus compiler is nearly like GCC, but does not support
    # PCH, LTO, sanitizers and color output as of version 1.21.x.
    def __init__(self, compiler_type, defines):
        GnuCompiler.__init__(self, compiler_type, defines)
        self.id = 'lcc'
        self.base_options = ['b_pgo', 'b_coverage',
                             'b_ndebug', 'b_staticpic',
                             'b_lundef', 'b_asneeded']

    # FIXME: use _build_wrapper to call this so that linker flags from the env
    # get applied
    def get_library_dirs(self, env):
        os_env = os.environ.copy()
        os_env['LC_ALL'] = 'C'
        stdo = Popen_safe(self.exelist + ['--print-search-dirs'], env=os_env)[1]
        paths = ()
        for line in stdo.split('\n'):
            if line.startswith('libraries:'):
                # lcc does not include '=' in --print-search-dirs output.
                libstr = line.split(' ', 1)[1]
                paths = (os.path.realpath(p) for p in libstr.split(':'))
                break
        return paths

    def get_program_dirs(self, env):
        os_env = os.environ.copy()
        os_env['LC_ALL'] = 'C'
        stdo = Popen_safe(self.exelist + ['--print-search-dirs'], env=os_env)[1]
        paths = ()
        for line in stdo.split('\n'):
            if line.startswith('programs:'):
                # lcc does not include '=' in --print-search-dirs output.
                libstr = line.split(' ', 1)[1]
                paths = (os.path.realpath(p) for p in libstr.split(':'))
                break
        return paths


class ClangCompiler(GnuLikeCompiler):
    def __init__(self, compiler_type):
        super().__init__(compiler_type)
        self.id = 'clang'
        self.base_options.append('b_colorout')
        if self.compiler_type.is_osx_compiler:
            self.base_options.append('b_bitcode')
        # All Clang backends can also do LLVM IR
        self.can_compile_suffixes.add('ll')

    def get_colorout_args(self, colortype):
        return clang_color_args[colortype][:]

    def get_optimization_args(self, optimization_level):
        return clike_optimization_args[optimization_level]

    def get_pch_suffix(self):
        return 'pch'

    def get_pch_use_args(self, pch_dir, header):
        # Workaround for Clang bug http://llvm.org/bugs/show_bug.cgi?id=15136
        # This flag is internal to Clang (or at least not documented on the man page)
        # so it might change semantics at any time.
        return ['-include-pch', os.path.join(pch_dir, self.get_pch_name(header))]

    def has_multi_arguments(self, args, env):
        myargs = ['-Werror=unknown-warning-option', '-Werror=unused-command-line-argument']
        if mesonlib.version_compare(self.version, '>=3.6.0'):
            myargs.append('-Werror=ignored-optimization-argument')
        return super().has_multi_arguments(
            myargs + args,
            env)

    def has_function(self, funcname, prefix, env, extra_args=None, dependencies=None):
        if extra_args is None:
            extra_args = []
        # Starting with XCode 8, we need to pass this to force linker
        # visibility to obey OS X and iOS minimum version targets with
        # -mmacosx-version-min, -miphoneos-version-min, etc.
        # https://github.com/Homebrew/homebrew-core/issues/3727
        if self.compiler_type.is_osx_compiler and version_compare(self.version, '>=8.0'):
            extra_args.append('-Wl,-no_weak_imports')
        return super().has_function(funcname, prefix, env, extra_args, dependencies)

    def openmp_flags(self):
        if version_compare(self.version, '>=3.8.0'):
            return ['-fopenmp']
        elif version_compare(self.version, '>=3.7.0'):
            return ['-fopenmp=libomp']
        else:
            # Shouldn't work, but it'll be checked explicitly in the OpenMP dependency.
            return []


class ArmclangCompiler:
    def __init__(self, compiler_type):
        if not self.is_cross:
            raise EnvironmentException('armclang supports only cross-compilation.')
        # Check whether 'armlink.exe' is available in path
        self.linker_exe = 'armlink.exe'
        args = '--vsn'
        try:
            p, stdo, stderr = Popen_safe(self.linker_exe, args)
        except OSError as e:
            err_msg = 'Unknown linker\nRunning "{0}" gave \n"{1}"'.format(' '.join([self.linker_exe] + [args]), e)
            raise EnvironmentException(err_msg)
        # Verify the armlink version
        ver_str = re.search('.*Component.*', stdo)
        if ver_str:
            ver_str = ver_str.group(0)
        else:
            EnvironmentException('armlink version string not found')
        # Using the regular expression from environment.search_version,
        # which is used for searching compiler version
        version_regex = '(?<!(\d|\.))(\d{1,2}(\.\d+)+(-[a-zA-Z0-9]+)?)'
        linker_ver = re.search(version_regex, ver_str)
        if linker_ver:
            linker_ver = linker_ver.group(0)
        if not version_compare(self.version, '==' + linker_ver):
            raise EnvironmentException('armlink version does not match with compiler version')
        self.id = 'armclang'
        self.compiler_type = compiler_type
        self.base_options = ['b_pch', 'b_lto', 'b_pgo', 'b_sanitize', 'b_coverage',
                             'b_ndebug', 'b_staticpic', 'b_colorout']
        # Assembly
        self.can_compile_suffixes.update('s')

    def can_linker_accept_rsp(self):
        return False

    def get_pic_args(self):
        # PIC support is not enabled by default for ARM,
        # if users want to use it, they need to add the required arguments explicitly
        return []

    def get_colorout_args(self, colortype):
        return clang_color_args[colortype][:]

    def get_buildtype_args(self, buildtype):
        return armclang_buildtype_args[buildtype]

    def get_buildtype_linker_args(self, buildtype):
        return arm_buildtype_linker_args[buildtype]

    # Override CCompiler.get_std_shared_lib_link_args
    def get_std_shared_lib_link_args(self):
        return []

    def get_pch_suffix(self):
        return 'gch'

    def get_pch_use_args(self, pch_dir, header):
        # Workaround for Clang bug http://llvm.org/bugs/show_bug.cgi?id=15136
        # This flag is internal to Clang (or at least not documented on the man page)
        # so it might change semantics at any time.
        return ['-include-pch', os.path.join(pch_dir, self.get_pch_name(header))]

    # Override CCompiler.get_dependency_gen_args
    def get_dependency_gen_args(self, outtarget, outfile):
        return []

    # Override CCompiler.build_rpath_args
    def build_rpath_args(self, build_dir, from_dir, rpath_paths, build_rpath, install_rpath):
        return []

    def get_linker_exelist(self):
        return [self.linker_exe]

    def get_optimization_args(self, optimization_level):
        return armclang_optimization_args[optimization_level]

    def get_debug_args(self, is_debug):
        return clike_debug_args[is_debug]

    def gen_export_dynamic_link_args(self, env):
        """
        The args for export dynamic
        """
        return ['--export_dynamic']

    def gen_import_library_args(self, implibname):
        """
        The args of the outputted import library

        ArmLinker's symdefs output can be used as implib
        """
        return ['--symdefs=' + implibname]

    def get_lto_compile_args(self):
        return ['-flto']

    def get_lto_link_args(self):
        return ['-flto']


# Tested on linux for ICC 14.0.3, 15.0.6, 16.0.4, 17.0.1
class IntelCompiler(GnuLikeCompiler):
    def __init__(self, compiler_type):
        super().__init__(compiler_type)
        self.id = 'intel'
        self.lang_header = 'none'

    def get_optimization_args(self, optimization_level):
        return clike_optimization_args[optimization_level]

    def get_pch_suffix(self):
        return 'pchi'

    def get_pch_use_args(self, pch_dir, header):
        return ['-pch', '-pch_dir', os.path.join(pch_dir), '-x',
                self.lang_header, '-include', header, '-x', 'none']

    def get_pch_name(self, header_name):
        return os.path.basename(header_name) + '.' + self.get_pch_suffix()

    def openmp_flags(self):
        if version_compare(self.version, '>=15.0.0'):
            return ['-qopenmp']
        else:
            return ['-openmp']

    def has_arguments(self, args, env, code, mode):
        # -diag-error 10148 is required to catch invalid -W options
        return super().has_arguments(args + ['-diag-error', '10006', '-diag-error', '10148'], env, code, mode)


class ArmCompiler:
    # Functionality that is common to all ARM family compilers.
    def __init__(self, compiler_type):
        if not self.is_cross:
            raise EnvironmentException('armcc supports only cross-compilation.')
        self.id = 'arm'
        self.compiler_type = compiler_type
        default_warn_args = []
        self.warn_args = {'1': default_warn_args,
                          '2': default_warn_args + [],
                          '3': default_warn_args + []}
        # Assembly
        self.can_compile_suffixes.add('s')

    def can_linker_accept_rsp(self):
        return False

    def get_pic_args(self):
        # FIXME: Add /ropi, /rwpi, /fpic etc. qualifiers to --apcs
        return []

    def get_buildtype_args(self, buildtype):
        return arm_buildtype_args[buildtype]

    def get_buildtype_linker_args(self, buildtype):
        return arm_buildtype_linker_args[buildtype]

    # Override CCompiler.get_always_args
    def get_always_args(self):
        return []

    # Override CCompiler.get_dependency_gen_args
    def get_dependency_gen_args(self, outtarget, outfile):
        return []

    # Override CCompiler.get_std_shared_lib_link_args
    def get_std_shared_lib_link_args(self):
        return []

    def get_pch_use_args(self, pch_dir, header):
        # FIXME: Add required arguments
        # NOTE from armcc user guide:
        # "Support for Precompiled Header (PCH) files is deprecated from ARM Compiler 5.05
        # onwards on all platforms. Note that ARM Compiler on Windows 8 never supported
        # PCH files."
        return []

    def get_pch_suffix(self):
        # NOTE from armcc user guide:
        # "Support for Precompiled Header (PCH) files is deprecated from ARM Compiler 5.05
        # onwards on all platforms. Note that ARM Compiler on Windows 8 never supported
        # PCH files."
        return 'pch'

    def thread_flags(self, env):
        return []

    def thread_link_flags(self, env):
        return []

    def get_linker_exelist(self):
        args = ['armlink']
        return args

    def get_coverage_args(self):
        return []

    def get_coverage_link_args(self):
        return []

    def get_optimization_args(self, optimization_level):
        return arm_optimization_args[optimization_level]

    def get_debug_args(self, is_debug):
        return clike_debug_args[is_debug]
