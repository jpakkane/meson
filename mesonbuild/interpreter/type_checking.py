# SPDX-License-Identifier: Apache-2.0
# Copyright © 2021 Intel Corporation

"""Helpers for strict type checking."""

from __future__ import annotations
import os
import re
import typing as T

from .. import compilers
from ..build import (
    BothLibraries,
    BuildTarget,
    CustomTarget,
    CustomTargetIndex,
    EnvInitValueType,
    EnvironmentVariables,
    Executable,
    ExtractedObjects,
    GeneratedList,
    IncludeDirs,
    Jar,
    SharedLibrary,
    SharedModule,
    StaticLibrary,
    StructuredSources,
)
from ..coredata import UserFeatureOption
from ..dependencies import Dependency, InternalDependency
from .. import environment
from ..interpreterbase.decorators import KwargInfo, ContainerTypeInfo
from ..mesonlib import File, FileMode, MachineChoice, listify, has_path_sep, OptionKey
from ..programs import ExternalProgram

# Helper definition for type checks that are `Optional[T]`
NoneType: T.Type[None] = type(None)

if T.TYPE_CHECKING:
    from typing_extensions import Literal

    from ..interpreterbase import TYPE_var

def in_set_validator(choices: T.Set[str]) -> T.Callable[[str], T.Optional[str]]:
    """Check that the choice given was one of the given set."""

    def inner(check: str) -> T.Optional[str]:
        if check not in choices:
            return f"must be one of {', '.join(sorted(choices))}, not {check}"
        return None

    return inner


def _language_validator(l: T.List[str]) -> T.Optional[str]:
    """Validate language keyword argument.

    Particularly for functions like `add_compiler()`, and `add_*_args()`
    """
    diff = {a.lower() for a in l}.difference(compilers.all_languages)
    if diff:
        return f'unknown languages: {", ".join(diff)}'
    return None


def _install_mode_validator(mode: T.List[T.Union[str, bool, int]]) -> T.Optional[str]:
    """Validate the `install_mode` keyword argument.

    This is a rather odd thing, it's a scalar, or an array of 3 values in the form:
    [(str | False), (str | int | False) = False, (str | int | False) = False]
    where the second and third components are not required and default to False.
    """
    if not mode:
        return None
    if True in mode:
        return 'components can only be permission strings, numbers, or False'
    if len(mode) > 3:
        return 'may have at most 3 elements'

    perms = mode[0]
    if not isinstance(perms, (str, bool)):
        return 'first component must be a permissions string or False'

    if isinstance(perms, str):
        if not len(perms) == 9:
            return ('permissions string must be exactly 9 characters in the form rwxr-xr-x,'
                    f' got {len(perms)}')
        for i in [0, 3, 6]:
            if perms[i] not in {'-', 'r'}:
                return f'permissions character {i+1} must be "-" or "r", not {perms[i]}'
        for i in [1, 4, 7]:
            if perms[i] not in {'-', 'w'}:
                return f'permissions character {i+1} must be "-" or "w", not {perms[i]}'
        for i in [2, 5]:
            if perms[i] not in {'-', 'x', 's', 'S'}:
                return f'permissions character {i+1} must be "-", "s", "S", or "x", not {perms[i]}'
        if perms[8] not in {'-', 'x', 't', 'T'}:
            return f'permission character 9 must be "-", "t", "T", or "x", not {perms[8]}'

        if len(mode) >= 2 and not isinstance(mode[1], (int, str, bool)):
            return 'second componenent can only be a string, number, or False'
        if len(mode) >= 3 and not isinstance(mode[2], (int, str, bool)):
            return 'third componenent can only be a string, number, or False'

    return None


def _install_mode_convertor(mode: T.Optional[T.List[T.Union[str, bool, int]]]) -> FileMode:
    """Convert the DSL form of the `install_mode` keyword argument to `FileMode`

    This is not required, and if not required returns None

    TODO: It's not clear to me why this needs to be None and not just return an
    empty FileMode.
    """
    # this has already been validated by the validator
    return FileMode(*(m if isinstance(m, str) else None for m in mode))


def _lower_strlist(input: T.List[str]) -> T.List[str]:
    """Lower a list of strings.

    mypy (but not pyright) gets confused about using a lambda as the convertor function
    """
    return [i.lower() for i in input]


def variables_validator(contents: T.Union[T.List[str], T.Dict[str, str]]) -> T.Optional[str]:
    if isinstance(contents, dict):
        variables = contents
    else:
        variables = {}
        for v in contents:
            try:
                key, val = v.split('=', 1)
            except ValueError:
                return f'variable {v!r} must have a value separated by equals sign.'
            variables[key.strip()] = val.strip()
    for k, v in variables.items():
        if not k:
            return 'empty variable name'
        if not v:
            return 'empty variable value'
        if any(c.isspace() for c in k):
            return f'invalid whitespace in variable name {k!r}'
    return None


def variables_convertor(contents: T.Union[T.List[str], T.Dict[str, str]]) -> T.Dict[str, str]:
    if isinstance(contents, dict):
        return contents
    variables = {}
    for v in contents:
        key, val = v.split('=', 1)
        variables[key.strip()] = val.strip()
    return variables


NATIVE_KW = KwargInfo(
    'native', bool,
    default=False,
    convertor=lambda n: MachineChoice.BUILD if n else MachineChoice.HOST)

LANGUAGE_KW = KwargInfo(
    'language', ContainerTypeInfo(list, str, allow_empty=False),
    listify=True,
    required=True,
    validator=_language_validator,
    convertor=_lower_strlist)

INSTALL_MODE_KW: KwargInfo[T.List[T.Union[str, bool, int]]] = KwargInfo(
    'install_mode',
    ContainerTypeInfo(list, (str, bool, int)),
    listify=True,
    default=[],
    validator=_install_mode_validator,
    convertor=_install_mode_convertor,
)

REQUIRED_KW: KwargInfo[T.Union[bool, UserFeatureOption]] = KwargInfo(
    'required',
    (bool, UserFeatureOption),
    default=True,
    # TODO: extract_required_kwarg could be converted to a convertor
)

DISABLER_KW: KwargInfo[bool] = KwargInfo('disabler', bool, default=False)

def _env_validator(value: T.Union[EnvironmentVariables, T.List['TYPE_var'], T.Dict[str, 'TYPE_var'], str, None],
                   allow_dict_list: bool = True) -> T.Optional[str]:
    def _splitter(v: str) -> T.Optional[str]:
        split = v.split('=', 1)
        if len(split) == 1:
            return f'"{v}" is not two string values separated by an "="'
        return None

    if isinstance(value, str):
        v = _splitter(value)
        if v is not None:
            return v
    elif isinstance(value, list):
        for i in listify(value):
            if not isinstance(i, str):
                return f"All array elements must be a string, not {i!r}"
            v = _splitter(i)
            if v is not None:
                return v
    elif isinstance(value, dict):
        # We don't need to spilt here, just do the type checking
        for k, dv in value.items():
            if allow_dict_list:
                if any(i for i in listify(dv) if not isinstance(i, str)):
                    return f"Dictionary element {k} must be a string or list of strings not {dv!r}"
            elif not isinstance(dv, str):
                return f"Dictionary element {k} must be a string not {dv!r}"
    # We know that otherwise we have an EnvironmentVariables object or None, and
    # we're okay at this point
    return None

def _options_validator(value: T.Union[EnvironmentVariables, T.List['TYPE_var'], T.Dict[str, 'TYPE_var'], str, None]) -> T.Optional[str]:
    # Reusing the env validator is a littl overkill, but nicer than duplicating the code
    return _env_validator(value, allow_dict_list=False)

def split_equal_string(input: str) -> T.Tuple[str, str]:
    """Split a string in the form `x=y`

    This assumes that the string has already been validated to split properly.
    """
    a, b = input.split('=', 1)
    return (a, b)

_FullEnvInitValueType = T.Union[EnvironmentVariables, T.List[str], T.List[T.List[str]], EnvInitValueType, str, None]

# Split _env_convertor() and env_convertor_with_method() to make mypy happy.
# It does not want extra arguments in KwargInfo convertor callable.
def env_convertor_with_method(value: _FullEnvInitValueType,
                              init_method: Literal['set', 'prepend', 'append'] = 'set',
                              separator: str = os.pathsep) -> EnvironmentVariables:
    if isinstance(value, str):
        return EnvironmentVariables(dict([split_equal_string(value)]), init_method, separator)
    elif isinstance(value, list):
        return EnvironmentVariables(dict(split_equal_string(v) for v in listify(value)), init_method, separator)
    elif isinstance(value, dict):
        return EnvironmentVariables(value, init_method, separator)
    elif value is None:
        return EnvironmentVariables()
    return value

def _env_convertor(value: _FullEnvInitValueType) -> EnvironmentVariables:
    return env_convertor_with_method(value)

ENV_KW: KwargInfo[T.Union[EnvironmentVariables, T.List, T.Dict, str, None]] = KwargInfo(
    'env',
    (EnvironmentVariables, list, dict, str, NoneType),
    validator=_env_validator,
    convertor=_env_convertor,
)

DEPFILE_KW: KwargInfo[T.Optional[str]] = KwargInfo(
    'depfile',
    (str, type(None)),
    validator=lambda x: 'Depfile must be a plain filename with a subdirectory' if has_path_sep(x) else None
)

# TODO: CustomTargetIndex should be supported here as well
DEPENDS_KW: KwargInfo[T.List[T.Union[BuildTarget, CustomTarget]]] = KwargInfo(
    'depends',
    ContainerTypeInfo(list, (BuildTarget, CustomTarget)),
    listify=True,
    default=[],
)

DEPEND_FILES_KW: KwargInfo[T.List[T.Union[str, File]]] = KwargInfo(
    'depend_files',
    ContainerTypeInfo(list, (File, str)),
    listify=True,
    default=[],
)

COMMAND_KW: KwargInfo[T.List[T.Union[str, BuildTarget, CustomTarget, CustomTargetIndex, ExternalProgram, File]]] = KwargInfo(
    'command',
    # TODO: should accept CustomTargetIndex as well?
    ContainerTypeInfo(list, (str, BuildTarget, CustomTarget, CustomTargetIndex, ExternalProgram, File), allow_empty=False),
    required=True,
    listify=True,
    default=[],
)

def _override_options_convertor(raw: T.List[str]) -> T.Dict[OptionKey, str]:
    output: T.Dict[OptionKey, str] = {}
    for each in raw:
        k, v = split_equal_string(each)
        output[OptionKey.from_string(k)] = v
    return output


OVERRIDE_OPTIONS_KW: KwargInfo[T.List[str]] = KwargInfo(
    'override_options',
    ContainerTypeInfo(list, str),
    listify=True,
    default=[],
    validator=_options_validator,
    convertor=_override_options_convertor,
)


def _output_validator(outputs: T.List[str]) -> T.Optional[str]:
    for i in outputs:
        if i == '':
            return 'Output must not be empty.'
        elif i.strip() == '':
            return 'Output must not consist only of whitespace.'
        elif has_path_sep(i):
            return f'Output {i!r} must not contain a path segment.'
        elif '@INPUT' in i:
            return f'output {i!r} contains "@INPUT", which is invalid. Did you mean "@PLAINNAME@" or "@BASENAME@?'

    return None

MULTI_OUTPUT_KW: KwargInfo[T.List[str]] = KwargInfo(
    'output',
    ContainerTypeInfo(list, str, allow_empty=False),
    listify=True,
    required=True,
    default=[],
    validator=_output_validator,
)

OUTPUT_KW: KwargInfo[str] = KwargInfo(
    'output',
    str,
    required=True,
    validator=lambda x: _output_validator([x])
)

CT_INPUT_KW: KwargInfo[T.List[T.Union[str, File, ExternalProgram, BuildTarget, CustomTarget, CustomTargetIndex, ExtractedObjects, GeneratedList]]] = KwargInfo(
    'input',
    ContainerTypeInfo(list, (str, File, ExternalProgram, BuildTarget, CustomTarget, CustomTargetIndex, ExtractedObjects, GeneratedList)),
    listify=True,
    default=[],
)

CT_INSTALL_TAG_KW: KwargInfo[T.List[T.Union[str, bool]]] = KwargInfo(
    'install_tag',
    ContainerTypeInfo(list, (str, bool)),
    listify=True,
    default=[],
    since='0.60.0',
    convertor=lambda x: [y if isinstance(y, str) else None for y in x],
)

INSTALL_TAG_KW: KwargInfo[T.Optional[str]] = KwargInfo('install_tag', (str, NoneType))

INSTALL_KW = KwargInfo('install', bool, default=False)

CT_INSTALL_DIR_KW: KwargInfo[T.List[T.Union[str, Literal[False]]]] = KwargInfo(
    'install_dir',
    ContainerTypeInfo(list, (str, bool)),
    listify=True,
    default=[],
    validator=lambda x: 'must be `false` if boolean' if True in x else None,
)

CT_BUILD_BY_DEFAULT: KwargInfo[T.Optional[bool]] = KwargInfo('build_by_default', (bool, type(None)), since='0.40.0')

CT_BUILD_ALWAYS: KwargInfo[T.Optional[bool]] = KwargInfo(
    'build_always', (bool, NoneType),
    deprecated='0.47.0',
    deprecated_message='combine build_by_default and build_always_stale instead.',
)

CT_BUILD_ALWAYS_STALE: KwargInfo[T.Optional[bool]] = KwargInfo(
    'build_always_stale', (bool, NoneType),
    since='0.47.0',
)

INSTALL_DIR_KW: KwargInfo[T.Optional[str]] = KwargInfo('install_dir', (str, NoneType))

INCLUDE_DIRECTORIES: KwargInfo[T.List[T.Union[str, IncludeDirs]]] = KwargInfo(
    'include_directories',
    ContainerTypeInfo(list, (str, IncludeDirs)),
    listify=True,
    default=[],
)

# for cases like default_options and override_options
DEFAULT_OPTIONS: KwargInfo[T.List[str]] = KwargInfo(
    'default_options',
    ContainerTypeInfo(list, str),
    listify=True,
    default=[],
    validator=_options_validator,
)

ENV_METHOD_KW = KwargInfo('method', str, default='set', since='0.62.0',
    validator=in_set_validator({'set', 'prepend', 'append'}))

ENV_SEPARATOR_KW = KwargInfo('separator', str, default=os.pathsep)

DEPENDENCIES_KW: KwargInfo[T.List[Dependency]] = KwargInfo(
    'dependencies',
    # InternalDependency is a subclass of Dependency, but we want to
    # print it in error messages
    ContainerTypeInfo(list, (Dependency, InternalDependency)),
    listify=True,
    default=[],
)

D_MODULE_VERSIONS_KW: KwargInfo[T.List[T.Union[str, int]]] = KwargInfo(
    'd_module_versions',
    ContainerTypeInfo(list, (str, int)),
    listify=True,
    default=[],
)

_link_with_error = '''can only be self-built targets, external dependencies (including libraries) must go in "dependencies".'''

# Allow Dependency for the better error message? But then in other cases it will list this as one of the allowed types!
LINK_WITH_KW: KwargInfo[T.List[T.Union[BothLibraries, SharedLibrary, StaticLibrary, CustomTarget, CustomTargetIndex, Jar, Executable]]] = KwargInfo(
    'link_with',
    ContainerTypeInfo(list, (BothLibraries, SharedLibrary, StaticLibrary, CustomTarget, CustomTargetIndex, Jar, Executable, Dependency)),
    listify=True,
    default=[],
    validator=lambda x: _link_with_error if isinstance(x, Dependency) else None,
)

def link_whole_validator(values: T.List[T.Union[StaticLibrary, CustomTarget, CustomTargetIndex, Dependency]]) -> T.Optional[str]:
    for l in values:
        if isinstance(l, (CustomTarget, CustomTargetIndex)) and l.links_dynamically():
            return f'{type(l).__name__} returning a shared library is not allowed'
        if isinstance(l, Dependency):
            return _link_with_error
    return None

LINK_WHOLE_KW: KwargInfo[T.List[T.Union[BothLibraries, StaticLibrary, CustomTarget, CustomTargetIndex]]] = KwargInfo(
    'link_whole',
    ContainerTypeInfo(list, (BothLibraries, StaticLibrary, CustomTarget, CustomTargetIndex, Dependency)),
    listify=True,
    default=[],
    validator=link_whole_validator,
)

SOURCES_KW: KwargInfo[T.List[T.Union[str, File, CustomTarget, CustomTargetIndex, GeneratedList]]] = KwargInfo(
    'sources',
    ContainerTypeInfo(list, (str, File, CustomTarget, CustomTargetIndex, GeneratedList)),
    listify=True,
    default=[],
)

VARIABLES_KW: KwargInfo[T.Dict[str, str]] = KwargInfo(
    'variables',
    (ContainerTypeInfo(list, str), ContainerTypeInfo(dict, str)),
    validator=variables_validator,
    convertor=variables_convertor,
    default={},
)

PRESERVE_PATH_KW: KwargInfo[bool] = KwargInfo('preserve_path', bool, default=False, since='0.63.0')

def _pch_validator(val: T.List[str]) -> T.Optional[str]:
    if len(val) > 2:
        return 'must be of length 1 or 2 if provided'

    if len(val) == 1:
        if not environment.is_header(val[0]):
            return f'PCH argument {val[0]} is not a header'
    else:
        err = 'PCH definition must contain one header and at most one source.'
        if len(val) == 0:
            return err
        if environment.is_header(val[0]):
            if not environment.is_source(val[1]):
                return err
        elif environment.is_source(val[0]):
            if not environment.is_header(val[1]):
                return err
            val = [val[1], val[0]]

        if os.path.dirname(val[0]) != os.path.dirname(val[1]):
            return 'PCH files must be stored in the same folder.'
    return None

_PCH_KW: KwargInfo[T.List[str]] = KwargInfo(
    'c_pch',
    ContainerTypeInfo(list, str),
    default=[],
    listify=True,
    validator=_pch_validator,
)

_VS_MODULE_DEF_KW: KwargInfo[T.Union[str, File, CustomTarget, CustomTargetIndex]] = KwargInfo(
    'vs_module_defs',
    (str, File, CustomTarget, CustomTargetIndex, NoneType),
)


_NAME_PREFIX_KW: KwargInfo[T.Union[str, list, None]] = KwargInfo(
    'name_prefix',
    (str, list, NoneType),
    default=[],
    validator=lambda x: 'must be an empty list to signifiy default value' if (isinstance(x, list) and x) else None,
    convertor=lambda x: None if isinstance(x, list) else x,
)

# A variant used internally for build targets, and is stricter than the public
# one.
_LINK_WITH_KW: KwargInfo[T.List[T.Union[BothLibraries, SharedLibrary, SharedModule, StaticLibrary, CustomTarget, CustomTargetIndex]]] = KwargInfo(
    'link_with',
    ContainerTypeInfo(
        list,
        (BothLibraries, SharedLibrary, StaticLibrary,
         SharedModule, CustomTarget, CustomTargetIndex,
         Dependency)),
    default=[],
    listify=True,
    validator=lambda x: _link_with_error if isinstance(x, Dependency) else None,
)

_BUILD_TARGET_KWS: T.List[KwargInfo] = [
    # Keep this one first since build_taget will exclude it
    INSTALL_MODE_KW.evolve(since='0.47.0'),

    KwargInfo('build_by_default', bool, default=True, since='0.40.0'),
    KwargInfo('build_rpath', str, default='', since='0.42.0'),
    KwargInfo('d_debug', ContainerTypeInfo(list, (str, int)), default=[], listify=True),
    INCLUDE_DIRECTORIES.evolve(name='d_import_dirs'),
    D_MODULE_VERSIONS_KW,
    KwargInfo('d_unittest', bool, default=False),
    DEPENDENCIES_KW,
    KwargInfo(
        'extra_files',
        ContainerTypeInfo(list, (str, File, CustomTarget, CustomTargetIndex)),
        default=[],
        listify=True,
    ),
    KwargInfo(
        'gnu_symbol_visibility', str, default='default', since='0.48.0',
        validator=in_set_validator({'default', 'internal', 'hidden', 'protected', 'inlineshidden'}),
    ),
    KwargInfo('implicit_include_directories', bool, default=True, since='0.42.0'),
    INCLUDE_DIRECTORIES,
    INSTALL_KW,
    # TODO: Eventually we want this to just be the generic INSTALL_DIR_KW, but in the mean time
    # this is allowed to be a `List[str | bool]` (not just `False`) so we have to handle it manually
    KwargInfo(
        'install_dir',
        ContainerTypeInfo(list, (str, bool)),
        default=[],
        listify=True,
    ),
    KwargInfo('install_rpath', str, default=''),
    INSTALL_TAG_KW.evolve(since='0.60.0'),
    KwargInfo('install_vala_gir', (str, bool, NoneType), since='0.64.0'),
    KwargInfo('install_vala_header', (str, bool, NoneType), since='0.64.0'),
    KwargInfo('install_vala_vapi', (str, bool, NoneType), since='0.64.0'),
    KwargInfo('link_args', ContainerTypeInfo(list, str), default=[], listify=True),
    KwargInfo(
        'link_depends',
        ContainerTypeInfo(list, (str, File, CustomTarget, CustomTargetIndex)),
        default=[],
        listify=True,
    ),
    KwargInfo(
        'link_language',
        (str, NoneType),
        since='0.51.0',
        validator=in_set_validator(set(compilers.all_languages)),
    ),
    LINK_WHOLE_KW.evolve(since='0.40.0'),
    _NAME_PREFIX_KW,
    _NAME_PREFIX_KW.evolve(name='name_suffix'),
    NATIVE_KW,
    KwargInfo(
        'objects',
        ContainerTypeInfo(list, (str, File, ExtractedObjects)),
        default=[],
        listify=True,
    ),
    OVERRIDE_OPTIONS_KW.evolve(since='0.40.0'),
    KwargInfo(
        'sources',
        ContainerTypeInfo(list, (str, File, CustomTarget, CustomTargetIndex, GeneratedList)),
        default=[],
        listify=True,
    ),
    KwargInfo(
        'resources',
        ContainerTypeInfo(list, str),
        default=[],
        listify=True,
    ),
    _PCH_KW,
    _PCH_KW.evolve(name='cpp_pch'),
    KwargInfo('vala_header', (str, NoneType)),
    KwargInfo('vala_vapi', (str, NoneType)),
    KwargInfo('vala_gir', (str, NoneType)),
]

_RUST_CRATE_TYPE_KW = KwargInfo(
    'rust_crate_type',
    str,
    default='lib',
    since='0.42.0',
)

_PIE_KW: KwargInfo[T.Optional[bool]] = KwargInfo(
    'pie', (bool, NoneType), since='0.49.0',
)

_LANGUAGE_KWS: T.List[KwargInfo] = [
    KwargInfo(f'{lang}_args', ContainerTypeInfo(list, str), listify=True, default=[])
    for lang in compilers.all_languages
]

_EXCLUSIVE_STATIC_LIB_KWS: T.List[KwargInfo] = [
    KwargInfo('pic', (bool, NoneType), since='0.36.0'),
    KwargInfo('prelink', bool, default=False, since='0.57.0'),
]

STATIC_LIB_KWS: T.List[KwargInfo] = (
    _BUILD_TARGET_KWS + _LANGUAGE_KWS + _EXCLUSIVE_STATIC_LIB_KWS +
    [_LINK_WITH_KW,
     _RUST_CRATE_TYPE_KW.evolve(validator=in_set_validator({'lib', 'rlib', 'staticlib'}))]
)

def _validate_darwin_versions(darwin_versions: T.List[T.Union[str, int]]) -> T.Optional[str]:
    if len(darwin_versions) > 2:
        return f"Must have 1, 2, or 3 elements, not {len(darwin_versions)}"
    if len(darwin_versions) == 1:
        darwin_versions = 2 * darwin_versions
    for  v in darwin_versions:
        if isinstance(v, int):
            v = str(v)
        if not re.fullmatch(r'[0-9]+(\.[0-9]+){0,2}', v):
            return 'must be X.Y.Z where X, Y, Z are numbers, and Y and Z are optional'
        try:
            parts = v.split('.')
        except ValueError:
            return f'badly formed value: "{v}, not in X.Y.Z form'
        if len(parts) in (1, 2, 3) and int(parts[0]) > 65535:
            return 'must be X.Y.Z where X is [0, 65535] and Y, Z are optional'
        if len(parts) in (2, 3) and int(parts[1]) > 255:
            return 'must be X.Y.Z where Y is [0, 255] and Y, Z are optional'
        if len(parts) == 3 and int(parts[2]) > 255:
            return 'must be X.Y.Z where Z is [0, 255] and Y, Z are optional'
    return None

def _convert_darwin_versions(val: T.List[T.Union[str, int]]) -> T.Optional[T.Tuple[str, str]]:
    if not val:
        return None
    elif len(val) == 1:
        v = str(val[0])
        return (v, v)
    return (str(val[0]), str(val[1]))

_EXCLUSIVE_SHARED_LIB_KWS: T.List[KwargInfo] = [
    _VS_MODULE_DEF_KW,
    _LINK_WITH_KW,
    KwargInfo('version', (str, NoneType)),
    KwargInfo('soversion', (str, int, NoneType), convertor=lambda x: str(x) if x is not None else None),
    KwargInfo(
        'darwin_versions',
        ContainerTypeInfo(list, (str, int)),
        default=[],
        listify=True,
        validator=_validate_darwin_versions,
        convertor=_convert_darwin_versions,
        since='0.48.0',
    ),
]

SHARED_LIB_KWS: T.List[KwargInfo] = (
    _BUILD_TARGET_KWS + _LANGUAGE_KWS + _EXCLUSIVE_SHARED_LIB_KWS +
    [_RUST_CRATE_TYPE_KW.evolve(
        validator=in_set_validator({'lib', 'dylib', 'cdylib', 'proc-macro'}),
        since_values={'proc-macro': '0.62.0'},
    )]
)

SHARED_MOD_KWS: T.List[KwargInfo] = [
    *_BUILD_TARGET_KWS,
    *_LANGUAGE_KWS,
    _VS_MODULE_DEF_KW.evolve(since='0.52.0'),
    # Shared modules can additionally by linked with Executables
    KwargInfo(
        'link_with',
        ContainerTypeInfo(
            list,
            (BothLibraries, SharedLibrary, StaticLibrary,
             SharedModule, CustomTarget, CustomTargetIndex,
             Executable)),
        default=[],
        listify=True,
    ),
]

BOTH_LIB_KWS: T.List[KwargInfo] = (
    _BUILD_TARGET_KWS + _LANGUAGE_KWS + _EXCLUSIVE_SHARED_LIB_KWS + _EXCLUSIVE_STATIC_LIB_KWS +
    # XXX: rust_crate_type (and rust in general?) is busted with both lib
    [_RUST_CRATE_TYPE_KW.evolve(
        validator=in_set_validator({'lib', 'dylib', 'cdylib', 'rlib', 'staticlib', 'proc-macro'}),
        since_values={'proc-macro': '0.62.0'}),
     _PIE_KW,
    ]
)

def _win_subsystem_validator(value: T.Optional[str]) -> T.Optional[str]:
    value = value.lower()
    if re.fullmatch(r'(boot_application|console|efi_application|efi_boot_service_driver|efi_rom|efi_runtime_driver|native|posix|windows)(,\d+(\.\d+)?)?', value) is None:
        return f'Invalid value for win_subsystem: {value}.'
    return None


_EXCLUSIVE_EXECUTABLE_KWS: T.List[KwargInfo] = [
    KwargInfo('export_dynamic', bool, default=False, since='0.45.0'),
    KwargInfo('gui_app', (bool, NoneType), deprecated='0.56.0', deprecated_message="Use 'win_subsystem' instead."),
    KwargInfo('implib', (bool, str, NoneType), since='0.42.0'),
    KwargInfo('win_subsystem', (str, NoneType), since='0.56.0', validator=_win_subsystem_validator),
    _LINK_WITH_KW,
]

EXECUTABLE_KWS: T.List[KwargInfo] = \
    _BUILD_TARGET_KWS + _LANGUAGE_KWS + _EXCLUSIVE_EXECUTABLE_KWS + [
        _PIE_KW,
        _RUST_CRATE_TYPE_KW.evolve(default='bin', validator=in_set_validator({'bin'})),
    ]

_MAIN_CLASS_KW = KwargInfo('main_class', str, default='')

JAR_KWS: T.List[KwargInfo] = [
    *_BUILD_TARGET_KWS,
    *_LANGUAGE_KWS,
    _MAIN_CLASS_KW,
    KwargInfo('java_resources', (StructuredSources, NoneType), since='0.62.0'),
    # Jars can only be linked with other JARs
    KwargInfo(
        'link_with',
        ContainerTypeInfo(list, Jar),
        default=[],
        listify=True,
    )
]

BUILD_TARGET_KWS: T.List[KwargInfo] = [
    *_BUILD_TARGET_KWS,
    *_LANGUAGE_KWS,
    *_EXCLUSIVE_SHARED_LIB_KWS,
    *_EXCLUSIVE_STATIC_LIB_KWS,
    *_EXCLUSIVE_EXECUTABLE_KWS,
    _PIE_KW,
    _RUST_CRATE_TYPE_KW.evolve(
        validator=in_set_validator({'lib', 'dylib', 'cdylib', 'rlib', 'staticlib', 'proc-macro', 'bin'}),
        since_values={'proc-macro': '0.62.0'}),
    _MAIN_CLASS_KW,
    KwargInfo(
        'target_type', str, required=True,
        validator=in_set_validator({
            'executable', 'shared_library', 'shared_module',
            'static_library', 'both_libraries', 'library',
            'jar',
        })
    )
]
