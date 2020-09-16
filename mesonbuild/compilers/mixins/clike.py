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


"""Mixin classes to be shared between C and C++ compilers.

Without this we'll end up with awful diamond inherintance problems. The goal
of this is to have mixin's, which are classes that are designed *not* to be
standalone, they only work through inheritance.
"""

import functools
import glob
import itertools
import os
import re
import subprocess
import typing as T
from pathlib import Path
from itertools import groupby
from operator import itemgetter

from ... import arglist
from ... import mesonlib
from ... import mlog
from ...linkers import GnuLikeDynamicLinkerMixin, SolarisDynamicLinker
from ...mesonlib import LibType
from .. import compilers
from .visualstudio import VisualStudioLikeCompiler

if T.TYPE_CHECKING:
    from ...environment import Environment

GROUP_FLAGS = re.compile(r'''[^-].*\.so (?:\.[0-9]+)? (?:\.[0-9]+)? (?:\.[0-9]+)?$ |
                             ^(?:-Wl,)?-l |
                             \.a$''', re.X)

def group_consecutive_integer(data):
    ''' Find all slices having the consecutive integers '''
    groups = list()
    for k, g in groupby(enumerate(data), lambda x: x[0]-x[1]):
        group = (map(itemgetter(1), g))
        group = list(map(int, group))
        groups.append((group[0], group[-1]))

    return groups

class CLikeCompilerArgs(arglist.CompilerArgs):
    prepend_prefixes = ('-I', '-L')
    dedup2_prefixes = ('-I', '-isystem', '-L', '-D', '-U')

    # NOTE: not thorough. A list of potential corner cases can be found in
    # https://github.com/mesonbuild/meson/pull/4593#pullrequestreview-182016038
    dedup1_prefixes = ('-l', '-Wl,-l', '-Wl,--export-dynamic')
    dedup1_suffixes = ('.lib', '.dll', '.so', '.dylib', '.a')
    dedup1_args = ('-c', '-S', '-E', '-pipe', '-pthread')

    def to_native(self, copy: bool = False) -> T.List[str]:
        # Check if we need to add --start/end-group for circular dependencies
        # between static libraries, and for recursively searching for symbols
        # needed by static libraries that are provided by object files or
        # shared libraries.
        self.flush_pre_post()
        if copy:
            new = self.copy()
        else:
            new = self
        # This covers all ld.bfd, ld.gold, ld.gold, and xild on Linux, which
        # all act like (or are) gnu ld
        # TODO: this could probably be added to the DynamicLinker instead
        if isinstance(self.compiler.linker, (GnuLikeDynamicLinkerMixin, SolarisDynamicLinker)):
            is_library = list()

            for i, each in enumerate(new):
                if not GROUP_FLAGS.search(each):
                    continue
                is_library.append(i)

            # For each slice, enclose the arguments with '--start-group' and '--end-group'
            offset = 0
            for _group_start, _group_end in group_consecutive_integer(is_library):
                # Skip groups that contains single link object
                if _group_end - _group_start < 2:
                    continue

                # Last occurrence of a library in the subslice
                new.insert(_group_end + offset + 1, '-Wl,--end-group')
                new.insert(_group_start + offset, '-Wl,--start-group')
                offset += 2

        # Remove system/default include paths added with -isystem
        if hasattr(self.compiler, 'get_default_include_dirs'):
            default_dirs = self.compiler.get_default_include_dirs()
            bad_idx_list = []  # type: T.List[int]
            for i, each in enumerate(new):
                if not each.startswith('-isystem'):
                    continue

                # Remove the -isystem and the path if the path is a default path
                if (each == '-isystem' and
                        i < (len(new) - 1) and
                        new[i + 1] in default_dirs):
                    bad_idx_list += [i, i + 1]
                elif each.startswith('-isystem=') and each[9:] in default_dirs:
                    bad_idx_list += [i]
                elif each[8:] in default_dirs:
                    bad_idx_list += [i]
            for i in reversed(bad_idx_list):
                new.pop(i)
        return self.compiler.unix_args_to_native(new._container)

    def __repr__(self) -> str:
        self.flush_pre_post()
        return 'CLikeCompilerArgs({!r}, {!r})'.format(self.compiler, self._container)


class CLikeCompiler:

    """Shared bits for the C and CPP Compilers."""

    # TODO: Replace this manual cache with functools.lru_cache
    library_dirs_cache = {}
    program_dirs_cache = {}
    find_library_cache = {}
    find_framework_cache = {}
    internal_libs = arglist.UNIXY_COMPILER_INTERNAL_LIBS

    def __init__(self, is_cross: bool, exe_wrapper: T.Optional[str] = None):
        # If a child ObjC or CPP class has already set it, don't set it ourselves
        self.is_cross = is_cross
        self.can_compile_suffixes.add('h')
        # If the exe wrapper was not found, pretend it wasn't set so that the
        # sanity check is skipped and compiler checks use fallbacks.
        if not exe_wrapper or not exe_wrapper.found() or not exe_wrapper.get_command():
            self.exe_wrapper = None
        else:
            self.exe_wrapper = exe_wrapper.get_command()

    def compiler_args(self, args: T.Optional[T.Iterable[str]] = None) -> CLikeCompilerArgs:
        return CLikeCompilerArgs(self, args)

    def needs_static_linker(self):
        return True # When compiling static libraries, so yes.

    def get_always_args(self):
        '''
        Args that are always-on for all C compilers other than MSVC
        '''
        return ['-pipe'] + compilers.get_largefile_args(self)

    def get_no_stdinc_args(self):
        return ['-nostdinc']

    def get_no_stdlib_link_args(self):
        return ['-nostdlib']

    def get_warn_args(self, level):
        return self.warn_args[level]

    def get_no_warn_args(self):
        # Almost every compiler uses this for disabling warnings
        return ['-w']

    def split_shlib_to_parts(self, fname):
        return None, fname

    def depfile_for_object(self, objfile):
        return objfile + '.' + self.get_depfile_suffix()

    def get_depfile_suffix(self):
        return 'd'

    def get_exelist(self):
        return self.exelist[:]

    def get_preprocess_only_args(self):
        return ['-E', '-P']

    def get_compile_only_args(self):
        return ['-c']

    def get_no_optimization_args(self):
        return ['-O0']

    def get_compiler_check_args(self):
        '''
        Get arguments useful for compiler checks such as being permissive in
        the code quality and not doing any optimization.
        '''
        return self.get_no_optimization_args()

    def get_output_args(self, target):
        return ['-o', target]

    def get_werror_args(self):
        return ['-Werror']

    def get_std_exe_link_args(self):
        # TODO: is this a linker property?
        return []

    def get_include_args(self, path, is_system):
        if path == '':
            path = '.'
        if is_system:
            return ['-isystem', path]
        return ['-I' + path]

    def get_compiler_dirs(self, env: 'Environment', name: str) -> T.List[str]:
        '''
        Get dirs from the compiler, either `libraries:` or `programs:`
        '''
        return []

    @functools.lru_cache()
    def get_library_dirs(self, env, elf_class = None):
        dirs = self.get_compiler_dirs(env, 'libraries')
        if elf_class is None or elf_class == 0:
            return dirs

        # if we do have an elf class for 32-bit or 64-bit, we want to check that
        # the directory in question contains libraries of the appropriate class. Since
        # system directories aren't mixed, we only need to check one file for each
        # directory and go by that. If we can't check the file for some reason, assume
        # the compiler knows what it's doing, and accept the directory anyway.
        retval = []
        for d in dirs:
            files = [f for f in os.listdir(d) if f.endswith('.so') and os.path.isfile(os.path.join(d, f))]
            # if no files, accept directory and move on
            if not files:
                retval.append(d)
                continue

            for f in files:
                file_to_check = os.path.join(d, f)
                try:
                    with open(file_to_check, 'rb') as fd:
                        header = fd.read(5)
                        # if file is not an ELF file, it's weird, but accept dir
                        # if it is elf, and the class matches, accept dir
                        if header[1:4] != b'ELF' or int(header[4]) == elf_class:
                            retval.append(d)
                        # at this point, it's an ELF file which doesn't match the
                        # appropriate elf_class, so skip this one
                    # stop scanning after the first sucessful read
                    break
                except OSError:
                    # Skip the file if we can't read it
                    pass

        return tuple(retval)

    @functools.lru_cache()
    def get_program_dirs(self, env):
        '''
        Programs used by the compiler. Also where toolchain DLLs such as
        libstdc++-6.dll are found with MinGW.
        '''
        return self.get_compiler_dirs(env, 'programs')

    def get_pic_args(self) -> T.List[str]:
        return ['-fPIC']

    def name_string(self) -> str:
        return ' '.join(self.exelist)

    def get_pch_use_args(self, pch_dir: str, header: str) -> T.List[str]:
        return ['-include', os.path.basename(header)]

    def get_pch_name(self, header_name: str) -> str:
        return os.path.basename(header_name) + '.' + self.get_pch_suffix()

    def get_linker_search_args(self, dirname: str) -> T.List[str]:
        return self.linker.get_search_args(dirname)

    def get_default_include_dirs(self):
        return []

    def gen_export_dynamic_link_args(self, env: 'Environment') -> T.List[str]:
        return self.linker.export_dynamic_args(env)

    def gen_import_library_args(self, implibname: str) -> T.List[str]:
        return self.linker.import_library_args(implibname)

    def sanity_check_impl(self, work_dir, environment, sname, code):
        mlog.debug('Sanity testing ' + self.get_display_language() + ' compiler:', ' '.join(self.exelist))
        mlog.debug('Is cross compiler: %s.' % str(self.is_cross))

        source_name = os.path.join(work_dir, sname)
        binname = sname.rsplit('.', 1)[0]
        mode = 'link'
        if self.is_cross:
            binname += '_cross'
            if self.exe_wrapper is None:
                # Linking cross built apps is painful. You can't really
                # tell if you should use -nostdlib or not and for example
                # on OSX the compiler binary is the same but you need
                # a ton of compiler flags to differentiate between
                # arm and x86_64. So just compile.
                mode = 'compile'
        cargs, largs = self._get_basic_compiler_args(environment, mode)
        extra_flags = cargs + self.linker_to_compiler_args(largs)

        # Is a valid executable output for all toolchains and platforms
        binname += '.exe'
        # Write binary check source
        binary_name = os.path.join(work_dir, binname)
        with open(source_name, 'w') as ofile:
            ofile.write(code)
        # Compile sanity check
        # NOTE: extra_flags must be added at the end. On MSVC, it might contain a '/link' argument
        # after which all further arguments will be passed directly to the linker
        cmdlist = self.exelist + [source_name] + self.get_output_args(binary_name) + extra_flags
        pc, stdo, stde = mesonlib.Popen_safe(cmdlist, cwd=work_dir)
        mlog.debug('Sanity check compiler command line:', ' '.join(cmdlist))
        mlog.debug('Sanity check compile stdout:')
        mlog.debug(stdo)
        mlog.debug('-----\nSanity check compile stderr:')
        mlog.debug(stde)
        mlog.debug('-----')
        if pc.returncode != 0:
            raise mesonlib.EnvironmentException('Compiler {0} can not compile programs.'.format(self.name_string()))
        # Run sanity check
        if self.is_cross:
            if self.exe_wrapper is None:
                # Can't check if the binaries run so we have to assume they do
                return
            cmdlist = self.exe_wrapper + [binary_name]
        else:
            cmdlist = [binary_name]
        mlog.debug('Running test binary command: ' + ' '.join(cmdlist))
        try:
            pe = subprocess.Popen(cmdlist)
        except Exception as e:
            raise mesonlib.EnvironmentException('Could not invoke sanity test executable: %s.' % str(e))
        pe.wait()
        if pe.returncode != 0:
            raise mesonlib.EnvironmentException('Executables created by {0} compiler {1} are not runnable.'.format(self.language, self.name_string()))

    def sanity_check(self, work_dir, environment):
        code = 'int main(void) { int class=0; return class; }\n'
        return self.sanity_check_impl(work_dir, environment, 'sanitycheckc.c', code)

    def check_header(self, hname: str, prefix: str, env, *, extra_args=None, dependencies=None):
        fargs = {'prefix': prefix, 'header': hname}
        code = '''{prefix}
        #include <{header}>'''
        return self.compiles(code.format(**fargs), env, extra_args=extra_args,
                             dependencies=dependencies)

    def has_header(self, hname: str, prefix: str, env, *, extra_args=None, dependencies=None, disable_cache: bool = False):
        fargs = {'prefix': prefix, 'header': hname}
        code = '''{prefix}
        #ifdef __has_include
         #if !__has_include("{header}")
          #error "Header '{header}' could not be found"
         #endif
        #else
         #include <{header}>
        #endif'''
        return self.compiles(code.format(**fargs), env, extra_args=extra_args,
                             dependencies=dependencies, mode='preprocess', disable_cache=disable_cache)

    def has_header_symbol(self, hname: str, symbol: str, prefix: str, env, *, extra_args=None, dependencies=None):
        fargs = {'prefix': prefix, 'header': hname, 'symbol': symbol}
        t = '''{prefix}
        #include <{header}>
        int main(void) {{
            /* If it's not defined as a macro, try to use as a symbol */
            #ifndef {symbol}
                {symbol};
            #endif
            return 0;
        }}'''
        return self.compiles(t.format(**fargs), env, extra_args=extra_args,
                             dependencies=dependencies)

    def _get_basic_compiler_args(self, env, mode: str):
        cargs, largs = [], []
        if mode == 'link':
            # Sometimes we need to manually select the CRT to use with MSVC.
            # One example is when trying to do a compiler check that involves
            # linking with static libraries since MSVC won't select a CRT for
            # us in that case and will error out asking us to pick one.
            try:
                crt_val = env.coredata.base_options['b_vscrt'].value
                buildtype = env.coredata.builtins['buildtype'].value
                cargs += self.get_crt_compile_args(crt_val, buildtype)
            except (KeyError, AttributeError):
                pass

        # Add CFLAGS/CXXFLAGS/OBJCFLAGS/OBJCXXFLAGS and CPPFLAGS from the env
        sys_args = env.coredata.get_external_args(self.for_machine, self.language)
        # Apparently it is a thing to inject linker flags both
        # via CFLAGS _and_ LDFLAGS, even though the former are
        # also used during linking. These flags can break
        # argument checks. Thanks, Autotools.
        cleaned_sys_args = self.remove_linkerlike_args(sys_args)
        cargs += cleaned_sys_args

        if mode == 'link':
            ld_value = env.lookup_binary_entry(self.for_machine, self.language + '_ld')
            if ld_value is not None:
                largs += self.use_linker_args(ld_value[0])

            # Add LDFLAGS from the env
            sys_ld_args = env.coredata.get_external_link_args(self.for_machine, self.language)
            # CFLAGS and CXXFLAGS go to both linking and compiling, but we want them
            # to only appear on the command line once. Remove dupes.
            largs += [x for x in sys_ld_args if x not in sys_args]

        cargs += self.get_compiler_args_for_mode(mode)
        return cargs, largs

    def _get_compiler_check_args(self, env, extra_args: list, dependencies, mode: str = 'compile') -> T.List[str]:
        if extra_args is None:
            extra_args = []
        else:
            extra_args = mesonlib.listify(extra_args)
        extra_args = mesonlib.listify([e(mode) if callable(e) else e for e in extra_args])

        if dependencies is None:
            dependencies = []
        elif not isinstance(dependencies, list):
            dependencies = [dependencies]
        # Collect compiler arguments
        cargs = self.compiler_args()
        largs = []
        for d in dependencies:
            # Add compile flags needed by dependencies
            cargs += d.get_compile_args()
            if mode == 'link':
                # Add link flags needed to find dependencies
                largs += d.get_link_args()

        ca, la = self._get_basic_compiler_args(env, mode)
        cargs += ca
        largs += la

        cargs += self.get_compiler_check_args()

        # on MSVC compiler and linker flags must be separated by the "/link" argument
        # at this point, the '/link' argument may already be part of extra_args, otherwise, it is added here
        if self.linker_to_compiler_args([]) == ['/link'] and largs != [] and not ('/link' in extra_args):
            extra_args += ['/link']

        args = cargs + extra_args + largs
        return args

    def compiles(self, code: str, env, *,
                 extra_args: T.Sequence[T.Union[T.Sequence[str], str]] = None,
                 dependencies=None, mode: str = 'compile', disable_cache: bool = False) -> T.Tuple[bool, bool]:
        with self._build_wrapper(code, env, extra_args, dependencies, mode, disable_cache=disable_cache) as p:
            return p.returncode == 0, p.cached

    def _build_wrapper(self, code: str, env, extra_args, dependencies=None, mode: str = 'compile', want_output: bool = False, disable_cache: bool = False, temp_dir: str = None) -> T.Tuple[bool, bool]:
        args = self._get_compiler_check_args(env, extra_args, dependencies, mode)
        if disable_cache or want_output:
            return self.compile(code, extra_args=args, mode=mode, want_output=want_output, temp_dir=env.scratch_dir)
        return self.cached_compile(code, env.coredata, extra_args=args, mode=mode, temp_dir=env.scratch_dir)

    def links(self, code, env, *, extra_args=None, dependencies=None, disable_cache=False):
        return self.compiles(code, env, extra_args=extra_args,
                             dependencies=dependencies, mode='link', disable_cache=disable_cache)

    def run(self, code: str, env, *, extra_args=None, dependencies=None):
        need_exe_wrapper = env.need_exe_wrapper(self.for_machine)
        if need_exe_wrapper and self.exe_wrapper is None:
            raise compilers.CrossNoRunException('Can not run test applications in this cross environment.')
        with self._build_wrapper(code, env, extra_args, dependencies, mode='link', want_output=True) as p:
            if p.returncode != 0:
                mlog.debug('Could not compile test file %s: %d\n' % (
                    p.input_name,
                    p.returncode))
                return compilers.RunResult(False)
            if need_exe_wrapper:
                cmdlist = self.exe_wrapper + [p.output_name]
            else:
                cmdlist = p.output_name
            try:
                pe, so, se = mesonlib.Popen_safe(cmdlist)
            except Exception as e:
                mlog.debug('Could not run: %s (error: %s)\n' % (cmdlist, e))
                return compilers.RunResult(False)

        mlog.debug('Program stdout:\n')
        mlog.debug(so)
        mlog.debug('Program stderr:\n')
        mlog.debug(se)
        return compilers.RunResult(True, pe.returncode, so, se)

    def _compile_int(self, expression, prefix, env, extra_args, dependencies):
        fargs = {'prefix': prefix, 'expression': expression}
        t = '''#include <stdio.h>
        {prefix}
        int main(void) {{ static int a[1-2*!({expression})]; a[0]=0; return 0; }}'''
        return self.compiles(t.format(**fargs), env, extra_args=extra_args,
                             dependencies=dependencies)[0]

    def cross_compute_int(self, expression, low, high, guess, prefix, env, extra_args, dependencies):
        # Try user's guess first
        if isinstance(guess, int):
            if self._compile_int('%s == %d' % (expression, guess), prefix, env, extra_args, dependencies):
                return guess

        # If no bounds are given, compute them in the limit of int32
        maxint = 0x7fffffff
        minint = -0x80000000
        if not isinstance(low, int) or not isinstance(high, int):
            if self._compile_int('%s >= 0' % (expression), prefix, env, extra_args, dependencies):
                low = cur = 0
                while self._compile_int('%s > %d' % (expression, cur), prefix, env, extra_args, dependencies):
                    low = cur + 1
                    if low > maxint:
                        raise mesonlib.EnvironmentException('Cross-compile check overflowed')
                    cur = cur * 2 + 1
                    if cur > maxint:
                        cur = maxint
                high = cur
            else:
                high = cur = -1
                while self._compile_int('%s < %d' % (expression, cur), prefix, env, extra_args, dependencies):
                    high = cur - 1
                    if high < minint:
                        raise mesonlib.EnvironmentException('Cross-compile check overflowed')
                    cur = cur * 2
                    if cur < minint:
                        cur = minint
                low = cur
        else:
            # Sanity check limits given by user
            if high < low:
                raise mesonlib.EnvironmentException('high limit smaller than low limit')
            condition = '%s <= %d && %s >= %d' % (expression, high, expression, low)
            if not self._compile_int(condition, prefix, env, extra_args, dependencies):
                raise mesonlib.EnvironmentException('Value out of given range')

        # Binary search
        while low != high:
            cur = low + int((high - low) / 2)
            if self._compile_int('%s <= %d' % (expression, cur), prefix, env, extra_args, dependencies):
                high = cur
            else:
                low = cur + 1

        return low

    def compute_int(self, expression, low, high, guess, prefix, env, *, extra_args=None, dependencies=None):
        if extra_args is None:
            extra_args = []
        if self.is_cross:
            return self.cross_compute_int(expression, low, high, guess, prefix, env, extra_args, dependencies)
        fargs = {'prefix': prefix, 'expression': expression}
        t = '''#include<stdio.h>
        {prefix}
        int main(void) {{
            printf("%ld\\n", (long)({expression}));
            return 0;
        }};'''
        res = self.run(t.format(**fargs), env, extra_args=extra_args,
                       dependencies=dependencies)
        if not res.compiled:
            return -1
        if res.returncode != 0:
            raise mesonlib.EnvironmentException('Could not run compute_int test binary.')
        return int(res.stdout)

    def cross_sizeof(self, typename, prefix, env, *, extra_args=None, dependencies=None):
        if extra_args is None:
            extra_args = []
        fargs = {'prefix': prefix, 'type': typename}
        t = '''#include <stdio.h>
        {prefix}
        int main(void) {{
            {type} something;
            return 0;
        }}'''
        if not self.compiles(t.format(**fargs), env, extra_args=extra_args,
                             dependencies=dependencies)[0]:
            return -1
        return self.cross_compute_int('sizeof(%s)' % typename, None, None, None, prefix, env, extra_args, dependencies)

    def sizeof(self, typename, prefix, env, *, extra_args=None, dependencies=None):
        if extra_args is None:
            extra_args = []
        fargs = {'prefix': prefix, 'type': typename}
        if self.is_cross:
            return self.cross_sizeof(typename, prefix, env, extra_args=extra_args,
                                     dependencies=dependencies)
        t = '''#include<stdio.h>
        {prefix}
        int main(void) {{
            printf("%ld\\n", (long)(sizeof({type})));
            return 0;
        }};'''
        res = self.run(t.format(**fargs), env, extra_args=extra_args,
                       dependencies=dependencies)
        if not res.compiled:
            return -1
        if res.returncode != 0:
            raise mesonlib.EnvironmentException('Could not run sizeof test binary.')
        return int(res.stdout)

    def cross_alignment(self, typename, prefix, env, *, extra_args=None, dependencies=None):
        if extra_args is None:
            extra_args = []
        fargs = {'prefix': prefix, 'type': typename}
        t = '''#include <stdio.h>
        {prefix}
        int main(void) {{
            {type} something;
            return 0;
        }}'''
        if not self.compiles(t.format(**fargs), env, extra_args=extra_args,
                             dependencies=dependencies)[0]:
            return -1
        t = '''#include <stddef.h>
        {prefix}
        struct tmp {{
            char c;
            {type} target;
        }};'''
        return self.cross_compute_int('offsetof(struct tmp, target)', None, None, None, t.format(**fargs), env, extra_args, dependencies)

    def alignment(self, typename, prefix, env, *, extra_args=None, dependencies=None):
        if extra_args is None:
            extra_args = []
        if self.is_cross:
            return self.cross_alignment(typename, prefix, env, extra_args=extra_args,
                                        dependencies=dependencies)
        fargs = {'prefix': prefix, 'type': typename}
        t = '''#include <stdio.h>
        #include <stddef.h>
        {prefix}
        struct tmp {{
            char c;
            {type} target;
        }};
        int main(void) {{
            printf("%d", (int)offsetof(struct tmp, target));
            return 0;
        }}'''
        res = self.run(t.format(**fargs), env, extra_args=extra_args,
                       dependencies=dependencies)
        if not res.compiled:
            raise mesonlib.EnvironmentException('Could not compile alignment test.')
        if res.returncode != 0:
            raise mesonlib.EnvironmentException('Could not run alignment test binary.')
        align = int(res.stdout)
        if align == 0:
            raise mesonlib.EnvironmentException('Could not determine alignment of %s. Sorry. You might want to file a bug.' % typename)
        return align

    def get_define(self, dname, prefix, env, extra_args, dependencies, disable_cache=False):
        delim = '"MESON_GET_DEFINE_DELIMITER"'
        fargs = {'prefix': prefix, 'define': dname, 'delim': delim}
        code = '''
        {prefix}
        #ifndef {define}
        # define {define}
        #endif
        {delim}\n{define}'''
        args = self._get_compiler_check_args(env, extra_args, dependencies,
                                             mode='preprocess').to_native()
        func = lambda: self.cached_compile(code.format(**fargs), env.coredata, extra_args=args, mode='preprocess')
        if disable_cache:
            func = lambda: self.compile(code.format(**fargs), extra_args=args, mode='preprocess', temp_dir=env.scratch_dir)
        with func() as p:
            cached = p.cached
            if p.returncode != 0:
                raise mesonlib.EnvironmentException('Could not get define {!r}'.format(dname))
        # Get the preprocessed value after the delimiter,
        # minus the extra newline at the end and
        # merge string literals.
        return self.concatenate_string_literals(p.stdo.split(delim + '\n')[-1][:-1]), cached

    def get_return_value(self, fname, rtype, prefix, env, extra_args, dependencies):
        if rtype == 'string':
            fmt = '%s'
            cast = '(char*)'
        elif rtype == 'int':
            fmt = '%lli'
            cast = '(long long int)'
        else:
            raise AssertionError('BUG: Unknown return type {!r}'.format(rtype))
        fargs = {'prefix': prefix, 'f': fname, 'cast': cast, 'fmt': fmt}
        code = '''{prefix}
        #include <stdio.h>
        int main(void) {{
            printf ("{fmt}", {cast} {f}());
            return 0;
        }}'''.format(**fargs)
        res = self.run(code, env, extra_args=extra_args, dependencies=dependencies)
        if not res.compiled:
            m = 'Could not get return value of {}()'
            raise mesonlib.EnvironmentException(m.format(fname))
        if rtype == 'string':
            return res.stdout
        elif rtype == 'int':
            try:
                return int(res.stdout.strip())
            except ValueError:
                m = 'Return value of {}() is not an int'
                raise mesonlib.EnvironmentException(m.format(fname))

    @staticmethod
    def _no_prototype_templ():
        """
        Try to find the function without a prototype from a header by defining
        our own dummy prototype and trying to link with the C library (and
        whatever else the compiler links in by default). This is very similar
        to the check performed by Autoconf for AC_CHECK_FUNCS.
        """
        # Define the symbol to something else since it is defined by the
        # includes or defines listed by the user or by the compiler. This may
        # include, for instance _GNU_SOURCE which must be defined before
        # limits.h, which includes features.h
        # Then, undef the symbol to get rid of it completely.
        head = '''
        #define {func} meson_disable_define_of_{func}
        {prefix}
        #include <limits.h>
        #undef {func}
        '''
        # Override any GCC internal prototype and declare our own definition for
        # the symbol. Use char because that's unlikely to be an actual return
        # value for a function which ensures that we override the definition.
        head += '''
        #ifdef __cplusplus
        extern "C"
        #endif
        char {func} (void);
        '''
        # The actual function call
        main = '''
        int main(void) {{
          return {func} ();
        }}'''
        return head, main

    @staticmethod
    def _have_prototype_templ():
        """
        Returns a head-er and main() call that uses the headers listed by the
        user for the function prototype while checking if a function exists.
        """
        # Add the 'prefix', aka defines, includes, etc that the user provides
        # This may include, for instance _GNU_SOURCE which must be defined
        # before limits.h, which includes features.h
        head = '{prefix}\n#include <limits.h>\n'
        # We don't know what the function takes or returns, so return it as an int.
        # Just taking the address or comparing it to void is not enough because
        # compilers are smart enough to optimize it away. The resulting binary
        # is not run so we don't care what the return value is.
        main = '''\nint main(void) {{
            void *a = (void*) &{func};
            long long b = (long long) a;
            return (int) b;
        }}'''
        return head, main

    def has_function(self, funcname, prefix, env, *, extra_args=None, dependencies=None):
        """
        First, this function looks for the symbol in the default libraries
        provided by the compiler (stdlib + a few others usually). If that
        fails, it checks if any of the headers specified in the prefix provide
        an implementation of the function, and if that fails, it checks if it's
        implemented as a compiler-builtin.
        """
        if extra_args is None:
            extra_args = []

        # Short-circuit if the check is already provided by the cross-info file
        varname = 'has function ' + funcname
        varname = varname.replace(' ', '_')
        if self.is_cross:
            val = env.properties.host.get(varname, None)
            if val is not None:
                if isinstance(val, bool):
                    return val, False
                raise mesonlib.EnvironmentException('Cross variable {0} is not a boolean.'.format(varname))

        fargs = {'prefix': prefix, 'func': funcname}

        # glibc defines functions that are not available on Linux as stubs that
        # fail with ENOSYS (such as e.g. lchmod). In this case we want to fail
        # instead of detecting the stub as a valid symbol.
        # We already included limits.h earlier to ensure that these are defined
        # for stub functions.
        stubs_fail = '''
        #if defined __stub_{func} || defined __stub___{func}
        fail fail fail this function is not going to work
        #endif
        '''

        # If we have any includes in the prefix supplied by the user, assume
        # that the user wants us to use the symbol prototype defined in those
        # includes. If not, then try to do the Autoconf-style check with
        # a dummy prototype definition of our own.
        # This is needed when the linker determines symbol availability from an
        # SDK based on the prototype in the header provided by the SDK.
        # Ignoring this prototype would result in the symbol always being
        # marked as available.
        if '#include' in prefix:
            head, main = self._have_prototype_templ()
        else:
            head, main = self._no_prototype_templ()
        templ = head + stubs_fail + main

        res, cached = self.links(templ.format(**fargs), env, extra_args=extra_args,
                                 dependencies=dependencies)
        if res:
            return True, cached

        # MSVC does not have compiler __builtin_-s.
        if self.get_id() in {'msvc', 'intel-cl'}:
            return False, False

        # Detect function as a built-in
        #
        # Some functions like alloca() are defined as compiler built-ins which
        # are inlined by the compiler and you can't take their address, so we
        # need to look for them differently. On nice compilers like clang, we
        # can just directly use the __has_builtin() macro.
        fargs['no_includes'] = '#include' not in prefix
        is_builtin = funcname.startswith('__builtin_')
        fargs['is_builtin'] = is_builtin
        fargs['__builtin_'] = '' if is_builtin else '__builtin_'
        t = '''{prefix}
        int main(void) {{

        /* With some toolchains (MSYS2/mingw for example) the compiler
         * provides various builtins which are not really implemented and
         * fall back to the stdlib where they aren't provided and fail at
         * build/link time. In case the user provides a header, including
         * the header didn't lead to the function being defined, and the
         * function we are checking isn't a builtin itself we assume the
         * builtin is not functional and we just error out. */
        #if !{no_includes:d} && !defined({func}) && !{is_builtin:d}
            #error "No definition for {__builtin_}{func} found in the prefix"
        #endif

        #ifdef __has_builtin
            #if !__has_builtin({__builtin_}{func})
                #error "{__builtin_}{func} not found"
            #endif
        #elif ! defined({func})
            {__builtin_}{func};
        #endif
        return 0;
        }}'''
        return self.links(t.format(**fargs), env, extra_args=extra_args,
                          dependencies=dependencies)

    def has_members(self, typename, membernames, prefix, env, *, extra_args=None, dependencies=None):
        if extra_args is None:
            extra_args = []
        fargs = {'prefix': prefix, 'type': typename, 'name': 'foo'}
        # Create code that accesses all members
        members = ''
        for member in membernames:
            members += '{}.{};\n'.format(fargs['name'], member)
        fargs['members'] = members
        t = '''{prefix}
        void bar(void) {{
            {type} {name};
            {members}
        }};'''
        return self.compiles(t.format(**fargs), env, extra_args=extra_args,
                             dependencies=dependencies)

    def has_type(self, typename, prefix, env, extra_args, dependencies=None):
        fargs = {'prefix': prefix, 'type': typename}
        t = '''{prefix}
        void bar(void) {{
            sizeof({type});
        }};'''
        return self.compiles(t.format(**fargs), env, extra_args=extra_args,
                             dependencies=dependencies)

    def symbols_have_underscore_prefix(self, env):
        '''
        Check if the compiler prefixes an underscore to global C symbols
        '''
        symbol_name = b'meson_uscore_prefix'
        code = '''#ifdef __cplusplus
        extern "C" {
        #endif
        void ''' + symbol_name.decode() + ''' (void) {}
        #ifdef __cplusplus
        }
        #endif
        '''
        args = self.get_compiler_check_args()
        n = 'symbols_have_underscore_prefix'
        with self._build_wrapper(code, env, extra_args=args, mode='compile', want_output=True, temp_dir=env.scratch_dir) as p:
            if p.returncode != 0:
                m = 'BUG: Unable to compile {!r} check: {}'
                raise RuntimeError(m.format(n, p.stdo))
            if not os.path.isfile(p.output_name):
                m = 'BUG: Can\'t find compiled test code for {!r} check'
                raise RuntimeError(m.format(n))
            with open(p.output_name, 'rb') as o:
                for line in o:
                    # Check if the underscore form of the symbol is somewhere
                    # in the output file.
                    if b'_' + symbol_name in line:
                        mlog.debug("Symbols have underscore prefix: YES")
                        return True
                    # Else, check if the non-underscored form is present
                    elif symbol_name in line:
                        mlog.debug("Symbols have underscore prefix: NO")
                        return False
        raise RuntimeError('BUG: {!r} check failed unexpectedly'.format(n))

    def _get_patterns(self, env, prefixes, suffixes, shared=False):
        patterns = []
        for p in prefixes:
            for s in suffixes:
                patterns.append(p + '{}.' + s)
        if shared and env.machines[self.for_machine].is_openbsd():
            # Shared libraries on OpenBSD can be named libfoo.so.X.Y:
            # https://www.openbsd.org/faq/ports/specialtopics.html#SharedLibs
            #
            # This globbing is probably the best matching we can do since regex
            # is expensive. It's wrong in many edge cases, but it will match
            # correctly-named libraries and hopefully no one on OpenBSD names
            # their files libfoo.so.9a.7b.1.0
            for p in prefixes:
                patterns.append(p + '{}.so.[0-9]*.[0-9]*')
        return patterns

    def get_library_naming(self, env, libtype: LibType, strict=False):
        '''
        Get library prefixes and suffixes for the target platform ordered by
        priority
        '''
        stlibext = ['a']
        # We've always allowed libname to be both `foo` and `libfoo`, and now
        # people depend on it. Also, some people use prebuilt `foo.so` instead
        # of `libfoo.so` for unknown reasons, and may also want to create
        # `foo.so` by setting name_prefix to ''
        if strict and not isinstance(self, VisualStudioLikeCompiler): # lib prefix is not usually used with msvc
            prefixes = ['lib']
        else:
            prefixes = ['lib', '']
        # Library suffixes and prefixes
        if env.machines[self.for_machine].is_darwin():
            shlibext = ['dylib', 'so']
        elif env.machines[self.for_machine].is_windows():
            # FIXME: .lib files can be import or static so we should read the
            # file, figure out which one it is, and reject the wrong kind.
            if isinstance(self, VisualStudioLikeCompiler):
                shlibext = ['lib']
            else:
                shlibext = ['dll.a', 'lib', 'dll']
            # Yep, static libraries can also be foo.lib
            stlibext += ['lib']
        elif env.machines[self.for_machine].is_cygwin():
            shlibext = ['dll', 'dll.a']
            prefixes = ['cyg'] + prefixes
        else:
            # Linux/BSDs
            shlibext = ['so']
        # Search priority
        if libtype is LibType.PREFER_SHARED:
            patterns = self._get_patterns(env, prefixes, shlibext, True)
            patterns.extend([x for x in self._get_patterns(env, prefixes, stlibext, False) if x not in patterns])
        elif libtype is LibType.PREFER_STATIC:
            patterns = self._get_patterns(env, prefixes, stlibext, False)
            patterns.extend([x for x in self._get_patterns(env, prefixes, shlibext, True) if x not in patterns])
        elif libtype is LibType.SHARED:
            patterns = self._get_patterns(env, prefixes, shlibext, True)
        else:
            assert libtype is LibType.STATIC
            patterns = self._get_patterns(env, prefixes, stlibext, False)
        return tuple(patterns)

    @staticmethod
    def _sort_shlibs_openbsd(libs):
        filtered = []
        for lib in libs:
            # Validate file as a shared library of type libfoo.so.X.Y
            ret = lib.rsplit('.so.', maxsplit=1)
            if len(ret) != 2:
                continue
            try:
                float(ret[1])
            except ValueError:
                continue
            filtered.append(lib)
        float_cmp = lambda x: float(x.rsplit('.so.', maxsplit=1)[1])
        return sorted(filtered, key=float_cmp, reverse=True)

    @classmethod
    def _get_trials_from_pattern(cls, pattern, directory, libname):
        f = Path(directory) / pattern.format(libname)
        # Globbing for OpenBSD
        if '*' in pattern:
            # NOTE: globbing matches directories and broken symlinks
            # so we have to do an isfile test on it later
            return [Path(x) for x in cls._sort_shlibs_openbsd(glob.glob(str(f)))]
        return [f]

    @staticmethod
    def _get_file_from_list(env, files: T.List[str]) -> Path:
        '''
        We just check whether the library exists. We can't do a link check
        because the library might have unresolved symbols that require other
        libraries. On macOS we check if the library matches our target
        architecture.
        '''
        # If not building on macOS for Darwin, do a simple file check
        paths = [Path(f) for f in files]
        if not env.machines.host.is_darwin() or not env.machines.build.is_darwin():
            for p in paths:
                if p.is_file():
                    return p
        # Run `lipo` and check if the library supports the arch we want
        for p in paths:
            if not p.is_file():
                continue
            archs = mesonlib.darwin_get_object_archs(str(p))
            if archs and env.machines.host.cpu_family in archs:
                return p
            else:
                mlog.debug('Rejected {}, supports {} but need {}'
                           .format(p, archs, env.machines.host.cpu_family))
        return None

    @functools.lru_cache()
    def output_is_64bit(self, env):
        '''
        returns true if the output produced is 64-bit, false if 32-bit
        '''
        return self.sizeof('void *', '', env) == 8

    def find_library_real(self, libname, env, extra_dirs, code, libtype: LibType):
        # First try if we can just add the library as -l.
        # Gcc + co seem to prefer builtin lib dirs to -L dirs.
        # Only try to find std libs if no extra dirs specified.
        # The built-in search procedure will always favour .so and then always
        # search for .a. This is only allowed if libtype is LibType.PREFER_SHARED
        if ((not extra_dirs and libtype is LibType.PREFER_SHARED) or
                libname in self.internal_libs):
            cargs = ['-l' + libname]
            largs = self.get_linker_always_args() + self.get_allow_undefined_link_args()
            extra_args = cargs + self.linker_to_compiler_args(largs)

            if self.links(code, env, extra_args=extra_args, disable_cache=True)[0]:
                return cargs
            # Don't do a manual search for internal libs
            if libname in self.internal_libs:
                return None
        # Not found or we want to use a specific libtype? Try to find the
        # library file itself.
        patterns = self.get_library_naming(env, libtype)
        # try to detect if we are 64-bit or 32-bit. If we can't
        # detect, we will just skip path validity checks done in
        # get_library_dirs() call
        try:
            if self.output_is_64bit(env):
                elf_class = 2
            else:
                elf_class = 1
        except (mesonlib.MesonException, KeyError): # TODO evaluate if catching KeyError is wanted here
            elf_class = 0
        # Search in the specified dirs, and then in the system libraries
        for d in itertools.chain(extra_dirs, self.get_library_dirs(env, elf_class)):
            for p in patterns:
                trial = self._get_trials_from_pattern(p, d, libname)
                if not trial:
                    continue
                trial = self._get_file_from_list(env, trial)
                if not trial:
                    continue
                return [trial.as_posix()]
        return None

    def find_library_impl(self, libname, env, extra_dirs, code, libtype: LibType):
        # These libraries are either built-in or invalid
        if libname in self.ignore_libs:
            return []
        if isinstance(extra_dirs, str):
            extra_dirs = [extra_dirs]
        key = (tuple(self.exelist), libname, tuple(extra_dirs), code, libtype)
        if key not in self.find_library_cache:
            value = self.find_library_real(libname, env, extra_dirs, code, libtype)
            self.find_library_cache[key] = value
        else:
            value = self.find_library_cache[key]
        if value is None:
            return None
        return value[:]

    def find_library(self, libname, env, extra_dirs, libtype: LibType = LibType.PREFER_SHARED):
        code = 'int main(void) { return 0; }\n'
        return self.find_library_impl(libname, env, extra_dirs, code, libtype)

    def find_framework_paths(self, env):
        '''
        These are usually /Library/Frameworks and /System/Library/Frameworks,
        unless you select a particular macOS SDK with the -isysroot flag.
        You can also add to this by setting -F in CFLAGS.
        '''
        if self.id != 'clang':
            raise mesonlib.MesonException('Cannot find framework path with non-clang compiler')
        # Construct the compiler command-line
        commands = self.get_exelist() + ['-v', '-E', '-']
        commands += self.get_always_args()
        # Add CFLAGS/CXXFLAGS/OBJCFLAGS/OBJCXXFLAGS from the env
        commands += env.coredata.get_external_args(self.for_machine, self.language)
        mlog.debug('Finding framework path by running: ', ' '.join(commands), '\n')
        os_env = os.environ.copy()
        os_env['LC_ALL'] = 'C'
        _, _, stde = mesonlib.Popen_safe(commands, env=os_env, stdin=subprocess.PIPE)
        paths = []
        for line in stde.split('\n'):
            if '(framework directory)' not in line:
                continue
            # line is of the form:
            # ` /path/to/framework (framework directory)`
            paths.append(line[:-21].strip())
        return paths

    def find_framework_real(self, name, env, extra_dirs, allow_system):
        code = 'int main(void) { return 0; }'
        link_args = []
        for d in extra_dirs:
            link_args += ['-F' + d]
        # We can pass -Z to disable searching in the system frameworks, but
        # then we must also pass -L/usr/lib to pick up libSystem.dylib
        extra_args = [] if allow_system else ['-Z', '-L/usr/lib']
        link_args += ['-framework', name]
        if self.links(code, env, extra_args=(extra_args + link_args), disable_cache=True)[0]:
            return link_args

    def find_framework_impl(self, name, env, extra_dirs, allow_system):
        if isinstance(extra_dirs, str):
            extra_dirs = [extra_dirs]
        key = (tuple(self.exelist), name, tuple(extra_dirs), allow_system)
        if key in self.find_framework_cache:
            value = self.find_framework_cache[key]
        else:
            value = self.find_framework_real(name, env, extra_dirs, allow_system)
            self.find_framework_cache[key] = value
        if value is None:
            return None
        return value[:]

    def find_framework(self, name, env, extra_dirs, allow_system=True):
        '''
        Finds the framework with the specified name, and returns link args for
        the same or returns None when the framework is not found.
        '''
        if self.id != 'clang':
            raise mesonlib.MesonException('Cannot find frameworks with non-clang compiler')
        return self.find_framework_impl(name, env, extra_dirs, allow_system)

    def get_crt_compile_args(self, crt_val: str, buildtype: str) -> T.List[str]:
        return []

    def get_crt_link_args(self, crt_val: str, buildtype: str) -> T.List[str]:
        return []

    def thread_flags(self, env):
        host_m = env.machines[self.for_machine]
        if host_m.is_haiku() or host_m.is_darwin():
            return []
        return ['-pthread']

    def thread_link_flags(self, env: 'Environment') -> T.List[str]:
        return self.linker.thread_flags(env)

    def linker_to_compiler_args(self, args):
        return args

    def has_arguments(self, args: T.Sequence[str], env, code: str, mode: str) -> T.Tuple[bool, bool]:
        return self.compiles(code, env, extra_args=args, mode=mode)

    def has_multi_arguments(self, args, env):
        for arg in args[:]:
            # some compilers, e.g. GCC, don't warn for unsupported warning-disable
            # flags, so when we are testing a flag like "-Wno-forgotten-towel", also
            # check the equivalent enable flag too "-Wforgotten-towel"
            if arg.startswith('-Wno-'):
                args.append('-W' + arg[5:])
            if arg.startswith('-Wl,'):
                mlog.warning('{} looks like a linker argument, '
                             'but has_argument and other similar methods only '
                             'support checking compiler arguments. Using them '
                             'to check linker arguments are never supported, '
                             'and results are likely to be wrong regardless of '
                             'the compiler you are using. has_link_argument or '
                             'other similar method can be used instead.'
                             .format(arg))
        code = 'extern int i;\nint i;\n'
        return self.has_arguments(args, env, code, mode='compile')

    def has_multi_link_arguments(self, args, env):
        # First time we check for link flags we need to first check if we have
        # --fatal-warnings, otherwise some linker checks could give some
        # false positive.
        args = self.linker.fatal_warnings() + args
        args = self.linker_to_compiler_args(args)
        code = 'int main(void) { return 0; }\n'
        return self.has_arguments(args, env, code, mode='link')

    @staticmethod
    def concatenate_string_literals(s):
        pattern = re.compile(r'(?P<pre>.*([^\\]")|^")(?P<str1>([^\\"]|\\.)*)"\s+"(?P<str2>([^\\"]|\\.)*)(?P<post>".*)')
        ret = s
        m = pattern.match(ret)
        while m:
            ret = ''.join(m.group('pre', 'str1', 'str2', 'post'))
            m = pattern.match(ret)
        return ret

    def get_has_func_attribute_extra_args(self, name):
        # Most compilers (such as GCC and Clang) only warn about unknown or
        # ignored attributes, so force an error. Overriden in GCC and Clang
        # mixins.
        return ['-Werror']

    def has_func_attribute(self, name, env):
        # Just assume that if we're not on windows that dllimport and dllexport
        # don't work
        m = env.machines[self.for_machine]
        if not (m.is_windows() or m.is_cygwin()):
            if name in ['dllimport', 'dllexport']:
                return False, False

        return self.compiles(self.attribute_check_func(name), env,
                             extra_args=self.get_has_func_attribute_extra_args(name))

    def get_disable_assert_args(self) -> T.List[str]:
        return ['-DNDEBUG']
