# Copyright 2013-2021 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

__all__ = [
    'InterpreterObject',
    'MesonInterpreterObject',
    'ObjectHolder',
    'IterableObject',
    'MutableInterpreterObject',

    'MesonOperator',

    'Disabler',
    'is_disabled',

    'InterpreterException',
    'InvalidCode',
    'InvalidArguments',
    'SubdirDoneRequest',
    'ContinueRequest',
    'BreakRequest',

    'default_resolve_key',
    'flatten',
    'resolve_second_level_holders',

    'noPosargs',
    'noKwargs',
    'stringArgs',
    'noArgsFlattening',
    'noSecondLevelHolderResolving',
    'unholder_return',
    'disablerIfNotFound',
    'permittedKwargs',
    'typed_operator',
    'unary_operator',
    'typed_pos_args',
    'ContainerTypeInfo',
    'KwargInfo',
    'typed_kwargs',
    'FeatureCheckBase',
    'FeatureNew',
    'FeatureDeprecated',
    'FeatureNewKwargs',
    'FeatureDeprecatedKwargs',

    'InterpreterBase',

    'SubProject',

    'TV_fw_var',
    'TV_fw_args',
    'TV_fw_kwargs',
    'TV_func',
    'TYPE_elementary',
    'TYPE_var',
    'TYPE_nvar',
    'TYPE_kwargs',
    'TYPE_nkwargs',
    'TYPE_key_resolver',
    'TYPE_HoldableTypes',

    'HoldableTypes',
]

from .baseobjects import (
    HoldableTypes, InterpreterObject, IterableObject, MesonInterpreterObject,
    MutableInterpreterObject, ObjectHolder, SubProject, TV_func, TV_fw_args,
    TV_fw_kwargs, TV_fw_var, TYPE_elementary, TYPE_HoldableTypes,
    TYPE_key_resolver, TYPE_kwargs, TYPE_nkwargs, TYPE_nvar, TYPE_var
)
from .decorators import (
    ContainerTypeInfo, FeatureCheckBase, FeatureDeprecated,
    FeatureDeprecatedKwargs, FeatureNew, FeatureNewKwargs, KwargInfo,
    disablerIfNotFound, noArgsFlattening, noKwargs, noPosargs,
    noSecondLevelHolderResolving, permittedKwargs, stringArgs, typed_kwargs,
    typed_operator, typed_pos_args, unary_operator, unholder_return
)
from .disabler import Disabler, is_disabled
from .exceptions import (
    BreakRequest, ContinueRequest, InterpreterException, InvalidArguments,
    InvalidCode, SubdirDoneRequest
)
from .helpers import default_resolve_key, flatten, resolve_second_level_holders
from .interpreterbase import InterpreterBase
from .operator import MesonOperator
