# Copyright 2012-2022 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Contains the strict minimum to run scripts.

When the backend needs to call back into Meson during compilation for running
scripts or wrapping commands, it is important to load as little python modules
as possible for performance reasons.
"""

from __future__ import annotations
from dataclasses import dataclass
import os
import abc
import typing as T

if T.TYPE_CHECKING:
    from hashlib import _Hash
    from typing_extensions import Literal
    from ..mparser import BaseNode
    from .. import programs

    EnvironOrDict = T.Union[T.Dict[str, str], os._Environ[str]]

    EnvInitValueType = T.Dict[str, T.Union[str, T.List[str]]]


class MesonException(Exception):
    '''Exceptions thrown by Meson'''

    def __init__(self, *args: object, file: T.Optional[str] = None,
                 lineno: T.Optional[int] = None, colno: T.Optional[int] = None):
        super().__init__(*args)
        self.file = file
        self.lineno = lineno
        self.colno = colno

    def update_position(self, node: BaseNode) -> None:
        """Set file and line information from a node

        :param node: A node object to get the information from
        """
        self.file = node.filename
        self.lineno = node.lineno
        self.colno = node.colno

    @classmethod
    def from_node(cls, *args: object, node: BaseNode) -> MesonException:
        """Create a MesonException with location data from a BaseNode

        :param node: A BaseNode to set location data from
        :return: A Meson Exception instance
        """
        return cls(*args, file=node.filename, lineno=node.lineno, colno=node.colno)


class MesonExceptionWrapper(Exception):

    """Exception that wraps a non-meson exception with parser information.

    This allows use to store parsing information for non-meson exception (the
    file, line and colum numbers), without resorting to adding new attributes
    and calling hasattr/getattr everywhere.
    """

    def __init__(self, e: Exception, file: T.Optional[str] = None,
                 lineno: T.Optional[int] = None, colno: T.Optional[int] = None):
        super().__init__('Unhandled python exception')
        # Force python to not show the MesonExceptionWrapper as a cause for the wrapped exception
        # See: https://peps.python.org/pep-3134/#open-issue-suppressing-context
        # for why this happens
        e.__cause__ = None

        self.wrapped = e
        self.file = file
        self.lineno = lineno
        self.colno = colno

    @classmethod
    def from_node(cls, e: Exception, node: BaseNode) -> MesonExceptionWrapper:
        """Create a MesonExceptionWrapper with location data from a BaseNode

        :param node: A BaseNode to set location data from
        :return: A MesonExceptionWrapper instance
        """
        return cls(e, file=node.filename, lineno=node.lineno, colno=node.colno)

    def __str__(self) -> str:
        # We always want to return the string value of the wrapped error
        return super().__str__()

    def __repr__(self) -> str:
        return f'MesonExceptionWrapper({self.wrapped!r}, {self.file!r}, {self.lineno!r}, {self.colno!r})'


class MesonBugException(MesonException):
    '''Exceptions thrown when there is a clear Meson bug that should be reported'''

    def __init__(self, msg: str, file: T.Optional[str] = None,
                 lineno: T.Optional[int] = None, colno: T.Optional[int] = None):
        super().__init__(msg + '\n\n    This is a Meson bug and should be reported!',
                         file=file, lineno=lineno, colno=colno)

class HoldableObject(metaclass=abc.ABCMeta):
    ''' Dummy base class for all objects that can be
        held by an interpreter.baseobjects.ObjectHolder '''

class EnvironmentVariables(HoldableObject):
    def __init__(self, values: T.Optional[EnvInitValueType] = None,
                 init_method: Literal['set', 'prepend', 'append'] = 'set', separator: str = os.pathsep) -> None:
        self.envvars: T.List[T.Tuple[T.Callable[[T.Dict[str, str], str, T.List[str], str, T.Optional[str]], str], str, T.List[str], str]] = []
        # The set of all env vars we have operations for. Only used for self.has_name()
        self.varnames: T.Set[str] = set()

        if values:
            init_func = getattr(self, init_method)
            for name, value in values.items():
                v = value if isinstance(value, list) else [value]
                init_func(name, v, separator)

    def __repr__(self) -> str:
        repr_str = "<{0}: {1}>"
        return repr_str.format(self.__class__.__name__, self.envvars)

    def hash(self, hasher: _Hash) -> None:
        myenv = self.get_env({})
        for key in sorted(myenv.keys()):
            hasher.update(bytes(key, encoding='utf-8'))
            hasher.update(b',')
            hasher.update(bytes(myenv[key], encoding='utf-8'))
            hasher.update(b';')

    def has_name(self, name: str) -> bool:
        return name in self.varnames

    def get_names(self) -> T.Set[str]:
        return self.varnames

    def merge(self, other: EnvironmentVariables) -> None:
        for method, name, values, separator in other.envvars:
            self.varnames.add(name)
            self.envvars.append((method, name, values, separator))

    def set(self, name: str, values: T.List[str], separator: str = os.pathsep) -> None:
        self.varnames.add(name)
        self.envvars.append((self._set, name, values, separator))

    def append(self, name: str, values: T.List[str], separator: str = os.pathsep) -> None:
        self.varnames.add(name)
        self.envvars.append((self._append, name, values, separator))

    def prepend(self, name: str, values: T.List[str], separator: str = os.pathsep) -> None:
        self.varnames.add(name)
        self.envvars.append((self._prepend, name, values, separator))

    @staticmethod
    def _set(env: T.Dict[str, str], name: str, values: T.List[str], separator: str, default_value: T.Optional[str]) -> str:
        return separator.join(values)

    @staticmethod
    def _append(env: T.Dict[str, str], name: str, values: T.List[str], separator: str, default_value: T.Optional[str]) -> str:
        curr = env.get(name, default_value)
        return separator.join(values if curr is None else [curr] + values)

    @staticmethod
    def _prepend(env: T.Dict[str, str], name: str, values: T.List[str], separator: str, default_value: T.Optional[str]) -> str:
        curr = env.get(name, default_value)
        return separator.join(values if curr is None else values + [curr])

    def get_env(self, full_env: EnvironOrDict, default_fmt: T.Optional[str] = None) -> T.Dict[str, str]:
        env = full_env.copy()
        for method, name, values, separator in self.envvars:
            default_value = default_fmt.format(name) if default_fmt else None
            env[name] = method(env, name, values, separator, default_value)
        return env


@dataclass(eq=False)
class ExecutableSerialisation:

    # XXX: should capture and feed default to False, instead of None?

    cmd_args: T.List[str]
    env: T.Optional[EnvironmentVariables] = None
    exe_wrapper: T.Optional['programs.ExternalProgram'] = None
    workdir: T.Optional[str] = None
    extra_paths: T.Optional[T.List] = None
    capture: T.Optional[bool] = None
    feed: T.Optional[bool] = None
    tag: T.Optional[str] = None
    verbose: bool = False
    installdir_map: T.Optional[T.Dict[str, str]] = None

    def __post_init__(self) -> None:
        self.pickled = False
        self.skip_if_destdir = False
        self.subproject = ''
        self.dry_run = False
