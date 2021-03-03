# Copyright 2019 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This file contains the detection logic for external dependencies that
# are UI-related.

import os

from .. import build
from ..mesonlib import unholder, relpath
import typing as T

if T.TYPE_CHECKING:
    from ..interpreter import Interpreter
    from ..interpreterbase import TYPE_var, TYPE_nvar, TYPE_nkwargs

class ModuleState:
    """Object passed to all module methods.

    This is a WIP API provided to modules, it should be extended to have everything
    needed so modules does not touch any other part of Meson internal APIs.
    """

    def __init__(self, interpreter: 'Interpreter') -> None:
        self.source_root = interpreter.environment.get_source_dir()
        self.build_to_src = relpath(interpreter.environment.get_source_dir(),
                                    interpreter.environment.get_build_dir())
        self.subproject = interpreter.subproject
        self.subdir = interpreter.subdir
        self.current_lineno = interpreter.current_lineno
        self.environment = interpreter.environment
        self.project_name = interpreter.build.project_name
        self.project_version = interpreter.build.dep_manifest[interpreter.active_projectname]
        # The backend object is under-used right now, but we will need it:
        # https://github.com/mesonbuild/meson/issues/1419
        self.backend = interpreter.backend
        self.targets = interpreter.build.targets
        self.data = interpreter.build.data
        self.headers = interpreter.build.get_headers()
        self.man = interpreter.build.get_man()
        self.global_args = interpreter.build.global_args.host
        self.project_args = interpreter.build.projects_args.host.get(interpreter.subproject, {})
        self.build_machine = interpreter.builtin['build_machine'].held_object
        self.host_machine = interpreter.builtin['host_machine'].held_object
        self.target_machine = interpreter.builtin['target_machine'].held_object
        self.current_node = interpreter.current_node

class ModuleObject:
    """Base class for all objects returned by modules
    """
    def __init__(self, interpreter: T.Optional['Interpreter'] = None) -> None:
        self.methods = {}  # type: T.Dict[str, T.Callable[[T.List[TYPE_nvar], TYPE_nkwargs], TYPE_var]]
        # FIXME: Port all modules to stop using self.interpreter and use API on
        # ModuleState instead.
        self.interpreter = interpreter
        # FIXME: Port all modules to remove snippets methods.
        self.snippets: T.Set[str] = set()

# FIXME: Port all modules to use ModuleObject directly.
class ExtensionModule(ModuleObject):
    pass

def get_include_args(include_dirs, prefix='-I'):
    '''
    Expand include arguments to refer to the source and build dirs
    by using @SOURCE_ROOT@ and @BUILD_ROOT@ for later substitution
    '''
    if not include_dirs:
        return []

    dirs_str = []
    for dirs in unholder(include_dirs):
        if isinstance(dirs, str):
            dirs_str += ['%s%s' % (prefix, dirs)]
            continue

        # Should be build.IncludeDirs object.
        basedir = dirs.get_curdir()
        for d in dirs.get_incdirs():
            expdir = os.path.join(basedir, d)
            srctreedir = os.path.join('@SOURCE_ROOT@', expdir)
            buildtreedir = os.path.join('@BUILD_ROOT@', expdir)
            dirs_str += ['%s%s' % (prefix, buildtreedir),
                         '%s%s' % (prefix, srctreedir)]
        for d in dirs.get_extra_build_dirs():
            dirs_str += ['%s%s' % (prefix, d)]

    return dirs_str

def is_module_library(fname):
    '''
    Check if the file is a library-like file generated by a module-specific
    target, such as GirTarget or TypelibTarget
    '''
    if hasattr(fname, 'fname'):
        fname = fname.fname
    suffix = fname.split('.')[-1]
    return suffix in ('gir', 'typelib')


class ModuleReturnValue:
    def __init__(self, return_value: 'TYPE_var', new_objects: T.List['TYPE_var']) -> None:
        self.return_value = return_value
        assert(isinstance(new_objects, list))
        self.new_objects = new_objects

class GResourceTarget(build.CustomTarget):
    def __init__(self, name, subdir, subproject, kwargs):
        super().__init__(name, subdir, subproject, kwargs)

class GResourceHeaderTarget(build.CustomTarget):
    def __init__(self, name, subdir, subproject, kwargs):
        super().__init__(name, subdir, subproject, kwargs)

class GirTarget(build.CustomTarget):
    def __init__(self, name, subdir, subproject, kwargs):
        super().__init__(name, subdir, subproject, kwargs)

class TypelibTarget(build.CustomTarget):
    def __init__(self, name, subdir, subproject, kwargs):
        super().__init__(name, subdir, subproject, kwargs)

class VapiTarget(build.CustomTarget):
    def __init__(self, name, subdir, subproject, kwargs):
        super().__init__(name, subdir, subproject, kwargs)
