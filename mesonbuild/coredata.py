# Copyright 2012-2021 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from . import mlog, mparser
import pickle, os, uuid
import sys
from itertools import chain
from pathlib import PurePath
from collections import OrderedDict
from .mesonlib import (
    MesonException, EnvironmentException, MachineChoice, PerMachine,
    PerMachineDefaultable, default_libdir, default_libexecdir,
    default_prefix, split_args, OptionKey, OptionType,
)
from .wrap import WrapMode
import ast
import argparse
import configparser
import enum
import shlex
import typing as T

if T.TYPE_CHECKING:
    from . import dependencies
    from .compilers.compilers import Compiler, CompileResult  # noqa: F401
    from .environment import Environment
    from .mesonlib import OptionOverrideProxy

    OptionDictType = T.Union[T.Dict[str, 'UserOption[T.Any]'], OptionOverrideProxy]
    KeyedOptionDictType = T.Union[T.Dict['OptionKey', 'UserOption[T.Any]'], OptionOverrideProxy]
    CompilerCheckCacheKey = T.Tuple[T.Tuple[str, ...], str, str, T.Tuple[str, ...], str]

version = '0.58.999'
backendlist = ['ninja', 'vs', 'vs2010', 'vs2015', 'vs2017', 'vs2019', 'xcode']

default_yielding = False

# Can't bind this near the class method it seems, sadly.
_T = T.TypeVar('_T')

BUILDTYPE_2_DEBUG = {'plain': False,
        'debug': True,
        'debugoptimized': True,
        'release': False,
        'minsize': True,
        }

BUILDTYPE_2_OPTIMIZATION = {'plain': '0',
        'debug':'0',
        'debugoptimized':'2',
        'release': '3',
        'minsize':'s',
        }

class MesonVersionMismatchException(MesonException):
    '''Build directory generated with Meson version is incompatible with current version'''
    def __init__(self, old_version: str, current_version: str) -> None:
        super().__init__('Build directory has been generated with Meson version {}, '
                         'which is incompatible with the current version {}.'
                         .format(old_version, current_version))
        self.old_version = old_version
        self.current_version = current_version


class UserOption(T.Generic[_T]):
    def __init__(self, description: str, choices: T.Optional[T.Union[str, T.List[_T]]], yielding: T.Optional[bool]):
        super().__init__()
        self.choices = choices
        self.description = description
        if yielding is None:
            yielding = default_yielding
        if not isinstance(yielding, bool):
            raise MesonException('Value of "yielding" must be a boolean.')
        self.yielding = yielding

    def printable_value(self) -> T.Union[str, int, bool, T.List[T.Union[str, int, bool]]]:
        assert isinstance(self.value, (str, int, bool, list))
        return self.value

    # Check that the input is a valid value and return the
    # "cleaned" or "native" version. For example the Boolean
    # option could take the string "true" and return True.
    def validate_value(self, value: T.Any) -> _T:
        raise RuntimeError('Derived option class did not override validate_value.')

    def set_value(self, newvalue: T.Any) -> None:
        self.value = self.validate_value(newvalue)

class UserStringOption(UserOption[str]):
    def __init__(self, description: str, value: T.Any, yielding: T.Optional[bool] = None):
        super().__init__(description, None, yielding)
        self.set_value(value)

    def validate_value(self, value: T.Any) -> str:
        if not isinstance(value, str):
            raise MesonException('Value "%s" for string option is not a string.' % str(value))
        return value

class UserFilePathOption(UserOption[str]):
    def __init__(self, description: str, value: T.Any, yielding: T.Optional[bool] = None):
        super().__init__(description, None, yielding)
        self.path_must_exist = True
        self.set_value(value)

    def validate_value(self, value: T.Any) -> str:
        if not isinstance(value, str):
            raise MesonException('Value "%s" for file path option is not a string.' % str(value))
        if not value:
            return value
         # Store absolute paths, because the original Meson command
         # might not have been run from the build root.
        if not os.path.isabs(value):
            value = os.path.join(os.getcwd(), value)
        if not self.path_must_exist:
            return value
        if not os.path.exists(value):
            raise MesonException(f'File path "{value}" for does not exist on the file system.')
        return value

class UserBooleanOption(UserOption[bool]):
    def __init__(self, description: str, value, yielding: T.Optional[bool] = None) -> None:
        super().__init__(description, [True, False], yielding)
        self.set_value(value)

    def __bool__(self) -> bool:
        return self.value

    def validate_value(self, value: T.Any) -> bool:
        if isinstance(value, bool):
            return value
        if not isinstance(value, str):
            raise MesonException(f'Value {value} cannot be converted to a boolean')
        if value.lower() == 'true':
            return True
        if value.lower() == 'false':
            return False
        raise MesonException('Value %s is not boolean (true or false).' % value)

class UserIntegerOption(UserOption[int]):
    def __init__(self, description: str, value: T.Any, yielding: T.Optional[bool] = None):
        min_value, max_value, default_value = value
        self.min_value = min_value
        self.max_value = max_value
        c = []
        if min_value is not None:
            c.append('>=' + str(min_value))
        if max_value is not None:
            c.append('<=' + str(max_value))
        choices = ', '.join(c)
        super().__init__(description, choices, yielding)
        self.set_value(default_value)

    def validate_value(self, value: T.Any) -> int:
        if isinstance(value, str):
            value = self.toint(value)
        if not isinstance(value, int):
            raise MesonException('New value for integer option is not an integer.')
        if self.min_value is not None and value < self.min_value:
            raise MesonException('New value %d is less than minimum value %d.' % (value, self.min_value))
        if self.max_value is not None and value > self.max_value:
            raise MesonException('New value %d is more than maximum value %d.' % (value, self.max_value))
        return value

    def toint(self, valuestring: str) -> int:
        try:
            return int(valuestring)
        except ValueError:
            raise MesonException('Value string "%s" is not convertible to an integer.' % valuestring)

class OctalInt(int):
    # NinjaBackend.get_user_option_args uses str() to converts it to a command line option
    # UserUmaskOption.toint() uses int(str, 8) to convert it to an integer
    # So we need to use oct instead of dec here if we do not want values to be misinterpreted.
    def __str__(self):
        return oct(int(self))

class UserUmaskOption(UserIntegerOption, UserOption[T.Union[str, OctalInt]]):
    def __init__(self, description: str, value: T.Any, yielding: T.Optional[bool] = None):
        super().__init__(description, (0, 0o777, value), yielding)
        self.choices = ['preserve', '0000-0777']

    def printable_value(self) -> str:
        if self.value == 'preserve':
            return self.value
        return format(self.value, '04o')

    def validate_value(self, value: T.Any) -> T.Union[str, OctalInt]:
        if value is None or value == 'preserve':
            return 'preserve'
        return OctalInt(super().validate_value(value))

    def toint(self, valuestring: T.Union[str, OctalInt]) -> int:
        try:
            return int(valuestring, 8)
        except ValueError as e:
            raise MesonException(f'Invalid mode: {e}')

class UserComboOption(UserOption[str]):
    def __init__(self, description: str, choices: T.List[str], value: T.Any, yielding: T.Optional[bool] = None):
        super().__init__(description, choices, yielding)
        if not isinstance(self.choices, list):
            raise MesonException('Combo choices must be an array.')
        for i in self.choices:
            if not isinstance(i, str):
                raise MesonException('Combo choice elements must be strings.')
        self.set_value(value)

    def validate_value(self, value: T.Any) -> str:
        if value not in self.choices:
            if isinstance(value, bool):
                _type = 'boolean'
            elif isinstance(value, (int, float)):
                _type = 'number'
            else:
                _type = 'string'
            optionsstring = ', '.join([f'"{item}"' for item in self.choices])
            raise MesonException('Value "{}" (of type "{}") for combo option "{}" is not one of the choices.'
                                 ' Possible choices are (as string): {}.'.format(
                                     value, _type, self.description, optionsstring))
        return value

class UserArrayOption(UserOption[T.List[str]]):
    def __init__(self, description: str, value: T.Union[str, T.List[str]], split_args: bool = False, user_input: bool = False, allow_dups: bool = False, **kwargs: T.Any) -> None:
        super().__init__(description, kwargs.get('choices', []), yielding=kwargs.get('yielding', None))
        self.split_args = split_args
        self.allow_dups = allow_dups
        self.value = self.validate_value(value, user_input=user_input)

    def validate_value(self, value: T.Union[str, T.List[str]], user_input: bool = True) -> T.List[str]:
        # User input is for options defined on the command line (via -D
        # options). Users can put their input in as a comma separated
        # string, but for defining options in meson_options.txt the format
        # should match that of a combo
        if not user_input and isinstance(value, str) and not value.startswith('['):
            raise MesonException('Value does not define an array: ' + value)

        if isinstance(value, str):
            if value.startswith('['):
                try:
                    newvalue = ast.literal_eval(value)
                except ValueError:
                    raise MesonException(f'malformed option {value}')
            elif value == '':
                newvalue = []
            else:
                if self.split_args:
                    newvalue = split_args(value)
                else:
                    newvalue = [v.strip() for v in value.split(',')]
        elif isinstance(value, list):
            newvalue = value
        else:
            raise MesonException(f'"{newvalue}" should be a string array, but it is not')

        if not self.allow_dups and len(set(newvalue)) != len(newvalue):
            msg = 'Duplicated values in array option is deprecated. ' \
                  'This will become a hard error in the future.'
            mlog.deprecation(msg)
        for i in newvalue:
            if not isinstance(i, str):
                raise MesonException('String array element "{}" is not a string.'.format(str(newvalue)))
        if self.choices:
            bad = [x for x in newvalue if x not in self.choices]
            if bad:
                raise MesonException('Options "{}" are not in allowed choices: "{}"'.format(
                    ', '.join(bad), ', '.join(self.choices)))
        return newvalue

    def extend_value(self, value: T.Union[str, T.List[str]]) -> None:
        """Extend the value with an additional value."""
        new = self.validate_value(value)
        self.set_value(self.value + new)


class UserFeatureOption(UserComboOption):
    static_choices = ['enabled', 'disabled', 'auto']

    def __init__(self, description: str, value: T.Any, yielding: T.Optional[bool] = None):
        super().__init__(description, self.static_choices, value, yielding)

    def is_enabled(self) -> bool:
        return self.value == 'enabled'

    def is_disabled(self) -> bool:
        return self.value == 'disabled'

    def is_auto(self) -> bool:
        return self.value == 'auto'

if T.TYPE_CHECKING:
    CacheKeyType = T.Tuple[T.Tuple[T.Any, ...], ...]
    SubCacheKeyType = T.Tuple[T.Any, ...]


class DependencyCacheType(enum.Enum):

    OTHER = 0
    PKG_CONFIG = 1
    CMAKE = 2

    @classmethod
    def from_type(cls, dep: 'dependencies.Dependency') -> 'DependencyCacheType':
        from . import dependencies
        # As more types gain search overrides they'll need to be added here
        if isinstance(dep, dependencies.PkgConfigDependency):
            return cls.PKG_CONFIG
        if isinstance(dep, dependencies.CMakeDependency):
            return cls.CMAKE
        return cls.OTHER


class DependencySubCache:

    def __init__(self, type_: DependencyCacheType):
        self.types = [type_]
        self.__cache = {}  # type: T.Dict[SubCacheKeyType, dependencies.Dependency]

    def __getitem__(self, key: 'SubCacheKeyType') -> 'dependencies.Dependency':
        return self.__cache[key]

    def __setitem__(self, key: 'SubCacheKeyType', value: 'dependencies.Dependency') -> None:
        self.__cache[key] = value

    def __contains__(self, key: 'SubCacheKeyType') -> bool:
        return key in self.__cache

    def values(self) -> T.Iterable['dependencies.Dependency']:
        return self.__cache.values()


class DependencyCache:

    """Class that stores a cache of dependencies.

    This class is meant to encapsulate the fact that we need multiple keys to
    successfully lookup by providing a simple get/put interface.
    """

    def __init__(self, builtins: 'KeyedOptionDictType', for_machine: MachineChoice):
        self.__cache = OrderedDict()  # type: T.MutableMapping[CacheKeyType, DependencySubCache]
        self.__builtins = builtins
        self.__pkg_conf_key = OptionKey('pkg_config_path', machine=for_machine)
        self.__cmake_key = OptionKey('cmake_prefix_path', machine=for_machine)

    def __calculate_subkey(self, type_: DependencyCacheType) -> T.Tuple[T.Any, ...]:
        if type_ is DependencyCacheType.PKG_CONFIG:
            return tuple(self.__builtins[self.__pkg_conf_key].value)
        elif type_ is DependencyCacheType.CMAKE:
            return tuple(self.__builtins[self.__cmake_key].value)
        assert type_ is DependencyCacheType.OTHER, 'Someone forgot to update subkey calculations for a new type'
        return tuple()

    def __iter__(self) -> T.Iterator['CacheKeyType']:
        return self.keys()

    def put(self, key: 'CacheKeyType', dep: 'dependencies.Dependency') -> None:
        t = DependencyCacheType.from_type(dep)
        if key not in self.__cache:
            self.__cache[key] = DependencySubCache(t)
        subkey = self.__calculate_subkey(t)
        self.__cache[key][subkey] = dep

    def get(self, key: 'CacheKeyType') -> T.Optional['dependencies.Dependency']:
        """Get a value from the cache.

        If there is no cache entry then None will be returned.
        """
        try:
            val = self.__cache[key]
        except KeyError:
            return None

        for t in val.types:
            subkey = self.__calculate_subkey(t)
            try:
                return val[subkey]
            except KeyError:
                pass
        return None

    def values(self) -> T.Iterator['dependencies.Dependency']:
        for c in self.__cache.values():
            yield from c.values()

    def keys(self) -> T.Iterator['CacheKeyType']:
        return iter(self.__cache.keys())

    def items(self) -> T.Iterator[T.Tuple['CacheKeyType', T.List['dependencies.Dependency']]]:
        for k, v in self.__cache.items():
            vs = []
            for t in v.types:
                subkey = self.__calculate_subkey(t)
                if subkey in v:
                    vs.append(v[subkey])
            yield k, vs

    def clear(self) -> None:
        self.__cache.clear()


# Can't bind this near the class method it seems, sadly.
_V = T.TypeVar('_V')

# This class contains all data that must persist over multiple
# invocations of Meson. It is roughly the same thing as
# cmakecache.

class CoreData:

    def __init__(self, options: argparse.Namespace, scratch_dir: str, meson_command: T.List[str]):
        self.lang_guids = {
            'default': '8BC9CEB8-8B4A-11D0-8D11-00A0C91BC942',
            'c': '8BC9CEB8-8B4A-11D0-8D11-00A0C91BC942',
            'cpp': '8BC9CEB8-8B4A-11D0-8D11-00A0C91BC942',
            'test': '3AC096D0-A1C2-E12C-1390-A8335801FDAB',
            'directory': '2150E333-8FDC-42A3-9474-1A3956D46DE8',
        }
        self.test_guid = str(uuid.uuid4()).upper()
        self.regen_guid = str(uuid.uuid4()).upper()
        self.install_guid = str(uuid.uuid4()).upper()
        self.meson_command = meson_command
        self.target_guids = {}
        self.version = version
        self.options: 'KeyedOptionDictType' = {}
        self.cross_files = self.__load_config_files(options, scratch_dir, 'cross')
        self.compilers = PerMachine(OrderedDict(), OrderedDict())  # type: PerMachine[T.Dict[str, Compiler]]

        # Set of subprojects that have already been initialized once, this is
        # required to be stored and reloaded with the coredata, as we don't
        # want to overwrite options for such subprojects.
        self.initialized_subprojects: T.Set[str] = set()

        # For host == build configuraitons these caches should be the same.
        self.deps: PerMachine[DependencyCache] = PerMachineDefaultable.default(
            self.is_cross_build(),
            DependencyCache(self.options, MachineChoice.BUILD),
            DependencyCache(self.options, MachineChoice.HOST))

        self.compiler_check_cache = OrderedDict()  # type: T.Dict[CompilerCheckCacheKey, compiler.CompileResult]

        # Only to print a warning if it changes between Meson invocations.
        self.config_files = self.__load_config_files(options, scratch_dir, 'native')
        self.builtin_options_libdir_cross_fixup()
        self.init_builtins('')

    @staticmethod
    def __load_config_files(options: argparse.Namespace, scratch_dir: str, ftype: str) -> T.List[str]:
        # Need to try and make the passed filenames absolute because when the
        # files are parsed later we'll have chdir()d.
        if ftype == 'cross':
            filenames = options.cross_file
        else:
            filenames = options.native_file

        if not filenames:
            return []

        found_invalid = []  # type: T.List[str]
        missing = []        # type: T.List[str]
        real = []           # type: T.List[str]
        for i, f in enumerate(filenames):
            f = os.path.expanduser(os.path.expandvars(f))
            if os.path.exists(f):
                if os.path.isfile(f):
                    real.append(os.path.abspath(f))
                    continue
                elif os.path.isdir(f):
                    found_invalid.append(os.path.abspath(f))
                else:
                    # in this case we've been passed some kind of pipe, copy
                    # the contents of that file into the meson private (scratch)
                    # directory so that it can be re-read when wiping/reconfiguring
                    copy = os.path.join(scratch_dir, f'{uuid.uuid4()}.{ftype}.ini')
                    with open(f) as rf:
                        with open(copy, 'w') as wf:
                            wf.write(rf.read())
                    real.append(copy)

                    # Also replace the command line argument, as the pipe
                    # probably won't exist on reconfigure
                    filenames[i] = copy
                    continue
            if sys.platform != 'win32':
                paths = [
                    os.environ.get('XDG_DATA_HOME', os.path.expanduser('~/.local/share')),
                ] + os.environ.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':')
                for path in paths:
                    path_to_try = os.path.join(path, 'meson', ftype, f)
                    if os.path.isfile(path_to_try):
                        real.append(path_to_try)
                        break
                else:
                    missing.append(f)
            else:
                missing.append(f)

        if missing:
            if found_invalid:
                mlog.log('Found invalid candidates for', ftype, 'file:', *found_invalid)
            mlog.log('Could not find any valid candidate for', ftype, 'files:', *missing)
            raise MesonException(f'Cannot find specified {ftype} file: {f}')
        return real

    def builtin_options_libdir_cross_fixup(self):
        # By default set libdir to "lib" when cross compiling since
        # getting the "system default" is always wrong on multiarch
        # platforms as it gets a value like lib/x86_64-linux-gnu.
        if self.cross_files:
            BUILTIN_OPTIONS[OptionKey('libdir')].default = 'lib'

    def sanitize_prefix(self, prefix):
        prefix = os.path.expanduser(prefix)
        if not os.path.isabs(prefix):
            raise MesonException('prefix value {!r} must be an absolute path'
                                 ''.format(prefix))
        if prefix.endswith('/') or prefix.endswith('\\'):
            # On Windows we need to preserve the trailing slash if the
            # string is of type 'C:\' because 'C:' is not an absolute path.
            if len(prefix) == 3 and prefix[1] == ':':
                pass
            # If prefix is a single character, preserve it since it is
            # the root directory.
            elif len(prefix) == 1:
                pass
            else:
                prefix = prefix[:-1]
        return prefix

    def sanitize_dir_option_value(self, prefix: str, option: OptionKey, value: T.Any) -> T.Any:
        '''
        If the option is an installation directory option and the value is an
        absolute path, check that it resides within prefix and return the value
        as a path relative to the prefix.

        This way everyone can do f.ex, get_option('libdir') and be sure to get
        the library directory relative to prefix.

        .as_posix() keeps the posix-like file seperators Meson uses.
        '''
        try:
            value = PurePath(value)
        except TypeError:
            return value
        if option.name.endswith('dir') and value.is_absolute() and \
           option not in BULITIN_DIR_NOPREFIX_OPTIONS:
            # Value must be a subdir of the prefix
            # commonpath will always return a path in the native format, so we
            # must use pathlib.PurePath to do the same conversion before
            # comparing.
            msg = ('The value of the \'{!s}\' option is \'{!s}\' which must be a '
                   'subdir of the prefix {!r}.\nNote that if you pass a '
                   'relative path, it is assumed to be a subdir of prefix.')
            # os.path.commonpath doesn't understand case-insensitive filesystems,
            # but PurePath().relative_to() does.
            try:
                value = value.relative_to(prefix)
            except ValueError:
                raise MesonException(msg.format(option, value, prefix))
            if '..' in str(value):
                raise MesonException(msg.format(option, value, prefix))
        return value.as_posix()

    def init_builtins(self, subproject: str) -> None:
        # Create builtin options with default values
        for key, opt in BUILTIN_OPTIONS.items():
            self.add_builtin_option(self.options, key.evolve(subproject=subproject), opt)
        for for_machine in iter(MachineChoice):
            for key, opt in BUILTIN_OPTIONS_PER_MACHINE.items():
                self.add_builtin_option(self.options, key.evolve(subproject=subproject, machine=for_machine), opt)

    @staticmethod
    def add_builtin_option(opts_map: 'KeyedOptionDictType', key: OptionKey,
                           opt: 'BuiltinOption') -> None:
        if key.subproject:
            if opt.yielding:
                # This option is global and not per-subproject
                return
            value = opts_map[key.as_root()].value
        else:
            value = None
        opts_map[key] = opt.init_option(key, value, default_prefix())

    def init_backend_options(self, backend_name: str) -> None:
        if backend_name == 'ninja':
            self.options[OptionKey('backend_max_links')] = UserIntegerOption(
                'Maximum number of linker processes to run or 0 for no '
                'limit',
                (0, None, 0))
        elif backend_name.startswith('vs'):
            self.options[OptionKey('backend_startup_project')] = UserStringOption(
                'Default project to execute in Visual Studio',
                '')

    def get_option(self, key: OptionKey) -> T.Union[str, int, bool, WrapMode]:
        try:
            v = self.options[key].value
            if key.name == 'wrap_mode':
                return WrapMode[v]
            return v
        except KeyError:
            pass

        try:
            v = self.options[key.as_root()]
            if v.yielding:
                if key.name == 'wrap_mode':
                    return WrapMode[v.value]
                return v.value
        except KeyError:
            pass

        raise MesonException(f'Tried to get unknown builtin option {str(key)}')

    def set_option(self, key: OptionKey, value) -> None:
        if key.is_builtin():
            if key.name == 'prefix':
                value = self.sanitize_prefix(value)
            else:
                prefix = self.options[OptionKey('prefix')].value
                value = self.sanitize_dir_option_value(prefix, key, value)

        try:
            self.options[key].set_value(value)
        except KeyError:
            raise MesonException(f'Tried to set unknown builtin option {str(key)}')

        if key.name == 'buildtype':
            self._set_others_from_buildtype(value)

    def get_nondefault_buildtype_args(self):
        result= []
        value = self.options[OptionKey('buildtype')].value
        if value == 'custom':
            return []
        opt = BUILDTYPE_2_OPTIMIZATION[value]
        debug = BUILDTYPE_2_DEBUG[value]
        actual_opt = self.options[OptionKey('optimization')].value
        actual_debug = self.options[OptionKey('debug')].value
        if actual_opt != opt:
            result.append(('optimization', actual_opt, opt))
        if actual_debug != debug:
            result.append(('debug', actual_debug, debug))
        return result

    def _set_others_from_buildtype(self, value: str) -> None:
        if value == 'plain':
            opt = '0'
            debug = False
        elif value == 'debug':
            opt = '0'
            debug = True
        elif value == 'debugoptimized':
            opt = '2'
            debug = True
        elif value == 'release':
            opt = '3'
            debug = False
        elif value == 'minsize':
            opt = 's'
            debug = True
        else:
            assert(value == 'custom')
            return
        self.options[OptionKey('optimization')].set_value(opt)
        self.options[OptionKey('debug')].set_value(debug)

    @staticmethod
    def is_per_machine_option(optname: OptionKey) -> bool:
        if optname.name in BUILTIN_OPTIONS_PER_MACHINE:
            return True
        return optname.lang is not None

    def validate_option_value(self, option_name: OptionKey, override_value):
        try:
            opt = self.options[option_name]
        except KeyError:
            raise MesonException(f'Tried to validate unknown option {str(option_name)}')
        try:
            return opt.validate_value(override_value)
        except MesonException as e:
            raise type(e)(('Validation failed for option %s: ' % option_name) + str(e)) \
                .with_traceback(sys.exc_info()[2])

    def get_external_args(self, for_machine: MachineChoice, lang: str) -> T.Union[str, T.List[str]]:
        return self.options[OptionKey('args', machine=for_machine, lang=lang)].value

    def get_external_link_args(self, for_machine: MachineChoice, lang: str) -> T.Union[str, T.List[str]]:
        return self.options[OptionKey('link_args', machine=for_machine, lang=lang)].value

    def update_project_options(self, options: 'KeyedOptionDictType') -> None:
        for key, value in options.items():
            if not key.is_project():
                continue
            if key not in self.options:
                self.options[key] = value
                continue

            oldval = self.options[key]
            if type(oldval) != type(value):
                self.options[key] = value
            elif oldval.choices != value.choices:
                # If the choices have changed, use the new value, but attempt
                # to keep the old options. If they are not valid keep the new
                # defaults but warn.
                self.options[key] = value
                try:
                    value.set_value(oldval.value)
                except MesonException as e:
                    mlog.warning(f'Old value(s) of {key} are no longer valid, resetting to default ({value.value}).')

    def is_cross_build(self, when_building_for: MachineChoice = MachineChoice.HOST) -> bool:
        if when_building_for == MachineChoice.BUILD:
            return False
        return len(self.cross_files) > 0

    def copy_build_options_from_regular_ones(self) -> None:
        assert not self.is_cross_build()
        for k in BUILTIN_OPTIONS_PER_MACHINE:
            o = self.options[k]
            self.options[k.as_build()].set_value(o.value)
        for bk, bv in self.options.items():
            if bk.machine is MachineChoice.BUILD:
                hk = bk.as_host()
                try:
                    hv = self.options[hk]
                    bv.set_value(hv.value)
                except KeyError:
                    continue

    def set_options(self, options: T.Dict[OptionKey, T.Any], subproject: str = '', warn_unknown: bool = True) -> None:
        if not self.is_cross_build():
            options = {k: v for k, v in options.items() if k.machine is not MachineChoice.BUILD}
        # Set prefix first because it's needed to sanitize other options
        pfk = OptionKey('prefix')
        if pfk in options:
            prefix = self.sanitize_prefix(options[pfk])
            self.options[OptionKey('prefix')].set_value(prefix)
            for key in BULITIN_DIR_NOPREFIX_OPTIONS:
                if key not in options:
                    self.options[key].set_value(BUILTIN_OPTIONS[key].prefixed_default(key, prefix))

        unknown_options: T.List[OptionKey] = []
        for k, v in options.items():
            if k == pfk:
                continue
            elif k not in self.options:
                unknown_options.append(k)
            else:
                self.set_option(k, v)
        if unknown_options and warn_unknown:
            unknown_options_str = ', '.join(sorted(str(s) for s in unknown_options))
            sub = f'In subproject {subproject}: ' if subproject else ''
            mlog.warning(f'{sub}Unknown options: "{unknown_options_str}"')
            mlog.log('The value of new options can be set with:')
            mlog.log(mlog.bold('meson setup <builddir> --reconfigure -Dnew_option=new_value ...'))
        if not self.is_cross_build():
            self.copy_build_options_from_regular_ones()

    def set_default_options(self, default_options: T.MutableMapping[OptionKey, str], subproject: str, env: 'Environment') -> None:
        # Preserve order: if env.options has 'buildtype' it must come after
        # 'optimization' if it is in default_options.
        options: T.MutableMapping[OptionKey, T.Any]
        if not subproject:
            options = OrderedDict(default_options)
            options.update(env.options)
            env.options = options

        # Create a subset of options, keeping only project and builtin
        # options for this subproject.
        # Language and backend specific options will be set later when adding
        # languages and setting the backend (builtin options must be set first
        # to know which backend we'll use).
        options = OrderedDict()

        for k, v in chain(default_options.items(), env.options.items()):
            # If this is a subproject, don't use other subproject options
            if k.subproject and k.subproject != subproject:
                continue
            # If the option is a builtin and is yielding then it's not allowed per subproject.
            #
            # Always test this using the HOST machine, as many builtin options
            # are not valid for the BUILD machine, but the yielding value does
            # not differ between them even when they are valid for both.
            if subproject and k.is_builtin() and self.options[k.evolve(subproject='', machine=MachineChoice.HOST)].yielding:
                continue
            # Skip base, compiler, and backend options, they are handled when
            # adding languages and setting backend.
            if k.type in {OptionType.COMPILER, OptionType.BACKEND, OptionType.BASE}:
                continue
            options[k] = v

        self.set_options(options, subproject=subproject)

    def add_compiler_options(self, options: 'KeyedOptionDictType', lang: str, for_machine: MachineChoice,
                             env: 'Environment') -> None:
        for k, o in options.items():
            value = env.options.get(k)
            if value is not None:
                o.set_value(value)
            self.options.setdefault(k, o)

    def add_lang_args(self, lang: str, comp: T.Type['Compiler'],
                      for_machine: MachineChoice, env: 'Environment') -> None:
        """Add global language arguments that are needed before compiler/linker detection."""
        from .compilers import compilers
        # These options are all new at this point, because the compiler is
        # responsible for adding its own options, thus calling
        # `self.options.update()`` is perfectly safe.
        self.options.update(compilers.get_global_options(lang, comp, for_machine, env))

    def process_new_compiler(self, lang: str, comp: 'Compiler', env: 'Environment') -> None:
        from . import compilers

        self.compilers[comp.for_machine][lang] = comp
        self.add_compiler_options(comp.get_options(), lang, comp.for_machine, env)

        enabled_opts: T.List[OptionKey] = []
        for key in comp.base_options:
            if key in self.options:
                continue
            oobj = compilers.base_options[key]
            if key in env.options:
                oobj.set_value(env.options[key])
                enabled_opts.append(key)
            self.options[key] = oobj
        self.emit_base_options_warnings(enabled_opts)

    def emit_base_options_warnings(self, enabled_opts: T.List[OptionKey]) -> None:
        if OptionKey('b_bitcode') in enabled_opts:
            mlog.warning('Base option \'b_bitcode\' is enabled, which is incompatible with many linker options. Incompatible options such as \'b_asneeded\' have been disabled.', fatal=False)
            mlog.warning('Please see https://mesonbuild.com/Builtin-options.html#Notes_about_Apple_Bitcode_support for more details.', fatal=False)

class CmdLineFileParser(configparser.ConfigParser):
    def __init__(self) -> None:
        # We don't want ':' as key delimiter, otherwise it would break when
        # storing subproject options like "subproject:option=value"
        super().__init__(delimiters=['='], interpolation=None)

    def optionxform(self, option: str) -> str:
        # Don't call str.lower() on keys
        return option

class MachineFileParser():
    def __init__(self, filenames: T.List[str]) -> None:
        self.parser = CmdLineFileParser()
        self.constants = {'True': True, 'False': False}
        self.sections = {}   

        self.parser.read(filenames)

        # Parse [constants] first so they can be used in other sections
        if self.parser.has_section('constants'):
            self.constants.update(self._parse_section('constants'))

        for s in self.parser.sections():
            if s == 'constants':
                continue
            self.sections[s] = self._parse_section(s)

    def _parse_section(self, s):
        self.scope = self.constants.copy()
        section = {}
        for entry, value in self.parser.items(s):
            if ' ' in entry or '\t' in entry or "'" in entry or '"' in entry:
                raise EnvironmentException(f'Malformed variable name {entry!r} in machine file.')
            # Windows paths...
            value = value.replace('\\', '\\\\')
            try:
                ast = mparser.Parser(value, 'machinefile').parse()
                res = self._evaluate_statement(ast.lines[0])
            except MesonException:
                raise EnvironmentException(f'Malformed value in machine file variable {entry!r}.')
            except KeyError as e:
                raise EnvironmentException('Undefined constant {!r} in machine file variable {!r}.'.format(e.args[0], entry))
            section[entry] = res
            self.scope[entry] = res
        return section

    def _evaluate_statement(self, node):
        if isinstance(node, (mparser.StringNode)):
            return node.value
        elif isinstance(node, mparser.BooleanNode):
            return node.value
        elif isinstance(node, mparser.NumberNode):
            return node.value
        elif isinstance(node, mparser.ArrayNode):
            return [self._evaluate_statement(arg) for arg in node.args.arguments]
        elif isinstance(node, mparser.IdNode):
            return self.scope[node.value]
        elif isinstance(node, mparser.ArithmeticNode):
            l = self._evaluate_statement(node.left)
            r = self._evaluate_statement(node.right)
            if node.operation == 'add':
                if (isinstance(l, str) and isinstance(r, str)) or \
                   (isinstance(l, list) and isinstance(r, list)):
                    return l + r
            elif node.operation == 'div':
                if isinstance(l, str) and isinstance(r, str):
                    return os.path.join(l, r)
        raise EnvironmentException('Unsupported node type')

def parse_machine_files(filenames):
    parser = MachineFileParser(filenames)
    return parser.sections

def get_cmd_line_file(build_dir: str) -> str:
    return os.path.join(build_dir, 'meson-private', 'cmd_line.txt')

def read_cmd_line_file(build_dir: str, options: argparse.Namespace) -> None:
    filename = get_cmd_line_file(build_dir)
    if not os.path.isfile(filename):
        return

    config = CmdLineFileParser()
    config.read(filename)

    # Do a copy because config is not really a dict. options.cmd_line_options
    # overrides values from the file.
    d = {OptionKey.from_string(k): v for k, v in config['options'].items()}
    d.update(options.cmd_line_options)
    options.cmd_line_options = d

    properties = config['properties']
    if not options.cross_file:
        options.cross_file = ast.literal_eval(properties.get('cross_file', '[]'))
    if not options.native_file:
        # This will be a string in the form: "['first', 'second', ...]", use
        # literal_eval to get it into the list of strings.
        options.native_file = ast.literal_eval(properties.get('native_file', '[]'))

def write_cmd_line_file(build_dir: str, options: argparse.Namespace) -> None:
    filename = get_cmd_line_file(build_dir)
    config = CmdLineFileParser()

    properties = OrderedDict()
    if options.cross_file:
        properties['cross_file'] = options.cross_file
    if options.native_file:
        properties['native_file'] = options.native_file

    config['options'] = {str(k): str(v) for k, v in options.cmd_line_options.items()}
    config['properties'] = properties
    with open(filename, 'w') as f:
        config.write(f)

def update_cmd_line_file(build_dir: str, options: argparse.Namespace):
    filename = get_cmd_line_file(build_dir)
    config = CmdLineFileParser()
    config.read(filename)
    config['options'].update({str(k): str(v) for k, v in options.cmd_line_options.items()})
    with open(filename, 'w') as f:
        config.write(f)

def get_cmd_line_options(build_dir: str, options: argparse.Namespace) -> str:
    copy = argparse.Namespace(**vars(options))
    read_cmd_line_file(build_dir, copy)
    cmdline = ['-D{}={}'.format(str(k), v) for k, v in copy.cmd_line_options.items()]
    if options.cross_file:
        cmdline += [f'--cross-file {f}' for f in options.cross_file]
    if options.native_file:
        cmdline += [f'--native-file {f}' for f in options.native_file]
    return ' '.join([shlex.quote(x) for x in cmdline])

def major_versions_differ(v1: str, v2: str) -> bool:
    return v1.split('.')[0:2] != v2.split('.')[0:2]

def load(build_dir: str) -> CoreData:
    filename = os.path.join(build_dir, 'meson-private', 'coredata.dat')
    load_fail_msg = f'Coredata file {filename!r} is corrupted. Try with a fresh build tree.'
    try:
        with open(filename, 'rb') as f:
            obj = pickle.load(f)
    except (pickle.UnpicklingError, EOFError):
        raise MesonException(load_fail_msg)
    except (ModuleNotFoundError, AttributeError):
        raise MesonException(
            "Coredata file {!r} references functions or classes that don't "
            "exist. This probably means that it was generated with an old "
            "version of meson.".format(filename))
    if not isinstance(obj, CoreData):
        raise MesonException(load_fail_msg)
    if major_versions_differ(obj.version, version):
        raise MesonVersionMismatchException(obj.version, version)
    return obj

def save(obj: CoreData, build_dir: str) -> str:
    filename = os.path.join(build_dir, 'meson-private', 'coredata.dat')
    prev_filename = filename + '.prev'
    tempfilename = filename + '~'
    if major_versions_differ(obj.version, version):
        raise MesonException('Fatal version mismatch corruption.')
    if os.path.exists(filename):
        import shutil
        shutil.copyfile(filename, prev_filename)
    with open(tempfilename, 'wb') as f:
        pickle.dump(obj, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tempfilename, filename)
    return filename


def register_builtin_arguments(parser: argparse.ArgumentParser) -> None:
    for n, b in BUILTIN_OPTIONS.items():
        b.add_to_argparse(str(n), parser, '')
    for n, b in BUILTIN_OPTIONS_PER_MACHINE.items():
        b.add_to_argparse(str(n), parser, ' (just for host machine)')
        b.add_to_argparse(str(n.as_build()), parser, ' (just for build machine)')
    parser.add_argument('-D', action='append', dest='projectoptions', default=[], metavar="option",
                        help='Set the value of an option, can be used several times to set multiple options.')

def create_options_dict(options: T.List[str], subproject: str = '') -> T.Dict[OptionKey, str]:
    result: T.OrderedDict[OptionKey, str] = OrderedDict()
    for o in options:
        try:
            (key, value) = o.split('=', 1)
        except ValueError:
            raise MesonException(f'Option {o!r} must have a value separated by equals sign.')
        k = OptionKey.from_string(key)
        if subproject:
            k = k.evolve(subproject=subproject)
        result[k] = value
    return result

def parse_cmd_line_options(args: argparse.Namespace) -> None:
    args.cmd_line_options = create_options_dict(args.projectoptions)

    # Merge builtin options set with --option into the dict.
    for key in chain(
            BUILTIN_OPTIONS.keys(),
            (k.as_build() for k in BUILTIN_OPTIONS_PER_MACHINE.keys()),
            BUILTIN_OPTIONS_PER_MACHINE.keys(),
    ):
        name = str(key)
        value = getattr(args, name, None)
        if value is not None:
            if key in args.cmd_line_options:
                cmdline_name = BuiltinOption.argparse_name_to_arg(name)
                raise MesonException(
                    'Got argument {0} as both -D{0} and {1}. Pick one.'.format(name, cmdline_name))
            args.cmd_line_options[key] = value
            delattr(args, name)


_U = T.TypeVar('_U', bound=UserOption[_T])

class BuiltinOption(T.Generic[_T, _U]):

    """Class for a builtin option type.

    There are some cases that are not fully supported yet.
    """

    def __init__(self, opt_type: T.Type[_U], description: str, default: T.Any, yielding: bool = True, *,
                 choices: T.Any = None):
        self.opt_type = opt_type
        self.description = description
        self.default = default
        self.choices = choices
        self.yielding = yielding

    def init_option(self, name: 'OptionKey', value: T.Optional[T.Any], prefix: str) -> _U:
        """Create an instance of opt_type and return it."""
        if value is None:
            value = self.prefixed_default(name, prefix)
        keywords = {'yielding': self.yielding, 'value': value}
        if self.choices:
            keywords['choices'] = self.choices
        return self.opt_type(self.description, **keywords)

    def _argparse_action(self) -> T.Optional[str]:
        # If the type is a boolean, the presence of the argument in --foo form
        # is to enable it. Disabling happens by using -Dfoo=false, which is
        # parsed under `args.projectoptions` and does not hit this codepath.
        if isinstance(self.default, bool):
            return 'store_true'
        return None

    def _argparse_choices(self) -> T.Any:
        if self.opt_type is UserBooleanOption:
            return [True, False]
        elif self.opt_type is UserFeatureOption:
            return UserFeatureOption.static_choices
        return self.choices

    @staticmethod
    def argparse_name_to_arg(name: str) -> str:
        if name == 'warning_level':
            return '--warnlevel'
        else:
            return '--' + name.replace('_', '-')

    def prefixed_default(self, name: 'OptionKey', prefix: str = '') -> T.Any:
        if self.opt_type in [UserComboOption, UserIntegerOption]:
            return self.default
        try:
            return BULITIN_DIR_NOPREFIX_OPTIONS[name][prefix]
        except KeyError:
            pass
        return self.default

    def add_to_argparse(self, name: str, parser: argparse.ArgumentParser, help_suffix: str) -> None:
        kwargs = OrderedDict()

        c = self._argparse_choices()
        b = self._argparse_action()
        h = self.description
        if not b:
            h = '{} (default: {}).'.format(h.rstrip('.'), self.prefixed_default(name))
        else:
            kwargs['action'] = b
        if c and not b:
            kwargs['choices'] = c
        kwargs['default'] = argparse.SUPPRESS
        kwargs['dest'] = name

        cmdline_name = self.argparse_name_to_arg(name)
        parser.add_argument(cmdline_name, help=h + help_suffix, **kwargs)


# Update `docs/markdown/Builtin-options.md` after changing the options below
# Also update mesonlib._BUILTIN_NAMES. See the comment there for why this is required.
BUILTIN_DIR_OPTIONS: 'KeyedOptionDictType' = OrderedDict([
    (OptionKey('prefix'),          BuiltinOption(UserStringOption, 'Installation prefix', default_prefix())),
    (OptionKey('bindir'),          BuiltinOption(UserStringOption, 'Executable directory', 'bin')),
    (OptionKey('datadir'),         BuiltinOption(UserStringOption, 'Data file directory', 'share')),
    (OptionKey('includedir'),      BuiltinOption(UserStringOption, 'Header file directory', 'include')),
    (OptionKey('infodir'),         BuiltinOption(UserStringOption, 'Info page directory', 'share/info')),
    (OptionKey('libdir'),          BuiltinOption(UserStringOption, 'Library directory', default_libdir())),
    (OptionKey('libexecdir'),      BuiltinOption(UserStringOption, 'Library executable directory', default_libexecdir())),
    (OptionKey('localedir'),       BuiltinOption(UserStringOption, 'Locale data directory', 'share/locale')),
    (OptionKey('localstatedir'),   BuiltinOption(UserStringOption, 'Localstate data directory', 'var')),
    (OptionKey('mandir'),          BuiltinOption(UserStringOption, 'Manual page directory', 'share/man')),
    (OptionKey('sbindir'),         BuiltinOption(UserStringOption, 'System executable directory', 'sbin')),
    (OptionKey('sharedstatedir'),  BuiltinOption(UserStringOption, 'Architecture-independent data directory', 'com')),
    (OptionKey('sysconfdir'),      BuiltinOption(UserStringOption, 'Sysconf data directory', 'etc')),
])

BUILTIN_CORE_OPTIONS: 'KeyedOptionDictType' = OrderedDict([
    (OptionKey('auto_features'),      BuiltinOption(UserFeatureOption,  "Override value of all 'auto' features", 'auto')),
    (OptionKey('backend'),            BuiltinOption(UserComboOption,    'Backend to use', 'ninja', choices=backendlist)),
    (OptionKey('buildtype'),          BuiltinOption(UserComboOption,    'Build type to use', 'debug',
                                                    choices=['plain', 'debug', 'debugoptimized', 'release', 'minsize', 'custom'])),
    (OptionKey('debug'),              BuiltinOption(UserBooleanOption,  'Debug', True)),
    (OptionKey('default_library'),    BuiltinOption(UserComboOption,    'Default library type', 'shared', choices=['shared', 'static', 'both'],
                                                    yielding=False)),
    (OptionKey('errorlogs'),          BuiltinOption(UserBooleanOption,  "Whether to print the logs from failing tests", True)),
    (OptionKey('install_umask'),      BuiltinOption(UserUmaskOption,    'Default umask to apply on permissions of installed files', '022')),
    (OptionKey('layout'),             BuiltinOption(UserComboOption,    'Build directory layout', 'mirror', choices=['mirror', 'flat'])),
    (OptionKey('optimization'),       BuiltinOption(UserComboOption,    'Optimization level', '0', choices=['0', 'g', '1', '2', '3', 's'])),
    (OptionKey('override_file'),      BuiltinOption(UserFilePathOption, 'Override file path', '')),
    (OptionKey('stdsplit'),           BuiltinOption(UserBooleanOption,   'Split stdout and stderr in test logs', True)),
    (OptionKey('strip'),              BuiltinOption(UserBooleanOption,  'Strip targets on install', False)),
    (OptionKey('unity'),              BuiltinOption(UserComboOption,    'Unity build', 'off', choices=['on', 'off', 'subprojects'])),
    (OptionKey('unity_size'),         BuiltinOption(UserIntegerOption,  'Unity block size', (2, None, 4))),
    (OptionKey('warning_level'),      BuiltinOption(UserComboOption,    'Compiler warning level to use', '1', choices=['0', '1', '2', '3'], yielding=False)),
    (OptionKey('werror'),             BuiltinOption(UserBooleanOption,  'Treat warnings as errors', False, yielding=False)),
    (OptionKey('wrap_mode'),          BuiltinOption(UserComboOption,    'Wrap mode', 'default', choices=['default', 'nofallback', 'nodownload', 'forcefallback', 'nopromote'])),
    (OptionKey('force_fallback_for'), BuiltinOption(UserArrayOption, 'Force fallback for those subprojects', [])),
])

BUILTIN_OPTIONS = OrderedDict(chain(BUILTIN_DIR_OPTIONS.items(), BUILTIN_CORE_OPTIONS.items()))

BUILTIN_OPTIONS_PER_MACHINE: 'KeyedOptionDictType' = OrderedDict([
    (OptionKey('pkg_config_path'), BuiltinOption(UserArrayOption, 'List of additional paths for pkg-config to search', [])),
    (OptionKey('cmake_prefix_path'), BuiltinOption(UserArrayOption, 'List of additional prefixes for cmake to search', [])),
])

# Special prefix-dependent defaults for installation directories that reside in
# a path outside of the prefix in FHS and common usage.
BULITIN_DIR_NOPREFIX_OPTIONS: T.Dict[OptionKey, T.Dict[str, str]] = {
    OptionKey('sysconfdir'):     {'/usr': '/etc'},
    OptionKey('localstatedir'):  {'/usr': '/var',     '/usr/local': '/var/local'},
    OptionKey('sharedstatedir'): {'/usr': '/var/lib', '/usr/local': '/var/local/lib'},
}

FORBIDDEN_TARGET_NAMES = {'clean': None,
                          'clean-ctlist': None,
                          'clean-gcno': None,
                          'clean-gcda': None,
                          'coverage': None,
                          'coverage-text': None,
                          'coverage-xml': None,
                          'coverage-html': None,
                          'phony': None,
                          'PHONY': None,
                          'all': None,
                          'test': None,
                          'benchmark': None,
                          'install': None,
                          'uninstall': None,
                          'build.ninja': None,
                          'scan-build': None,
                          'reconfigure': None,
                          'dist': None,
                          'distcheck': None,
                          }

