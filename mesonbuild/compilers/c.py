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

import re
import glob
import os.path
import subprocess
import functools
import itertools
from pathlib import Path
from typing import List

from .. import mlog
from .. import coredata
from . import compilers
from ..mesonlib import (
    EnvironmentException, MachineChoice, MesonException, Popen_safe, listify,
    version_compare, for_windows, for_darwin, for_cygwin, for_haiku,
    for_openbsd, darwin_get_object_archs, LibType
)
from .c_function_attributes import C_FUNC_ATTRIBUTES

from .compilers import (
    get_largefile_args,
    gnu_winlibs,
    msvc_winlibs,
    unixy_compiler_internal_libs,
    vs32_instruction_set_args,
    vs64_instruction_set_args,
    ArmCompiler,
    ArmclangCompiler,
    ClangCompiler,
    Compiler,
    CompilerArgs,
    CompilerType,
    CrossNoRunException,
    GnuCompiler,
    ElbrusCompiler,
    IntelCompiler,
    PGICompiler,
    RunResult,
    CcrxCompiler,
)


class CCompiler(Compiler):
    # TODO: Replace this manual cache with functools.lru_cache
    library_dirs_cache = {}
    program_dirs_cache = {}
    find_library_cache = {}
    find_framework_cache = {}
    internal_libs = unixy_compiler_internal_libs

    @staticmethod
    def attribute_check_func(name):
        try:
            return C_FUNC_ATTRIBUTES[name]
        except KeyError:
            raise MesonException('Unknown function attribute "{}"'.format(name))

    def __init__(self, exelist, version, is_cross, exe_wrapper=None, **kwargs):
        # If a child ObjC or CPP class has already set it, don't set it ourselves
        if not hasattr(self, 'language'):
            self.language = 'c'
        super().__init__(exelist, version, **kwargs)
        self.id = 'unknown'
        self.is_cross = is_cross
        self.can_compile_suffixes.add('h')
        # If the exe wrapper was not found, pretend it wasn't set so that the
        # sanity check is skipped and compiler checks use fallbacks.
        if not exe_wrapper or not exe_wrapper.found():
            self.exe_wrapper = None
        else:
            self.exe_wrapper = exe_wrapper.get_command()

        # Set to None until we actually need to check this
        self.has_fatal_warnings_link_arg = None

    def needs_static_linker(self):
        return True # When compiling static libraries, so yes.

    def get_always_args(self):
        '''
        Args that are always-on for all C compilers other than MSVC
        '''
        return ['-pipe'] + get_largefile_args(self)

    def get_linker_debug_crt_args(self):
        """
        Arguments needed to select a debug crt for the linker
        This is only needed for MSVC
        """
        return []

    def get_no_stdinc_args(self):
        return ['-nostdinc']

    def get_no_stdlib_link_args(self):
        return ['-nostdlib']

    def get_warn_args(self, level):
        return self.warn_args[level]

    def get_no_warn_args(self):
        # Almost every compiler uses this for disabling warnings
        return ['-w']

    def get_soname_args(self, *args):
        return []

    def split_shlib_to_parts(self, fname):
        return None, fname

    # The default behavior is this, override in MSVC
    @functools.lru_cache(maxsize=None)
    def build_rpath_args(self, build_dir, from_dir, rpath_paths, build_rpath, install_rpath):
        if self.compiler_type.is_windows_compiler:
            return []
        return self.build_unix_rpath_args(build_dir, from_dir, rpath_paths, build_rpath, install_rpath)

    def get_dependency_gen_args(self, outtarget, outfile):
        return ['-MD', '-MQ', outtarget, '-MF', outfile]

    def depfile_for_object(self, objfile):
        return objfile + '.' + self.get_depfile_suffix()

    def get_depfile_suffix(self):
        return 'd'

    def get_exelist(self):
        return self.exelist[:]

    def get_linker_exelist(self):
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

    def get_linker_output_args(self, outputname):
        return ['-o', outputname]

    def get_coverage_args(self):
        return ['--coverage']

    def get_coverage_link_args(self):
        return ['--coverage']

    def get_werror_args(self):
        return ['-Werror']

    def get_std_exe_link_args(self):
        return []

    def get_include_args(self, path, is_system):
        if path == '':
            path = '.'
        if is_system:
            return ['-isystem', path]
        return ['-I' + path]

    def get_std_shared_lib_link_args(self):
        return ['-shared']

    @functools.lru_cache()
    def _get_search_dirs(self, env):
        extra_args = ['--print-search-dirs']
        stdo = None
        with self._build_wrapper('', env, extra_args=extra_args,
                                 dependencies=None, mode='compile',
                                 want_output=True) as p:
            stdo = p.stdo
        return stdo

    @staticmethod
    def _split_fetch_real_dirs(pathstr, sep=':'):
        paths = []
        for p in pathstr.split(sep):
            # GCC returns paths like this:
            # /usr/lib/gcc/x86_64-linux-gnu/8/../../../../x86_64-linux-gnu/lib
            # It would make sense to normalize them to get rid of the .. parts
            # Sadly when you are on a merged /usr fs it also kills these:
            # /lib/x86_64-linux-gnu
            # since /lib is a symlink to /usr/lib. This would mean
            # paths under /lib would be considered not a "system path",
            # which is wrong and breaks things. Store everything, just to be sure.
            pobj = Path(p)
            unresolved = pobj.as_posix()
            if pobj.exists():
                if unresolved not in paths:
                    paths.append(unresolved)
                try:
                    resolved = Path(p).resolve().as_posix()
                    if resolved not in paths:
                        paths.append(resolved)
                except FileNotFoundError:
                    pass
        return tuple(paths)

    def get_compiler_dirs(self, env, name):
        '''
        Get dirs from the compiler, either `libraries:` or `programs:`
        '''
        stdo = self._get_search_dirs(env)
        for line in stdo.split('\n'):
            if line.startswith(name + ':'):
                return CCompiler._split_fetch_real_dirs(line.split('=', 1)[1])
        return ()

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
            if len(files) == 0:
                retval.append(d)
                continue
            file_to_check = os.path.join(d, files[0])
            with open(file_to_check, 'rb') as fd:
                header = fd.read(5)
                # if file is not an ELF file, it's weird, but accept dir
                # if it is elf, and the class matches, accept dir
                if header[1:4] != b'ELF' or int(header[4]) == elf_class:
                    retval.append(d)
                # at this point, it's an ELF file which doesn't match the
                # appropriate elf_class, so skip this one
                pass
        return tuple(retval)

    @functools.lru_cache()
    def get_program_dirs(self, env):
        '''
        Programs used by the compiler. Also where toolchain DLLs such as
        libstdc++-6.dll are found with MinGW.
        '''
        return self.get_compiler_dirs(env, 'programs')

    def get_pic_args(self):
        return ['-fPIC']

    def name_string(self):
        return ' '.join(self.exelist)

    def get_pch_use_args(self, pch_dir, header):
        return ['-include', os.path.basename(header)]

    def get_pch_name(self, header_name):
        return os.path.basename(header_name) + '.' + self.get_pch_suffix()

    def get_linker_search_args(self, dirname):
        return ['-L' + dirname]

    def get_default_include_dirs(self):
        return []

    def gen_export_dynamic_link_args(self, env):
        if for_windows(env.is_cross_build(), env) or for_cygwin(env.is_cross_build(), env):
            return ['-Wl,--export-all-symbols']
        elif for_darwin(env.is_cross_build(), env):
            return []
        else:
            return ['-Wl,-export-dynamic']

    def gen_import_library_args(self, implibname):
        """
        The name of the outputted import library

        This implementation is used only on Windows by compilers that use GNU ld
        """
        return ['-Wl,--out-implib=' + implibname]

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
        extra_flags = self._get_basic_compiler_args(environment, mode)

        # Is a valid executable output for all toolchains and platforms
        binname += '.exe'
        # Write binary check source
        binary_name = os.path.join(work_dir, binname)
        with open(source_name, 'w') as ofile:
            ofile.write(code)
        # Compile sanity check
        cmdlist = self.exelist + extra_flags + [source_name] + self.get_output_args(binary_name)
        pc, stdo, stde = Popen_safe(cmdlist, cwd=work_dir)
        mlog.debug('Sanity check compiler command line:', ' '.join(cmdlist))
        mlog.debug('Sanity check compile stdout:')
        mlog.debug(stdo)
        mlog.debug('-----\nSanity check compile stderr:')
        mlog.debug(stde)
        mlog.debug('-----')
        if pc.returncode != 0:
            raise EnvironmentException('Compiler {0} can not compile programs.'.format(self.name_string()))
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
            raise EnvironmentException('Could not invoke sanity test executable: %s.' % str(e))
        pe.wait()
        if pe.returncode != 0:
            raise EnvironmentException('Executables created by {0} compiler {1} are not runnable.'.format(self.language, self.name_string()))

    def sanity_check(self, work_dir, environment):
        code = 'int main(int argc, char **argv) { int class=0; return class; }\n'
        return self.sanity_check_impl(work_dir, environment, 'sanitycheckc.c', code)

    def check_header(self, hname, prefix, env, *, extra_args=None, dependencies=None):
        fargs = {'prefix': prefix, 'header': hname}
        code = '''{prefix}
        #include <{header}>'''
        return self.compiles(code.format(**fargs), env, extra_args=extra_args,
                             dependencies=dependencies)

    def has_header(self, hname, prefix, env, *, extra_args=None, dependencies=None):
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
                             dependencies=dependencies, mode='preprocess')

    def has_header_symbol(self, hname, symbol, prefix, env, *, extra_args=None, dependencies=None):
        fargs = {'prefix': prefix, 'header': hname, 'symbol': symbol}
        t = '''{prefix}
        #include <{header}>
        int main () {{
            /* If it's not defined as a macro, try to use as a symbol */
            #ifndef {symbol}
                {symbol};
            #endif
            return 0;
        }}'''
        return self.compiles(t.format(**fargs), env, extra_args=extra_args,
                             dependencies=dependencies)

    def _get_basic_compiler_args(self, env, mode):
        args = []
        # Select a CRT if needed since we're linking
        if mode == 'link':
            args += self.get_linker_debug_crt_args()
        if env.is_cross_build() and not self.is_cross:
            for_machine = MachineChoice.BUILD
        else:
            for_machine = MachineChoice.HOST
        if mode in {'compile', 'preprocess'}:
            # Add CFLAGS/CXXFLAGS/OBJCFLAGS/OBJCXXFLAGS and CPPFLAGS from the env
            sys_args = env.coredata.get_external_args(for_machine, self.language)
            # Apparently it is a thing to inject linker flags both
            # via CFLAGS _and_ LDFLAGS, even though the former are
            # also used during linking. These flags can break
            # argument checks. Thanks, Autotools.
            cleaned_sys_args = self.remove_linkerlike_args(sys_args)
            args += cleaned_sys_args
        elif mode == 'link':
            # Add LDFLAGS from the env
            args += env.coredata.get_external_link_args(for_machine, self.language)
        return args

    def _get_compiler_check_args(self, env, extra_args, dependencies, mode='compile'):
        if extra_args is None:
            extra_args = []
        else:
            extra_args = listify(extra_args)
        extra_args = listify([e(mode) if callable(e) else e for e in extra_args])

        if dependencies is None:
            dependencies = []
        elif not isinstance(dependencies, list):
            dependencies = [dependencies]
        # Collect compiler arguments
        args = CompilerArgs(self)
        for d in dependencies:
            # Add compile flags needed by dependencies
            args += d.get_compile_args()
            if mode == 'link':
                # Add link flags needed to find dependencies
                args += d.get_link_args()

        args += self._get_basic_compiler_args(env, mode)

        args += self.get_compiler_check_args()
        # extra_args must override all other arguments, so we add them last
        args += extra_args
        return args

    def compiles(self, code, env, *, extra_args=None, dependencies=None, mode='compile'):
        with self._build_wrapper(code, env, extra_args, dependencies, mode) as p:
            return p.returncode == 0

    def _build_wrapper(self, code, env, extra_args, dependencies=None, mode='compile', want_output=False):
        args = self._get_compiler_check_args(env, extra_args, dependencies, mode)
        return self.compile(code, args, mode, want_output=want_output)

    def links(self, code, env, *, extra_args=None, dependencies=None):
        return self.compiles(code, env, extra_args=extra_args,
                             dependencies=dependencies, mode='link')

    def run(self, code: str, env, *, extra_args=None, dependencies=None):
        if self.is_cross and self.exe_wrapper is None:
            raise CrossNoRunException('Can not run test applications in this cross environment.')
        with self._build_wrapper(code, env, extra_args, dependencies, mode='link', want_output=True) as p:
            if p.returncode != 0:
                mlog.debug('Could not compile test file %s: %d\n' % (
                    p.input_name,
                    p.returncode))
                return RunResult(False)
            if self.is_cross:
                cmdlist = self.exe_wrapper + [p.output_name]
            else:
                cmdlist = p.output_name
            try:
                pe, so, se = Popen_safe(cmdlist)
            except Exception as e:
                mlog.debug('Could not run: %s (error: %s)\n' % (cmdlist, e))
                return RunResult(False)

        mlog.debug('Program stdout:\n')
        mlog.debug(so)
        mlog.debug('Program stderr:\n')
        mlog.debug(se)
        return RunResult(True, pe.returncode, so, se)

    def _compile_int(self, expression, prefix, env, extra_args, dependencies):
        fargs = {'prefix': prefix, 'expression': expression}
        t = '''#include <stdio.h>
        {prefix}
        int main() {{ static int a[1-2*!({expression})]; a[0]=0; return 0; }}'''
        return self.compiles(t.format(**fargs), env, extra_args=extra_args,
                             dependencies=dependencies)

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
                        raise EnvironmentException('Cross-compile check overflowed')
                    cur = cur * 2 + 1
                    if cur > maxint:
                        cur = maxint
                high = cur
            else:
                low = cur = -1
                while self._compile_int('%s < %d' % (expression, cur), prefix, env, extra_args, dependencies):
                    high = cur - 1
                    if high < minint:
                        raise EnvironmentException('Cross-compile check overflowed')
                    cur = cur * 2
                    if cur < minint:
                        cur = minint
                low = cur
        else:
            # Sanity check limits given by user
            if high < low:
                raise EnvironmentException('high limit smaller than low limit')
            condition = '%s <= %d && %s >= %d' % (expression, high, expression, low)
            if not self._compile_int(condition, prefix, env, extra_args, dependencies):
                raise EnvironmentException('Value out of given range')

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
        int main(int argc, char **argv) {{
            printf("%ld\\n", (long)({expression}));
            return 0;
        }};'''
        res = self.run(t.format(**fargs), env, extra_args=extra_args,
                       dependencies=dependencies)
        if not res.compiled:
            return -1
        if res.returncode != 0:
            raise EnvironmentException('Could not run compute_int test binary.')
        return int(res.stdout)

    def cross_sizeof(self, typename, prefix, env, *, extra_args=None, dependencies=None):
        if extra_args is None:
            extra_args = []
        fargs = {'prefix': prefix, 'type': typename}
        t = '''#include <stdio.h>
        {prefix}
        int main(int argc, char **argv) {{
            {type} something;
            return 0;
        }}'''
        if not self.compiles(t.format(**fargs), env, extra_args=extra_args,
                             dependencies=dependencies):
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
        int main(int argc, char **argv) {{
            printf("%ld\\n", (long)(sizeof({type})));
            return 0;
        }};'''
        res = self.run(t.format(**fargs), env, extra_args=extra_args,
                       dependencies=dependencies)
        if not res.compiled:
            return -1
        if res.returncode != 0:
            raise EnvironmentException('Could not run sizeof test binary.')
        return int(res.stdout)

    def cross_alignment(self, typename, prefix, env, *, extra_args=None, dependencies=None):
        if extra_args is None:
            extra_args = []
        fargs = {'prefix': prefix, 'type': typename}
        t = '''#include <stdio.h>
        {prefix}
        int main(int argc, char **argv) {{
            {type} something;
            return 0;
        }}'''
        if not self.compiles(t.format(**fargs), env, extra_args=extra_args,
                             dependencies=dependencies):
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
        int main(int argc, char **argv) {{
            printf("%d", (int)offsetof(struct tmp, target));
            return 0;
        }}'''
        res = self.run(t.format(**fargs), env, extra_args=extra_args,
                       dependencies=dependencies)
        if not res.compiled:
            raise EnvironmentException('Could not compile alignment test.')
        if res.returncode != 0:
            raise EnvironmentException('Could not run alignment test binary.')
        align = int(res.stdout)
        if align == 0:
            raise EnvironmentException('Could not determine alignment of %s. Sorry. You might want to file a bug.' % typename)
        return align

    def get_define(self, dname, prefix, env, extra_args, dependencies):
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
        with self.compile(code.format(**fargs), args, 'preprocess') as p:
            if p.returncode != 0:
                raise EnvironmentException('Could not get define {!r}'.format(dname))
        # Get the preprocessed value after the delimiter,
        # minus the extra newline at the end and
        # merge string literals.
        return CCompiler.concatenate_string_literals(p.stdo.split(delim + '\n')[-1][:-1])

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
        int main(int argc, char *argv[]) {{
            printf ("{fmt}", {cast} {f}());
            return 0;
        }}'''.format(**fargs)
        res = self.run(code, env, extra_args=extra_args, dependencies=dependencies)
        if not res.compiled:
            m = 'Could not get return value of {}()'
            raise EnvironmentException(m.format(fname))
        if rtype == 'string':
            return res.stdout
        elif rtype == 'int':
            try:
                return int(res.stdout.strip())
            except ValueError:
                m = 'Return value of {}() is not an int'
                raise EnvironmentException(m.format(fname))

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
        char {func} ();
        '''
        # The actual function call
        main = '''
        int main () {{
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
        main = '''\nint main() {{
            void *a = (void*) &{func};
            long b = (long) a;
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
                    return val
                raise EnvironmentException('Cross variable {0} is not a boolean.'.format(varname))

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

        if self.links(templ.format(**fargs), env, extra_args=extra_args,
                      dependencies=dependencies):
            return True

        # MSVC does not have compiler __builtin_-s.
        if self.get_id() == 'msvc':
            return False

        # Detect function as a built-in
        #
        # Some functions like alloca() are defined as compiler built-ins which
        # are inlined by the compiler and you can't take their address, so we
        # need to look for them differently. On nice compilers like clang, we
        # can just directly use the __has_builtin() macro.
        fargs['no_includes'] = '#include' not in prefix
        t = '''{prefix}
        int main() {{
        #ifdef __has_builtin
            #if !__has_builtin(__builtin_{func})
                #error "__builtin_{func} not found"
            #endif
        #elif ! defined({func})
            /* Check for __builtin_{func} only if no includes were added to the
             * prefix above, which means no definition of {func} can be found.
             * We would always check for this, but we get false positives on
             * MSYS2 if we do. Their toolchain is broken, but we can at least
             * give them a workaround. */
            #if {no_includes:d}
                __builtin_{func};
            #else
                #error "No definition for __builtin_{func} found in the prefix"
            #endif
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
        void bar() {{
            {type} {name};
            {members}
        }};'''
        return self.compiles(t.format(**fargs), env, extra_args=extra_args,
                             dependencies=dependencies)

    def has_type(self, typename, prefix, env, extra_args, dependencies=None):
        fargs = {'prefix': prefix, 'type': typename}
        t = '''{prefix}
        void bar() {{
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
        void ''' + symbol_name.decode() + ''' () {}
        #ifdef __cplusplus
        }
        #endif
        '''
        args = self.get_compiler_check_args()
        n = 'symbols_have_underscore_prefix'
        with self.compile(code, args, 'compile', want_output=True) as p:
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
                        return True
                    # Else, check if the non-underscored form is present
                    elif symbol_name in line:
                        return False
        raise RuntimeError('BUG: {!r} check failed unexpectedly'.format(n))

    def _get_patterns(self, env, prefixes, suffixes, shared=False):
        patterns = []
        for p in prefixes:
            for s in suffixes:
                patterns.append(p + '{}.' + s)
        if shared and for_openbsd(self.is_cross, env):
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
        if strict and not isinstance(self, VisualStudioCCompiler): # lib prefix is not usually used with msvc
            prefixes = ['lib']
        else:
            prefixes = ['lib', '']
        # Library suffixes and prefixes
        if for_darwin(env.is_cross_build(), env):
            shlibext = ['dylib', 'so']
        elif for_windows(env.is_cross_build(), env):
            # FIXME: .lib files can be import or static so we should read the
            # file, figure out which one it is, and reject the wrong kind.
            if isinstance(self, VisualStudioCCompiler):
                shlibext = ['lib']
            else:
                shlibext = ['dll.a', 'lib', 'dll']
            # Yep, static libraries can also be foo.lib
            stlibext += ['lib']
        elif for_cygwin(env.is_cross_build(), env):
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
    def _get_file_from_list(env, files: List[str]) -> Path:
        '''
        We just check whether the library exists. We can't do a link check
        because the library might have unresolved symbols that require other
        libraries. On macOS we check if the library matches our target
        architecture.
        '''
        # If not building on macOS for Darwin, do a simple file check
        files = [Path(f) for f in files]
        if not env.machines.host.is_darwin() or not env.machines.build.is_darwin():
            for f in files:
                if f.is_file():
                    return f
        # Run `lipo` and check if the library supports the arch we want
        for f in files:
            if not f.is_file():
                continue
            archs = darwin_get_object_archs(f)
            if archs and env.machines.host.cpu_family in archs:
                return f
            else:
                mlog.debug('Rejected {}, supports {} but need {}'
                           .format(f, archs, env.machines.host.cpu_family))
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
            args = ['-l' + libname]
            largs = self.linker_to_compiler_args(self.get_allow_undefined_link_args())
            if self.links(code, env, extra_args=(args + largs)):
                return args
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
        except:
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
        code = 'int main(int argc, char **argv) { return 0; }'
        return self.find_library_impl(libname, env, extra_dirs, code, libtype)

    def find_framework_paths(self, env):
        '''
        These are usually /Library/Frameworks and /System/Library/Frameworks,
        unless you select a particular macOS SDK with the -isysroot flag.
        You can also add to this by setting -F in CFLAGS.
        '''
        if self.id != 'clang':
            raise MesonException('Cannot find framework path with non-clang compiler')
        # Construct the compiler command-line
        commands = self.get_exelist() + ['-v', '-E', '-']
        commands += self.get_always_args()
        # Add CFLAGS/CXXFLAGS/OBJCFLAGS/OBJCXXFLAGS from the env
        if env.is_cross_build() and not self.is_cross:
            for_machine = MachineChoice.BUILD
        else:
            for_machine = MachineChoice.HOST
        commands += env.coredata.get_external_args(for_machine, self.language)
        mlog.debug('Finding framework path by running: ', ' '.join(commands), '\n')
        os_env = os.environ.copy()
        os_env['LC_ALL'] = 'C'
        _, _, stde = Popen_safe(commands, env=os_env, stdin=subprocess.PIPE)
        paths = []
        for line in stde.split('\n'):
            if '(framework directory)' not in line:
                continue
            # line is of the form:
            # ` /path/to/framework (framework directory)`
            paths.append(line[:-21].strip())
        return paths

    def find_framework_real(self, name, env, extra_dirs, allow_system):
        code = 'int main(int argc, char **argv) { return 0; }'
        link_args = []
        for d in extra_dirs:
            link_args += ['-F' + d]
        # We can pass -Z to disable searching in the system frameworks, but
        # then we must also pass -L/usr/lib to pick up libSystem.dylib
        extra_args = [] if allow_system else ['-Z', '-L/usr/lib']
        link_args += ['-framework', name]
        if self.links(code, env, extra_args=(extra_args + link_args)):
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
            raise MesonException('Cannot find frameworks with non-clang compiler')
        return self.find_framework_impl(name, env, extra_dirs, allow_system)

    def thread_flags(self, env):
        if for_haiku(self.is_cross, env) or for_darwin(self.is_cross, env):
            return []
        return ['-pthread']

    def thread_link_flags(self, env):
        if for_haiku(self.is_cross, env) or for_darwin(self.is_cross, env):
            return []
        return ['-pthread']

    def linker_to_compiler_args(self, args):
        return args

    def has_arguments(self, args, env, code, mode):
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
        code = 'int i;\n'
        return self.has_arguments(args, env, code, mode='compile')

    def has_multi_link_arguments(self, args, env):
        # First time we check for link flags we need to first check if we have
        # --fatal-warnings, otherwise some linker checks could give some
        # false positive.
        fatal_warnings_args = ['-Wl,--fatal-warnings']
        if self.has_fatal_warnings_link_arg is None:
            self.has_fatal_warnings_link_arg = False
            self.has_fatal_warnings_link_arg = self.has_multi_link_arguments(fatal_warnings_args, env)

        if self.has_fatal_warnings_link_arg:
            args = fatal_warnings_args + args

        args = self.linker_to_compiler_args(args)
        code = 'int main(int argc, char **argv) { return 0; }'
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

    def has_func_attribute(self, name, env):
        # Just assume that if we're not on windows that dllimport and dllexport
        # don't work
        if not (for_windows(env.is_cross_build(), env) or
                for_cygwin(env.is_cross_build(), env)):
            if name in ['dllimport', 'dllexport']:
                return False

        # Clang and GCC both return warnings if the __attribute__ is undefined,
        # so set -Werror
        return self.compiles(self.attribute_check_func(name), env, extra_args='-Werror')


class ClangCCompiler(ClangCompiler, CCompiler):
    def __init__(self, exelist, version, compiler_type, is_cross, exe_wrapper=None, **kwargs):
        CCompiler.__init__(self, exelist, version, is_cross, exe_wrapper, **kwargs)
        ClangCompiler.__init__(self, compiler_type)
        default_warn_args = ['-Wall', '-Winvalid-pch']
        self.warn_args = {'0': [],
                          '1': default_warn_args,
                          '2': default_warn_args + ['-Wextra'],
                          '3': default_warn_args + ['-Wextra', '-Wpedantic']}

    def get_options(self):
        opts = CCompiler.get_options(self)
        c_stds = ['c89', 'c99', 'c11']
        g_stds = ['gnu89', 'gnu99', 'gnu11']
        if self.compiler_type is CompilerType.CLANG_OSX:
            v = '>=10.0.0'
        else:
            v = '>=7.0.0'
        if version_compare(self.version, v):
            c_stds += ['c17']
            g_stds += ['gnu17']
        opts.update({'c_std': coredata.UserComboOption('c_std', 'C language standard to use',
                                                       ['none'] + c_stds + g_stds,
                                                       'none')})
        return opts

    def get_option_compile_args(self, options):
        args = []
        std = options['c_std']
        if std.value != 'none':
            args.append('-std=' + std.value)
        return args

    def get_option_link_args(self, options):
        return []

    def get_linker_always_args(self):
        basic = super().get_linker_always_args()
        if self.compiler_type.is_osx_compiler:
            return basic + ['-Wl,-headerpad_max_install_names']
        return basic


class ArmclangCCompiler(ArmclangCompiler, CCompiler):
    def __init__(self, exelist, version, compiler_type, is_cross, exe_wrapper=None, **kwargs):
        CCompiler.__init__(self, exelist, version, is_cross, exe_wrapper, **kwargs)
        ArmclangCompiler.__init__(self, compiler_type)
        default_warn_args = ['-Wall', '-Winvalid-pch']
        self.warn_args = {'0': [],
                          '1': default_warn_args,
                          '2': default_warn_args + ['-Wextra'],
                          '3': default_warn_args + ['-Wextra', '-Wpedantic']}

    def get_options(self):
        opts = CCompiler.get_options(self)
        opts.update({'c_std': coredata.UserComboOption('c_std', 'C language standard to use',
                                                       ['none', 'c90', 'c99', 'c11',
                                                        'gnu90', 'gnu99', 'gnu11'],
                                                       'none')})
        return opts

    def get_option_compile_args(self, options):
        args = []
        std = options['c_std']
        if std.value != 'none':
            args.append('-std=' + std.value)
        return args

    def get_option_link_args(self, options):
        return []


class GnuCCompiler(GnuCompiler, CCompiler):
    def __init__(self, exelist, version, compiler_type, is_cross, exe_wrapper=None, defines=None, **kwargs):
        CCompiler.__init__(self, exelist, version, is_cross, exe_wrapper, **kwargs)
        GnuCompiler.__init__(self, compiler_type, defines)
        default_warn_args = ['-Wall', '-Winvalid-pch']
        self.warn_args = {'0': [],
                          '1': default_warn_args,
                          '2': default_warn_args + ['-Wextra'],
                          '3': default_warn_args + ['-Wextra', '-Wpedantic']}

    def get_options(self):
        opts = CCompiler.get_options(self)
        c_stds = ['c89', 'c99', 'c11']
        g_stds = ['gnu89', 'gnu99', 'gnu11']
        v = '>=8.0.0'
        if version_compare(self.version, v):
            c_stds += ['c17', 'c18']
            g_stds += ['gnu17', 'gnu18']
        opts.update({'c_std': coredata.UserComboOption('c_std', 'C language standard to use',
                                                       ['none'] + c_stds + g_stds,
                                                       'none')})
        if self.compiler_type.is_windows_compiler:
            opts.update({
                'c_winlibs': coredata.UserArrayOption('c_winlibs', 'Standard Win libraries to link against',
                                                      gnu_winlibs), })
        return opts

    def get_option_compile_args(self, options):
        args = []
        std = options['c_std']
        if std.value != 'none':
            args.append('-std=' + std.value)
        return args

    def get_option_link_args(self, options):
        if self.compiler_type.is_windows_compiler:
            return options['c_winlibs'].value[:]
        return []

    def get_pch_use_args(self, pch_dir, header):
        return ['-fpch-preprocess', '-include', os.path.basename(header)]


class PGICCompiler(PGICompiler, CCompiler):
    def __init__(self, exelist, version, is_cross, exe_wrapper=None, **kwargs):
        CCompiler.__init__(self, exelist, version, is_cross, exe_wrapper, **kwargs)
        PGICompiler.__init__(self, CompilerType.PGI_STANDARD)


class ElbrusCCompiler(GnuCCompiler, ElbrusCompiler):
    def __init__(self, exelist, version, compiler_type, is_cross, exe_wrapper=None, defines=None, **kwargs):
        GnuCCompiler.__init__(self, exelist, version, compiler_type, is_cross, exe_wrapper, defines, **kwargs)
        ElbrusCompiler.__init__(self, compiler_type, defines)

    # It does support some various ISO standards and c/gnu 90, 9x, 1x in addition to those which GNU CC supports.
    def get_options(self):
        opts = CCompiler.get_options(self)
        opts.update({'c_std': coredata.UserComboOption('c_std', 'C language standard to use',
                                                       ['none', 'c89', 'c90', 'c9x', 'c99', 'c1x', 'c11',
                                                        'gnu89', 'gnu90', 'gnu9x', 'gnu99', 'gnu1x', 'gnu11',
                                                        'iso9899:2011', 'iso9899:1990', 'iso9899:199409', 'iso9899:1999'],
                                                       'none')})
        return opts

    # Elbrus C compiler does not have lchmod, but there is only linker warning, not compiler error.
    # So we should explicitly fail at this case.
    def has_function(self, funcname, prefix, env, *, extra_args=None, dependencies=None):
        if funcname == 'lchmod':
            return False
        else:
            return super().has_function(funcname, prefix, env,
                                        extra_args=extra_args,
                                        dependencies=dependencies)


class IntelCCompiler(IntelCompiler, CCompiler):
    def __init__(self, exelist, version, compiler_type, is_cross, exe_wrapper=None, **kwargs):
        CCompiler.__init__(self, exelist, version, is_cross, exe_wrapper, **kwargs)
        IntelCompiler.__init__(self, compiler_type)
        self.lang_header = 'c-header'
        default_warn_args = ['-Wall', '-w3', '-diag-disable:remark']
        self.warn_args = {'0': [],
                          '1': default_warn_args,
                          '2': default_warn_args + ['-Wextra'],
                          '3': default_warn_args + ['-Wextra']}

    def get_options(self):
        opts = CCompiler.get_options(self)
        c_stds = ['c89', 'c99']
        g_stds = ['gnu89', 'gnu99']
        if version_compare(self.version, '>=16.0.0'):
            c_stds += ['c11']
        opts.update({'c_std': coredata.UserComboOption('c_std', 'C language standard to use',
                                                       ['none'] + c_stds + g_stds,
                                                       'none')})
        return opts

    def get_option_compile_args(self, options):
        args = []
        std = options['c_std']
        if std.value != 'none':
            args.append('-std=' + std.value)
        return args


class VisualStudioCCompiler(CCompiler):
    std_warn_args = ['/W3']
    std_opt_args = ['/O2']
    ignore_libs = unixy_compiler_internal_libs
    internal_libs = ()

    crt_args = {'none': [],
                'md': ['/MD'],
                'mdd': ['/MDd'],
                'mt': ['/MT'],
                'mtd': ['/MTd'],
                }

    def __init__(self, exelist, version, is_cross, exe_wrap, target):
        CCompiler.__init__(self, exelist, version, is_cross, exe_wrap)
        self.id = 'msvc'
        # /showIncludes is needed for build dependency tracking in Ninja
        # See: https://ninja-build.org/manual.html#_deps
        self.always_args = ['/nologo', '/showIncludes']
        self.warn_args = {'0': ['/W1'],
                          '1': ['/W2'],
                          '2': ['/W3'],
                          '3': ['/W4']}
        self.base_options = ['b_pch', 'b_ndebug', 'b_vscrt'] # FIXME add lto, pgo and the like
        self.target = target
        self.is_64 = ('x64' in target) or ('x86_64' in target)
        # do some canonicalization of target machine
        if 'x86_64' in target:
            self.machine = 'x64'
        elif '86' in target:
            self.machine = 'x86'
        else:
            self.machine = target

    # Override CCompiler.get_always_args
    def get_always_args(self):
        return self.always_args

    def get_linker_debug_crt_args(self):
        """
        Arguments needed to select a debug crt for the linker

        Sometimes we need to manually select the CRT (C runtime) to use with
        MSVC. One example is when trying to link with static libraries since
        MSVC won't auto-select a CRT for us in that case and will error out
        asking us to select one.
        """
        return ['/MDd']

    def get_buildtype_args(self, buildtype):
        args = compilers.msvc_buildtype_args[buildtype]
        if self.id == 'msvc' and version_compare(self.version, '<18.0'):
            args = [arg for arg in args if arg != '/Gw']
        return args

    def get_buildtype_linker_args(self, buildtype):
        return compilers.msvc_buildtype_linker_args[buildtype]

    def get_pch_suffix(self):
        return 'pch'

    def get_pch_name(self, header):
        chopped = os.path.basename(header).split('.')[:-1]
        chopped.append(self.get_pch_suffix())
        pchname = '.'.join(chopped)
        return pchname

    def get_pch_use_args(self, pch_dir, header):
        base = os.path.basename(header)
        if self.id == 'clang-cl':
            base = header
        pchname = self.get_pch_name(header)
        return ['/FI' + base, '/Yu' + base, '/Fp' + os.path.join(pch_dir, pchname)]

    def get_preprocess_only_args(self):
        return ['/EP']

    def get_compile_only_args(self):
        return ['/c']

    def get_no_optimization_args(self):
        return ['/Od']

    def get_output_args(self, target):
        if target.endswith('.exe'):
            return ['/Fe' + target]
        return ['/Fo' + target]

    def get_optimization_args(self, optimization_level):
        return compilers.msvc_optimization_args[optimization_level]

    def get_debug_args(self, is_debug):
        return compilers.msvc_debug_args[is_debug]

    def get_dependency_gen_args(self, outtarget, outfile):
        return []

    def get_linker_exelist(self):
        # FIXME, should have same path as compiler.
        # FIXME, should be controllable via cross-file.
        if self.id == 'clang-cl':
            return ['lld-link']
        else:
            return ['link']

    def get_linker_always_args(self):
        return ['/nologo']

    def get_linker_output_args(self, outputname):
        return ['/MACHINE:' + self.machine, '/OUT:' + outputname]

    def get_linker_search_args(self, dirname):
        return ['/LIBPATH:' + dirname]

    def linker_to_compiler_args(self, args):
        return ['/link'] + args

    def get_gui_app_args(self, value):
        # the default is for the linker to guess the subsystem based on presence
        # of main or WinMain symbols, so always be explicit
        if value:
            return ['/SUBSYSTEM:WINDOWS']
        else:
            return ['/SUBSYSTEM:CONSOLE']

    def get_pic_args(self):
        return [] # PIC is handled by the loader on Windows

    def gen_export_dynamic_link_args(self, env):
        return [] # Not applicable with MSVC

    def get_std_shared_lib_link_args(self):
        return ['/DLL']

    def gen_vs_module_defs_args(self, defsfile):
        if not isinstance(defsfile, str):
            raise RuntimeError('Module definitions file should be str')
        # With MSVC, DLLs only export symbols that are explicitly exported,
        # so if a module defs file is specified, we use that to export symbols
        return ['/DEF:' + defsfile]

    def gen_pch_args(self, header, source, pchname):
        objname = os.path.splitext(pchname)[0] + '.obj'
        return objname, ['/Yc' + header, '/Fp' + pchname, '/Fo' + objname]

    def gen_import_library_args(self, implibname):
        "The name of the outputted import library"
        return ['/IMPLIB:' + implibname]

    def build_rpath_args(self, build_dir, from_dir, rpath_paths, build_rpath, install_rpath):
        return []

    def openmp_flags(self):
        return ['/openmp']

    # FIXME, no idea what these should be.
    def thread_flags(self, env):
        return []

    def thread_link_flags(self, env):
        return []

    def get_options(self):
        opts = CCompiler.get_options(self)
        opts.update({'c_winlibs': coredata.UserArrayOption('c_winlibs',
                                                           'Windows libs to link against.',
                                                           msvc_winlibs)})
        return opts

    def get_option_link_args(self, options):
        return options['c_winlibs'].value[:]

    @classmethod
    def unix_args_to_native(cls, args):
        result = []
        for i in args:
            # -mms-bitfields is specific to MinGW-GCC
            # -pthread is only valid for GCC
            if i in ('-mms-bitfields', '-pthread'):
                continue
            if i.startswith('-L'):
                i = '/LIBPATH:' + i[2:]
            # Translate GNU-style -lfoo library name to the import library
            elif i.startswith('-l'):
                name = i[2:]
                if name in cls.ignore_libs:
                    # With MSVC, these are provided by the C runtime which is
                    # linked in by default
                    continue
                else:
                    i = name + '.lib'
            # -pthread in link flags is only used on Linux
            elif i == '-pthread':
                continue
            result.append(i)
        return result

    def get_werror_args(self):
        return ['/WX']

    def get_include_args(self, path, is_system):
        if path == '':
            path = '.'
        # msvc does not have a concept of system header dirs.
        return ['-I' + path]

    def compute_parameters_with_absolute_paths(self, parameter_list, build_dir):
        for idx, i in enumerate(parameter_list):
            if i[:2] == '-I' or i[:2] == '/I':
                parameter_list[idx] = i[:2] + os.path.normpath(os.path.join(build_dir, i[2:]))
            elif i[:9] == '/LIBPATH:':
                parameter_list[idx] = i[:9] + os.path.normpath(os.path.join(build_dir, i[9:]))

        return parameter_list

    # Visual Studio is special. It ignores some arguments it does not
    # understand and you can't tell it to error out on those.
    # http://stackoverflow.com/questions/15259720/how-can-i-make-the-microsoft-c-compiler-treat-unknown-flags-as-errors-rather-t
    def has_arguments(self, args, env, code, mode):
        warning_text = '4044' if mode == 'link' else '9002'
        if self.id == 'clang-cl' and mode != 'link':
            args = args + ['-Werror=unknown-argument']
        with self._build_wrapper(code, env, extra_args=args, mode=mode) as p:
            if p.returncode != 0:
                return False
            return not(warning_text in p.stde or warning_text in p.stdo)

    def get_compile_debugfile_args(self, rel_obj, pch=False):
        pdbarr = rel_obj.split('.')[:-1]
        pdbarr += ['pdb']
        args = ['/Fd' + '.'.join(pdbarr)]
        # When generating a PDB file with PCH, all compile commands write
        # to the same PDB file. Hence, we need to serialize the PDB
        # writes using /FS since we do parallel builds. This slows down the
        # build obviously, which is why we only do this when PCH is on.
        # This was added in Visual Studio 2013 (MSVC 18.0). Before that it was
        # always on: https://msdn.microsoft.com/en-us/library/dn502518.aspx
        if pch and self.id == 'msvc' and version_compare(self.version, '>=18.0'):
            args = ['/FS'] + args
        return args

    def get_link_debugfile_args(self, targetfile):
        pdbarr = targetfile.split('.')[:-1]
        pdbarr += ['pdb']
        return ['/DEBUG', '/PDB:' + '.'.join(pdbarr)]

    def get_link_whole_for(self, args):
        # Only since VS2015
        args = listify(args)
        return ['/WHOLEARCHIVE:' + x for x in args]

    def get_instruction_set_args(self, instruction_set):
        if self.is_64:
            return vs64_instruction_set_args.get(instruction_set, None)
        if self.id == 'msvc' and self.version.split('.')[0] == '16' and instruction_set == 'avx':
            # VS documentation says that this exists and should work, but
            # it does not. The headers do not contain AVX intrinsics
            # and the can not be called.
            return None
        return vs32_instruction_set_args.get(instruction_set, None)

    def get_toolset_version(self):
        if self.id == 'clang-cl':
            # I have no idea
            return '14.1'

        # See boost/config/compiler/visualc.cpp for up to date mapping
        try:
            version = int(''.join(self.version.split('.')[0:2]))
        except ValueError:
            return None
        if version < 1310:
            return '7.0'
        elif version < 1400:
            return '7.1' # (Visual Studio 2003)
        elif version < 1500:
            return '8.0' # (Visual Studio 2005)
        elif version < 1600:
            return '9.0' # (Visual Studio 2008)
        elif version < 1700:
            return '10.0' # (Visual Studio 2010)
        elif version < 1800:
            return '11.0' # (Visual Studio 2012)
        elif version < 1900:
            return '12.0' # (Visual Studio 2013)
        elif version < 1910:
            return '14.0' # (Visual Studio 2015)
        elif version < 1920:
            return '14.1' # (Visual Studio 2017)
        return None

    def get_default_include_dirs(self):
        if 'INCLUDE' not in os.environ:
            return []
        return os.environ['INCLUDE'].split(os.pathsep)

    def get_crt_compile_args(self, crt_val, buildtype):
        if crt_val in self.crt_args:
            return self.crt_args[crt_val]
        assert(crt_val == 'from_buildtype')
        # Match what build type flags used to do.
        if buildtype == 'plain':
            return []
        elif buildtype == 'debug':
            return self.crt_args['mdd']
        elif buildtype == 'debugoptimized':
            return self.crt_args['md']
        elif buildtype == 'release':
            return self.crt_args['md']
        elif buildtype == 'minsize':
            return self.crt_args['md']
        else:
            assert(buildtype == 'custom')
            raise EnvironmentException('Requested C runtime based on buildtype, but buildtype is "custom".')

    def has_func_attribute(self, name, env):
        # MSVC doesn't have __attribute__ like Clang and GCC do, so just return
        # false without compiling anything
        return name in ['dllimport', 'dllexport']

    def get_argument_syntax(self):
        return 'msvc'

    def get_allow_undefined_link_args(self):
        # link.exe
        return ['/FORCE:UNRESOLVED']


class ClangClCCompiler(VisualStudioCCompiler):
    def __init__(self, exelist, version, is_cross, exe_wrap, target):
        super().__init__(exelist, version, is_cross, exe_wrap, target)
        self.id = 'clang-cl'


class ArmCCompiler(ArmCompiler, CCompiler):
    def __init__(self, exelist, version, compiler_type, is_cross, exe_wrapper=None, **kwargs):
        CCompiler.__init__(self, exelist, version, is_cross, exe_wrapper, **kwargs)
        ArmCompiler.__init__(self, compiler_type)

    def get_options(self):
        opts = CCompiler.get_options(self)
        opts.update({'c_std': coredata.UserComboOption('c_std', 'C language standard to use',
                                                       ['none', 'c90', 'c99'],
                                                       'none')})
        return opts

    def get_option_compile_args(self, options):
        args = []
        std = options['c_std']
        if std.value != 'none':
            args.append('--' + std.value)
        return args

class CcrxCCompiler(CcrxCompiler, CCompiler):
    def __init__(self, exelist, version, compiler_type, is_cross, exe_wrapper=None, **kwargs):
        CCompiler.__init__(self, exelist, version, is_cross, exe_wrapper, **kwargs)
        CcrxCompiler.__init__(self, compiler_type)

    # Override CCompiler.get_always_args
    def get_always_args(self):
        return ['-nologo']

    def get_options(self):
        opts = CCompiler.get_options(self)
        opts.update({'c_std': coredata.UserComboOption('c_std', 'C language standard to use',
                                                       ['none', 'c89', 'c99'],
                                                       'none')})
        return opts

    def get_option_compile_args(self, options):
        args = []
        std = options['c_std']
        if std.value == 'c89':
            args.append('-lang=c')
        elif std.value == 'c99':
            args.append('-lang=c99')
        return args

    def get_compile_only_args(self):
        return []

    def get_no_optimization_args(self):
        return ['-optimize=0']

    def get_output_args(self, target):
        return ['-output=obj=%s' % target]

    def get_linker_output_args(self, outputname):
        return ['-output=%s' % outputname]

    def get_werror_args(self):
        return ['-change_message=error']

    def get_include_args(self, path, is_system):
        if path == '':
            path = '.'
        return ['-include=' + path]
