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

import sysconfig
import typing as T

from .. import mesonlib
from . import ExtensionModule
from mesonbuild.modules import ModuleReturnValue
from ..interpreterbase import noKwargs, noPosargs, permittedKwargs, FeatureDeprecated, typed_pos_args
from ..build import known_shmod_kwargs
from ..programs import ExternalProgram


class Python3Module(ExtensionModule):
    @FeatureDeprecated('python3 module', '0.48.0')
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.snippets.add('extension_module')

    @permittedKwargs(known_shmod_kwargs)
    def extension_module(self, interpreter, state, args, kwargs):
        if 'name_prefix' in kwargs:
            raise mesonlib.MesonException('Name_prefix is set automatically, specifying it is forbidden.')
        if 'name_suffix' in kwargs:
            raise mesonlib.MesonException('Name_suffix is set automatically, specifying it is forbidden.')
        host_system = state.host_machine.system
        if host_system == 'darwin':
            # Default suffix is 'dylib' but Python does not use it for extensions.
            suffix = 'so'
        elif host_system == 'windows':
            # On Windows the extension is pyd for some unexplainable reason.
            suffix = 'pyd'
        else:
            suffix = []
        kwargs['name_prefix'] = ''
        kwargs['name_suffix'] = suffix
        return interpreter.func_shared_module(None, args, kwargs)

    @noKwargs
    @noPosargs
    def find_python(self, state, args, kwargs):
        command = state.environment.lookup_binary_entry(mesonlib.MachineChoice.HOST, 'python3')
        if command is not None:
            py3 = ExternalProgram.from_entry('python3', command)
        else:
            py3 = ExternalProgram('python3', mesonlib.python_command, silent=True)
        return ModuleReturnValue(py3, [py3])

    @noKwargs
    @noPosargs
    def language_version(self, state, args, kwargs):
        return ModuleReturnValue(sysconfig.get_python_version(), [])

    @noKwargs
    @typed_pos_args('python3.sysconfig_path', str)
    def sysconfig_path(self, state, args: T.Tuple[str], kwargs):
        path_name = args[0]
        valid_names = sysconfig.get_path_names()
        if path_name not in valid_names:
            raise mesonlib.MesonException(f'{path_name} is not a valid path name {valid_names}.')

        # Get a relative path without a prefix, e.g. lib/python3.6/site-packages
        path = sysconfig.get_path(path_name, vars={'base': '', 'platbase': '', 'installed_base': ''})[1:]
        return ModuleReturnValue(path, [])


def initialize(*args, **kwargs):
    return Python3Module(*args, **kwargs)
