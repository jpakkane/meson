# Copyright 2013-2017 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This file contains the detection logic for miscellaneous external dependencies.

import glob
import os

from .. import mlog
from .. import mesonlib
from ..mesonlib import LibType
from ..environment import detect_cpu_family

from .base import (DependencyException, ExternalDependency)
from .misc import threads_factory

# On windows 3 directory layouts are supported:
# * The default layout (versioned) installed:
#   - $BOOST_ROOT/include/boost-x_x/boost/*.hpp
#   - $BOOST_ROOT/lib/*.lib
# * The non-default layout (system) installed:
#   - $BOOST_ROOT/include/boost/*.hpp
#   - $BOOST_ROOT/lib/*.lib
# * The pre-built binaries from sf.net:
#   - $BOOST_ROOT/boost/*.hpp
#   - $BOOST_ROOT/lib<arch>-<compiler>/*.lib where arch=32/64 and compiler=msvc-14.1
#
# Note that we should also try to support:
# mingw-w64 / Windows : libboost_<module>-mt.a            (location = <prefix>/mingw64/lib/)
#                       libboost_<module>-mt.dll.a
#
# Library names supported:
#   - libboost_<module>-<compiler>-mt-gd-x_x.lib (static)
#   - boost_<module>-<compiler>-mt-gd-x_x.lib|.dll (shared)
#   - libboost_<module>.lib (static)
#   - boost_<module>.lib|.dll (shared)
#   where compiler is vc141 for example.
#
# NOTE: -gd means runtime and build time debugging is on
#       -mt means threading=multi
#
# The `modules` argument accept library names. This is because every module that
# has libraries to link against also has multiple options regarding how to
# link. See for example:
# * http://www.boost.org/doc/libs/1_65_1/libs/test/doc/html/boost_test/usage_variants.html
# * http://www.boost.org/doc/libs/1_65_1/doc/html/stacktrace/configuration_and_build.html
# * http://www.boost.org/doc/libs/1_65_1/libs/math/doc/html/math_toolkit/main_tr1.html

# **On Unix**, official packaged versions of boost libraries follow the following schemes:
#
# Linux / Debian:   libboost_<module>.so -> libboost_<module>.so.1.66.0
# Linux / Red Hat:  libboost_<module>.so -> libboost_<module>.so.1.66.0
# Linux / OpenSuse: libboost_<module>.so -> libboost_<module>.so.1.66.0
# Win   / Cygwin:   libboost_<module>.dll.a                                 (location = /usr/lib)
#                   libboost_<module>.a
#                   cygboost_<module>_1_64.dll                              (location = /usr/bin)
# Win   / VS:       boost_<module>-vc<ver>-mt[-gd]-<arch>-1_67.dll          (location = C:/local/boost_1_67_0)
# Mac   / homebrew: libboost_<module>.dylib + libboost_<module>-mt.dylib    (location = /usr/local/lib)
# Mac   / macports: libboost_<module>.dylib + libboost_<module>-mt.dylib    (location = /opt/local/lib)
#
# Its not clear that any other abi tags (e.g. -gd) are used in official packages.
#
# On Linux systems, boost libs have multithreading support enabled, but without the -mt tag.
#
# Boost documentation recommends using complex abi tags like "-lboost_regex-gcc34-mt-d-1_36".
# (See http://www.boost.org/doc/libs/1_66_0/more/getting_started/unix-variants.html#library-naming)
# However, its not clear that any Unix distribution follows this scheme.
# Furthermore, the boost documentation for unix above uses examples from windows like
#   "libboost_regex-vc71-mt-d-x86-1_34.lib", so apparently the abi tags may be more aimed at windows.
#
# Probably we should use the linker search path to decide which libraries to use.  This will
# make it possible to find the macports boost libraries without setting BOOST_ROOT, and will
# also mean that it would be possible to use user-installed boost libraries when official
# packages are installed.
#
# We thus follow the following strategy:
# 1. Look for libraries using compiler.find_library( )
#   1.1 On Linux, just look for boost_<module>
#   1.2 On other systems (e.g. Mac) look for boost_<module>-mt if multithreading.
#   1.3 Otherwise look for boost_<module>
# 2. Fall back to previous approach
#   2.1. Search particular directories.
#   2.2. Find boost libraries with unknown suffixes using file-name globbing.

# TODO: Unix: Don't assume we know where the boost dir is, rely on -Idir and -Ldir being set.
# TODO: Allow user to specify suffix in BOOST_SUFFIX, or add specific options like BOOST_DEBUG for 'd' for debug.

class BoostDependency(ExternalDependency):
    def __init__(self, environment, kwargs):
        super().__init__('boost', environment, kwargs, language='cpp')
        self.need_static_link = ['boost_exception', 'boost_test_exec_monitor']
        self.is_debug = environment.coredata.get_builtin_option('buildtype').startswith('debug')
        threading = kwargs.get("threading", "multi")
        self.is_multithreading = threading == "multi"

        self.requested_modules = self.get_requested(kwargs)
        if 'thread' in self.requested_modules:
            if not self._add_sub_dependency(threads_factory(environment, self.for_machine, {})):
                self.is_found = False
                return

        self.boost_root = None
        self.boost_roots = []
        self.incdir = None
        self.libdir = None

        if 'BOOST_ROOT' in os.environ:
            self.boost_root = os.environ['BOOST_ROOT']
            self.boost_roots = [self.boost_root]
            if not os.path.isabs(self.boost_root):
                raise DependencyException('BOOST_ROOT must be an absolute path.')
        if 'BOOST_INCLUDEDIR' in os.environ:
            self.incdir = os.environ['BOOST_INCLUDEDIR']
        if 'BOOST_LIBRARYDIR' in os.environ:
            self.libdir = os.environ['BOOST_LIBRARYDIR']

        if self.boost_root is None:
            if self.env.machines[self.for_machine].is_windows():
                self.boost_roots = self.detect_win_roots()
            else:
                self.boost_roots = self.detect_nix_roots()

        if self.incdir is None:
            if self.env.machines[self.for_machine].is_windows():
                self.incdir = self.detect_win_incdir()
            else:
                self.incdir = self.detect_nix_incdir()

        mlog.debug('Boost library root dir is', mlog.bold(self.boost_root))
        mlog.debug('Boost include directory is', mlog.bold(self.incdir))

        # 1. check if we can find BOOST headers.
        self.detect_headers_and_version()

        if not self.is_found:
            return # if we can not find 'boost/version.hpp'

        # 2. check if we can find BOOST libraries.
        self.detect_lib_modules()
        mlog.debug('Boost library directory is', mlog.bold(self.libdir))

        mlog.debug('Installed Boost libraries: ')
        for key in sorted(self.lib_modules.keys()):
            mlog.debug(key, self.lib_modules[key])

        # 3. check if requested modules are valid, that is, either found or in the list of known boost libraries
        self.check_invalid_modules()

        # 4. final check whether or not we find all requested and valid modules
        self.check_find_requested_modules()

    def check_invalid_modules(self):
        invalid_modules = [c for c in self.requested_modules if 'boost_' + c not in self.lib_modules and 'boost_' + c not in BOOST_LIBS]

        # previous versions of meson allowed include dirs as modules
        remove = []
        for m in invalid_modules:
            if m in BOOST_DIRS:
                mlog.warning('Requested boost library', mlog.bold(m), 'that doesn\'t exist. '
                             'This will be an error in the future')
                remove.append(m)

        self.requested_modules = [x for x in self.requested_modules if x not in remove]
        invalid_modules = [x for x in invalid_modules if x not in remove]

        if invalid_modules:
            mlog.error('Invalid Boost modules: ' + ', '.join(invalid_modules))
            return True
        else:
            return False

    def log_details(self):
        module_str = ', '.join(self.requested_modules)
        return module_str

    def log_info(self):
        if self.boost_root:
            return self.boost_root
        return ''

    def detect_nix_roots(self):
        return [os.path.abspath(os.path.join(x, '..'))
                for x in self.clib_compiler.get_default_include_dirs()]

    def detect_win_roots(self):
        res = []
        # Where boost documentation says it should be
        globtext = 'C:\\Program Files\\boost\\boost_*'
        files = glob.glob(globtext)
        res.extend(files)

        # Where boost built from source actually installs it
        if os.path.isdir('C:\\Boost'):
            res.append('C:\\Boost')

        # Where boost prebuilt binaries are
        globtext = 'C:\\local\\boost_*'
        files = glob.glob(globtext)
        res.extend(files)
        return res

    def detect_nix_incdir(self):
        if self.boost_root:
            return os.path.join(self.boost_root, 'include')
        return None

    # FIXME: Should pick a version that matches the requested version
    # Returns the folder that contains the boost folder.
    def detect_win_incdir(self):
        for root in self.boost_roots:
            globtext = os.path.join(root, 'include', 'boost-*')
            incdirs = glob.glob(globtext)
            if incdirs:
                return incdirs[0]
            incboostdir = os.path.join(root, 'include', 'boost')
            if os.path.isdir(incboostdir):
                return os.path.join(root, 'include')
            incboostdir = os.path.join(root, 'boost')
            if os.path.isdir(incboostdir):
                return root
        return None

    def get_compile_args(self):
        args = []
        include_dir = self.incdir

        # Use "-isystem" when including boost headers instead of "-I"
        # to avoid compiler warnings/failures when "-Werror" is used

        # Careful not to use "-isystem" on default include dirs as it
        # breaks some of the headers for certain gcc versions

        # For example, doing g++ -isystem /usr/include on a simple
        # "int main()" source results in the error:
        # "/usr/include/c++/6.3.1/cstdlib:75:25: fatal error: stdlib.h: No such file or directory"

        # See https://gcc.gnu.org/bugzilla/show_bug.cgi?id=70129
        # and http://stackoverflow.com/questions/37218953/isystem-on-a-system-include-directory-causes-errors
        # for more details

        if include_dir and include_dir not in self.clib_compiler.get_default_include_dirs():
            args.append("".join(self.clib_compiler.get_include_args(include_dir, True)))
        return args

    def get_requested(self, kwargs):
        candidates = mesonlib.extract_as_list(kwargs, 'modules')
        for c in candidates:
            if not isinstance(c, str):
                raise DependencyException('Boost module argument is not a string.')
        return candidates

    def detect_headers_and_version(self):
        try:
            version = self.clib_compiler.get_define('BOOST_LIB_VERSION', '#include <boost/version.hpp>', self.env, self.get_compile_args(), [], disable_cache=True)[0]
        except mesonlib.EnvironmentException:
            return
        except TypeError:
            return
        # Remove quotes
        version = version[1:-1]
        # Fix version string
        self.version = version.replace('_', '.')
        self.is_found = True

    def detect_lib_modules(self):
        self.lib_modules = {}
        # 1. Try to find modules using compiler.find_library( )
        if self.find_libraries_with_abi_tags(self.abi_tags()):
            pass
        # 2. Fall back to the old method
        else:
            if self.env.machines[self.for_machine].is_windows():
                self.detect_lib_modules_win()
            else:
                self.detect_lib_modules_nix()

    def check_find_requested_modules(self):
        # 3. Check if we can find the modules
        for m in self.requested_modules:
            if 'boost_' + m not in self.lib_modules:
                mlog.debug('Requested Boost library {!r} not found'.format(m))
                self.is_found = False

    def modname_from_filename(self, filename):
        modname = os.path.basename(filename)
        modname = modname.split('.', 1)[0]
        modname = modname.split('-', 1)[0]
        if modname.startswith('libboost'):
            modname = modname[3:]
        return modname

    def compiler_tag(self):
        tag = None
        compiler = self.env.detect_cpp_compiler(self.for_machine)
        if self.env.machines[self.for_machine].is_windows():
            if compiler.get_id() in ['msvc', 'clang-cl']:
                comp_ts_version = compiler.get_toolset_version()
                compiler_ts = comp_ts_version.split('.')
                # FIXME - what about other compilers?
                tag = '-vc{}{}'.format(compiler_ts[0], compiler_ts[1])
            else:
                tag = ''
        return tag

    def threading_tag(self):
        if not self.is_multithreading:
            return ''

        if self.env.machines[self.for_machine].is_darwin():
            # - Mac:      requires -mt for multithreading, so should not fall back to non-mt libraries.
            return '-mt'
        elif self.env.machines[self.for_machine].is_windows():
            # - Windows:  requires -mt for multithreading, so should not fall back to non-mt libraries.
            return '-mt'
        else:
            # - Linux:    leaves off -mt but libraries are multithreading-aware.
            # - Cygwin:   leaves off -mt but libraries are multithreading-aware.
            return ''

    def version_tag(self):
        return '-' + self.version.replace('.', '_')

    def debug_tag(self):
        return '-gd' if self.is_debug else ''

    def arch_tag(self):
        # currently only applies to windows msvc installed binaries
        if self.env.detect_cpp_compiler(self.for_machine).get_id() not in ['msvc', 'clang-cl']:
            return ''
        # pre-compiled binaries only added arch tag for versions > 1.64
        if float(self.version) < 1.65:
            return ''
        arch = detect_cpu_family(self.env.coredata.compilers.host)
        if arch == 'x86':
            return '-x32'
        elif arch == 'x86_64':
            return '-x64'
        return ''

    def versioned_abi_tag(self):
        return self.compiler_tag() + self.threading_tag() + self.debug_tag() + self.arch_tag() + self.version_tag()

    # FIXME - how to handle different distributions, e.g. for Mac? Currently we handle homebrew and macports, but not fink.
    def abi_tags(self):
        if self.env.machines[self.for_machine].is_windows():
            return [self.versioned_abi_tag(), self.threading_tag()]
        else:
            return [self.threading_tag()]

    def sourceforge_dir(self):
        if self.env.detect_cpp_compiler(self.for_machine).get_id() != 'msvc':
            return None
        comp_ts_version = self.env.detect_cpp_compiler(self.for_machine).get_toolset_version()
        arch = detect_cpu_family(self.env.coredata.compilers.host)
        if arch == 'x86':
            return 'lib32-msvc-{}'.format(comp_ts_version)
        elif arch == 'x86_64':
            return 'lib64-msvc-{}'.format(comp_ts_version)
        else:
            # Does anyone do Boost cross-compiling to other archs on Windows?
            return None

    def find_libraries_with_abi_tag(self, tag):

        # All modules should have the same tag
        self.lib_modules = {}

        all_found = True
        libtype = LibType.PREFER_STATIC if self.static else LibType.PREFER_SHARED

        for module in self.requested_modules:
            libname = 'boost_' + module + tag

            args = self.clib_compiler.find_library(libname, self.env, self.extra_lib_dirs(), libtype=libtype)
            if args is None:
                mlog.debug("Couldn\'t find library '{}' for boost module '{}'  (ABI tag = '{}')".format(libname, module, tag))
                all_found = False
            else:
                mlog.debug('Link args for boost module "{}" are {}'.format(module, args))
                self.lib_modules['boost_' + module] = args

        return all_found

    def find_libraries_with_abi_tags(self, tags):
        for tag in tags:
            if self.find_libraries_with_abi_tag(tag):
                return True
        return False

    def detect_lib_modules_win(self):
        if not self.libdir:
            # The libdirs in the distributed binaries (from sf)
            lib_sf = self.sourceforge_dir()

            if self.boost_root:
                roots = [self.boost_root]
            else:
                roots = self.boost_roots
            for root in roots:
                # The default libdir when building
                libdir = os.path.join(root, 'lib')
                if os.path.isdir(libdir):
                    self.libdir = libdir
                    break
                if lib_sf:
                    full_path = os.path.join(root, lib_sf)
                    if os.path.isdir(full_path):
                        self.libdir = full_path
                        break

        if not self.libdir:
            return

        for name in self.need_static_link:
            # FIXME - why are we only looking for *.lib? Mingw provides *.dll.a and *.a
            libname = 'lib' + name + self.versioned_abi_tag() + '.lib'
            if os.path.isfile(os.path.join(self.libdir, libname)):
                self.lib_modules[self.modname_from_filename(libname)] = [libname]
            else:
                libname = "lib{}.lib".format(name)
                if os.path.isfile(os.path.join(self.libdir, libname)):
                    self.lib_modules[name[3:]] = [libname]

        # globber1 applies to a layout=system installation
        # globber2 applies to a layout=versioned installation
        globber1 = 'libboost_*' if self.static else 'boost_*'
        globber2 = globber1 + self.versioned_abi_tag()
        # FIXME - why are we only looking for *.lib? Mingw provides *.dll.a and *.a
        globber2_matches = glob.glob(os.path.join(self.libdir, globber2 + '.lib'))
        for entry in globber2_matches:
            fname = os.path.basename(entry)
            self.lib_modules[self.modname_from_filename(fname)] = [fname]
        if not globber2_matches:
            # FIXME - why are we only looking for *.lib? Mingw provides *.dll.a and *.a
            for entry in glob.glob(os.path.join(self.libdir, globber1 + '.lib')):
                if self.static:
                    fname = os.path.basename(entry)
                    self.lib_modules[self.modname_from_filename(fname)] = [fname]

    def detect_lib_modules_nix(self):
        if self.static:
            libsuffix = 'a'
        elif self.env.machines[self.for_machine].is_darwin():
            libsuffix = 'dylib'
        else:
            libsuffix = 'so'

        globber = 'libboost_*.{}'.format(libsuffix)
        if self.libdir:
            libdirs = [self.libdir]
        elif self.boost_root is None:
            libdirs = mesonlib.get_library_dirs()
        else:
            libdirs = [os.path.join(self.boost_root, 'lib')]
        for libdir in libdirs:
            for name in self.need_static_link:
                libname = 'lib{}.a'.format(name)
                if os.path.isfile(os.path.join(libdir, libname)):
                    self.lib_modules[name] = [libname]
            for entry in glob.glob(os.path.join(libdir, globber)):
                # I'm not 100% sure what to do here. Some distros
                # have modules such as thread only as -mt versions.
                # On debian all packages are built threading=multi
                # but not suffixed with -mt.
                # FIXME: implement detect_lib_modules_{debian, redhat, ...}
                # FIXME: this wouldn't work with -mt-gd either. -BDR
                if self.is_multithreading and mesonlib.is_debianlike():
                    pass
                elif self.is_multithreading and entry.endswith('-mt.{}'.format(libsuffix)):
                    pass
                elif not entry.endswith('-mt.{}'.format(libsuffix)):
                    pass
                else:
                    continue
                modname = self.modname_from_filename(entry)
                if modname not in self.lib_modules:
                    self.lib_modules[modname] = [entry]

    def extra_lib_dirs(self):
        if self.libdir:
            return [self.libdir]
        elif self.boost_root:
            return [os.path.join(self.boost_root, 'lib')]
        return []

    def get_link_args(self, **kwargs):
        args = []
        for d in self.extra_lib_dirs():
            args += self.clib_compiler.get_linker_search_args(d)
        for lib in self.requested_modules:
            args += self.lib_modules['boost_' + lib]
        return args

    def get_sources(self):
        return []

# Generated with boost_names.py
BOOST_LIBS = [
    'boost_atomic',
    'boost_chrono',
    'boost_chrono',
    'boost_container',
    'boost_context',
    'boost_coroutine',
    'boost_date_time',
    'boost_exception',
    'boost_fiber',
    'boost_filesystem',
    'boost_graph',
    'boost_iostreams',
    'boost_locale',
    'boost_log',
    'boost_log_setup',
    'boost_math_tr1',
    'boost_math_tr1f',
    'boost_math_tr1l',
    'boost_math_c99',
    'boost_math_c99f',
    'boost_math_c99l',
    'boost_math_tr1',
    'boost_math_tr1f',
    'boost_math_tr1l',
    'boost_math_c99',
    'boost_math_c99f',
    'boost_math_c99l',
    'boost_math_tr1',
    'boost_math_tr1f',
    'boost_math_tr1l',
    'boost_math_c99',
    'boost_math_c99f',
    'boost_math_c99l',
    'boost_math_tr1',
    'boost_math_tr1f',
    'boost_math_tr1l',
    'boost_math_c99',
    'boost_math_c99f',
    'boost_math_c99l',
    'boost_math_tr1',
    'boost_math_tr1f',
    'boost_math_tr1l',
    'boost_math_c99',
    'boost_math_c99f',
    'boost_math_c99l',
    'boost_math_tr1',
    'boost_math_tr1f',
    'boost_math_tr1l',
    'boost_math_c99',
    'boost_math_c99f',
    'boost_math_c99l',
    'boost_mpi',
    'boost_program_options',
    'boost_random',
    'boost_regex',
    'boost_serialization',
    'boost_wserialization',
    'boost_signals',
    'boost_stacktrace_noop',
    'boost_stacktrace_backtrace',
    'boost_stacktrace_addr2line',
    'boost_stacktrace_basic',
    'boost_stacktrace_windbg',
    'boost_stacktrace_windbg_cached',
    'boost_system',
    'boost_prg_exec_monitor',
    'boost_test_exec_monitor',
    'boost_unit_test_framework',
    'boost_thread',
    'boost_timer',
    'boost_type_erasure',
    'boost_wave'
]

BOOST_DIRS = [
    'lambda',
    'optional',
    'convert',
    'system',
    'uuid',
    'archive',
    'align',
    'timer',
    'chrono',
    'gil',
    'logic',
    'signals',
    'predef',
    'tr1',
    'multi_index',
    'property_map',
    'multi_array',
    'context',
    'random',
    'endian',
    'circular_buffer',
    'proto',
    'assign',
    'format',
    'math',
    'phoenix',
    'graph',
    'locale',
    'mpl',
    'pool',
    'unordered',
    'core',
    'exception',
    'ptr_container',
    'flyweight',
    'range',
    'typeof',
    'thread',
    'move',
    'spirit',
    'dll',
    'compute',
    'serialization',
    'ratio',
    'msm',
    'config',
    'metaparse',
    'coroutine2',
    'qvm',
    'program_options',
    'concept',
    'detail',
    'hana',
    'concept_check',
    'compatibility',
    'variant',
    'type_erasure',
    'mpi',
    'test',
    'fusion',
    'log',
    'sort',
    'local_function',
    'units',
    'functional',
    'preprocessor',
    'integer',
    'container',
    'polygon',
    'interprocess',
    'numeric',
    'iterator',
    'wave',
    'lexical_cast',
    'multiprecision',
    'utility',
    'tti',
    'asio',
    'dynamic_bitset',
    'algorithm',
    'xpressive',
    'bimap',
    'signals2',
    'type_traits',
    'regex',
    'statechart',
    'parameter',
    'icl',
    'python',
    'lockfree',
    'intrusive',
    'io',
    'pending',
    'geometry',
    'tuple',
    'iostreams',
    'heap',
    'atomic',
    'filesystem',
    'smart_ptr',
    'function',
    'fiber',
    'type_index',
    'accumulators',
    'function_types',
    'coroutine',
    'vmd',
    'date_time',
    'property_tree',
    'bind'
]
