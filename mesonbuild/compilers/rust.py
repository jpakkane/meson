# Copyright 2012-2022 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations

import subprocess, os.path
import textwrap
import typing as T

from .. import coredata
from ..mesonlib import EnvironmentException, MesonException, Popen_safe, OptionKey
from .compilers import Compiler, rust_buildtype_args, clike_debug_args

if T.TYPE_CHECKING:
    from ..coredata import MutableKeyedOptionDictType, KeyedOptionDictType
    from ..envconfig import MachineInfo
    from ..environment import Environment  # noqa: F401
    from ..linkers import DynamicLinker
    from ..mesonlib import MachineChoice
    from ..programs import ExternalProgram


rust_optimization_args = {
    '0': [],
    'g': ['-C', 'opt-level=0'],
    '1': ['-C', 'opt-level=1'],
    '2': ['-C', 'opt-level=2'],
    '3': ['-C', 'opt-level=3'],
    's': ['-C', 'opt-level=s'],
}  # type: T.Dict[str, T.List[str]]

class RustCompiler(Compiler):

    # rustc doesn't invoke the compiler itself, it doesn't need a LINKER_PREFIX
    language = 'rust'
    id = 'rustc'

    _WARNING_LEVELS: T.Dict[str, T.List[str]] = {
        '0': ['-A', 'warnings'],
        '1': [],
        '2': [],
        '3': ['-W', 'warnings'],
    }

    def __init__(self, exelist: T.List[str], version: str, for_machine: MachineChoice,
                 is_cross: bool, info: 'MachineInfo',
                 exe_wrapper: T.Optional['ExternalProgram'] = None,
                 full_version: T.Optional[str] = None,
                 linker: T.Optional['DynamicLinker'] = None):
        super().__init__(exelist, version, for_machine, info,
                         is_cross=is_cross, full_version=full_version,
                         linker=linker)
        self.exe_wrapper = exe_wrapper
        self.base_options.add(OptionKey('b_colorout'))
        if 'link' in self.linker.id:
            self.base_options.add(OptionKey('b_vscrt'))

    def needs_static_linker(self) -> bool:
        return False

    def sanity_check(self, work_dir: str, environment: 'Environment') -> None:
        source_name = os.path.join(work_dir, 'sanity.rs')
        output_name = os.path.join(work_dir, 'rusttest')
        with open(source_name, 'w', encoding='utf-8') as ofile:
            ofile.write(textwrap.dedent(
                '''fn main() {
                }
                '''))
        pc = subprocess.Popen(self.exelist + ['-o', output_name, source_name],
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,
                              cwd=work_dir)
        _stdo, _stde = pc.communicate()
        assert isinstance(_stdo, bytes)
        assert isinstance(_stde, bytes)
        stdo = _stdo.decode('utf-8', errors='replace')
        stde = _stde.decode('utf-8', errors='replace')
        if pc.returncode != 0:
            raise EnvironmentException('Rust compiler {} can not compile programs.\n{}\n{}'.format(
                self.name_string(),
                stdo,
                stde))
        if self.is_cross:
            if self.exe_wrapper is None:
                # Can't check if the binaries run so we have to assume they do
                return
            cmdlist = self.exe_wrapper.get_command() + [output_name]
        else:
            cmdlist = [output_name]
        pe = subprocess.Popen(cmdlist, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pe.wait()
        if pe.returncode != 0:
            raise EnvironmentException('Executables created by Rust compiler %s are not runnable.' % self.name_string())

    def get_dependency_gen_args(self, outtarget: str, outfile: str) -> T.List[str]:
        return ['--dep-info', outfile]

    def get_buildtype_args(self, buildtype: str) -> T.List[str]:
        return rust_buildtype_args[buildtype]

    def get_sysroot(self) -> str:
        cmd = self.exelist + ['--print', 'sysroot']
        p, stdo, stde = Popen_safe(cmd)
        return stdo.split('\n', maxsplit=1)[0]

    def get_debug_args(self, is_debug: bool) -> T.List[str]:
        return clike_debug_args[is_debug]

    def get_optimization_args(self, optimization_level: str) -> T.List[str]:
        return rust_optimization_args[optimization_level]

    def compute_parameters_with_absolute_paths(self, parameter_list: T.List[str],
                                               build_dir: str) -> T.List[str]:
        for idx, i in enumerate(parameter_list):
            if i[:2] == '-L':
                for j in ['dependency', 'crate', 'native', 'framework', 'all']:
                    combined_len = len(j) + 3
                    if i[:combined_len] == f'-L{j}=':
                        parameter_list[idx] = i[:combined_len] + os.path.normpath(os.path.join(build_dir, i[combined_len:]))
                        break

        return parameter_list

    def get_output_args(self, outputname: str) -> T.List[str]:
        return ['-o', outputname]

    @classmethod
    def use_linker_args(cls, linker: str, version: str) -> T.List[str]:
        return ['-C', f'linker={linker}']

    # Rust does not have a use_linker_args because it dispatches to a gcc-like
    # C compiler for dynamic linking, as such we invoke the C compiler's
    # use_linker_args method instead.

    def get_options(self) -> 'MutableKeyedOptionDictType':
        key = OptionKey('std', machine=self.for_machine, lang=self.language)
        return {
            key: coredata.UserComboOption(
                'Rust edition to use',
                ['none', '2015', '2018', '2021'],
                'none',
            ),
        }

    def get_option_compile_args(self, options: 'KeyedOptionDictType') -> T.List[str]:
        args = []
        key = OptionKey('std', machine=self.for_machine, lang=self.language)
        std = options[key]
        if std.value != 'none':
            args.append('--edition=' + std.value)
        return args

    def get_crt_compile_args(self, crt_val: str, buildtype: str) -> T.List[str]:
        # Rust handles this for us, we don't need to do anything
        return []

    def get_colorout_args(self, colortype: str) -> T.List[str]:
        if colortype in {'always', 'never', 'auto'}:
            return [f'--color={colortype}']
        raise MesonException(f'Invalid color type for rust {colortype}')

    def get_linker_always_args(self) -> T.List[str]:
        args: T.List[str] = []
        for a in super().get_linker_always_args():
            args.extend(['-C', f'link-arg={a}'])
        return args

    def get_werror_args(self) -> T.List[str]:
        # Use -D warnings, which makes every warning not explicitly allowed an
        # error
        return ['-D', 'warnings']

    def get_warn_args(self, level: str) -> T.List[str]:
        # TODO: I'm not really sure what to put here, Rustc doesn't have warning
        return self._WARNING_LEVELS[level]

    def get_no_warn_args(self) -> T.List[str]:
        return self._WARNING_LEVELS["0"]

    def get_pic_args(self) -> T.List[str]:
        # This defaults to
        return ['-C', 'relocation-model=pic']

    def get_pie_args(self) -> T.List[str]:
        # Rustc currently has no way to toggle this, it's controlled by whether
        # pic is on by rustc
        return []

    def has_arguments(self, args: T.List[str], env: 'Environment', code: str,
                      mode: str) -> T.Tuple[bool, bool]:
        return self.compiles(code, env, extra_args=args, mode=mode)

    def has_multi_arguments(self, args: T.List[str], env: 'Environment') -> T.Tuple[bool, bool]:
        return self.has_arguments(args, env, 'fn main { std::process::exit(0) };\n', 'compile')

    def _has_multi_link_arguments(self, args: T.List[str], env: 'Environment', code: str) -> T.Tuple[bool, bool]:
        args = self.linker.fatal_warnings() + args
        return self.has_arguments(args, env, code, mode='link')

    def has_multi_link_arguments(self, args: T.List[str], env: 'Environment') -> T.Tuple[bool, bool]:
        return self._has_multi_link_arguments(args, env, 'fn main { std::process::exit(0) };\n')


class ClippyRustCompiler(RustCompiler):

    """Clippy is a linter that wraps Rustc.

    This just provides us a different id
    """

    id = 'clippy-driver rustc'
