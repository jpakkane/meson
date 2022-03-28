# Copyright 2016-2017 The Meson development team

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
import sysconfig
from .. import mesonlib
import typing as T

from . import ExtensionModule, ModuleInfo
from .. import build
from ..interpreter.type_checking import SHARED_MOD_KWS
from ..interpreterbase import typed_pos_args, typed_kwargs, noPosargs, noKwargs
from ..programs import ExternalProgram

if T.TYPE_CHECKING:
    from . import ModuleState
    from ..interpreter.interpreter import BuildTargetSource
    from ..interpreter.kwargs import SharedModule, BuildTarget

_MOD_KWARGS = [k for k in SHARED_MOD_KWS if k.name not in {'name_prefix', 'name_suffix'}]


class Python3Module(ExtensionModule):

    INFO = ModuleInfo('python3', '0.38.0', deprecated='0.48.0')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.methods.update({
            'extension_module': self.extension_module,
            'find_python': self.find_python,
            'language_version': self.language_version,
            'sysconfig_path': self.sysconfig_path,
        })

    @typed_pos_args('python3.extension_module', str, varargs=(str, mesonlib.File, build.CustomTarget, build.CustomTargetIndex, build.GeneratedList))
    @typed_kwargs('python3.extension_module', *_MOD_KWARGS)
    def extension_module(self, state: ModuleState,
                         args: T.Tuple[str, T.List[BuildTargetSource]],
                         kwargs: SharedModule) -> build.SharedModule:
        host_system = state.host_machine.system
        suffix: T.Optional[str] = None
        if host_system == 'darwin':
            # Default suffix is 'dylib' but Python does not use it for extensions.
            suffix = 'so'
        elif host_system == 'windows':
            # On Windows the extension is pyd for some unexplainable reason.
            suffix = 'pyd'
        kwargs['name_prefix'] = ''
        kwargs['name_suffix'] = suffix
        return self.interpreter.build_target(
            state.current_node, (args[0], args[1]), T.cast('BuildTarget', kwargs), build.SharedModule)

    @noPosargs
    @noKwargs
    def find_python(self, state, args, kwargs):
        command = state.environment.lookup_binary_entry(mesonlib.MachineChoice.HOST, 'python3')
        if command is not None:
            py3 = ExternalProgram.from_entry('python3', command)
        else:
            py3 = ExternalProgram('python3', mesonlib.python_command, silent=True)
        return py3

    @noPosargs
    @noKwargs
    def language_version(self, state, args, kwargs):
        return sysconfig.get_python_version()

    @noKwargs
    @typed_pos_args('python3.sysconfig_path', str)
    def sysconfig_path(self, state, args, kwargs):
        path_name = args[0]
        valid_names = sysconfig.get_path_names()
        if path_name not in valid_names:
            raise mesonlib.MesonException(f'{path_name} is not a valid path name {valid_names}.')

        # Get a relative path without a prefix, e.g. lib/python3.6/site-packages
        return sysconfig.get_path(path_name, vars={'base': '', 'platbase': '', 'installed_base': ''})[1:]


def initialize(*args, **kwargs):
    return Python3Module(*args, **kwargs)
