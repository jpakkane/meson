# SPDX-License-Identifier: Apache-2.0
# Copyright © 2024 Intel Corporation

from __future__ import annotations
from dataclasses import dataclass
import copy
import itertools
import typing as T

from . import NewExtensionModule, ModuleInfo
from .. import programs
from ..build import BuildTarget, CustomTarget, CustomTargetIndex
from ..interpreterbase import ObjectHolder
from ..interpreterbase.decorators import (
    ContainerTypeInfo, KwargInfo, typed_pos_args, typed_kwargs,
)
from ..interpreterbase.exceptions import InvalidArguments
from ..interpreter.type_checking import (
    CT_BUILD_ALWAYS_STALE, CT_BUILD_BY_DEFAULT, CT_INPUT_KW, CT_INSTALL_DIR_KW,
    CT_INSTALL_TAG_KW, DEPENDS_KW, DEPEND_FILES_KW, DEPFILE_KW, ENV_KW,
    INSTALL_MODE_KW, NoneType, output_validator,
)
from ..utils.core import HoldableObject
from ..utils.universal import File

if T.TYPE_CHECKING:
    from typing_extensions import Literal, TypedDict

    from . import ModuleState
    from .. import build
    from .._typing import ImmutableListProtocol
    from ..interpreter.interpreter import Interpreter
    from ..interpreter.kwargs import CustomTarget as CTKWs
    from ..utils.core import EnvironmentVariables
    from ..utils.universal import FileMode

    class _TemplateBaseKWs(TypedDict):

        build_always: bool
        build_always_stale: T.Optional[bool]
        build_by_default: T.Optional[bool]
        command: T.List[T.Union[build.BuildTargetTypes, programs.ExternalProgram, File, str]]
        depend_files: T.List[T.Union[str, File]]
        depends: T.List[T.Union[build.BuildTarget, build.CustomTarget]]
        depfile: T.Optional[str]
        env: EnvironmentVariables
        input: T.List[T.Union[str, build.BuildTarget, build.GeneratedTypes, build.ExtractedObjects,
                              programs.ExternalProgram, File]]
        install: T.Optional[bool]
        install_dir: T.List[T.Union[str, T.Literal[False]]]
        install_mode: FileMode
        install_tag: T.List[T.Optional[str]]
        output: T.List[str]

    class TemplateCallKWs(_TemplateBaseKWs):

        parameters: T.Dict[str, str]

    class TemplateExtendKws(_TemplateBaseKWs):

        parameters: T.List[str]

    class TemplateKws(CTKWs):

        parameters: T.List[str]


_OUTPUT_KW: KwargInfo[T.List[str]] = KwargInfo(
    'output',
    ContainerTypeInfo(list, str),
    listify=True,
    default=[],
    validator=output_validator,
)

_COMMAND_KW: KwargInfo[T.List[T.Union[str, build.BuildTargetTypes, programs.ExternalProgram, File]]] = KwargInfo(
    'command',
    ContainerTypeInfo(list, (str, BuildTarget, CustomTarget, CustomTargetIndex, programs.ExternalProgram, File)),
    listify=True,
    default=[],
)

# Can be unset
_INSTALL_KW: KwargInfo[T.Optional[bool]] = KwargInfo('install', (bool, NoneType))


def _params_validator(params: T.List[str]) -> T.Optional[str]:
    bad: T.List[str] = []
    for k in params:
        if k.isupper():
            bad.append(k)
    if bad:
        return (
            'Keys may not be all uppercase, as these may conflict with Meson reserved values. '
            'Bad keys: {}'.format(', '.join(bad)))
    return None


_PARAMS_KW: KwargInfo[T.List[str]] = KwargInfo(
    'parameters',
    ContainerTypeInfo(list, str),
    default=[],
    listify=True,
    validator=_params_validator,
)

@dataclass
class CustomTargetTemplate(HoldableObject):

    name: str
    command: ImmutableListProtocol[T.Union[build.BuildTargetTypes, programs.ExternalProgram, File, str]]
    build_by_default: bool
    build_always_stale: bool
    sources: ImmutableListProtocol[T.Union[
        build.BuildTarget, build.GeneratedTypes, build.ExtractedObjects,
        programs.ExternalProgram, File]]
    install_dir: ImmutableListProtocol[T.Union[str, Literal[False]]]
    install_tag: ImmutableListProtocol[str]
    install_mode: FileMode
    outputs: ImmutableListProtocol[str]
    depend_files: ImmutableListProtocol[File]
    depends: ImmutableListProtocol[T.Union[build.BuildTarget, build.CustomTarget]]
    depfile: T.Optional[str]
    env: EnvironmentVariables
    install: T.Optional[bool]
    feed: bool
    capture: bool
    console: bool
    params: ImmutableListProtocol[str]


class CustomTargetTemplateHolder(ObjectHolder[CustomTargetTemplate]):

    def __init__(self, obj: CustomTargetTemplate, interpreter: Interpreter) -> None:
        super().__init__(obj, interpreter)
        self.methods.update({
            'call': self.call,
            'extend': self.extend,
        })

    @T.overload
    @staticmethod
    def __format(name: str, params: T.Mapping[str, str], argument: str) -> str: ...

    @T.overload
    @staticmethod
    def __format(name: str, params: T.Mapping[str, str], argument: T.Union[str, File, build.BuildTargetTypes, programs.ExternalProgram]) -> \
        T.Union[str, File, build.BuildTargetTypes, programs.ExternalProgram]: ...

    @T.overload
    @staticmethod
    def __format(name: str, params: T.Mapping[str, str], argument: T.Union[str, File, build.GeneratedTypes, build.BuildTarget, build.ExtractedObjects, programs.ExternalProgram]) -> \
        T.Union[str, File, build.GeneratedList, build.BuildTarget, build.ExtractedObjects, programs.ExternalProgram]: ...

    @staticmethod
    def __format(name: str, params: T.Mapping[str, str], argument: T.Union[str, File, build.GeneratedTypes, build.BuildTarget, build.ExtractedObjects, programs.ExternalProgram]) -> \
            T.Union[str, File, build.GeneratedList, build.BuildTarget, build.ExtractedObjects, programs.ExternalProgram]:
        if isinstance(argument, str):
            argument = argument.replace('@NAME@', name)
            for k, v in params.items():
                argument = argument.replace(f'@{k}@', v)
        return argument

    @typed_pos_args('template.call', str)
    @typed_kwargs(
        'template.call',
        _COMMAND_KW,
        CT_INPUT_KW,
        CT_INSTALL_DIR_KW,
        CT_INSTALL_TAG_KW,
        _OUTPUT_KW,
        _INSTALL_KW,
        KwargInfo('parameters', ContainerTypeInfo(dict, str), default={}),
    )
    def call(self, args: T.Tuple[str], kwargs: TemplateCallKWs) -> CustomTarget:
        name = args[0]

        if len(self.held_object.params) != len(kwargs['parameters']):
            missing_parameters = [k for k in self.held_object.params if k not in kwargs['parameters']]
            if missing_parameters:
                raise InvalidArguments('The following template parameters are missing: ', ', '.join(missing_parameters))
            extra_parameters = [k for k in kwargs['parameters'] if k not in set(self.held_object.params)]
            if extra_parameters:
                raise InvalidArguments(
                    'The following parameters were passed to template.call, but were not defined in the template: ',
                    ', '.join(extra_parameters))
            raise RuntimeError('WAT!?')

        inputs = list(itertools.chain(
            self.interpreter.source_strings_to_files([self.__format(name, kwargs['parameters'], s) for s in kwargs['input']]),
            (self.__format(name, kwargs['parameters'], s) for s in self.held_object.sources)
        ))
        outputs = [self.__format(name, kwargs['parameters'], s) for s in
                   itertools.chain(self.held_object.outputs, kwargs['output'])]
        command = [self.__format(name, kwargs['parameters'], s) for s in
                   itertools.chain(self.held_object.command, kwargs['command'])]
        install_dir = self.held_object.install_dir + kwargs['install_dir']
        install_tag = self.held_object.install_tag + kwargs['install_tag']

        if not command:
            raise InvalidArguments('template.call: must have a command, but it is empty')
        if not outputs:
            raise InvalidArguments('template.call: must have at least one output, but it is empty')
        if len(inputs) > 1 and self.held_object.feed:
            raise InvalidArguments('template.call: "feed" keyword argument can only be used with a single input')
        if len(outputs) > 1 and self.held_object.capture:
            raise InvalidArguments('template.call: "capture" keyword argument can only be used with a single output')
        for c in command:
            if self.held_object.capture and isinstance(c, str) and '@OUTPUT@' in c:
                raise InvalidArguments('template.call: "capture" keyword argument cannot be used with "@OUTPUT@"')
            if self.held_object.feed and isinstance(c, str) and '@INPUT@' in c:
                raise InvalidArguments('template.call: "feed" keyword argument cannot be used with "@INPUT@"')
        if self.held_object.install and not install_dir:
            raise InvalidArguments('template.call: "install_dir" keyword argument must be set when "install" is true.')
        if len(install_tag) not in {0, 1, len(outputs)}:
            raise InvalidArguments('template.call: install_tag argument must have 0 or 1 outputs, '
                                   'or the same number of elements as the output keyword argument. '
                                   f'(there are {len(install_tag)} install_tags, '
                                   f'and {len(outputs)} outputs)')
        if kwargs['install'] is not None:
            if self.held_object.install is not None:
                raise InvalidArguments.from_node(
                    'template.extend: "install" was previous set to an explicit value, and cannot be overwritten.',
                    node=self.interpreter.current_node)
            install = kwargs['install']
        else:
            install = self.held_object.install or False

        ct = CustomTarget(
            name,
            self.interpreter.subdir,
            self.interpreter.subproject,
            self.interpreter.environment,
            command,
            inputs,
            outputs,
            build_always_stale=self.held_object.build_always_stale,
            build_by_default=self.held_object.build_by_default,
            capture=self.held_object.capture,
            console=self.held_object.capture,
            depend_files=self.held_object.depend_files.copy(),
            depfile=self.__format(name, kwargs['parameters'], self.held_object.depfile) if self.held_object.depfile else None,
            extra_depends=self.held_object.depends.copy(),
            env=self.held_object.env,
            feed=self.held_object.feed,
            install=install,
            install_dir=install_dir,
            install_mode=self.held_object.install_mode,
            install_tag=install_tag,
            backend=self.interpreter.backend,
        )
        self.interpreter.add_target(name, ct)
        return ct

    @typed_pos_args('template.extend', str)
    @typed_kwargs(
        'template.extend',
        _COMMAND_KW,
        CT_INPUT_KW,
        CT_INSTALL_DIR_KW,
        CT_INSTALL_TAG_KW,
        _OUTPUT_KW,
        _INSTALL_KW,
        _PARAMS_KW,
    )
    def extend(self, args: T.Tuple[str], kwargs: TemplateExtendKws) -> CustomTargetTemplate:
        special = copy.copy(self.held_object)
        special.name = args[0]

        if kwargs['command']:
            special.command = special.command + kwargs['command']
        if kwargs['input']:
            special.sources = special.sources + self.interpreter.source_strings_to_files(kwargs['input'])
        if kwargs['install_dir']:
            special.install_dir = special.install_dir + kwargs['install_dir']
        if kwargs['install_tag']:
            special.install_tag = special.install_tag + kwargs['install_tag']
        if kwargs['output']:
            special.outputs = special.outputs + kwargs['output']
        if kwargs['install'] is not None:
            if special.install is not None:
                raise InvalidArguments.from_node(
                    'template.extend: "install" was previous set to an explicit value, and cannot be overwritten.',
                    node=self.interpreter.current_node)
            special.install = kwargs['install']
        if kwargs['parameters']:
            special.params = special.params + kwargs['parameters']

        return special


class GeneratorModule(NewExtensionModule):

    INFO = ModuleInfo('generator', '1.5.0', unstable=True)

    def __init__(self) -> None:
        super().__init__()
        self.methods.update({
            'template': self.template,
        })

    @typed_pos_args('generator.template', str)
    @typed_kwargs(
        'generator.template',
        _COMMAND_KW,
        CT_BUILD_ALWAYS_STALE,
        CT_BUILD_BY_DEFAULT,
        CT_INPUT_KW,
        CT_INSTALL_DIR_KW,
        CT_INSTALL_TAG_KW,
        DEPENDS_KW,
        DEPEND_FILES_KW,
        DEPFILE_KW,
        ENV_KW,
        INSTALL_MODE_KW,
        _OUTPUT_KW,
        _INSTALL_KW,
        _PARAMS_KW,
        KwargInfo('install', (bool, NoneType)),
        KwargInfo('feed', bool, default=False),
        KwargInfo('capture', bool, default=False),
        KwargInfo('console', bool, default=False),
    )
    def template(self, state: ModuleState, args: T.Tuple[str], kwargs: TemplateKws) -> CustomTargetTemplate:
        # TODO: validate lengths of various things.
        name = args[0]

        if kwargs['capture'] and kwargs['console']:
            raise InvalidArguments.from_node(
                'generator.template: "capture" and "console" keyword arguments are mutually exclusive',
                node=state.current_node)
        try:
            for t in kwargs['output']:
                state._interpreter.validate_forbidden_targets(t)
        except InvalidArguments as e:
            raise InvalidArguments.from_node('generator.template: ', str(e), node=state.current_node)

        return CustomTargetTemplate(
            name,
            kwargs['command'],
            kwargs['build_by_default'],
            kwargs['build_always_stale'],
            state._interpreter.source_strings_to_files(kwargs['input']),
            kwargs['install_dir'],
            kwargs['install_tag'],
            state._interpreter._warn_kwarg_install_mode_sticky(kwargs['install_mode']),
            kwargs['output'],
            state._interpreter.source_strings_to_files(kwargs['depend_files']),
            kwargs['depends'],
            kwargs['depfile'],
            kwargs['env'],
            kwargs['install'],
            kwargs['feed'],
            kwargs['capture'],
            kwargs['console'],
            kwargs['parameters'],
        )


def initialize(interp: Interpreter) -> GeneratorModule:
    interp.holder_map[CustomTargetTemplate] = CustomTargetTemplateHolder
    return GeneratorModule()
