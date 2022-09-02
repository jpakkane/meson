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

"""Representations specific to the CompCert C compiler family."""

from __future__ import annotations

import os
import re
import typing as T

if T.TYPE_CHECKING:
    from envconfig import MachineInfo
    from ...environment import Environment
    from ...compilers.compilers import Compiler
else:
    # This is a bit clever, for mypy we pretend that these mixins descend from
    # Compiler, so we get all of the methods and attributes defined for us, but
    # for runtime we make them descend from object (which all classes normally
    # do). This gives up DRYer type checking, with no runtime impact
    Compiler = object

ccomp_buildtype_args = {
    'plain': [''],
    'debug': ['-O0', '-g'],
    'debugoptimized': ['-O0', '-g'],
    'release': ['-O3'],
    'minsize': ['-Os'],
    'custom': ['-Obranchless'],
}  # type: T.Dict[str, T.List[str]]

ccomp_optimization_args = {
    '0': ['-O0'],
    'g': ['-O0'],
    '1': ['-O1'],
    '2': ['-O2'],
    '3': ['-O3'],
    's': ['-Os']
}  # type: T.Dict[str, T.List[str]]

ccomp_debug_args = {
    False: [],
    True: ['-g']
}  # type: T.Dict[bool, T.List[str]]

# As of CompCert 20.04, these arguments should be passed to the underlying gcc linker (via -WUl,<arg>)
# There are probably (many) more, but these are those used by picolibc
ccomp_args_to_wul = [
        r"^-ffreestanding$",
        r"^-r$"
] # type: T.List[str]

class CompCertCompiler(Compiler):

    id = 'ccomp'

    def __init__(self) -> None:
        # Assembly
        self.can_compile_suffixes.add('s')
        default_warn_args = []  # type: T.List[str]
        self.warn_args = {'0': [],
                          '1': default_warn_args,
                          '2': default_warn_args + [],
                          '3': default_warn_args + []}  # type: T.Dict[str, T.List[str]]

    def get_always_args(self) -> T.List[str]:
        return []

    def get_pic_args(self) -> T.List[str]:
        # As of now, CompCert does not support PIC
        return []

    def get_buildtype_args(self, buildtype: str) -> T.List[str]:
        return ccomp_buildtype_args[buildtype]

    def get_pch_suffix(self) -> str:
        return 'pch'

    def get_pch_use_args(self, pch_dir: str, header: str) -> T.List[str]:
        return []

    @classmethod
    def _unix_args_to_native(cls, args: T.List[str], info: MachineInfo) -> T.List[str]:
        "Always returns a copy that can be independently mutated"
        patched_args = []  # type: T.List[str]
        for arg in args:
            added = 0
            for ptrn in ccomp_args_to_wul:
                if re.match(ptrn, arg):
                    patched_args.append('-WUl,' + arg)
                    added = 1
            if not added:
                patched_args.append(arg)
        return patched_args

    def thread_flags(self, env: 'Environment') -> T.List[str]:
        return []

    def get_preprocess_only_args(self) -> T.List[str]:
        return ['-E']

    def get_compile_only_args(self) -> T.List[str]:
        return ['-c']

    def get_coverage_args(self) -> T.List[str]:
        return []

    def get_no_stdinc_args(self) -> T.List[str]:
        return ['-nostdinc']

    def get_no_stdlib_link_args(self) -> T.List[str]:
        return ['-nostdlib']

    def get_optimization_args(self, optimization_level: str) -> T.List[str]:
        return ccomp_optimization_args[optimization_level]

    def get_debug_args(self, is_debug: bool) -> T.List[str]:
        return ccomp_debug_args[is_debug]

    def compute_parameters_with_absolute_paths(self, parameter_list: T.List[str], build_dir: str) -> T.List[str]:
        for idx, i in enumerate(parameter_list):
            if i[:9] == '-I':
                parameter_list[idx] = i[:9] + os.path.normpath(os.path.join(build_dir, i[9:]))

        return parameter_list
