# SPDX-License-Identifier: Apache-2.0
# Copyright © 2024 Intel Corporation

from __future__ import annotations
import dataclasses
import os
import typing as T

from . import ExtensionModule, ModuleInfo, ModuleReturnValue
from ..build import CustomTarget, CustomTargetIndex, GeneratedList
from ..interpreter.type_checking import NoneType
from ..interpreterbase import (
    ContainerTypeInfo, KwargInfo, typed_pos_args, typed_kwargs
)
from ..mesonlib import File, MesonException, Popen_safe
from ..programs import ExternalProgram
from .. import mlog

if T.TYPE_CHECKING:
    from typing_extensions import Literal, TypeAlias, TypedDict

    from . import ModuleState
    from ..mesonlib import FileOrString
    from ..build import Executable
    from ..interpreter import Interpreter
    from ..programs import OverrideProgram
    from .._typing import ImmutableListProtocol

    Program: TypeAlias = T.Union[Executable, ExternalProgram, OverrideProgram]

    class LexKwargs(TypedDict):

        args: T.List[str]
        version: T.List[str]
        source: T.Optional[str]
        header: T.Optional[str]
        table: T.Optional[str]
        plainname: bool


@dataclasses.dataclass
class Generator:

    program: Program
    arguments: ImmutableListProtocol[str] = dataclasses.field(default_factory=list)

    def command(self) -> T.List[T.Union[Program, str]]:
        return (T.cast('T.List[T.Union[Program, str]]', [self.program]) +
                T.cast('T.List[T.Union[Program, str]]', self.arguments))


class CodeGenModule(ExtensionModule):

    """Module with helpers for codegen wrappers."""

    INFO = ModuleInfo('codegen', '1.6.0', unstable=True)

    def __init__(self, interpreter: Interpreter) -> None:
        super().__init__(interpreter)
        self._generators: T.Dict[Literal['lex'], Generator] = {}
        self.methods.update({
            'lex': self.lex_method,
        })

    def __find_lex(self, state: ModuleState, version: T.List[str]) -> None:
        names: T.List[FileOrString] = []
        assert state.environment.machines.host is not None, 'for mypy'
        if state.environment.machines.host.system == 'windows':
            names.append('win_flex')
        names.extend(['flex', 'lex'])

        for name in names:
            bin = state.find_program(name, wanted=version, required=name == names[-1])
            if bin.found():
                # If you're building reflex as a subproject, we consider that you
                # know what you're doing.
                if name == 'reflex' and isinstance(bin, ExternalProgram):
                    # there are potentially 3 programs called "reflex":
                    # 1. https://invisible-island.net/reflex/, an alternate fork
                    #    of the original flex, this is supported
                    # 2. https://www.genivia.com/doc/reflex/html/, an
                    #    alternative implementation for generating C++ scanners.
                    #    Not supported
                    # 3. https://github.com/cespare/reflex, which is not a lex
                    #    implementation at all, but a file watcher
                    _, out, err = Popen_safe(bin.get_command() + ['--version'])
                    if 'unknown flag: --version' in err:
                        mlog.debug('Skipping cespare/reflex, which is not a lexer and is not supported')
                        continue
                    if 'Written by Robert van Engelen' in out:
                        mlog.debug('Skipping RE/flex, which is not generally compatible with POSIX lex.')
                        continue
                break

        args: T.List[str] = []
        if bin.name == 'win_flex':
            args.append('--wincompat')
        args.extend(['-o', '@OUTPUT0@', '@INPUT@'])
        self._generators['lex'] = Generator(bin, T.cast('ImmutableListProtocol[str]', args))

    @typed_pos_args('codegen.lex', (str, File, GeneratedList, CustomTarget, CustomTargetIndex))
    @typed_kwargs(
        'codegen.lex',
        KwargInfo('version', ContainerTypeInfo(list, str), default=[], listify=True),
        KwargInfo('args', ContainerTypeInfo(list, str), default=[], listify=True),
        KwargInfo('source', (str, NoneType)),
        KwargInfo('header', (str, NoneType)),
        KwargInfo('table', (str, NoneType)),
        KwargInfo('plainname', bool, default=False),
    )
    def lex_method(self, state: ModuleState, args: T.Tuple[T.Union[str, File, GeneratedList, CustomTarget, CustomTargetIndex]], kwargs: LexKwargs) -> ModuleReturnValue:
        if 'lex' not in self._generators:
            self.__find_lex(state, kwargs['version'])

        input = state._interpreter.source_strings_to_files([args[0]])[0]
        if isinstance(input, File):
            is_cpp = input.endswith(".ll")
            name = os.path.splitext(input.fname)[0]
        else:
            is_cpp = input.get_outputs()[0].endswith('.ll')
            name = os.path.splitext(input.get_outputs()[0])[0]
        name = os.path.basename(name)

        if is_cpp and 'flex' in self._generators['lex'].program.name:
            # Flex uses FlexLexer.h for C++ code
            try:
                found = state.environment.coredata.compilers.host['cpp'].has_header('FlexLexer.h', '', state.environment)
                if not found[0]:
                    raise MesonException('Could not find FlexLexer.h, which is required for Flex with C++')
            except KeyError:
                raise MesonException("Could not find a C++ compiler to search for FlexLexer.h")

        if kwargs['source'] is None:
            outputs = [f'@BASENAME@.{"cpp" if is_cpp else "c"}']
        else:
            outputs = [kwargs['source']]

        command = self._generators['lex'].command()
        if kwargs['header'] is not None:
            outputs.append(kwargs['header'])
            command.append(f'--header-file=@OUTPUT{len(outputs)}@')
        if kwargs['table'] is not None:
            outputs.append(kwargs['table'])
            command.append(f'--tables-file=@OUTPUT{len(outputs)}@')
        command.extend(kwargs['args'])

        target = CustomTarget(
            f'codegen-lex-{name}',
            state.subdir,
            state.subproject,
            state.environment,
            command,
            [input],
            outputs,
            backend=state.backend,
            description='Generating lexer {} with lex',
        )

        return ModuleReturnValue(target, [target])


def initialize(interpreter: Interpreter) -> CodeGenModule:
    return CodeGenModule(interpreter)
