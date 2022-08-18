# Copyright 2012-2017 The Meson development team

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
from collections import defaultdict, OrderedDict
from dataclasses import dataclass, field, InitVar
from functools import lru_cache
import abc
import hashlib
import itertools, pathlib
import os
import pickle
import textwrap
import typing as T

from . import environment
from . import dependencies
from . import mlog
from . import programs
from .mesonlib import (
    HoldableObject, SecondLevelHolder,
    File, MesonException, MachineChoice, PerMachine, OrderedSet, listify,
    classify_unity_sources,
    get_filenames_templates_dict, substitute_values, has_path_sep,
    OptionKey, PerMachineDefaultable, OptionOverrideProxy,
    FileMode, MesonBugException
)
from .compilers import (
    is_object, clink_langs, sort_clink,
    is_known_suffix, detect_static_linker
)
from .interpreterbase import FeatureNew

if T.TYPE_CHECKING:
    from typing_extensions import Literal, Protocol, TypedDict

    from ._typing import ImmutableListProtocol
    from .backend.backends import Backend, ExecutableSerialisation
    from .compilers import Compiler
    from .dependencies.base import Dependency
    from .interpreter.interpreter import Test, SourceOutputs, Interpreter
    from .interpreter.kwargs import GNU_SYMBOL_VISIBILITY, LINK_LANGUAGE
    from .interpreterbase import SubProject
    from .linkers import StaticLinker
    from .mesonlib import FileOrString
    from .modules import ModuleState
    from .mparser import BaseNode
    from .wrap import WrapMode

    class HashFunctionProto(Protocol):

        def update(self, data: bytes) -> None: ...


    GeneratedTypes = T.Union['CustomTarget', 'CustomTargetIndex', 'GeneratedList']
    LibTypes = T.Union['SharedLibrary', 'StaticLibrary', 'CustomTarget', 'CustomTargetIndex']
    BuildTargetTypes = T.Union['BuildTarget', 'CustomTarget', 'CustomTargetIndex']

    class DFeatures(TypedDict):

        unittest: bool
        debug: T.List[T.Union[str, int]]
        import_dirs: T.List[IncludeDirs]
        versions: T.List[T.Union[str, int]]


def _process_install_tag(install_tag: T.Optional[T.Sequence[T.Optional[str]]],
                         num_outputs: int) -> T.List[T.Optional[str]]:
    _install_tag: T.List[T.Optional[str]]
    if not install_tag:
        _install_tag = [None] * num_outputs
    elif len(install_tag) == 1:
        _install_tag = list(install_tag) * num_outputs
    else:
        assert len(install_tag) == num_outputs, f'{len(install_tag)} == {num_outputs}'
        _install_tag = list(install_tag)
    return _install_tag


@lru_cache(maxsize=None)
def get_target_macos_dylib_install_name(ld: SharedLibrary) -> str:
    name = ['@rpath/', ld.prefix, ld.name]
    if ld.soversion is not None:
        name.append('.' + ld.soversion)
    name.append('.dylib')
    return ''.join(name)

class InvalidArguments(MesonException):
    pass

@dataclass(eq=False)
class DependencyOverride(HoldableObject):
    dep: dependencies.Dependency
    node: 'BaseNode'
    explicit: bool = True

@dataclass(eq=False)
class Headers(HoldableObject):
    sources: T.List[File]
    install_subdir: T.Optional[str]
    custom_install_dir: T.Optional[str]
    custom_install_mode: 'FileMode'
    subproject: str

    # TODO: we really don't need any of these methods, but they're preserved to
    # keep APIs relying on them working.

    def set_install_subdir(self, subdir: str) -> None:
        self.install_subdir = subdir

    def get_install_subdir(self) -> T.Optional[str]:
        return self.install_subdir

    def get_sources(self) -> T.List[File]:
        return self.sources

    def get_custom_install_dir(self) -> T.Optional[str]:
        return self.custom_install_dir

    def get_custom_install_mode(self) -> 'FileMode':
        return self.custom_install_mode


@dataclass(eq=False)
class Man(HoldableObject):
    sources: T.List[File]
    custom_install_dir: T.Optional[str]
    custom_install_mode: 'FileMode'
    subproject: str
    locale: T.Optional[str]

    def get_custom_install_dir(self) -> T.Optional[str]:
        return self.custom_install_dir

    def get_custom_install_mode(self) -> 'FileMode':
        return self.custom_install_mode

    def get_sources(self) -> T.List['File']:
        return self.sources


@dataclass(eq=False)
class EmptyDir(HoldableObject):
    path: str
    install_mode: 'FileMode'
    subproject: str
    install_tag: T.Optional[str] = None


@dataclass(eq=False)
class InstallDir(HoldableObject):
    source_subdir: str
    installable_subdir: str
    install_dir: str
    install_mode: 'FileMode'
    exclude: T.Tuple[T.Set[str], T.Set[str]]
    strip_directory: bool
    subproject: str
    from_source_dir: bool = True
    install_tag: T.Optional[str] = None

@dataclass(eq=False)
class DepManifest:
    version: str
    license: T.List[str]

    def to_json(self) -> T.Dict[str, T.Union[str, T.List[str]]]:
        return {
            'version': self.version,
            'license': self.license,
        }


# literally everything isn't dataclass stuff
class Build:
    """A class that holds the status of one build including
    all dependencies and so on.
    """

    def __init__(self, environment: environment.Environment):
        self.project_name = 'name of master project'
        self.project_version: T.Optional[str] = None
        self.environment = environment
        self.projects: T.Dict[SubProject, T.Optional[str]] = {}
        self.targets: 'T.OrderedDict[str, T.Union[CustomTarget, BuildTarget]]' = OrderedDict()
        self.run_target_names: T.Set[T.Tuple[str, str]] = set()
        self.global_args: PerMachine[T.Dict[str, T.List[str]]] = PerMachine({}, {})
        self.global_link_args: PerMachine[T.Dict[str, T.List[str]]] = PerMachine({}, {})
        self.projects_args: PerMachine[T.Dict[str, T.Dict[str, T.List[str]]]] = PerMachine({}, {})
        self.projects_link_args: PerMachine[T.Dict[str, T.Dict[str, T.List[str]]]] = PerMachine({}, {})
        self.tests: T.List['Test'] = []
        self.benchmarks: T.List['Test'] = []
        self.headers: T.List[Headers] = []
        self.man: T.List[Man] = []
        self.emptydir: T.List[EmptyDir] = []
        self.data: T.List[Data] = []
        self.symlinks: T.List[SymlinkData] = []
        self.static_linker: PerMachine[StaticLinker] = PerMachine(None, None)
        self.subprojects: T.Dict[SubProject, T.Optional[str]] = {}
        self.subproject_dir = ''
        self.install_scripts: T.List['ExecutableSerialisation'] = []
        self.postconf_scripts: T.List['ExecutableSerialisation'] = []
        self.dist_scripts: T.List['ExecutableSerialisation'] = []
        self.install_dirs: T.List[InstallDir] = []
        self.dep_manifest_name: T.Optional[str] = None
        self.dep_manifest: T.Dict[str, DepManifest] = {}
        self.stdlibs: PerMachine[T.Dict] = PerMachine({}, {})
        self.test_setups: T.Dict[str, TestSetup] = {}
        self.test_setup_default_name = None
        self.find_overrides: T.Dict[str, T.Union['Executable', programs.ExternalProgram, programs.OverrideProgram]] = {}
        self.searched_programs: T.Set[str] = set() # The list of all programs that have been searched for.

        # If we are doing a cross build we need two caches, if we're doing a
        # build == host compilation the both caches should point to the same place.
        self.dependency_overrides: PerMachine[T.Dict[T.Tuple, DependencyOverride]] = PerMachineDefaultable.default(
            environment.is_cross_build(), {}, {})
        self.devenv: T.List[EnvironmentVariables] = []
        self.modules: T.List[str] = []
        self.need_vsenv = False

    def get_build_targets(self) -> T.Mapping[str, BuildTarget]:
        build_targets = OrderedDict()
        for name, t in self.targets.items():
            if isinstance(t, BuildTarget):
                build_targets[name] = t
        return build_targets

    def get_custom_targets(self) -> T.Mapping[str, CustomTarget]:
        # XXX: should this also be returning CustomTargetIndex?
        custom_targets = OrderedDict()
        for name, t in self.targets.items():
            if isinstance(t, CustomTarget):
                custom_targets[name] = t
        return custom_targets

    def copy(self) -> Build:
        other = Build(self.environment)
        for k, v in self.__dict__.items():
            if isinstance(v, (list, dict, set, OrderedDict)):
                other.__dict__[k] = v.copy()
            else:
                other.__dict__[k] = v
        return other

    def merge(self, other: Build) -> None:
        for k, v in other.__dict__.items():
            self.__dict__[k] = v

    def ensure_static_linker(self, compiler: Compiler) -> None:
        if self.static_linker[compiler.for_machine] is None and compiler.needs_static_linker():
            self.static_linker[compiler.for_machine] = detect_static_linker(self.environment, compiler)

    def get_project(self) -> T.Optional[str]:
        return self.projects[T.cast('SubProject', '')]

    def get_subproject_dir(self) -> str:
        return self.subproject_dir

    def get_targets(self) -> 'T.OrderedDict[str, T.Union[CustomTarget, BuildTarget]]':
        return self.targets

    def get_tests(self) -> T.List['Test']:
        return self.tests

    def get_benchmarks(self) -> T.List['Test']:
        return self.benchmarks

    def get_headers(self) -> T.List['Headers']:
        return self.headers

    def get_man(self) -> T.List['Man']:
        return self.man

    def get_data(self) -> T.List['Data']:
        return self.data

    def get_symlinks(self) -> T.List['SymlinkData']:
        return self.symlinks

    def get_emptydir(self) -> T.List['EmptyDir']:
        return self.emptydir

    def get_install_subdirs(self) -> T.List['InstallDir']:
        return self.install_dirs

    def get_global_args(self, compiler: 'Compiler', for_machine: 'MachineChoice') -> T.List[str]:
        d = self.global_args[for_machine]
        return d.get(compiler.get_language(), [])

    def get_project_args(self, compiler: 'Compiler', project: str, for_machine: 'MachineChoice') -> T.List[str]:
        d = self.projects_args[for_machine]
        args = d.get(project)
        if not args:
            return []
        return args.get(compiler.get_language(), [])

    def get_global_link_args(self, compiler: 'Compiler', for_machine: 'MachineChoice') -> T.List[str]:
        d = self.global_link_args[for_machine]
        return d.get(compiler.get_language(), [])

    def get_project_link_args(self, compiler: 'Compiler', project: str, for_machine: 'MachineChoice') -> T.List[str]:
        d = self.projects_link_args[for_machine]

        link_args = d.get(project)
        if not link_args:
            return []

        return link_args.get(compiler.get_language(), [])

@dataclass(eq=False)
class IncludeDirs(HoldableObject):

    """Internal representation of an include_directories call."""

    curdir: str
    incdirs: T.List[str]
    is_system: bool
    # Interpreter has validated that all given directories
    # actually exist.
    extra_build_dirs: T.List[str] = field(default_factory=list)

    def __repr__(self) -> str:
        r = '<{} {}/{}>'
        return r.format(self.__class__.__name__, self.curdir, self.incdirs)

    def get_curdir(self) -> str:
        return self.curdir

    def get_incdirs(self) -> T.List[str]:
        return self.incdirs

    def get_extra_build_dirs(self) -> T.List[str]:
        return self.extra_build_dirs

    def to_string_list(self, sourcedir: str, builddir: T.Optional[str] = None) -> T.List[str]:
        """Convert IncludeDirs object to a list of strings.

        :param sourcedir: The absolute source directory
        :param builddir: The absolute build directory, option, buid dir will not
            be added if this is unset
        :returns: A list of strings (without compiler argument)
        """
        strlist: T.List[str] = []
        for idir in self.incdirs:
            strlist.append(os.path.join(sourcedir, self.curdir, idir))
            if builddir:
                strlist.append(os.path.join(builddir, self.curdir, idir))
        return strlist

@dataclass(eq=False)
class ExtractedObjects(HoldableObject):
    '''
    Holds a list of sources for which the objects must be extracted
    '''
    target: 'BuildTarget'
    srclist: T.List[File] = field(default_factory=list)
    genlist: T.List['GeneratedTypes'] = field(default_factory=list)
    objlist: T.List[T.Union[str, 'File', 'ExtractedObjects']] = field(default_factory=list)
    recursive: bool = True

    def __post_init__(self) -> None:
        if self.target.is_unity:
            self.check_unity_compatible()

    def __repr__(self) -> str:
        r = '<{0} {1!r}: {2}>'
        return r.format(self.__class__.__name__, self.target.name, self.srclist)

    @staticmethod
    def get_sources(sources: T.Sequence['FileOrString'], generated_sources: T.Sequence['GeneratedTypes']) -> T.List['FileOrString']:
        # Merge sources and generated sources
        sources = list(sources)
        for gensrc in generated_sources:
            for s in gensrc.get_outputs():
                # We cannot know the path where this source will be generated,
                # but all we need here is the file extension to determine the
                # compiler.
                sources.append(s)

        # Filter out headers and all non-source files
        return [s for s in sources if environment.is_source(s) and not environment.is_header(s)]

    def classify_all_sources(self, sources: T.Sequence[FileOrString], generated_sources: T.Sequence['GeneratedTypes']) -> T.Dict['Compiler', T.List['FileOrString']]:
        sources_ = self.get_sources(sources, generated_sources)
        return classify_unity_sources(self.target.compilers.values(), sources_)

    def check_unity_compatible(self) -> None:
        # Figure out if the extracted object list is compatible with a Unity
        # build. When we're doing a Unified build, we go through the sources,
        # and create a single source file from each subset of the sources that
        # can be compiled with a specific compiler. Then we create one object
        # from each unified source file. So for each compiler we can either
        # extra all its sources or none.
        cmpsrcs = self.classify_all_sources(self.target.sources, self.target.generated)
        extracted_cmpsrcs = self.classify_all_sources(self.srclist, self.genlist)

        for comp, srcs in extracted_cmpsrcs.items():
            if set(srcs) != set(cmpsrcs[comp]):
                raise MesonException('Single object files can not be extracted '
                                     'in Unity builds. You can only extract all '
                                     'the object files for each compiler at once.')


@dataclass(eq=False, order=False)
class StructuredSources(HoldableObject):

    """A container for sources in languages that use filesystem hierarchy.

    Languages like Rust and Cython rely on the layout of files in the filesystem
    as part of the compiler implementation. This structure allows us to
    represent the required filesystem layout.
    """

    sources: T.DefaultDict[str, T.List[T.Union[File, GeneratedTypes]]] = field(
        default_factory=lambda: defaultdict(list))

    def __add__(self, other: StructuredSources) -> StructuredSources:
        sources = self.sources.copy()
        for k, v in other.sources.items():
            sources[k].extend(v)
        return StructuredSources(sources)

    def __bool__(self) -> bool:
        return bool(self.sources)

    def first_file(self) -> T.Union[File, GeneratedTypes]:
        """Get the first source in the root

        :return: The first source in the root
        """
        return self.sources[''][0]

    def as_list(self) -> T.List[T.Union[File, GeneratedTypes]]:
        return list(itertools.chain.from_iterable(self.sources.values()))

    def needs_copy(self) -> bool:
        """Do we need to create a structure in the build directory.

        This allows us to avoid making copies if the structures exists in the
        source dir. Which could happen in situations where a generated source
        only exists in some configurations
        """
        for files in self.sources.values():
            for f in files:
                if isinstance(f, File):
                    if f.is_built:
                        return True
                else:
                    return True
        return False


EnvInitValueType = T.Dict[str, T.Union[str, T.List[str]]]


class EnvironmentVariables(HoldableObject):
    def __init__(self, values: T.Optional[EnvInitValueType] = None,
                 init_method: Literal['set', 'prepend', 'append'] = 'set', separator: str = os.pathsep) -> None:
        self.envvars: T.List[T.Tuple[T.Callable[[T.Dict[str, str], str, T.List[str], str], str], str, T.List[str], str]] = []
        # The set of all env vars we have operations for. Only used for self.has_name()
        self.varnames: T.Set[str] = set()

        if values:
            init_func = getattr(self, init_method)
            for name, value in values.items():
                init_func(name, listify(value), separator)

    def __repr__(self) -> str:
        repr_str = "<{0}: {1}>"
        return repr_str.format(self.__class__.__name__, self.envvars)

    def hash(self, hasher: HashFunctionProto) -> None:
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
    def _set(env: T.Dict[str, str], name: str, values: T.List[str], separator: str) -> str:
        return separator.join(values)

    @staticmethod
    def _append(env: T.Dict[str, str], name: str, values: T.List[str], separator: str) -> str:
        curr = env.get(name)
        return separator.join(values if curr is None else [curr] + values)

    @staticmethod
    def _prepend(env: T.Dict[str, str], name: str, values: T.List[str], separator: str) -> str:
        curr = env.get(name)
        return separator.join(values if curr is None else values + [curr])

    def get_env(self, full_env: T.MutableMapping[str, str]) -> T.Dict[str, str]:
        env: T.Dict[str, str] = {}
        env.update(full_env)
        for method, name, values, separator in self.envvars:
            env[name] = method(env, name, values, separator)
        return env

@dataclass(eq=False)
class Target(HoldableObject):

    TYPE_SUFFIX: T.ClassVar[str]
    TYPENAME: T.ClassVar[str]

    name: str
    subdir: str
    subproject: SubProject
    build_by_default: bool
    for_machine: MachineChoice
    environment: environment.Environment
    install: bool = False
    build_always_stale: bool = False
    extra_files: T.List[File] = field(default_factory=list)
    override_options: InitVar[T.Optional[T.Dict[OptionKey, str]]] = None

    def __post_init__(self, overrides: T.Optional[T.Dict[OptionKey, str]]) -> None:
        self.options = OptionOverrideProxy(overrides or {}, self.environment.coredata.options, self.subproject)
        # XXX: this should happen in the interpreter
        if has_path_sep(self.name):
            # Fix failing test 53 when this becomes an error.
            mlog.warning(textwrap.dedent(f'''\
                Target "{self.name}" has a path separator in its name.
                This is not supported, it can cause unexpected failures and will become
                a hard error in the future.'''))

    # dataclass comparators?
    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Target):
            return NotImplemented
        return self.get_id() < other.get_id()

    def __le__(self, other: object) -> bool:
        if not isinstance(other, Target):
            return NotImplemented
        return self.get_id() <= other.get_id()

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, Target):
            return NotImplemented
        return self.get_id() > other.get_id()

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, Target):
            return NotImplemented
        return self.get_id() >= other.get_id()

    def get_default_install_dir(self) -> T.Tuple[str, str]:
        raise NotImplementedError

    def get_custom_install_dir(self) -> T.List[T.Union[str, Literal[False]]]:
        raise NotImplementedError

    def get_install_dir(self) -> T.Tuple[T.List[T.Union[str, Literal[False]]], T.Optional[str], bool]:
        # Find the installation directory.
        default_install_dir, default_install_dir_name = self.get_default_install_dir()
        outdirs: T.List[T.Union[str, Literal[False]]] = self.get_custom_install_dir()
        if outdirs and outdirs[0] != default_install_dir:
            # Either the value is set to a non-default value, or is set to
            # False (which means we want this specific output out of many
            # outputs to not be installed).
            custom_install_dir = True
            default_install_dir_name = None
        else:
            custom_install_dir = False
            assert outdirs, 'We should always have something in the outdirs'

        return outdirs, default_install_dir_name, custom_install_dir

    def get_basename(self) -> str:
        return self.name

    def get_subdir(self) -> str:
        return self.subdir

    def get_typename(self) -> str:
        return self.TYPENAME

    @staticmethod
    def _get_id_hash(target_id: str) -> str:
        # We don't really need cryptographic security here.
        # Small-digest hash function with unlikely collision is good enough.
        h = hashlib.sha256()
        h.update(target_id.encode(encoding='utf-8', errors='replace'))
        # This ID should be case-insensitive and should work in Visual Studio,
        # e.g. it should not start with leading '-'.
        return h.hexdigest()[:7]

    @staticmethod
    def construct_id_from_path(subdir: str, name: str, type_suffix: str) -> str:
        """Construct target ID from subdir, name and type suffix.

        This helper function is made public mostly for tests."""
        # This ID must also be a valid file name on all OSs.
        # It should also avoid shell metacharacters for obvious
        # reasons. '@' is not used as often as '_' in source code names.
        # In case of collisions consider using checksums.
        # FIXME replace with assert when slash in names is prohibited
        name_part = name.replace('/', '@').replace('\\', '@')
        assert not has_path_sep(type_suffix)
        my_id = name_part + type_suffix
        if subdir:
            subdir_part = Target._get_id_hash(subdir)
            # preserve myid for better debuggability
            return subdir_part + '@@' + my_id
        return my_id

    def get_id(self) -> str:
        return self.construct_id_from_path(
            self.subdir, self.name, self.TYPE_SUFFIX)

    def set_option_overrides(self, option_overrides: T.Dict[OptionKey, str]) -> None:
        self.options.overrides = {}
        for k, v in option_overrides.items():
            if k.lang:
                self.options.overrides[k.evolve(machine=self.for_machine)] = v
            else:
                self.options.overrides[k] = v

    def get_options(self) -> OptionOverrideProxy:
        return self.options

    def get_option(self, key: 'OptionKey') -> T.Union[str, int, bool, 'WrapMode']:
        # We don't actually have wrapmode here to do an assert, so just do a
        # cast, we know what's in coredata anyway.
        # TODO: if it's possible to annotate get_option or validate_option_value
        # in the future we might be able to remove the cast here
        return T.cast('T.Union[str, int, bool, WrapMode]', self.options[key].value)

    def is_linkable_target(self) -> bool:
        return False

    def get_outputs(self) -> T.List[str]:
        return []

    def should_install(self) -> bool:
        return False

class BuildTarget(Target, metaclass=abc.ABCMeta):

    # There are dangerous defaults below, but onlya s InitVars, which are then
    # prsented to the `__post_init__` dunder ad `ImmutableListProtocol` instances,
    # So the default is not mutated. This is due to a limitation of dataclasses,
    # which doesn't allow default_factory for InitVar

    def __init__(
            self,
            name: str,
            subdir: str,
            subproject: 'SubProject',
            for_machine: MachineChoice,
            environment: environment.Environment,
            sources: T.Optional[T.Sequence['SourceOutputs']] = None,
            structured_sources: T.Optional[StructuredSources] = None,
            objects: T.Optional[T.List[T.Union[str, File, ExtractedObjects]]] = None,
            all_compilers: T.Optional[T.Dict[str, Compiler]] = None,
            *,
            build_by_default: bool = True,
            install: bool = False,
            build_always_stale: bool = False,
            extra_files: T.Optional[T.List[File]] = None,
            option_overrides: T.Optional[T.Dict[OptionKey, str]] = None,
            build_rpath: str = '',
            d_debug: T.Optional[T.List[T.Union[str, int]]] = None,
            d_import_dirs: T.Optional[T.List[IncludeDirs]] = None,
            d_module_versions: T.Optional[T.List[T.Union[str, int]]] = None,
            d_unittest: T.Optional[bool] = False,
            dependencies: T.Optional[T.List[dependencies.Dependency]] = None,
            dot_net_resources: T.Optional[T.List[File]] = None,
            gnu_symbol_visibility: GNU_SYMBOL_VISIBILITY = 'default',
            implicit_include_directories: bool = True,
            include_directories: T.Optional[T.List[IncludeDirs]] = None,
            install_dir: T.Optional[str] = None,
            install_mode: T.Optional[FileMode] = None,
            install_rpath: str = '',
            install_tag: T.Optional[T.List[T.Optional[str]]] = None,
            install_vala_targets: T.Optional[T.Tuple[T.Union[str, bool], T.Union[str, bool], T.Union[str, bool]]] = None,
            language_args: T.Optional[T.Dict[str, T.List[str]]] = None,
            link_args: T.Optional[T.List[str]] = None,
            link_depends: T.Optional[T.List[T.Union[File, CustomTarget, CustomTargetIndex]]] = None,
            link_language: T.Optional[LINK_LANGUAGE] = None,
            link_whole: T.Optional[T.List[T.Union[StaticLibrary, CustomTarget, CustomTargetIndex]]] = None,
            link_with: T.Optional[T.List[T.Union[SharedLibrary, StaticLibrary, SharedModule, CustomTarget, CustomTargetIndex]]] = None,
            name_prefix: T.Optional[str] = None,
            name_suffix: T.Optional[str] = None,
            pch_args: T.Optional[T.Dict[str, T.List[str]]] = None,
            rust_crate_type: str = 'bin',
            # None means "use default", False means "Don't generate".
            # False is only used for both_library where the target must be
            # compiled twice, to avoid having two targets producing the same
            # header
            vala_gir: T.Optional[T.Union[Literal[False], str]] = None,
            vala_header: T.Optional[T.Union[Literal[False], str]] = None,
            vala_vapi: T.Optional[T.Union[Literal[False], str]] = None,
            ) -> None:
        super().__init__(name, subdir, subproject, build_by_default, for_machine, environment,
                         install, build_always_stale, extra_files, option_overrides)
        self.extra_args: T.DefaultDict[str, T.List['FileOrString']] = defaultdict(list)
        self.external_deps: T.List[Dependency] = []
        self.link_with: T.List[BuildTargetTypes] = []
        self.link_whole: T.List[T.Union[StaticLibrary, CustomTarget, CustomTargetIndex]] = []
        self.pch: T.Dict[str, T.List[str]] = {}
        self.sources: T.List[File] = []
        self.generated: T.List[GeneratedTypes] = []
        self._added_deps: T.Set[Dependency] = set()

        self.structured_sources = structured_sources
        self.all_compilers = all_compilers or {}
        self.objects = objects or []

        self.build_rpath = build_rpath
        self.gnu_symbol_visibility = gnu_symbol_visibility
        self.implicit_include_directories = implicit_include_directories
        self.include_dirs = include_directories or []
        self.install_dir: T.List[T.Union[str, Literal[False]]] = [install_dir if install_dir is not None else self.get_default_install_dir()[0]]
        self.install_mode = install_mode if install_mode is not None else FileMode()
        self.install_rpath = install_rpath
        self.link_args = link_args or []
        self.link_depends = link_depends or []
        self.link_language = link_language
        self._prefix = name_prefix
        self._suffix = name_suffix
        self.dot_net_resources = dot_net_resources or []
        # Track build_rpath entries so we can remove them at install time
        self.rpath_dirs_to_remove: T.Set[bytes] = set()
        self.__install_vala = install_vala_targets or (False, False, False)

        self.compilers = OrderedDict() # type: OrderedDict[str, Compiler]

        self.d_features: DFeatures = {
            'debug': d_debug or [],
            'import_dirs': d_import_dirs or [],
            'unittest': d_unittest,
            'versions': d_module_versions or [],
        }
        if sources is not None:
            self.process_sourcelist(sources)
        if dependencies is not None:
            self.add_deps(dependencies)
        if link_with is not None:
            self.add_link(link_with)
        if link_whole is not None:
            self.add_link_whole(link_whole)
        if language_args is not None:
            # Do a cast because of type invariance…
            self.extra_args.update(T.cast('T.Mapping[str, T.List[FileOrString]]', language_args))
        if pch_args is not None:
            for k, v in pch_args.items():
                if v:
                    self.pch[k] = v

        # Yes, forcing 1 here is intended
        self.install_tag = _process_install_tag(install_tag, 1)
        self.filename = 'no_name'
        self.outputs = [self.filename]

        def get_vala(val: T.Union[str, None, Literal[False]], ext: str) -> T.Optional[str]:
            if val is False:
                return None
            return val or f'{self.name}.{ext}'

        self.vala_header: T.Optional[str] = get_vala(vala_header, 'h')
        self.vala_vapi: T.Optional[str] = get_vala(vala_vapi, 'vapi')
        self.vala_gir = vala_gir or None

        self.rust_crate_type = rust_crate_type

        for l in self.link_args:
            if '-Wl,-rpath' in l or l.startswith('-rpath'):
                mlog.warning(textwrap.dedent('''\
                    Please do not define rpath with a linker argument, use install_rpath
                    or build_rpath properties instead.
                    This will become a hard error in a future Meson release.
                '''))

        if not any([self.sources, self.generated, self.objects, self.link_whole, self.structured_sources]):
            mlog.warning(f'Build target {name} has no sources. '
                         'This was never supposed to be allowed but did because of a bug, '
                         'support will be removed in a future release of Meson')
        self.validate_install()
        self.check_module_linking()

    @abc.abstractmethod
    def _default_prefix(self) -> str:
        """Return the default prefix for the target

        :return: the prefix as a string
        """
        pass

    @abc.abstractmethod
    def _default_suffix(self) -> str:
        """Return the default suffix as a string

        :return: the suffix as a string
        """
        pass

    @property
    def prefix(self) -> str:
        """Get the prefix if it is set, otherwise the default

        :return: the user provided prefix or the default
        """
        if self._prefix is not None:
            return self._prefix
        return self._default_prefix()

    @property
    def suffix(self) -> str:
        """Get the suffix if it is set, otherwise the default

        :return: the user provided suffix or the default
        """
        if self._suffix is not None:
            return self._suffix
        return self._default_suffix()

    @property
    def name_prefix_set(self) -> bool:
        # XXX: delete this
        return self._prefix is not None

    @property
    def name_suffix_set(self) -> bool:
        # XXX: delete this
        return self._suffix is not None

    def post_init(self) -> None:
        ''' Initialisations and checks requiring the final list of compilers to be known
        '''
        self.validate_sources()

        # Handle a bunch of Vala special casing, namely adding extra outputs
        if 'vala' in self.compilers:
            # Header and vapi can only be None in Executable, which deletes them
            # If export_dynamic is false
            if self.vala_header is not None:
                self.outputs.append(self.vala_header)
                self.install_tag.append('devel')
                if self.__install_vala[0] is True:
                    self.install_dir.append(self.environment.get_includedir())
                else:
                    self.install_dir.append(self.__install_vala[0])
            if self.vala_vapi is not None:
                self.outputs.append(self.vala_vapi)
                self.install_tag.append('devel')
                if self.__install_vala[1] is True:
                    self.install_dir.append(os.path.join(self.environment.get_datadir(), 'vala', 'vapi'))
                else:
                    self.install_dir.append(self.__install_vala[1])
            if self.vala_gir is not None:
                self.outputs.append(self.vala_gir)
                self.install_tag.append('devel')
                if self.__install_vala[2] is True:
                    self.install_dir.append(os.path.join(self.environment.get_datadir(), 'gir-1.0'))
                else:
                    self.install_dir.append(self.__install_vala[2])

        if self.structured_sources and any([self.sources, self.generated]):
            raise MesonException('cannot mix structured sources and unstructured sources')
        if self.structured_sources and 'rust' not in self.compilers:
            raise MesonException('structured sources are only supported in Rust targets')

    def __repr__(self) -> str:
        repr_str = "<{0} {1}: {2}>"
        return repr_str.format(self.__class__.__name__, self.get_id(), self.filename)

    def __str__(self) -> str:
        return f"{self.name}"

    @property
    def is_unity(self) -> bool:
        unity_opt = self.get_option(OptionKey('unity'))
        return unity_opt == 'on' or (unity_opt == 'subprojects' and self.subproject != '')

    def validate_install(self) -> None:
        if self.for_machine is MachineChoice.BUILD and self.need_install:
            if self.environment.is_cross_build():
                raise InvalidArguments('Tried to install a target for the build machine in a cross build.')
            else:
                mlog.warning('Installing target build for the build machine. This will fail in a cross build.')


    def process_sourcelist(self, sources: T.Sequence[SourceOutputs]) -> None:
        """Split sources into generated and static sources.

        Sources can be:
        1. Pre-existing source files in the source tree (static)
        2. Pre-existing sources generated by configure_file in the build tree.
           (static as they are only regenerated if meson itself is regenerated)
        3. Sources files generated by another target or a Generator (generated)
        """
        added_sources: T.Set[File] = set() # If the same source is defined multiple times, use it only once.
        for s in sources:
            if isinstance(s, File):
                if s not in added_sources:
                    self.sources.append(s)
                    added_sources.add(s)
            elif isinstance(s, (CustomTarget, CustomTargetIndex, GeneratedList)):
                self.generated.append(s)

    @staticmethod
    def can_compile_remove_sources(compiler: 'Compiler', sources: T.List['FileOrString']) -> bool:
        removed = False
        for s in sources[:]:
            if compiler.can_compile(s):
                sources.remove(s)
                removed = True
        return removed

    def process_compilers_late(self, extra_languages: T.List[str]) -> None:
        """Processes additional compilers after kwargs have been evaluated.

        This can add extra compilers that might be required by keyword
        arguments, such as link_with or dependencies. It will also try to guess
        which compiler to use if one hasn't been selected already.
        """
        for lang in extra_languages:
            self.compilers[lang] = self.all_compilers[lang]

        # did user override clink_langs for this target?
        link_langs = [self.link_language] if self.link_language else clink_langs

        # If this library is linked against another library we need to consider
        # the languages of those libraries as well.
        if self.link_with or self.link_whole:
            for t in itertools.chain(self.link_with, self.link_whole):
                if isinstance(t, CustomTarget) or isinstance(t, CustomTargetIndex):
                    continue # We can't know anything about these.
                for name, compiler in t.compilers.items():
                    if name in link_langs and name not in self.compilers:
                        self.compilers[name] = compiler

        if not self.compilers:
            # No source files or parent targets, target consists of only object
            # files of unknown origin. Just add the first clink compiler
            # that we have and hope that it can link these objects
            for lang in link_langs:
                if lang in self.all_compilers:
                    self.compilers[lang] = self.all_compilers[lang]
                    break

        # Now that we have the final list of compilers we can sort it according
        # to clink_langs and do sanity checks.
        self.compilers = OrderedDict(sorted(self.compilers.items(),
                                            key=lambda t: sort_clink(t[0])))
        self.post_init()

    def process_compilers(self) -> T.List[str]:
        '''
        Populate self.compilers, which is the list of compilers that this
        target will use for compiling all its sources.
        We also add compilers that were used by extracted objects to simplify
        dynamic linker determination.
        Returns a list of missing languages that we can add implicitly, such as
        C/C++ compiler for cython.
        '''
        missing_languages: T.List[str] = []
        if not any([self.sources, self.generated, self.objects, self.structured_sources]):
            return missing_languages
        # Pre-existing sources
        sources: T.List['FileOrString'] = list(self.sources)
        generated = self.generated.copy()

        if self.structured_sources:
            for v in self.structured_sources.sources.values():
                for src in v:
                    if isinstance(src, (str, File)):
                        sources.append(src)
                    else:
                        generated.append(src)

        # All generated sources
        for gensrc in generated:
            for s in gensrc.get_outputs():
                # Generated objects can't be compiled, so don't use them for
                # compiler detection. If our target only has generated objects,
                # we will fall back to using the first c-like compiler we find,
                # which is what we need.
                if not is_object(s):
                    sources.append(s)
        for d in self.external_deps:
            for t in d.sources:
                if isinstance(t, (str, File)):
                    sources.append(t)

        # Sources that were used to create our extracted objects
        for o in self.objects:
            if not isinstance(o, ExtractedObjects):
                continue
            compsrcs = o.classify_all_sources(o.srclist, [])
            for comp in compsrcs:
                # Don't add Vala sources since that will pull in the Vala
                # compiler even though we will never use it since we are
                # dealing with compiled C code.
                if comp.language == 'vala':
                    continue
                if comp.language not in self.compilers:
                    self.compilers[comp.language] = comp
        if sources:
            # For each source, try to add one compiler that can compile it.
            #
            # If it has a suffix that belongs to a known language, we must have
            # a compiler for that language.
            #
            # Otherwise, it's ok if no compilers can compile it, because users
            # are expected to be able to add arbitrary non-source files to the
            # sources list
            for w in sources:
                for lang, compiler in self.all_compilers.items():
                    if compiler.can_compile(w):
                        if lang not in self.compilers:
                            self.compilers[lang] = compiler
                        break
                else:
                    if is_known_suffix(w):
                        path = pathlib.Path(str(w)).as_posix()
                        m = f'No {self.for_machine.get_lower_case_name()} machine compiler for {path!r}'
                        raise MesonException(m)

        # If all our sources are Vala, our target also needs the C compiler but
        # it won't get added above.
        if 'vala' in self.compilers and 'c' not in self.compilers:
            self.compilers['c'] = self.all_compilers['c']
        if 'cython' in self.compilers:
            key = OptionKey('language', machine=self.for_machine, lang='cython')
            value = self.get_option(key)
            assert isinstance(value, str), 'for mypy'

            try:
                self.compilers[value] = self.all_compilers[value]
            except KeyError:
                missing_languages.append(value)

        return missing_languages

    def validate_sources(self) -> None:
        if len(self.compilers) > 1 and any(lang in self.compilers for lang in {'cs', 'java'}):
            langs = ', '.join(self.compilers.keys())
            raise InvalidArguments(f'Cannot mix those languages into a target: {langs}')

    def extract_objects(self, srclist: T.List[T.Union['FileOrString', 'GeneratedTypes']]) -> ExtractedObjects:
        sources_set = set(self.sources)
        generated_set = set(self.generated)

        obj_src: T.List['File'] = []
        obj_gen: T.List['GeneratedTypes'] = []
        for src in srclist:
            if isinstance(src, (str, File)):
                if isinstance(src, str):
                    src = File(False, self.subdir, src)
                else:
                    FeatureNew.single_use('File argument for extract_objects', '0.50.0', self.subproject)
                if src not in sources_set:
                    raise MesonException(f'Tried to extract unknown source {src}.')
                obj_src.append(src)
            elif isinstance(src, (CustomTarget, CustomTargetIndex, GeneratedList)):
                FeatureNew.single_use('Generated sources for extract_objects', '0.61.0', self.subproject)
                target = src.target if isinstance(src, CustomTargetIndex) else src
                if src not in generated_set and target not in generated_set:
                    raise MesonException(f'Tried to extract unknown source {target.get_basename()}.')
                obj_gen.append(src)
            else:
                raise MesonException(f'Object extraction arguments must be strings, Files or targets (got {type(src).__name__}).')
        return ExtractedObjects(self, obj_src, obj_gen)

    def extract_all_objects(self, recursive: bool = True) -> ExtractedObjects:
        return ExtractedObjects(self, self.sources, self.generated, self.objects,
                                recursive)

    def get_all_link_deps(self) -> ImmutableListProtocol[BuildTargetTypes]:
        return self.get_transitive_link_deps()

    @lru_cache(maxsize=None)
    def get_transitive_link_deps(self) -> ImmutableListProtocol[BuildTargetTypes]:
        result: T.List[BuildTargetTypes] = []
        for i in self.link_with:
            result += i.get_all_link_deps()
        return result

    def get_link_deps_mapping(self, prefix: str) -> T.Mapping[str, str]:
        return self.get_transitive_link_deps_mapping(prefix)

    @lru_cache(maxsize=None)
    def get_transitive_link_deps_mapping(self, prefix: str) -> T.Mapping[str, str]:
        result: T.Dict[str, str] = {}
        for i in self.link_with:
            mapping = i.get_link_deps_mapping(prefix)
            #we are merging two dictionaries, while keeping the earlier one dominant
            result_tmp = dict(mapping)
            result_tmp.update(result)
            result = result_tmp
        return result

    @lru_cache(maxsize=None)
    def get_link_dep_subdirs(self) -> T.AbstractSet[str]:
        result: OrderedSet[str] = OrderedSet()
        for i in self.link_with:
            if not isinstance(i, StaticLibrary):
                result.add(i.get_subdir())
            result.update(i.get_link_dep_subdirs())
        return result

    def get_default_install_dir(self) -> T.Tuple[str, str]:
        return self.environment.get_libdir(), '{libdir}'

    def get_custom_install_dir(self) -> T.List[T.Union[str, Literal[False]]]:
        return self.install_dir

    def get_custom_install_mode(self) -> T.Optional['FileMode']:
        return self.install_mode

    @property
    def need_install(self) -> bool:
        # TODO: get rid of this and just use install directly
        return self.install

    def _extract_pic_pie(self, val: T.Optional[bool], arg: str) -> bool:
        m = self.environment.machines[self.for_machine]

        # Executables must be PIE on Android
        if arg == 'pie' and m.is_android():
            return True
        # You can't disable PIC on OS X. The compiler ignores -fno-PIC.
        # PIC is always on for Windows (all code is position-independent
        # since library loading is done differently)
        if arg == 'pic' and (m.is_darwin() or m.is_windows()):
            return True

        # Check if we have -fPIC, -fpic, -fPIE, or -fpie in cflags
        all_flags = self.extra_args['c'] + self.extra_args['cpp']
        if '-f' + arg.lower() in all_flags or '-f' + arg.upper() in all_flags:
            mlog.warning(f"Use the '{arg}' kwarg instead of passing '-f{arg}' manually to {self.name!r}")
            return True

        if val is None:
            k = OptionKey('b_staticpic' if arg == 'pic' else 'b_pie')
            if k in self.environment.coredata.options:
                val = self.environment.coredata.options[k].value
            else:
                val = False

        return val

    def get_filename(self) -> str:
        return self.filename

    def get_outputs(self) -> T.List[str]:
        return self.outputs

    def get_extra_args(self, language: str) -> T.List[FileOrString]:
        # TODO: use a Literal to further constrain this
        return self.extra_args.get(language, [])

    def get_dependencies(self, exclude: T.Optional[T.List[BuildTargetTypes]] = None
                         ) -> T.List[BuildTargetTypes]:
        transitive_deps: T.List[BuildTargetTypes] = []
        if exclude is None:
            exclude = []
        for t in itertools.chain(self.link_with, self.link_whole):
            if t in transitive_deps or t in exclude:
                continue
            transitive_deps.append(t)
            if isinstance(t, StaticLibrary):
                transitive_deps += t.get_dependencies(transitive_deps + exclude)
        return transitive_deps

    def get_source_subdir(self) -> str:
        return self.subdir

    def get_sources(self) -> T.List[File]:
        return self.sources

    def get_objects(self) -> T.List[T.Union[str, 'File', 'ExtractedObjects']]:
        return self.objects

    def get_generated_sources(self) -> T.List['GeneratedTypes']:
        return self.generated

    def should_install(self) -> bool:
        return self.need_install

    def has_pch(self) -> bool:
        return bool(self.pch)

    def get_pch(self, language: str) -> T.List[str]:
        return self.pch.get(language, [])

    def get_include_dirs(self) -> T.List['IncludeDirs']:
        return self.include_dirs

    def add_deps(self, deps: T.List[dependencies.Dependency]) -> None:
        deps = listify(deps)
        for dep in deps:
            if dep in self._added_deps:
                continue

            if isinstance(dep, dependencies.InternalDependency):
                # Those parts that are internal.
                self.process_sourcelist(dep.sources)
                self.add_include_dirs(dep.include_directories, dep.get_include_type())
                self.add_link(dep.libraries)
                self.add_link_whole(dep.whole_libraries)
                if dep.get_compile_args() or dep.get_link_args():
                    # Those parts that are external.
                    extpart = dependencies.InternalDependency('undefined',
                                                              [],
                                                              dep.get_compile_args(),
                                                              dep.get_link_args(),
                                                              [], [], [], [], {}, [], [])
                    self.external_deps.append(extpart)
                # Deps of deps.
                self.add_deps(dep.ext_deps)
            elif isinstance(dep, dependencies.Dependency):
                if dep not in self.external_deps:
                    self.external_deps.append(dep)
                    self.process_sourcelist(dep.get_sources())
                self.add_deps(dep.ext_deps)
            elif isinstance(dep, BuildTarget):
                raise InvalidArguments('''Tried to use a build target as a dependency.
You probably should put it in link_with instead.''')
            else:
                if hasattr(dep, 'project_args_frozen') or hasattr(dep, 'global_args_frozen'):
                    raise InvalidArguments('Tried to use subproject object as a dependency.\n'
                                           'You probably wanted to use a dependency declared in it instead.\n'
                                           'Access it by calling get_variable() on the subproject object.')
                raise InvalidArguments(f'Argument is of an unacceptable type {type(dep).__name__!r}.\nMust be '
                                       'either an external dependency (returned by find_library() or '
                                       'dependency()) or an internal dependency (returned by '
                                       'declare_dependency()).')
            if 'versions' in dep.d_features:
                self.d_features['versions'].extend(dep.d_features['versions'])
            if 'import_dirs' in dep.d_features:
                self.d_features['import_dirs'].extend(dep.d_features['import_dirs'])

            self._added_deps.add(dep)

    def get_external_deps(self) -> T.List[dependencies.Dependency]:
        return self.external_deps

    def is_internal(self) -> bool:
        return False

    def add_link(self, target: T.Sequence[BuildTargetTypes]) -> None:
        for t in target:
            if isinstance(self, StaticLibrary) and self.need_install:
                if isinstance(t, (CustomTarget, CustomTargetIndex)):
                    if not t.should_install():
                        mlog.warning(f'Try to link an installed static library target {self.name} with a'
                                     'custom target that is not installed, this might cause problems'
                                     'when you try to use this static library')
                elif t.is_internal():
                    # When we're a static library and we link_with to an
                    # internal/convenience library, promote to link_whole.
                    return self.add_link_whole([t])
            if not isinstance(t, (Target, CustomTargetIndex)):
                raise InvalidArguments(f'{t!r} is not a target.')
            if not t.is_linkable_target():
                raise InvalidArguments(f"Link target '{t!s}' is not linkable.")
            if isinstance(self, SharedLibrary) and isinstance(t, StaticLibrary) and not t.pic:
                msg = f"Can't link non-PIC static library {t.name!r} into shared library {self.name!r}. "
                msg += "Use the 'pic' option to static_library to build with PIC."
                raise InvalidArguments(msg)
            if self.for_machine is not t.for_machine:
                msg = f'Tried to mix libraries for machines {self.for_machine} and {t.for_machine} in target {self.name!r}'
                if self.environment.is_cross_build():
                    raise InvalidArguments(msg + ' This is not possible in a cross build.')
                else:
                    mlog.warning(msg + ' This will fail in cross build.')
            self.link_with.append(t)

    def add_link_whole(self, target: T.Sequence[BuildTargetTypes]) -> None:
        for t in target:
            if isinstance(t, (CustomTarget, CustomTargetIndex)):
                if not t.is_linkable_target():
                    raise InvalidArguments(f'Custom target {t!r} is not linkable.')
                if t.links_dynamically():
                    raise InvalidArguments('Can only link_whole custom targets that are static archives.')
                if isinstance(self, StaticLibrary):
                    # FIXME: We could extract the .a archive to get object files
                    raise InvalidArguments('Cannot link_whole a custom target into a static library')
            elif not isinstance(t, StaticLibrary):
                raise InvalidArguments(f'{t!r} is not a static library.')
            elif isinstance(self, SharedLibrary) and not t.pic:
                msg = f"Can't link non-PIC static library {t.name!r} into shared library {self.name!r}. "
                msg += "Use the 'pic' option to static_library to build with PIC."
                raise InvalidArguments(msg)
            if self.for_machine is not t.for_machine:
                msg = f'Tried to mix libraries for machines {self.for_machine} and {t.for_machine} in target {self.name!r}'
                if self.environment.is_cross_build():
                    raise InvalidArguments(msg + ' This is not possible in a cross build.')
                else:
                    mlog.warning(msg + ' This will fail in cross build.')
            if isinstance(self, StaticLibrary):
                # When we're a static library and we link_whole: to another static
                # library, we need to add that target's objects to ourselves.
                self.objects += t.extract_all_objects_recurse()
            self.link_whole.append(t)

    def extract_all_objects_recurse(self) -> T.List[T.Union[str, 'ExtractedObjects']]:
        objs: T.List[T.Union[str, ExtractedObjects]] = [self.extract_all_objects()]
        for t in self.link_with:
            if t.is_internal():
                objs += t.extract_all_objects_recurse()
        return objs

    def add_include_dirs(self, args: T.Sequence['IncludeDirs'], set_is_system: T.Optional[str] = None) -> None:
        ids: T.List['IncludeDirs'] = []
        for a in args:
            if not isinstance(a, IncludeDirs):
                raise InvalidArguments('Include directory to be added is not an include directory object.')
            ids.append(a)
        if set_is_system is None:
            set_is_system = 'preserve'
        if set_is_system != 'preserve':
            is_system = set_is_system == 'system'
            ids = [IncludeDirs(x.get_curdir(), x.get_incdirs(), is_system, x.get_extra_build_dirs()) for x in ids]
        self.include_dirs += ids

    def add_compiler_args(self, language: str, args: T.Iterable['FileOrString']) -> None:
        self.extra_args[language].extend(args)

    def get_aliases(self) -> T.List[T.Tuple[str, str, str]]:
        return []

    def get_langs_used_by_deps(self) -> T.List[str]:
        '''
        Sometimes you want to link to a C++ library that exports C API, which
        means the linker must link in the C++ stdlib, and we must use a C++
        compiler for linking. The same is also applicable for objc/objc++, etc,
        so we can keep using clink_langs for the priority order.

        See: https://github.com/mesonbuild/meson/issues/1653
        '''
        langs = [] # type: T.List[str]

        # Check if any of the external libraries were written in this language
        for dep in self.external_deps:
            if dep.language is None:
                continue
            if dep.language not in langs:
                langs.append(dep.language)
        # Check if any of the internal libraries this target links to were
        # written in this language
        for link_target in itertools.chain(self.link_with, self.link_whole):
            if isinstance(link_target, (CustomTarget, CustomTargetIndex)):
                continue
            for language in link_target.compilers:
                if language not in langs:
                    langs.append(language)

        return langs

    def get_prelinker(self) -> Compiler:
        if self.link_language:
            comp = self.all_compilers[self.link_language]
            return comp
        for l in clink_langs:
            if l in self.compilers:
                try:
                    prelinker = self.all_compilers[l]
                except KeyError:
                    raise MesonException(
                        f'Could not get a prelinker linker for build target {self.name!r}. '
                        f'Requires a compiler for language "{l}", but that is not '
                        'a project language.')
                return prelinker
        raise MesonException(f'Could not determine prelinker for {self.name!r}.')

    def get_clink_dynamic_linker_and_stdlibs(self) -> T.Tuple['Compiler', T.List[str]]:
        '''
        We use the order of languages in `clink_langs` to determine which
        linker to use in case the target has sources compiled with multiple
        compilers. All languages other than those in this list have their own
        linker.
        Note that Vala outputs C code, so Vala sources can use any linker
        that can link compiled C. We don't actually need to add an exception
        for Vala here because of that.
        '''
        # If the user set the link_language, just return that.
        if self.link_language:
            comp = self.all_compilers[self.link_language]
            return comp, comp.language_stdlib_only_link_flags(self.environment)

        # Since dependencies could come from subprojects, they could have
        # languages we don't have in self.all_compilers. Use the global list of
        # all compilers here.
        all_compilers = self.environment.coredata.compilers[self.for_machine]

        # Languages used by dependencies
        dep_langs = self.get_langs_used_by_deps()

        # This set contains all the languages a linker can link natively
        # without extra flags. For instance, nvcc (cuda) can link C++
        # without injecting -lc++/-lstdc++, see
        #   https://github.com/mesonbuild/meson/issues/10570
        MASK_LANGS = frozenset([
            # (language, linker)
            ('cpp', 'cuda'),
        ])
        # Pick a compiler based on the language priority-order
        for l in clink_langs:
            if l in self.compilers or l in dep_langs:
                try:
                    linker = all_compilers[l]
                except KeyError:
                    raise MesonException(
                        f'Could not get a dynamic linker for build target {self.name!r}. '
                        f'Requires a linker for language "{l}", but that is not '
                        'a project language.')
                stdlib_args: T.List[str] = []
                for dl in itertools.chain(self.compilers, dep_langs):
                    if dl != linker.language and (dl, linker.language) not in MASK_LANGS:
                        stdlib_args += all_compilers[dl].language_stdlib_only_link_flags(self.environment)
                # Type of var 'linker' is Compiler.
                # Pretty hard to fix because the return value is passed everywhere
                return linker, stdlib_args

        raise AssertionError(f'Could not get a dynamic linker for build target {self.name!r}')

    def uses_rust(self) -> bool:
        return 'rust' in self.compilers

    def get_using_msvc(self) -> bool:
        '''
        Check if the dynamic linker is MSVC. Used by Executable, StaticLibrary,
        and SharedLibrary for deciding when to use MSVC-specific file naming
        and debug filenames.

        If at least some code is built with MSVC and the final library is
        linked with MSVC, we can be sure that some debug info will be
        generated. We only check the dynamic linker here because the static
        linker is guaranteed to be of the same type.

        Interesting cases:
        1. The Vala compiler outputs C code to be compiled by whatever
           C compiler we're using, so all objects will still be created by the
           MSVC compiler.
        2. If the target contains only objects, process_compilers guesses and
           picks the first compiler that smells right.
        '''
        # Rustc can use msvc style linkers
        if self.uses_rust():
            compiler = self.all_compilers['rust']
        else:
            compiler, _ = self.get_clink_dynamic_linker_and_stdlibs()
        # Mixing many languages with MSVC is not supported yet so ignore stdlibs.
        return compiler.get_linker_id() in {'link', 'lld-link', 'xilink', 'optlink'}

    def check_module_linking(self) -> None:
        '''
        Warn if shared modules are linked with target: (link_with) #2865
        '''
        for link_target in self.link_with:
            if isinstance(link_target, SharedModule) and not link_target.force_soname:
                if self.environment.machines[self.for_machine].is_darwin():
                    raise MesonException(
                        f'target {self.name} links against shared module {link_target.name}. This is not permitted on OSX')
                elif self.environment.machines[self.for_machine].is_android() and isinstance(self, SharedModule):
                    # Android requires shared modules that use symbols from other shared modules to
                    # be linked before they can be dlopen()ed in the correct order. Not doing so
                    # leads to a missing symbol error: https://github.com/android/ndk/issues/201
                    link_target.force_soname = True
                else:
                    mlog.deprecation(f'target {self.name} links against shared module {link_target.name}, which is incorrect.'
                                     '\n             '
                                     f'This will be an error in the future, so please use shared_library() for {link_target.name} instead.'
                                     '\n             '
                                     f'If shared_module() was used for {link_target.name} because it has references to undefined symbols,'
                                     '\n             '
                                     'use shared_libary() with `override_options: [\'b_lundef=false\']` instead.')
                    link_target.force_soname = True

class Generator(HoldableObject):
    def __init__(self, exe: T.Union['Executable', programs.ExternalProgram],
                 arguments: T.List[str],
                 output: T.List[str],
                 # how2dataclass
                 *,
                 depfile: T.Optional[str] = None,
                 capture: bool = False,
                 depends: T.Optional[T.List[T.Union[BuildTarget, 'CustomTarget']]] = None,
                 name: str = 'Generator'):
        self.exe = exe
        self.depfile = depfile
        self.capture = capture
        self.depends: T.List[T.Union[BuildTarget, 'CustomTarget']] = depends or []
        self.arglist = arguments
        self.outputs = output
        self.name = name

    def __repr__(self) -> str:
        repr_str = "<{0}: {1}>"
        return repr_str.format(self.__class__.__name__, self.exe)

    def get_exe(self) -> T.Union['Executable', programs.ExternalProgram]:
        return self.exe

    def get_base_outnames(self, inname: str) -> T.List[str]:
        plainname = os.path.basename(inname)
        basename = os.path.splitext(plainname)[0]
        bases = [x.replace('@BASENAME@', basename).replace('@PLAINNAME@', plainname) for x in self.outputs]
        return bases

    def get_dep_outname(self, inname: str) -> str:
        if self.depfile is None:
            raise InvalidArguments('Tried to get dep name for rule that does not have dependency file defined.')
        plainname = os.path.basename(inname)
        basename = os.path.splitext(plainname)[0]
        return self.depfile.replace('@BASENAME@', basename).replace('@PLAINNAME@', plainname)

    def get_arglist(self, inname: str) -> T.List[str]:
        plainname = os.path.basename(inname)
        basename = os.path.splitext(plainname)[0]
        return [x.replace('@BASENAME@', basename).replace('@PLAINNAME@', plainname) for x in self.arglist]

    @staticmethod
    def is_parent_path(parent: str, trial: str) -> bool:
        relpath = pathlib.PurePath(trial).relative_to(parent)
        return relpath.parts[0] != '..' # For subdirs we can only go "down".

    def process_files(self, files: T.Iterable[T.Union[str, File, GeneratedTypes]],
                      state: T.Union['Interpreter', 'ModuleState'],
                      preserve_path_from: T.Optional[str] = None,
                      extra_args: T.Optional[T.List[str]] = None) -> 'GeneratedList':
        output = GeneratedList(self, state.subdir, preserve_path_from, extra_args=extra_args if extra_args is not None else [])

        for e in files:
            if isinstance(e, CustomTarget):
                output.depends.add(e)
            if isinstance(e, CustomTargetIndex):
                output.depends.add(e.target)

            if isinstance(e, (CustomTarget, CustomTargetIndex, GeneratedList)):
                output.depends.add(e)
                fs = [File.from_built_file(state.subdir, f) for f in e.get_outputs()]
            elif isinstance(e, str):
                fs = [File.from_source_file(state.environment.source_dir, state.subdir, e)]
            else:
                fs = [e]

            for f in fs:
                if preserve_path_from:
                    abs_f = f.absolute_path(state.environment.source_dir, state.environment.build_dir)
                    if not self.is_parent_path(preserve_path_from, abs_f):
                        raise InvalidArguments('generator.process: When using preserve_path_from, all input files must be in a subdirectory of the given dir.')
                output.add_file(f, state)
        return output


@dataclass(eq=False)
class GeneratedList(HoldableObject):

    """The output of generator.process."""

    generator: Generator
    subdir: str
    preserve_path_from: T.Optional[str]
    extra_args: T.List[str]

    def __post_init__(self) -> None:
        self.name = self.generator.exe
        self.depends: T.Set[GeneratedTypes] = set()
        self.infilelist: T.List['File'] = []
        self.outfilelist: T.List[str] = []
        self.outmap: T.Dict[File, T.List[str]] = {}
        self.depend_files: T.List[File] = []

        if self.extra_args is None:
            self.extra_args: T.List[str] = []

        if isinstance(self.generator.exe, programs.ExternalProgram):
            if not self.generator.exe.found():
                raise InvalidArguments('Tried to use not-found external program as generator')
            path = self.generator.exe.get_path()
            if os.path.isabs(path):
                # Can only add a dependency on an external program which we
                # know the absolute path of
                self.depend_files.append(File.from_absolute_file(path))

    def get_basename(self) -> str:
        return f'Generator: {self.name.name}'

    def add_preserved_path_segment(self, infile: File, outfiles: T.List[str], state: T.Union['Interpreter', 'ModuleState']) -> T.List[str]:
        result: T.List[str] = []
        in_abs = infile.absolute_path(state.environment.source_dir, state.environment.build_dir)
        assert os.path.isabs(self.preserve_path_from)
        rel = os.path.relpath(in_abs, self.preserve_path_from)
        path_segment = os.path.dirname(rel)
        for of in outfiles:
            result.append(os.path.join(path_segment, of))
        return result

    def add_file(self, newfile: File, state: T.Union['Interpreter', 'ModuleState']) -> None:
        self.infilelist.append(newfile)
        outfiles = self.generator.get_base_outnames(newfile.fname)
        if self.preserve_path_from:
            outfiles = self.add_preserved_path_segment(newfile, outfiles, state)
        self.outfilelist += outfiles
        self.outmap[newfile] = outfiles

    def get_inputs(self) -> T.List['File']:
        return self.infilelist

    def get_outputs(self) -> T.List[str]:
        return self.outfilelist

    def get_outputs_for(self, filename: 'File') -> T.List[str]:
        return self.outmap[filename]

    def get_generator(self) -> 'Generator':
        return self.generator

    def get_extra_args(self) -> T.List[str]:
        return self.extra_args

    def get_subdir(self) -> str:
        return self.subdir


class Executable(BuildTarget):

    TYPENAME = 'executable'
    TYPE_SUFFIX = '@exe'

    def __init__(
            self,
            name: str,
            subdir: str,
            subproject: 'SubProject',
            for_machine: MachineChoice,
            environment: environment.Environment,
            sources: T.Optional[T.Sequence['SourceOutputs']] = None,
            structured_sources: T.Optional[StructuredSources] = None,
            objects: T.Optional[T.List[T.Union[str, File, ExtractedObjects]]] = None,
            all_compilers: T.Optional[T.Dict[str, Compiler]] = None,
            *,
            build_by_default: bool = True,
            install: bool = False,
            build_always_stale: bool = False,
            extra_files: T.Optional[T.List[File]] = None,
            build_rpath: str = '',
            option_overrides: T.Optional[T.Dict[OptionKey, str]] = None,
            d_debug: T.Optional[T.List[T.Union[str, int]]] = None,
            d_import_dirs: T.Optional[T.List[IncludeDirs]] = None,
            d_module_versions: T.Optional[T.List[T.Union[str, int]]] = None,
            d_unittest: T.Optional[bool] = False,
            dependencies: T.Optional[T.List[dependencies.Dependency]] = None,
            dot_net_resources: T.Optional[T.List[File]] = None,
            gnu_symbol_visibility: GNU_SYMBOL_VISIBILITY = 'default',
            implicit_include_directories: bool = True,
            include_directories: T.Optional[T.List[IncludeDirs]] = None,
            install_dir: T.Optional[str] = None,
            install_mode: T.Optional[FileMode] = None,
            install_rpath: str = '',
            install_tag: T.Optional[T.List[T.Optional[str]]] = None,
            install_vala_targets: T.Optional[T.Tuple[T.Union[str, bool], T.Union[str, bool], T.Union[str, bool]]] = None,
            language_args: T.Optional[T.Dict[str, T.List[str]]] = None,
            link_args: T.Optional[T.List[str]] = None,
            link_depends: T.Optional[T.List[T.Union[File, CustomTarget, CustomTargetIndex]]] = None,
            link_language: T.Optional[LINK_LANGUAGE] = None,
            link_whole: T.Optional[T.List[T.Union[StaticLibrary, CustomTarget, CustomTargetIndex]]] = None,
            link_with: T.Optional[T.List[T.Union[SharedLibrary, StaticLibrary, SharedModule, CustomTarget, CustomTargetIndex]]] = None,
            name_prefix: T.Optional[str] = None,
            name_suffix: T.Optional[str] = None,
            pch_args: T.Optional[T.Dict[str, T.List[str]]] = None,
            vala_gir: T.Optional[T.Union[Literal[False], str]] = None,
            vala_header: T.Optional[T.Union[Literal[False], str]] = None,
            vala_vapi: T.Optional[T.Union[Literal[False], str]] = None,

            pie: T.Optional[bool] = None,
            export_dynamic: bool = False,
            implib: T.Optional[T.Union[str, bool]] = False,
            win_subsystem: str = 'console',
            rust_crate_type: str = 'bin',
            ) -> None:
        super().__init__(
            name, subdir, subproject, for_machine, environment, sources,
            structured_sources, objects, all_compilers,
            option_overrides=option_overrides,
            build_always_stale=build_always_stale,
            build_by_default=build_by_default, install=install,
            extra_files=extra_files, build_rpath=build_rpath, d_debug=d_debug,
            d_import_dirs=d_import_dirs, d_module_versions=d_module_versions,
            d_unittest=d_unittest, dependencies=dependencies,
            dot_net_resources=dot_net_resources,
            gnu_symbol_visibility=gnu_symbol_visibility,
            implicit_include_directories=implicit_include_directories,
            include_directories=include_directories, install_dir=install_dir,
            install_mode=install_mode, install_rpath=install_rpath,
            install_tag=install_tag, install_vala_targets=install_vala_targets,
            language_args=language_args,
            link_args=link_args, link_depends=link_depends,
            link_language=link_language, link_whole=link_whole,
            link_with=link_with, name_prefix=name_prefix,
            name_suffix=name_suffix, pch_args=pch_args,
            rust_crate_type=rust_crate_type, vala_gir=vala_gir,
            vala_header=vala_header, vala_vapi=vala_vapi)
        self.export_dynamic = export_dynamic
        self.implib = implib
        self.win_subsystem = win_subsystem

        self.pie = self._extract_pic_pie(pie, 'pie')
        if self.implib:
            self.export_dynamic = True
        if self.export_dynamic and self.implib is False:
            raise InvalidArguments('Executable: "implib" keyword argument must not be false for if "export_dynamic" is true')

        # Only linkwithable if using export_dynamic
        self.is_linkwithable = self.export_dynamic

        if not self.export_dynamic:
            self.vala_gir = None
            self.vala_header = None
            self.vala_vapi = None

        # Remember that this exe was returned by `find_program()` through an override
        self.was_returned_by_find_program = False

    def post_init(self) -> None:
        super().post_init()
        machine = self.environment.machines[self.for_machine]
        # Unless overridden, executables have no suffix or prefix. Except on
        # Windows and with C#/Mono executables where the suffix is 'exe'
        # Executable for Windows or C#/Mono
        if machine.is_windows() or machine.is_cygwin() or 'cs' in self.compilers:
            self.__suffix = 'exe'
        elif machine.system.startswith('wasm') or machine.system == 'emscripten':
            self.__suffix = 'js'
        elif ('c' in self.compilers and self.compilers['c'].get_id().startswith('armclang') or
                'cpp' in self.compilers and self.compilers['cpp'].get_id().startswith('armclang')):
            self.__suffix = 'axf'
        elif ('c' in self.compilers and self.compilers['c'].get_id().startswith('ccrx') or
                'cpp' in self.compilers and self.compilers['cpp'].get_id().startswith('ccrx')):
            self.__suffix = 'abs'
        elif ('c' in self.compilers and self.compilers['c'].get_id().startswith('xc16')):
            self.__suffix = 'elf'
        elif ('c' in self.compilers and self.compilers['c'].get_id() in ('ti', 'c2000') or
                'cpp' in self.compilers and self.compilers['cpp'].get_id() in ('ti', 'c2000')):
            self.__suffix = 'out'
        else:
            self.__suffix = machine.get_exe_suffix()
        self.filename = self.name
        if self.suffix:
            self.filename += '.' + self.suffix
        self.outputs = [self.filename]

        # The import library this target will generate
        self.import_filename = None
        # The import library that Visual Studio would generate (and accept)
        self.vs_import_filename = None
        # The import library that GCC would generate (and prefer)
        self.gcc_import_filename = None
        # The debugging information file this target will generate
        self.debug_filename = None

        # If using export_dynamic, set the import library name
        if self.export_dynamic:
            implib_basename = self.name + '.exe'
            if isinstance(self.implib, str):
                implib_basename = self.implib
            if machine.is_windows() or machine.is_cygwin():
                self.vs_import_filename = f'{implib_basename}.lib'
                self.gcc_import_filename = f'lib{implib_basename}.a'
                if self.get_using_msvc():
                    self.import_filename = self.vs_import_filename
                else:
                    self.import_filename = self.gcc_import_filename

        if machine.is_windows() and ('cs' in self.compilers or
                                     self.uses_rust() or
                                     self.get_using_msvc()):
            self.debug_filename = self.name + '.pdb'

    def _default_prefix(self) -> str:
        return ''

    def _default_suffix(self) -> str:
        return self.__suffix

    def get_default_install_dir(self) -> T.Tuple[str, str]:
        return self.environment.get_bindir(), '{bindir}'

    def description(self) -> str:
        '''Human friendly description of the executable'''
        return self.name

    def get_import_filename(self) -> T.Optional[str]:
        """
        The name of the import library that will be outputted by the compiler

        Returns None if there is no import library required for this platform
        """
        return self.import_filename

    def get_import_filenameslist(self) -> T.List[T.Optional[str]]:
        if self.import_filename:
            return [self.vs_import_filename, self.gcc_import_filename]
        return []

    def get_debug_filename(self) -> T.Optional[str]:
        """
        The name of debuginfo file that will be created by the compiler

        Returns None if the build won't create any debuginfo file
        """
        return self.debug_filename

    def is_linkable_target(self) -> bool:
        return self.is_linkwithable

    def get_command(self) -> 'ImmutableListProtocol[str]':
        """Provides compatibility with ExternalProgram.

        Since you can override ExternalProgram instances with Executables.
        """
        return self.outputs

class StaticLibrary(BuildTarget):

    TYPENAME = 'static library'
    TYPE_SUFFIX = '@sta'

    def __init__(
            self,
            name: str,
            subdir: str,
            subproject: 'SubProject',
            for_machine: MachineChoice,
            environment: environment.Environment,
            sources: T.Optional[T.Sequence['SourceOutputs']] = None,
            structured_sources: T.Optional[StructuredSources] = None,
            objects: T.Optional[T.List[T.Union[str, File, ExtractedObjects]]] = None,
            all_compilers: T.Optional[T.Dict[str, Compiler]] = None,
            *,
            build_by_default: bool = True,
            install: bool = False,
            build_always_stale: bool = False,
            extra_files: T.Optional[T.List[File]] = None,
            option_overrides: T.Optional[T.Dict[OptionKey, str]] = None,
            build_rpath: str = '',
            d_debug: T.Optional[T.List[T.Union[str, int]]] = None,
            d_import_dirs: T.Optional[T.List[IncludeDirs]] = None,
            d_module_versions: T.Optional[T.List[T.Union[str, int]]] = None,
            d_unittest: T.Optional[bool] = False,
            dependencies: T.Optional[T.List[dependencies.Dependency]] = None,
            dot_net_resources: T.Optional[T.List[File]] = None,
            gnu_symbol_visibility: GNU_SYMBOL_VISIBILITY = 'default',
            implicit_include_directories: bool = True,
            include_directories: T.Optional[T.List[IncludeDirs]] = None,
            install_dir: T.Optional[str] = None,
            install_mode: T.Optional[FileMode] = None,
            install_rpath: str = '',
            install_tag: T.Optional[T.List[T.Optional[str]]] = None,
            install_vala_targets: T.Optional[T.Tuple[T.Union[str, bool], T.Union[str, bool], T.Union[str, bool]]] = None,
            language_args: T.Optional[T.Dict[str, T.List[str]]] = None,
            link_args: T.Optional[T.List[str]] = None,
            link_depends: T.Optional[T.List[T.Union[File, CustomTarget, CustomTargetIndex]]] = None,
            link_language: T.Optional[LINK_LANGUAGE] = None,
            link_whole: T.Optional[T.List[T.Union[StaticLibrary, CustomTarget, CustomTargetIndex]]] = None,
            link_with: T.Optional[T.List[T.Union[SharedLibrary, StaticLibrary, SharedModule, CustomTarget, CustomTargetIndex]]] = None,
            name_prefix: T.Optional[str] = None,
            name_suffix: T.Optional[str] = None,
            pch_args: T.Optional[T.Dict[str, T.List[str]]] = None,
            vala_gir: T.Optional[T.Union[Literal[False], str]] = None,
            vala_header: T.Optional[T.Union[Literal[False], str]] = None,
            vala_vapi: T.Optional[T.Union[Literal[False], str]] = None,

            prelink: bool = False,
            pic: T.Optional[bool] = None,
            pie: T.Optional[bool] = None,
            rust_crate_type: str = 'lib',
            ) -> None:
        super().__init__(
            name, subdir, subproject, for_machine, environment, sources,
            structured_sources, objects, all_compilers,
            option_overrides=option_overrides,
            build_always_stale=build_always_stale,
            build_by_default=build_by_default, install=install,
            extra_files=extra_files, build_rpath=build_rpath, d_debug=d_debug,
            d_import_dirs=d_import_dirs, d_module_versions=d_module_versions,
            d_unittest=d_unittest, dependencies=dependencies,
            dot_net_resources=dot_net_resources,
            gnu_symbol_visibility=gnu_symbol_visibility,
            implicit_include_directories=implicit_include_directories,
            include_directories=include_directories, install_dir=install_dir,
            install_mode=install_mode, install_rpath=install_rpath,
            install_tag=install_tag, install_vala_targets=install_vala_targets,
            language_args=language_args,
            link_args=link_args, link_depends=link_depends,
            link_language=link_language, link_whole=link_whole,
            link_with=link_with, name_prefix=name_prefix,
            name_suffix=name_suffix, pch_args=pch_args,
            rust_crate_type=rust_crate_type, vala_gir=vala_gir,
            vala_header=vala_header, vala_vapi=vala_vapi)
        self.pic = self._extract_pic_pie(pic, 'pic')
        self.pie = self._extract_pic_pie(pie, 'pie')
        self.prelink = prelink

    def _default_prefix(self) -> str:
        return 'lib'

    @lru_cache(1)
    def _default_suffix(self) -> str:
        # By default a static library is named libfoo.a even on Windows because
        # MSVC does not have a consistent convention for what static libraries
        # are called. The MSVC CRT uses libfoo.lib syntax but nothing else uses
        # it and GCC only looks for static libraries called foo.lib and
        # libfoo.a. However, we cannot use foo.lib because that's the same as
        # the import library. Using libfoo.a is ok because people using MSVC
        # always pass the library filename while linking anyway.
        if 'rust' in self.compilers and self.rust_crate_type == 'rlib':
            return 'rlib'
        return 'a'

    def post_init(self) -> None:
        super().post_init()
        if 'cs' in self.compilers:
            raise InvalidArguments('Static libraries not supported for C#.')
        if 'rust' in self.compilers:
            # If no crate type is specified, or it's the generic lib type, use rlib
            if self.rust_crate_type == 'lib':
                mlog.debug('Defaulting Rust static library target crate type to rlib')
                self.rust_crate_type = 'rlib'
        self.filename = f'{self.prefix}{self.name}.{self.suffix}'
        self.outputs = [self.filename]

    def get_link_deps_mapping(self, prefix: str) -> T.Mapping[str, str]:
        return {}

    def get_default_install_dir(self) -> T.Tuple[str, str]:
        return self.environment.get_static_lib_dir(), '{libdir_static}'

    def is_linkable_target(self) -> bool:
        return True

    def is_internal(self) -> bool:
        return not self.need_install

class SharedLibrary(BuildTarget):

    TYPENAME = 'shared library'
    TYPE_SUFFIX = '@sha'

    def __init__(
            self,
            name: str,
            subdir: str,
            subproject: 'SubProject',
            for_machine: MachineChoice,
            environment: environment.Environment,
            sources: T.Optional[T.Sequence['SourceOutputs']] = None,
            structured_sources: T.Optional[StructuredSources] = None,
            objects: T.Optional[T.List[T.Union[str, File, ExtractedObjects]]] = None,
            all_compilers: T.Optional[T.Dict[str, Compiler]] = None,
            *,
            build_by_default: bool = True,
            install: bool = False,
            build_always_stale: bool = False,
            extra_files: T.Optional[T.List[File]] = None,
            option_overrides: T.Optional[T.Dict[OptionKey, str]] = None,
            build_rpath: str = '',
            d_debug: T.Optional[T.List[T.Union[str, int]]] = None,
            d_import_dirs: T.Optional[T.List[IncludeDirs]] = None,
            d_module_versions: T.Optional[T.List[T.Union[str, int]]] = None,
            d_unittest: T.Optional[bool] = False,
            dependencies: T.Optional[T.List[dependencies.Dependency]] = None,
            dot_net_resources: T.Optional[T.List[File]] = None,
            gnu_symbol_visibility: GNU_SYMBOL_VISIBILITY = 'default',
            implicit_include_directories: bool = True,
            include_directories: T.Optional[T.List[IncludeDirs]] = None,
            install_dir: T.Optional[str] = None,
            install_mode: T.Optional[FileMode] = None,
            install_rpath: str = '',
            install_tag: T.Optional[T.List[T.Optional[str]]] = None,
            install_vala_targets: T.Optional[T.Tuple[T.Union[str, bool], T.Union[str, bool], T.Union[str, bool]]] = None,
            language_args: T.Optional[T.Dict[str, T.List[str]]] = None,
            link_args: T.Optional[T.List[str]] = None,
            link_depends: T.Optional[T.List[T.Union[File, CustomTarget, CustomTargetIndex]]] = None,
            link_language: T.Optional[LINK_LANGUAGE] = None,
            link_whole: T.Optional[T.List[T.Union[StaticLibrary, CustomTarget, CustomTargetIndex]]] = None,
            link_with: T.Optional[T.List[T.Union[SharedLibrary, StaticLibrary, SharedModule, CustomTarget, CustomTargetIndex]]] = None,
            name_prefix: T.Optional[str] = None,
            name_suffix: T.Optional[str] = None,
            pch_args: T.Optional[T.Dict[str, T.List[str]]] = None,
            vala_gir: T.Optional[T.Union[Literal[False], str]] = None,
            vala_header: T.Optional[T.Union[Literal[False], str]] = None,
            vala_vapi: T.Optional[T.Union[Literal[False], str]] = None,

            version: T.Optional[str] = None,
            soversion: T.Optional[str] = None,
            darwin_versions: T.Optional[T.Tuple[str, str]] = None,
            vs_module_defs: T.Optional[T.Union[File, CustomTarget, CustomTargetIndex]] = None,
            rust_crate_type: str = 'lib',
            ) -> None:
        super().__init__(
            name, subdir, subproject, for_machine, environment, sources,
            structured_sources, objects, all_compilers,
            option_overrides=option_overrides,
            build_always_stale=build_always_stale,
            build_by_default=build_by_default, install=install,
            extra_files=extra_files, build_rpath=build_rpath, d_debug=d_debug,
            d_import_dirs=d_import_dirs, d_module_versions=d_module_versions,
            d_unittest=d_unittest, dependencies=dependencies,
            dot_net_resources=dot_net_resources,
            gnu_symbol_visibility=gnu_symbol_visibility,
            implicit_include_directories=implicit_include_directories,
            include_directories=include_directories, install_dir=install_dir,
            install_mode=install_mode, install_rpath=install_rpath,
            install_tag=install_tag, install_vala_targets=install_vala_targets,
            language_args=language_args,
            link_args=link_args, link_depends=link_depends,
            link_language=link_language, link_whole=link_whole,
            link_with=link_with, name_prefix=name_prefix,
            name_suffix=name_suffix, pch_args=pch_args,
            rust_crate_type=rust_crate_type, vala_gir=vala_gir,
            vala_header=vala_header, vala_vapi=vala_vapi)
        self.ltversion = version
        self.soversion = soversion
        self.darwin_versions = darwin_versions
        self.vs_module_defs = vs_module_defs
        self.import_filename: T.Optional[str] = None
        self.vs_import_filename: T.Optional[str] = None
        self.gcc_import_filename: T.Optional[str] = None
        self.debug_filename: T.Optional[str] = None
        self.shared_library_only = False

        if self.environment.machines[self.for_machine].is_android():
            self.ltversion = None
            self.soversion = None
            self.darwin_versions = None
        else:
            if self.ltversion is not None and self.soversion is None:
                self.soversion = self.ltversion.split('.', 1)[0]
            if self.soversion is not None and self.darwin_versions is None:
                self.darwin_versions = (self.soversion, self.soversion)
        if self.vs_module_defs:
            self.link_depends.append(self.vs_module_defs)

    def post_init(self) -> None:
        super().post_init()
        self.basic_filename_tpl = '{0.prefix}{0.name}.{0.suffix}'
        if 'rust' in self.compilers:
            # If no crate type is specified, or it's the generic lib type, use rlib
            if self.rust_crate_type == 'lib':
                mlog.debug('Defaulting Rust dynamic library target crate type to dylib')
                self.rust_crate_type = 'dylib'
        self.determine_filenames()

    def get_link_deps_mapping(self, prefix: str) -> T.Mapping[str, str]:
        mappings = dict(self.get_transitive_link_deps_mapping(prefix))
        old = get_target_macos_dylib_install_name(self)
        if old not in mappings:
            fname = self.get_filename()
            outdirs, _, _ = self.get_install_dir()
            # I'm not entirely convinced this is correct, but joining False is obviously wrong so…
            od = outdirs[0] if outdirs[0] is not False else self.get_default_install_dir()[0]
            new = os.path.join(prefix, od, fname)
            mappings[old] = new
        return mappings

    def get_default_install_dir(self) -> T.Tuple[str, str]:
        return self.environment.get_shared_lib_dir(), '{libdir_shared}'

    def determine_filenames(self) -> None:
        """
        See https://github.com/mesonbuild/meson/pull/417 for details.

        First we determine the filename template (self.filename_tpl), then we
        set the output filename (self.filename).

        The template is needed while creating aliases (self.get_aliases),
        which are needed while generating .so shared libraries for Linux.

        Besides this, there's also the import library name, which is only used
        on Windows since on that platform the linker uses a separate library
        called the "import library" during linking instead of the shared
        library (DLL). The toolchain will output an import library in one of
        two formats: GCC or Visual Studio.

        When we're building with Visual Studio, the import library that will be
        generated by the toolchain is self.vs_import_filename, and with
        MinGW/GCC, it's self.gcc_import_filename. self.import_filename will
        always contain the import library name this target will generate.
        """
        prefix = ''
        suffix = ''
        create_debug_file = False
        self.filename_tpl = self.basic_filename_tpl
        # NOTE: manual prefix/suffix override is currently only tested for C/C++
        # C# and Mono
        if 'cs' in self.compilers:
            prefix = ''
            suffix = 'dll'
            self.filename_tpl = '{0.prefix}{0.name}.{0.suffix}'
            create_debug_file = True
        # C, C++, Swift, Vala
        # Only Windows uses a separate import library for linking
        # For all other targets/platforms import_filename stays None
        elif self.environment.machines[self.for_machine].is_windows():
            suffix = 'dll'
            self.vs_import_filename = '{}{}.lib'.format(self._prefix if self._prefix is not None else '', self.name)
            self.gcc_import_filename = '{}{}.dll.a'.format(self._prefix if self._prefix is not None else 'lib', self.name)
            if self.uses_rust():
                # Shared library is of the form foo.dll
                prefix = ''
                # Import library is called foo.dll.lib
                self.import_filename = f'{self.name}.dll.lib'
                create_debug_file = True
            elif self.get_using_msvc():
                # Shared library is of the form foo.dll
                prefix = ''
                # Import library is called foo.lib
                self.import_filename = self.vs_import_filename
                create_debug_file = True
            # Assume GCC-compatible naming
            else:
                # Shared library is of the form libfoo.dll
                prefix = 'lib'
                # Import library is called libfoo.dll.a
                self.import_filename = self.gcc_import_filename
            # Shared library has the soversion if it is defined
            if self.soversion:
                self.filename_tpl = '{0.prefix}{0.name}-{0.soversion}.{0.suffix}'
            else:
                self.filename_tpl = '{0.prefix}{0.name}.{0.suffix}'
        elif self.environment.machines[self.for_machine].is_cygwin():
            suffix = 'dll'
            self.gcc_import_filename = '{}{}.dll.a'.format(self._prefix if self._prefix is not None else 'lib', self.name)
            # Shared library is of the form cygfoo.dll
            # (ld --dll-search-prefix=cyg is the default)
            prefix = 'cyg'
            # Import library is called libfoo.dll.a
            self.import_filename = self.gcc_import_filename
            if self.soversion:
                self.filename_tpl = '{0.prefix}{0.name}-{0.soversion}.{0.suffix}'
            else:
                self.filename_tpl = '{0.prefix}{0.name}.{0.suffix}'
        elif self.environment.machines[self.for_machine].is_darwin():
            prefix = 'lib'
            suffix = 'dylib'
            # On macOS, the filename can only contain the major version
            if self.soversion:
                # libfoo.X.dylib
                self.filename_tpl = '{0.prefix}{0.name}.{0.soversion}.{0.suffix}'
            else:
                # libfoo.dylib
                self.filename_tpl = '{0.prefix}{0.name}.{0.suffix}'
        elif self.environment.machines[self.for_machine].is_android():
            prefix = 'lib'
            suffix = 'so'
            # Android doesn't support shared_library versioning
            self.filename_tpl = '{0.prefix}{0.name}.{0.suffix}'
        else:
            prefix = 'lib'
            suffix = 'so'
            if self.ltversion:
                # libfoo.so.X[.Y[.Z]] (.Y and .Z are optional)
                self.filename_tpl = '{0.prefix}{0.name}.{0.suffix}.{0.ltversion}'
            elif self.soversion:
                # libfoo.so.X
                self.filename_tpl = '{0.prefix}{0.name}.{0.suffix}.{0.soversion}'
            else:
                # No versioning, libfoo.so
                self.filename_tpl = '{0.prefix}{0.name}.{0.suffix}'
        self.__prefix = prefix
        self.__suffix = suffix
        self.filename = self.filename_tpl.format(self)
        # There may have been more outputs added by the time we get here, so
        # only replace the first entry
        self.outputs[0] = self.filename
        if create_debug_file:
            self.debug_filename = os.path.splitext(self.filename)[0] + '.pdb'

    def _default_prefix(self) -> str:
        return self.__prefix

    def _default_suffix(self) -> str:
        return self.__suffix


    def get_import_filename(self) -> T.Optional[str]:
        """
        The name of the import library that will be outputted by the compiler

        Returns None if there is no import library required for this platform
        """
        return self.import_filename

    def get_debug_filename(self) -> T.Optional[str]:
        """
        The name of debuginfo file that will be created by the compiler

        Returns None if the build won't create any debuginfo file
        """
        return self.debug_filename

    def get_import_filenameslist(self) -> T.List[T.Optional[str]]:
        if self.import_filename:
            return [self.vs_import_filename, self.gcc_import_filename]
        return []

    def get_all_link_deps(self) -> T.List[BuildTargetTypes]:
        l: T.List[BuildTargetTypes] = [self]
        l.extend(self.get_transitive_link_deps())
        return l

    def get_aliases(self) -> T.List[T.Tuple[str, str, str]]:
        """
        If the versioned library name is libfoo.so.0.100.0, aliases are:
        * libfoo.so.0 (soversion) -> libfoo.so.0.100.0
        * libfoo.so (unversioned; for linking) -> libfoo.so.0
        Same for dylib:
        * libfoo.dylib (unversioned; for linking) -> libfoo.0.dylib
        """
        aliases: T.List[T.Tuple[str, str, str]] = []
        # Aliases are only useful with .so and .dylib libraries. Also if
        # there's no self.soversion (no versioning), we don't need aliases.
        if self.suffix not in ('so', 'dylib') or not self.soversion:
            return aliases
        # With .so libraries, the minor and micro versions are also in the
        # filename. If ltversion != soversion we create an soversion alias:
        # libfoo.so.0 -> libfoo.so.0.100.0
        # Where libfoo.so.0.100.0 is the actual library
        if self.suffix == 'so' and self.ltversion and self.ltversion != self.soversion:
            alias_tpl = self.filename_tpl.replace('ltversion', 'soversion')
            ltversion_filename = alias_tpl.format(self)
            tag = self.install_tag[0] or 'runtime'
            aliases.append((ltversion_filename, self.filename, tag))
        # libfoo.so.0/libfoo.0.dylib is the actual library
        else:
            ltversion_filename = self.filename
        # Unversioned alias:
        #  libfoo.so -> libfoo.so.0
        #  libfoo.dylib -> libfoo.0.dylib
        tag = self.install_tag[0] or 'devel'
        aliases.append((self.basic_filename_tpl.format(self), ltversion_filename, tag))
        return aliases

    def is_linkable_target(self) -> bool:
        return True


class SharedModule(SharedLibrary):

    """A shared library that is meant to be used with dlopen rather than linking
    into something else.
    """

    TYPENAME = 'shared module'

    def __init__(
            self,
            name: str,
            subdir: str,
            subproject: 'SubProject',
            for_machine: MachineChoice,
            environment: environment.Environment,
            sources: T.Optional[T.Sequence['SourceOutputs']] = None,
            structured_sources: T.Optional[StructuredSources] = None,
            objects: T.Optional[T.List[T.Union[str, File, ExtractedObjects]]] = None,
            all_compilers: T.Optional[T.Dict[str, Compiler]] = None,
            *,
            build_by_default: bool = True,
            install: bool = False,
            build_always_stale: bool = False,
            extra_files: T.Optional[T.List[File]] = None,
            option_overrides: T.Optional[T.Dict[OptionKey, str]] = None,
            build_rpath: str = '',
            d_debug: T.Optional[T.List[T.Union[str, int]]] = None,
            d_import_dirs: T.Optional[T.List[IncludeDirs]] = None,
            d_module_versions: T.Optional[T.List[T.Union[str, int]]] = None,
            d_unittest: T.Optional[bool] = False,
            dependencies: T.Optional[T.List[dependencies.Dependency]] = None,
            dot_net_resources: T.Optional[T.List[File]] = None,
            gnu_symbol_visibility: GNU_SYMBOL_VISIBILITY = 'default',
            implicit_include_directories: bool = True,
            include_directories: T.Optional[T.List[IncludeDirs]] = None,
            install_dir: T.Optional[str] = None,
            install_mode: T.Optional[FileMode] = None,
            install_rpath: str = '',
            install_tag: T.Optional[T.List[T.Optional[str]]] = None,
            install_vala_targets: T.Optional[T.Tuple[T.Union[str, bool], T.Union[str, bool], T.Union[str, bool]]] = None,
            language_args: T.Optional[T.Dict[str, T.List[str]]] = None,
            link_args: T.Optional[T.List[str]] = None,
            link_depends: T.Optional[T.List[T.Union[File, CustomTarget, CustomTargetIndex]]] = None,
            link_language: T.Optional[LINK_LANGUAGE] = None,
            link_whole: T.Optional[T.List[T.Union[StaticLibrary, CustomTarget, CustomTargetIndex]]] = None,
            link_with: T.Optional[T.List[T.Union[SharedLibrary, StaticLibrary, SharedModule, CustomTarget, CustomTargetIndex]]] = None,
            name_prefix: T.Optional[str] = None,
            name_suffix: T.Optional[str] = None,
            pch_args: T.Optional[T.Dict[str, T.List[str]]] = None,
            vala_gir: T.Optional[T.Union[Literal[False], str]] = None,
            vala_header: T.Optional[T.Union[Literal[False], str]] = None,
            vala_vapi: T.Optional[T.Union[Literal[False], str]] = None,

            vs_module_defs: T.Optional[T.Union[File, CustomTarget, CustomTargetIndex]] = None,
            ) -> None:
        super().__init__(
            name, subdir, subproject, for_machine, environment, sources,
            structured_sources, objects, all_compilers,
            option_overrides=option_overrides,
            build_always_stale=build_always_stale,
            build_by_default=build_by_default, install=install,
            extra_files=extra_files, build_rpath=build_rpath,
            d_debug=d_debug, d_import_dirs=d_import_dirs,
            d_module_versions=d_module_versions, d_unittest=d_unittest,
            dependencies=dependencies, dot_net_resources=dot_net_resources,
            gnu_symbol_visibility=gnu_symbol_visibility,
            implicit_include_directories=implicit_include_directories,
            include_directories=include_directories, install_dir=install_dir,
            install_mode=install_mode, install_rpath=install_rpath,
            install_tag=install_tag, install_vala_targets=install_vala_targets,
            language_args=language_args,
            link_args=link_args, link_depends=link_depends,
            link_language=link_language, link_whole=link_whole,
            link_with=link_with, name_prefix=name_prefix,
            name_suffix=name_suffix, pch_args=pch_args, vala_gir=vala_gir,
            vala_header=vala_header, vala_vapi=vala_vapi,
            vs_module_defs=vs_module_defs,
            rust_crate_type='cdylib')  # TODO: this might be a bit sketchy

        # We need to set the soname in cases where build files link the module to
        # build targets, see: https://github.com/mesonbuild/meson/issues/9492
        self.force_soname: bool = False

    def get_default_install_dir(self) -> T.Tuple[str, str]:
        return self.environment.get_shared_module_dir(), '{moduledir_shared}'

class BothLibraries(SecondLevelHolder):
    def __init__(self, shared: SharedLibrary, static: StaticLibrary) -> None:
        self._preferred_library = 'shared'
        self.shared = shared
        self.static = static
        self.subproject = self.shared.subproject

    def __repr__(self) -> str:
        return f'<BothLibraries: static={repr(self.static)}; shared={repr(self.shared)}>'

    def get_default_object(self) -> BuildTarget:
        if self._preferred_library == 'shared':
            return self.shared
        elif self._preferred_library == 'static':
            return self.static
        raise MesonBugException(f'self._preferred_library == "{self._preferred_library}" is neither "shared" nor "static".')

def flatten_command(
        cmd: T.Sequence[T.Union[str, File, programs.ExternalProgram, BuildTarget, GeneratedTypes]],
        subproject: SubProject) ->  T.Tuple[
            T.List[T.Union[str, File, BuildTarget, CustomTarget]],
            T.Sequence[File],
            T.Sequence[T.Union[BuildTarget, CustomTarget]]]:
    cmd = listify(cmd)
    final_cmd: T.List[T.Union[str, File, BuildTarget, 'CustomTarget']] = []
    depend_files: T.List[File] = []
    dependencies: T.List[T.Union[CustomTarget, BuildTarget]] = []
    for c in cmd:
        if isinstance(c, str):
            final_cmd.append(c)
        elif isinstance(c, File):
            depend_files.append(c)
            final_cmd.append(c)
        elif isinstance(c, programs.ExternalProgram):
            if not c.found():
                raise InvalidArguments('Tried to use not-found external program in "command"')
            path = c.get_path()
            if os.path.isabs(path):
                # Can only add a dependency on an external program which we
                # know the absolute path of
                depend_files.append(File.from_absolute_file(path))
            final_cmd += c.get_command()
        elif isinstance(c, (BuildTarget, CustomTarget)):
            dependencies.append(c)
            final_cmd.append(c)
        elif isinstance(c, CustomTargetIndex):
            FeatureNew.single_use('CustomTargetIndex for command argument', '0.60', subproject)
            dependencies.append(c.target)
            c, df, d = flatten_command([File.from_built_file(c.get_subdir(), c.get_filename())], subproject)
            cmd.extend(c)
            depend_files.extend(df)
            dependencies.extend(d)
        else:
            raise InvalidArguments(f'Argument {c!r} in "command" is invalid')
    return final_cmd, depend_files, dependencies


class CustomTarget(Target):

    TYPENAME = 'custom'
    TYPE_SUFFIX = '@cus'

    def __init__(self,
                 name: T.Optional[str],
                 subdir: str,
                 subproject: SubProject,
                 environment: environment.Environment,
                 command: T.Sequence[T.Union[
                     str, BuildTargetTypes, GeneratedList,
                     programs.ExternalProgram, File]],
                 sources: T.Sequence[T.Union[
                     str, File, BuildTargetTypes, ExtractedObjects,
                     GeneratedList, programs.ExternalProgram]],
                 outputs: T.List[str],
                 *,
                 build_always_stale: bool = False,
                 build_by_default: T.Optional[bool] = None,
                 capture: bool = False,
                 console: bool = False,
                 depend_files: T.Optional[T.Sequence[FileOrString]] = None,
                 extra_depends: T.Optional[T.Sequence[T.Union[str, SourceOutputs]]] = None,
                 depfile: T.Optional[str] = None,
                 env: T.Optional[EnvironmentVariables] = None,
                 feed: bool = False,
                 install: bool = False,
                 install_dir: T.Optional[T.Sequence[T.Union[str, Literal[False]]]] = None,
                 install_mode: T.Optional[FileMode] = None,
                 install_tag: T.Optional[T.Sequence[T.Optional[str]]] = None,
                 absolute_paths: bool = False,
                 backend: T.Optional['Backend'] = None,
                 ):
        # TODO expose keyword arg to make MachineChoice.HOST configurable
        super().__init__(name, subdir, subproject, False, MachineChoice.HOST, environment,
                        install, build_always_stale)
        self.sources = list(sources)
        self.outputs = substitute_values(
            outputs, get_filenames_templates_dict(
                get_sources_string_names([s for s in sources if not isinstance(s, (programs.ExternalProgram, ExtractedObjects))], backend),
                []))
        self.build_by_default = build_by_default if build_by_default is not None else install
        self.capture = capture
        self.console = console
        self.depend_files = list(depend_files or [])
        self.dependencies: T.List[T.Union[CustomTarget, BuildTarget]] = []
        # must be after depend_files and dependencies
        self.command, df, d = flatten_command(command, self.subproject)
        self.depend_files.extend(df)
        self.dependencies.extend(d)
        self.depfile = depfile
        self.env = env or EnvironmentVariables()
        self.extra_depends = list(extra_depends or [])
        self.feed = feed
        self.install_dir = list(install_dir or [])
        self.install_mode = install_mode
        self.install_tag = _process_install_tag(install_tag or [], len(self.outputs))
        self.name = name if name else self.outputs[0]

        # Whether to use absolute paths for all files on the commandline
        self.absolute_paths = absolute_paths

    def get_default_install_dir(self) -> T.Tuple[str, str]:
        return None, None

    def __repr__(self) -> str:
        repr_str = "<{0} {1}: {2}>"
        return repr_str.format(self.__class__.__name__, self.get_id(), self.command)

    def get_target_dependencies(self) -> T.List[T.Union[SourceOutputs, str]]:
        deps: T.List[T.Union[SourceOutputs, str]] = []
        deps.extend(self.dependencies)
        deps.extend(self.extra_depends)
        for c in self.sources:
            if isinstance(c, CustomTargetIndex):
                deps.append(c.target)
            elif not isinstance(c, programs.ExternalProgram):
                deps.append(c)
        return deps

    def get_transitive_build_target_deps(self) -> T.Set[T.Union[BuildTarget, 'CustomTarget']]:
        '''
        Recursively fetch the build targets that this custom target depends on,
        whether through `command:`, `depends:`, or `sources:` The recursion is
        only performed on custom targets.
        This is useful for setting PATH on Windows for finding required DLLs.
        F.ex, if you have a python script that loads a C module that links to
        other DLLs in your project.
        '''
        bdeps: T.Set[T.Union[BuildTarget, 'CustomTarget']] = set()
        deps = self.get_target_dependencies()
        for d in deps:
            if isinstance(d, BuildTarget):
                bdeps.add(d)
            elif isinstance(d, CustomTarget):
                bdeps.update(d.get_transitive_build_target_deps())
        return bdeps

    def get_dependencies(self) -> T.List[T.Union[BuildTarget, CustomTarget]]:
        return self.dependencies

    def should_install(self) -> bool:
        return self.install

    def get_custom_install_dir(self) -> T.List[T.Union[str, Literal[False]]]:
        return self.install_dir

    def get_custom_install_mode(self) -> T.Optional['FileMode']:
        return self.install_mode

    def get_outputs(self) -> T.List[str]:
        return self.outputs

    def get_filename(self) -> str:
        return self.outputs[0]

    def get_sources(self) -> T.List[T.Union[str, File, BuildTarget, GeneratedTypes, ExtractedObjects, programs.ExternalProgram]]:
        return self.sources

    def get_generated_lists(self) -> T.List[GeneratedList]:
        genlists: T.List[GeneratedList] = []
        for c in self.sources:
            if isinstance(c, GeneratedList):
                genlists.append(c)
        return genlists

    def get_generated_sources(self) -> T.List[GeneratedList]:
        return self.get_generated_lists()

    def get_dep_outname(self, infilenames: T.List[str]) -> str:
        if self.depfile is None:
            raise InvalidArguments('Tried to get depfile name for custom_target that does not have depfile defined.')
        if infilenames:
            plainname = os.path.basename(infilenames[0])
            basename = os.path.splitext(plainname)[0]
            return self.depfile.replace('@BASENAME@', basename).replace('@PLAINNAME@', plainname)
        else:
            if '@BASENAME@' in self.depfile or '@PLAINNAME@' in self.depfile:
                raise InvalidArguments('Substitution in depfile for custom_target that does not have an input file.')
            return self.depfile

    def is_linkable_target(self) -> bool:
        if len(self.outputs) != 1:
            return False
        suf = os.path.splitext(self.outputs[0])[-1]
        return suf in {'.a', '.dll', '.lib', '.so', '.dylib'}

    def links_dynamically(self) -> bool:
        """Whether this target links dynamically or statically

        Does not assert the target is linkable, just that it is not shared

        :return: True if is dynamically linked, otherwise False
        """
        suf = os.path.splitext(self.outputs[0])[-1]
        return suf not in {'.a', '.lib'}

    def get_link_deps_mapping(self, prefix: str) -> T.Mapping[str, str]:
        return {}

    def get_link_dep_subdirs(self) -> T.AbstractSet[str]:
        return OrderedSet()

    def get_all_link_deps(self) -> ImmutableListProtocol[BuildTargetTypes]:
        return []

    def is_internal(self) -> bool:
        '''
        Returns True iif this is a not installed static library.
        '''
        if len(self.outputs) != 1:
            return False
        return CustomTargetIndex(self, self.outputs[0]).is_internal()

    def extract_all_objects_recurse(self) -> T.List[T.Union[str, 'ExtractedObjects']]:
        # The easiest solution to widening the type here is to just cast
        return T.cast('T.List[T.Union[str, ExtractedObjects]]', self.get_outputs())

    def __getitem__(self, index: int) -> 'CustomTargetIndex':
        return CustomTargetIndex(self, self.outputs[index])

    def __setitem__(self, index: T.Any, value: T.Any) -> None:
        raise NotImplementedError

    def __delitem__(self, index: int) -> None:
        raise NotImplementedError

    def __iter__(self) -> T.Iterator[CustomTargetIndex]:
        for i in self.outputs:
            yield CustomTargetIndex(self, i)

    def __len__(self) -> int:
        return len(self.outputs)

class RunTarget(Target):

    TYPENAME = 'run'
    TYPE_SUFFIX = '@run'

    def __init__(self, name: str,
                 command: T.Sequence[T.Union[str, File, BuildTargetTypes, programs.ExternalProgram]],
                 dependencies: T.Sequence[Target],
                 subdir: str,
                 subproject: SubProject,
                 environment: environment.Environment,
                 env: T.Optional['EnvironmentVariables'] = None,
                 default_env: bool = True):
        # These don't produce output artifacts
        super().__init__(name, subdir, subproject, False, MachineChoice.BUILD, environment)
        self.dependencies = list(dependencies)
        self.depend_files: T.List[File] = []
        self.command, df, d = flatten_command(command, self.subproject)
        self.depend_files.extend(df)
        self.dependencies.extend(d)
        self.absolute_paths = False
        self.env = env
        self.default_env = default_env

    def __repr__(self) -> str:
        repr_str = "<{0} {1}: {2}>"
        return repr_str.format(self.__class__.__name__, self.get_id(), self.command[0])

    def get_dependencies(self) -> T.List[Target]:
        return self.dependencies

    def get_generated_sources(self) -> T.List['GeneratedTypes']:
        return []

    def get_sources(self) -> T.List[File]:
        return []

    def should_install(self) -> bool:
        return False

    def get_filename(self) -> str:
        return self.name

    def get_outputs(self) -> T.List[str]:
        if isinstance(self.name, str):
            return [self.name]
        elif isinstance(self.name, list):
            return self.name
        else:
            raise RuntimeError('RunTarget: self.name is neither a list nor a string. This is a bug')

class AliasTarget(RunTarget):
    def __init__(self, name: str, dependencies: T.Sequence['Target'],
                 subdir: str, subproject: SubProject, environment: environment.Environment):
        super().__init__(name, [], dependencies, subdir, subproject, environment)

    def __repr__(self) -> str:
        repr_str = "<{0} {1}>"
        return repr_str.format(self.__class__.__name__, self.get_id())

class Jar(BuildTarget):

    TYPENAME = 'jar'
    TYPE_SUFFIX = '@jar'

    def __init__(
            self,
            name: str,
            subdir: str,
            subproject: 'SubProject',
            for_machine: MachineChoice,
            environment: environment.Environment,
            sources: T.Optional[T.Sequence['SourceOutputs']] = None,
            structured_sources: T.Optional[StructuredSources] = None,
            objects: T.Optional[T.List[T.Union[str, File, ExtractedObjects]]] = None,
            all_compilers: T.Optional[T.Dict[str, Compiler]] = None,
            *,
            build_by_default: bool = True,
            install: bool = False,
            build_always_stale: bool = False,
            extra_files: T.Optional[T.List[File]] = None,
            option_overrides: T.Optional[T.Dict[OptionKey, str]] = None,
            build_rpath: str = '',
            d_debug: T.Optional[T.List[T.Union[str, int]]] = None,
            d_import_dirs: T.Optional[T.List[IncludeDirs]] = None,
            d_module_versions: T.Optional[T.List[T.Union[str, int]]] = None,
            d_unittest: T.Optional[bool] = False,
            dependencies: T.Optional[T.List[dependencies.Dependency]] = None,
            dot_net_resources: T.Optional[T.List[File]] = None,
            gnu_symbol_visibility: GNU_SYMBOL_VISIBILITY = 'default',
            implicit_include_directories: bool = True,
            include_directories: T.Optional[T.List[IncludeDirs]] = None,
            install_dir: T.Optional[str] = None,
            install_mode: T.Optional[FileMode] = None,
            install_rpath: str = '',
            install_tag: T.Optional[T.List[T.Optional[str]]] = None,
            install_vala_targets: T.Optional[T.Tuple[T.Union[str, bool], T.Union[str, bool], T.Union[str, bool]]] = None,
            language_args: T.Optional[T.Dict[str, T.List[str]]] = None,
            link_args: T.Optional[T.List[str]] = None,
            link_depends: T.Optional[T.List[T.Union[File, CustomTarget, CustomTargetIndex]]] = None,
            link_language: T.Optional[LINK_LANGUAGE] = None,
            link_whole: T.Optional[T.List[T.Union[StaticLibrary, CustomTarget, CustomTargetIndex]]] = None,
            link_with: T.Optional[T.List[T.Union[SharedLibrary, StaticLibrary, SharedModule, CustomTarget, CustomTargetIndex]]] = None,
            name_prefix: T.Optional[str] = None,
            name_suffix: T.Optional[str] = None,
            pch_args: T.Optional[T.Dict[str, T.List[str]]] = None,
            vala_gir: T.Optional[T.Union[Literal[False], str]] = None,
            vala_header: T.Optional[T.Union[Literal[False], str]] = None,
            vala_vapi: T.Optional[T.Union[Literal[False], str]] = None,
            main_class: str = '',
            java_resources: T.Optional[StructuredSources] = None,
            ) -> None:
        super().__init__(
            name, subdir, subproject, for_machine, environment, sources,
            structured_sources, objects, all_compilers,
            option_overrides=option_overrides,
            build_by_default=build_by_default,
            build_always_stale=build_always_stale, build_rpath=build_rpath,
            d_debug=d_debug, d_import_dirs=d_import_dirs,
            d_module_versions=d_module_versions, d_unittest=d_unittest,
            dependencies=dependencies, dot_net_resources=dot_net_resources,
            extra_files=extra_files,
            gnu_symbol_visibility=gnu_symbol_visibility,
            implicit_include_directories=implicit_include_directories,
            include_directories=include_directories, install=install,
            install_dir=install_dir, install_mode=install_mode,
            install_tag=install_tag, install_vala_targets=install_vala_targets,
            language_args=language_args, link_args=link_args,
            link_depends=link_depends, link_language=link_language,
            link_whole=link_whole, link_with=link_with, name_prefix=name_prefix,
            name_suffix=name_suffix, pch_args=pch_args, vala_gir=vala_gir,
            vala_header=vala_header, vala_vapi=vala_vapi)
        self.main_class = main_class
        self.java_resources = java_resources

        # TODO: handle this validation in the interpreter
        for s in self.sources:
            if not s.endswith('.java'):
                raise InvalidArguments(f'Jar source {s} is not a java file.')
        if self.structured_sources:
            raise InvalidArguments('structured sources are not supported in Java targets.')

        # Override some things from the BuildTarget
        self.filename = self.name + '.jar'
        self.outputs = [self.filename]

    def _default_prefix(self) -> str:
        return ''

    def _default_suffix(self) -> str:
        return 'jar'

    def get_main_class(self) -> str:
        return self.main_class

    def get_java_args(self) -> T.List[FileOrString]:
        return self.extra_args['java']

    def get_java_resources(self) -> T.Optional[StructuredSources]:
        return self.java_resources

    def validate_install(self) -> None:
        # All jar targets are installable.
        pass

    def is_linkable_target(self) -> bool:
        return True

    def get_classpath_args(self) -> T.List[str]:
        cp_paths = [os.path.join(l.get_subdir(), l.get_filename()) for l in self.link_with]
        cp_string = os.pathsep.join(cp_paths)
        if cp_string:
            return ['-cp', os.pathsep.join(cp_paths)]
        return []

    def get_default_install_dir(self) -> T.Tuple[str, str]:
        return self.environment.get_jar_dir(), '{jardir}'

@dataclass(eq=False)
class CustomTargetIndex(HoldableObject):

    """A special opaque object returned by indexing a CustomTarget. This object
    exists in Meson, but acts as a proxy in the backends, making targets depend
    on the CustomTarget it's derived from, but only adding one source file to
    the sources.
    """

    TYPENAME = 'custom'

    target: CustomTarget
    output: str

    def __post_init__(self) -> None:
        self.for_machine = self.target.for_machine

    @property
    def name(self) -> str:
        return f'{self.target.name}[{self.output}]'

    def __repr__(self) -> str:
        return '<CustomTargetIndex: {!r}[{}]>'.format(
            self.target, self.target.get_outputs().index(self.output))

    def get_outputs(self) -> T.List[str]:
        return [self.output]

    def get_subdir(self) -> str:
        return self.target.get_subdir()

    def get_filename(self) -> str:
        return self.output

    def get_id(self) -> str:
        return self.target.get_id()

    def get_all_link_deps(self) -> ImmutableListProtocol[BuildTargetTypes]:
        return self.target.get_all_link_deps()

    def get_link_deps_mapping(self, prefix: str) -> T.Mapping[str, str]:
        return self.target.get_link_deps_mapping(prefix)

    def get_link_dep_subdirs(self) -> T.AbstractSet[str]:
        return self.target.get_link_dep_subdirs()

    def is_linkable_target(self) -> bool:
        suf = os.path.splitext(self.output)[-1]
        return suf in {'.a', '.dll', '.lib', '.so', '.dylib'}

    def links_dynamically(self) -> bool:
        """Whether this target links dynamically or statically

        Does not assert the target is linkable, just that it is not shared

        :return: True if is dynamically linked, otherwise False
        """
        suf = os.path.splitext(self.output)[-1]
        return suf not in {'.a', '.lib'}

    def should_install(self) -> bool:
        return self.target.should_install()

    def is_internal(self) -> bool:
        '''
        Returns True iif this is a not installed static library
        '''
        suf = os.path.splitext(self.output)[-1]
        return suf in {'.a', '.lib'} and not self.should_install()

    def extract_all_objects_recurse(self) -> T.List[T.Union[str, 'ExtractedObjects']]:
        return self.target.extract_all_objects_recurse()

    def get_custom_install_dir(self) -> T.List[T.Union[str, Literal[False]]]:
        return self.target.get_custom_install_dir()

class ConfigurationData(HoldableObject):
    def __init__(self, initial_values: T.Optional[T.Union[
                T.Dict[str, T.Tuple[T.Union[str, int, bool], T.Optional[str]]],
                T.Dict[str, T.Union[str, int, bool]]]
            ] = None):
        super().__init__()
        self.values: T.Dict[str, T.Tuple[T.Union[str, int, bool], T.Optional[str]]] = \
            {k: v if isinstance(v, tuple) else (v, None) for k, v in initial_values.items()} if initial_values else {}
        self.used: bool = False

    def __repr__(self) -> str:
        return repr(self.values)

    def __contains__(self, value: str) -> bool:
        return value in self.values

    def __bool__(self) -> bool:
        return bool(self.values)

    def get(self, name: str) -> T.Tuple[T.Union[str, int, bool], T.Optional[str]]:
        return self.values[name] # (val, desc)

    def keys(self) -> T.Iterable[str]:
        return self.values.keys()

# A bit poorly named, but this represents plain data files to copy
# during install.
@dataclass(eq=False)
class Data(HoldableObject):
    sources: T.List[File]
    install_dir: str
    install_dir_name: str
    install_mode: 'FileMode'
    subproject: str
    rename: T.List[str] = None
    install_tag: T.Optional[str] = None
    data_type: str = None

    def __post_init__(self) -> None:
        if self.rename is None:
            self.rename = [os.path.basename(f.fname) for f in self.sources]

@dataclass(eq=False)
class SymlinkData(HoldableObject):
    target: str
    name: str
    install_dir: str
    subproject: str
    install_tag: T.Optional[str] = None

    def __post_init__(self) -> None:
        if self.name != os.path.basename(self.name):
            raise InvalidArguments(f'Link name is "{self.name}", but link names cannot contain path separators. '
                                   'The dir part should be in install_dir.')

@dataclass(eq=False)
class TestSetup:
    exe_wrapper: T.List[str]
    gdb: bool
    timeout_multiplier: int
    env: EnvironmentVariables
    exclude_suites: T.List[str]


def get_sources_string_names(sources: T.Sequence[T.Union[FileOrString, BuildTarget, GeneratedTypes]], backend: Backend) -> T.List[str]:
    '''
    For the specified list of @sources which can be strings, Files, or targets,
    get all the output basenames.
    '''
    names: T.List[str] = []
    for s in sources:
        if isinstance(s, str):
            names.append(s)
        elif isinstance(s, (BuildTarget, CustomTarget, CustomTargetIndex, GeneratedList)):
            names += s.get_outputs()
        elif isinstance(s, ExtractedObjects):
            names += backend.determine_ext_objs(s)
        elif isinstance(s, File):
            names.append(s.fname)
        else:
            raise AssertionError(f'Unknown source type: {s!r}')
    return names

def load(build_dir: str) -> Build:
    filename = os.path.join(build_dir, 'meson-private', 'build.dat')
    load_fail_msg = f'Build data file {filename!r} is corrupted. Try with a fresh build tree.'
    nonexisting_fail_msg = f'No such build data file as "{filename!r}".'
    try:
        with open(filename, 'rb') as f:
            obj = pickle.load(f)
    except FileNotFoundError:
        raise MesonException(nonexisting_fail_msg)
    except (pickle.UnpicklingError, EOFError):
        raise MesonException(load_fail_msg)
    except AttributeError:
        raise MesonException(
            f"Build data file {filename!r} references functions or classes that don't "
            "exist. This probably means that it was generated with an old "
            "version of meson. Try running from the source directory "
            f"meson {build_dir} --wipe")
    if not isinstance(obj, Build):
        raise MesonException(load_fail_msg)
    return obj

def save(obj: Build, filename: str) -> None:
    with open(filename, 'wb') as f:
        pickle.dump(obj, f)
