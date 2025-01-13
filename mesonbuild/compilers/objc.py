# SPDX-License-Identifier: Apache-2.0
# Copyright 2012-2017 The Meson development team

from __future__ import annotations

import typing as T

from ..options import OptionKey, UserStdOption

from .c import ALL_STDS
from .compilers import Compiler
from .mixins.apple import AppleCStdsMixin
from .mixins.clang import ClangCompiler, ClangCStds
from .mixins.clike import CLikeCompiler
from .mixins.gnu import GnuCompiler, GnuCStds, gnu_common_warning_args, gnu_objc_warning_args

if T.TYPE_CHECKING:
    from .. import coredata
    from ..envconfig import MachineInfo
    from ..environment import Environment
    from ..linkers.linkers import DynamicLinker
    from ..mesonlib import MachineChoice


class ObjCCompiler(CLikeCompiler, Compiler):

    language = 'objc'

    def __init__(self, ccache: T.List[str], exelist: T.List[str], version: str, for_machine: MachineChoice,
                 is_cross: bool, info: 'MachineInfo',
                 linker: T.Optional['DynamicLinker'] = None,
                 full_version: T.Optional[str] = None):
        Compiler.__init__(self, ccache, exelist, version, for_machine, info,
                          is_cross=is_cross, full_version=full_version,
                          linker=linker)
        CLikeCompiler.__init__(self)

    def get_options(self) -> coredata.MutableKeyedOptionDictType:
        opts = super().get_options()
        key = self.form_compileropt_key('std')
        opts.update({
            key: UserStdOption('c', ALL_STDS),
        })
        return opts

    @staticmethod
    def get_display_language() -> str:
        return 'Objective-C'

    def sanity_check(self, work_dir: str, environment: 'Environment') -> None:
        code = '#import<stddef.h>\nint main(void) { return 0; }\n'
        return self._sanity_check_impl(work_dir, environment, 'sanitycheckobjc.m', code)

    def form_compileropt_key(self, basename: str) -> OptionKey:
        if basename == 'std':
            return OptionKey(f'c_{basename}', machine=self.for_machine)
        return super().form_compileropt_key(basename)


class GnuObjCCompiler(GnuCStds, GnuCompiler, ObjCCompiler):
    def __init__(self, ccache: T.List[str], exelist: T.List[str], version: str, for_machine: MachineChoice,
                 is_cross: bool, info: 'MachineInfo',
                 defines: T.Optional[T.Dict[str, str]] = None,
                 linker: T.Optional['DynamicLinker'] = None,
                 full_version: T.Optional[str] = None):
        ObjCCompiler.__init__(self, ccache, exelist, version, for_machine, is_cross,
                              info, linker=linker, full_version=full_version)
        GnuCompiler.__init__(self, defines)
        default_warn_args = ['-Wall', '-Winvalid-pch']
        self.warn_args = {'0': [],
                          '1': default_warn_args,
                          '2': default_warn_args + ['-Wextra'],
                          '3': default_warn_args + ['-Wextra', '-Wpedantic'],
                          'everything': (default_warn_args + ['-Wextra', '-Wpedantic'] +
                                         self.supported_warn_args(gnu_common_warning_args) +
                                         self.supported_warn_args(gnu_objc_warning_args))}

    def get_option_compile_args(self, options: 'coredata.KeyedOptionDictType') -> T.List[str]:
        args = []
        std = options.get_value(self.form_compileropt_key('std'))
        if std != 'none':
            args.append('-std=' + std)
        return args


class ClangObjCCompiler(ClangCStds, ClangCompiler, ObjCCompiler):
    def __init__(self, ccache: T.List[str], exelist: T.List[str], version: str, for_machine: MachineChoice,
                 is_cross: bool, info: 'MachineInfo',
                 defines: T.Optional[T.Dict[str, str]] = None,
                 linker: T.Optional['DynamicLinker'] = None,
                 full_version: T.Optional[str] = None):
        ObjCCompiler.__init__(self, ccache, exelist, version, for_machine, is_cross,
                              info, linker=linker, full_version=full_version)
        ClangCompiler.__init__(self, defines)
        default_warn_args = ['-Wall', '-Winvalid-pch']
        self.warn_args = {'0': [],
                          '1': default_warn_args,
                          '2': default_warn_args + ['-Wextra'],
                          '3': default_warn_args + ['-Wextra', '-Wpedantic'],
                          'everything': ['-Weverything']}

    def get_option_compile_args(self, options: 'coredata.KeyedOptionDictType') -> T.List[str]:
        args = []
        std = options.get_value(self.form_compileropt_key('std'))
        if std != 'none':
            args.append('-std=' + std)
        return args

class AppleClangObjCCompiler(AppleCStdsMixin, ClangObjCCompiler):

    """Handle the differences between Apple's clang and vanilla clang."""
