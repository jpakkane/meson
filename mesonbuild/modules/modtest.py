# SPDX-License-Identifier: Apache-2.0
# Copyright 2015 The Meson development team

from __future__ import annotations

import typing as T

from ..interpreterbase import noKwargs, noPosargs
from . import ModuleInfo, NewExtensionModule

if T.TYPE_CHECKING:
    from ..interpreter.interpreter import Interpreter
    from ..interpreterbase.baseobjects import TYPE_kwargs, TYPE_var
    from . import ModuleState


class TestModule(NewExtensionModule):

    INFO = ModuleInfo('modtest')

    def __init__(self, interpreter: Interpreter) -> None:
        super().__init__()
        self.methods.update({
            'print_hello': self.print_hello,
        })

    @noKwargs
    @noPosargs
    def print_hello(self, state: ModuleState, args: T.List[TYPE_var], kwargs: TYPE_kwargs) -> None:
        print('Hello from a Meson module')


def initialize(interp: Interpreter) -> TestModule:
    return TestModule(interp)
