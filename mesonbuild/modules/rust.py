# Copyright © 2020 Intel Corporation

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
import copy
import os
import typing as T

from . import ExtensionModule, ModuleReturnValue, ModuleInfo
from .. import mlog
from ..build import BothLibraries, BuildTarget, CustomTargetIndex, Executable, ExtractedObjects, GeneratedList, IncludeDirs, CustomTarget, StructuredSources
from ..dependencies import Dependency, ExternalLibrary
from ..interpreter.interpreter import TEST_KWARGS, OUTPUT_KW
from ..interpreterbase import ContainerTypeInfo, InterpreterException, KwargInfo, typed_kwargs, typed_pos_args, noPosargs
from ..mesonlib import File

if T.TYPE_CHECKING:
    from . import ModuleState
    from ..interpreter import Interpreter
    from ..interpreter import kwargs as _kwargs
    from ..interpreter.interpreter import SourceInputs, SourceOutputs
    from ..programs import ExternalProgram

    from typing_extensions import TypedDict

    class FuncTest(_kwargs.BaseTest):

        dependencies: T.List[T.Union[Dependency, ExternalLibrary]]
        is_parallel: bool

    class FuncBindgen(TypedDict):

        args: T.List[str]
        c_args: T.List[str]
        include_directories: T.List[IncludeDirs]
        input: T.List[SourceInputs]
        output: str


class RustModule(ExtensionModule):

    """A module that holds helper functions for rust."""

    INFO = ModuleInfo('rust', '0.57.0', unstable=True)

    def __init__(self, interpreter: 'Interpreter') -> None:
        super().__init__(interpreter)
        self._bindgen_bin: T.Optional['ExternalProgram'] = None
        self.methods.update({
            'test': self.test,
            'bindgen': self.bindgen,
        })

    @typed_pos_args('rust.test', str, BuildTarget)
    @typed_kwargs(
        'rust.test',
        *TEST_KWARGS,
        KwargInfo('is_parallel', bool, default=False),
        KwargInfo(
            'dependencies',
            ContainerTypeInfo(list, (Dependency, ExternalLibrary)),
            listify=True,
            default=[]),
    )
    def test(self, state: 'ModuleState', args: T.Tuple[str, BuildTarget], kwargs: 'FuncTest') -> ModuleReturnValue:
        """Generate a rust test target from a given rust target.

        Rust puts it's unitests inside it's main source files, unlike most
        languages that put them in external files. This means that normally
        you have to define two separate targets with basically the same
        arguments to get tests:

        ```meson
        rust_lib_sources = [...]
        rust_lib = static_library(
            'rust_lib',
            rust_lib_sources,
        )

        rust_lib_test = executable(
            'rust_lib_test',
            rust_lib_sources,
            rust_args : ['--test'],
        )

        test(
            'rust_lib_test',
            rust_lib_test,
            protocol : 'rust',
        )
        ```

        This is all fine, but not very DRY. This method makes it much easier
        to define rust tests:

        ```meson
        rust = import('unstable-rust')

        rust_lib = static_library(
            'rust_lib',
            [sources],
        )

        rust.test('rust_lib_test', rust_lib)
        ```
        """
        name = args[0]
        base_target: BuildTarget = args[1]
        if not base_target.uses_rust():
            raise InterpreterException('Second positional argument to rustmod.test() must be a rust based target')
        extra_args = kwargs['args']

        # Delete any arguments we don't want passed
        if '--test' in extra_args:
            mlog.warning('Do not add --test to rustmod.test arguments')
            extra_args.remove('--test')
        if '--format' in extra_args:
            mlog.warning('Do not add --format to rustmod.test arguments')
            i = extra_args.index('--format')
            # Also delete the argument to --format
            del extra_args[i + 1]
            del extra_args[i]
        for i, a in enumerate(extra_args):
            if isinstance(a, str) and a.startswith('--format='):
                del extra_args[i]
                break

        dependencies = [d for d in kwargs['dependencies']]

        # We need to cast here, as currently these don't have protocol in them, but test itself does.
        tkwargs = T.cast('_kwargs.FuncTest', kwargs.copy())

        tkwargs['args'] = extra_args + ['--test', '--format', 'pretty']
        tkwargs['protocol'] = 'rust'

        # If we have an Executable we can take a fast path
        if isinstance(base_target, Executable):
            new_target = copy.deepcopy(base_target)
            new_target.name = name
            new_target.subdir = state.subdir
            new_target.install = False
        else:
            new_target = Executable(
                name,
                state.subdir,
                state.subproject,
                base_target.for_machine,
                state.environment,
                base_target.sources,
                base_target.structured_sources,
                base_target.objects,
                base_target.compilers,
                build_by_default=base_target.build_by_default,
                build_always_stale=base_target.build_always_stale,
                install=False,
                extra_files=base_target.extra_files,
                # Option overrides intentionally not set here
                build_rpath=base_target.build_rpath,
                d_debug=base_target.d_features['debug'],
                d_import_dirs=base_target.d_features['import_dirs'],
                d_module_versions=base_target.d_features['versions'],
                d_unittest=base_target.d_features['unittest'],
                dependencies=list(base_target._added_deps),
                gnu_symbol_visibility=base_target.gnu_symbol_visibility,
                implicit_include_directories=base_target.implicit_include_directories,
                include_directories=base_target.include_dirs,
                # language args intentionally not set here
                link_args=base_target.link_args,
                link_depends=base_target.link_depends,
                link_language=base_target.link_language,
                link_whole=base_target.link_whole,
                name_prefix=base_target.prefix,
                name_suffix=base_target.suffix,
                # pch intentionally not set here
                vala_gir=base_target.vala_gir,
                vala_header=base_target.vala_header,
                vala_vapi=base_target.vala_vapi,
            )
            new_target.options = copy.deepcopy(base_target.options)
            new_target.extra_args = copy.deepcopy(base_target.extra_args)
            new_target.pch = copy.deepcopy(base_target.pch)
        new_target.extra_args['rust'].append('--test')
        new_target.add_deps(dependencies)

        test = self.interpreter.make_test(
            self.interpreter.current_node, (name, new_target), tkwargs)

        return ModuleReturnValue(None, [new_target, test])

    @noPosargs
    @typed_kwargs(
        'rust.bindgen',
        KwargInfo('c_args', ContainerTypeInfo(list, str), default=[], listify=True),
        KwargInfo('args', ContainerTypeInfo(list, str), default=[], listify=True),
        KwargInfo('include_directories', ContainerTypeInfo(list, IncludeDirs), default=[], listify=True),
        KwargInfo(
            'input',
            ContainerTypeInfo(list, (File, GeneratedList, BuildTarget, BothLibraries, ExtractedObjects, CustomTargetIndex, CustomTarget, str), allow_empty=False),
            default=[],
            listify=True,
            required=True,
        ),
        OUTPUT_KW,
    )
    def bindgen(self, state: 'ModuleState', args: T.List, kwargs: 'FuncBindgen') -> ModuleReturnValue:
        """Wrapper around bindgen to simplify it's use.

        The main thing this simplifies is the use of `include_directory`
        objects, instead of having to pass a plethora of `-I` arguments.
        """
        header, *_deps = self.interpreter.source_strings_to_files(kwargs['input'])

        # Split File and Target dependencies to add pass to CustomTarget
        depends: T.List['SourceOutputs'] = []
        depend_files: T.List[File] = []
        for d in _deps:
            if isinstance(d, File):
                depend_files.append(d)
            else:
                depends.append(d)

        inc_strs: T.List[str] = []
        for i in kwargs['include_directories']:
            # bindgen always uses clang, so it's safe to hardcode -I here
            inc_strs.extend([f'-I{x}' for x in i.to_string_list(
                state.environment.get_source_dir(), state.environment.get_build_dir())])

        if self._bindgen_bin is None:
            self._bindgen_bin = state.find_program('bindgen')

        name: str
        if isinstance(header, File):
            name = header.fname
        elif isinstance(header, (BuildTarget, BothLibraries, ExtractedObjects, StructuredSources)):
            raise InterpreterException('bindgen source file must be a C header, not an object or build target')
        else:
            name = header.get_outputs()[0]

        target = CustomTarget(
            f'rustmod-bindgen-{name}'.replace('/', '_'),
            state.subdir,
            state.subproject,
            state.environment,
            self._bindgen_bin.get_command() + [
                '@INPUT@', '--output',
                os.path.join(state.environment.build_dir, '@OUTPUT@')] +
                kwargs['args'] + ['--'] + kwargs['c_args'] + inc_strs +
                ['-MD', '-MQ', '@INPUT@', '-MF', '@DEPFILE@'],
            [header],
            [kwargs['output']],
            depfile='@PLAINNAME@.d',
            extra_depends=depends,
            depend_files=depend_files,
            backend=state.backend,
        )

        return ModuleReturnValue([target], [target])


def initialize(interp: 'Interpreter') -> RustModule:
    return RustModule(interp)
