# SPDX-License-Identifier: Apache-2.0
# Copyright 2013-2021 The Meson development team

from __future__ import annotations

import typing as T

from ..mesonlib import HoldableObject, MesonBugException
from .baseobjects import HoldableTypes, InterpreterObject, MesonInterpreterObject, ObjectHolder
from .exceptions import InvalidArguments

if T.TYPE_CHECKING:
    from .baseobjects import TYPE_var

def _unholder(obj: InterpreterObject) -> TYPE_var:
    if isinstance(obj, ObjectHolder):
        assert isinstance(obj.held_object, HoldableTypes)
        return obj.held_object
    elif isinstance(obj, MesonInterpreterObject):
        return obj
    elif isinstance(obj, HoldableObject):
        raise MesonBugException(f'Argument {obj} of type {type(obj).__name__} is not held by an ObjectHolder.')
    elif isinstance(obj, InterpreterObject):
        raise InvalidArguments(f'Argument {obj} of type {type(obj).__name__} cannot be passed to a method or function')
    raise MesonBugException(f'Unknown object {obj} of type {type(obj).__name__} in the parameters.')
