# SPDX-License-Identifier: Apache-2.0
# Copyright 2015 The Meson development team

from __future__ import annotations

import typing as T

from . import ModuleInfo
from .qt import QtBaseModule

if T.TYPE_CHECKING:
    from ..interpreter import Interpreter


class Qt4Module(QtBaseModule):

    INFO = ModuleInfo('qt4')

    def __init__(self, interpreter: Interpreter):
        QtBaseModule.__init__(self, interpreter, qt_version=4)


def initialize(interp: Interpreter) -> Qt4Module:
    return Qt4Module(interp)
