# Copyright 2012-2019 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Representations specific to the Renesas CC-RX compiler family."""

import os
import typing

from ...mesonlib import Popen_safe

ccrx_buildtype_args = {'plain': [],
                       'debug': [],
                       'debugoptimized': [],
                       'release': [],
                       'minsize': [],
                       'custom': [],
                       }

ccrx_buildtype_linker_args = {'plain': [],
                              'debug': [],
                              'debugoptimized': [],
                              'release': [],
                              'minsize': [],
                              'custom': [],
                              }
ccrx_optimization_args = {'0': ['-optimize=0'],
                          'g': ['-optimize=0'],
                          '1': ['-optimize=1'],
                          '2': ['-optimize=2'],
                          '3': ['-optimize=max'],
                          's': ['-optimize=2', '-size']
                          }
ccrx_debug_args = {False: [],
                   True: ['-debug']}


class CcrxCompiler:
    def __init__(self, compiler_type):
        if not self.is_cross:
            raise EnvironmentException('ccrx supports only cross-compilation.')
        # Check whether 'rlink.exe' is available in path
        self.linker_exe = 'rlink.exe'
        args = '--version'
        try:
            p, stdo, stderr = Popen_safe(self.linker_exe, args)
        except OSError as e:
            err_msg = 'Unknown linker\nRunning "{0}" gave \n"{1}"'.format(' '.join([self.linker_exe] + [args]), e)
            raise EnvironmentException(err_msg)
        self.id = 'ccrx'
        self.compiler_type = compiler_type
        # Assembly
        self.can_compile_suffixes.update('s')
        default_warn_args = []
        self.warn_args = {'0': [],
                          '1': default_warn_args,
                          '2': default_warn_args + [],
                          '3': default_warn_args + []}

    def can_linker_accept_rsp(self):
        return False

    def get_pic_args(self):
        # PIC support is not enabled by default for CCRX,
        # if users want to use it, they need to add the required arguments explicitly
        return []

    def get_buildtype_args(self, buildtype):
        return ccrx_buildtype_args[buildtype]

    def get_buildtype_linker_args(self, buildtype):
        return ccrx_buildtype_linker_args[buildtype]

    # Override CCompiler.get_std_shared_lib_link_args
    def get_std_shared_lib_link_args(self):
        return []

    def get_pch_suffix(self):
        return 'pch'

    def get_pch_use_args(self, pch_dir, header):
        return []

    # Override CCompiler.get_dependency_gen_args
    def get_dependency_gen_args(self, outtarget, outfile):
        return []

    # Override CCompiler.build_rpath_args
    def build_rpath_args(self, build_dir, from_dir, rpath_paths, build_rpath, install_rpath):
        return []

    def thread_flags(self, env):
        return []

    def thread_link_flags(self, env):
        return []

    def get_linker_exelist(self):
        return [self.linker_exe]

    def get_linker_lib_prefix(self):
        return '-lib='

    def get_coverage_args(self):
        return []

    def get_coverage_link_args(self):
        return []

    def get_optimization_args(self, optimization_level):
        return ccrx_optimization_args[optimization_level]

    def get_debug_args(self, is_debug):
        return ccrx_debug_args[is_debug]

    @classmethod
    def unix_args_to_native(cls, args):
        result = []
        for i in args:
            if i.startswith('-D'):
                i = '-define=' + i[2:]
            if i.startswith('-I'):
                i = '-include=' + i[2:]
            if i.startswith('-Wl,-rpath='):
                continue
            elif i == '--print-search-dirs':
                continue
            elif i.startswith('-L'):
                continue
            result.append(i)
        return result

    def compute_parameters_with_absolute_paths(self, parameter_list, build_dir):
        for idx, i in enumerate(parameter_list):
            if i[:9] == '-include=':
                parameter_list[idx] = i[:9] + os.path.normpath(os.path.join(build_dir, i[9:]))

        return parameter_list