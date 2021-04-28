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

from collections import OrderedDict
from functools import lru_cache
import copy
import hashlib
import itertools, pathlib
import os
import pickle
import re
import typing as T

from . import environment
from . import dependencies
from . import mlog
from . import programs
from .mesonlib import (
    File, MesonException, MachineChoice, PerMachine, OrderedSet, listify,
    extract_as_list, typeslistify, stringlistify, classify_unity_sources,
    get_filenames_templates_dict, substitute_values, has_path_sep, unholder,
    OptionKey
)
from .compilers import (
    Compiler, is_object, clink_langs, sort_clink, lang_suffixes,
    is_known_suffix
)
from .linkers import StaticLinker
from .interpreterbase import FeatureNew

if T.TYPE_CHECKING:
    from .interpreter import Test
    from .mesonlib import FileMode, FileOrString
    from .mesonlib.backend import Backend

pch_kwargs = {'c_pch', 'cpp_pch'}

lang_arg_kwargs = {
    'c_args',
    'cpp_args',
    'cuda_args',
    'd_args',
    'd_import_dirs',
    'd_unittest',
    'd_module_versions',
    'd_debug',
    'fortran_args',
    'java_args',
    'objc_args',
    'objcpp_args',
    'rust_args',
    'vala_args',
    'cs_args',
    'zig_args',
}

vala_kwargs = {'vala_header', 'vala_gir', 'vala_vapi'}
rust_kwargs = {'rust_crate_type'}
cs_kwargs = {'resources', 'cs_args'}

buildtarget_kwargs = {
    'build_by_default',
    'build_rpath',
    'dependencies',
    'extra_files',
    'gui_app',
    'link_with',
    'link_whole',
    'link_args',
    'link_depends',
    'implicit_include_directories',
    'include_directories',
    'install',
    'install_rpath',
    'install_dir',
    'install_mode',
    'name_prefix',
    'name_suffix',
    'native',
    'objects',
    'override_options',
    'sources',
    'gnu_symbol_visibility',
    'link_language',
    'win_subsystem',
}

known_build_target_kwargs = (
    buildtarget_kwargs |
    lang_arg_kwargs |
    pch_kwargs |
    vala_kwargs |
    rust_kwargs |
    cs_kwargs)

known_exe_kwargs = known_build_target_kwargs | {'implib', 'export_dynamic', 'pie', 'link_script'}
known_shlib_kwargs = known_build_target_kwargs | {'version', 'soversion', 'vs_module_defs', 'darwin_versions'}
known_shmod_kwargs = known_build_target_kwargs | {'vs_module_defs'}
known_stlib_kwargs = known_build_target_kwargs | {'pic', 'prelink'}
known_jar_kwargs = known_exe_kwargs | {'main_class'}

@lru_cache(maxsize=None)
def get_target_macos_dylib_install_name(ld) -> str:
    name = ['@rpath/', ld.prefix, ld.name]
    if ld.soversion is not None:
        name.append('.' + ld.soversion)
    name.append('.dylib')
    return ''.join(name)

class InvalidArguments(MesonException):
    pass

class DependencyOverride:
    def __init__(self, dep, node, explicit=True):
        self.dep = dep
        self.node = node
        self.explicit = explicit

class Headers:

    def __init__(self, sources: T.List[File], install_subdir: T.Optional[str],
                 install_dir: T.Optional[str], install_mode: T.Optional['FileMode'],
                 subproject: str):
        self.sources = sources
        self.install_subdir = install_subdir
        self.custom_install_dir = install_dir
        self.custom_install_mode = install_mode
        self.subproject = subproject

    # TODO: we really don't need any of these methods, but they're preserved to
    # keep APIs relying on them working.

    def set_install_subdir(self, subdir: str) -> None:
        self.install_subdir = subdir

    def get_install_subdir(self) -> str:
        return self.install_subdir

    def get_sources(self) -> T.List[File]:
        return self.sources

    def get_custom_install_dir(self) -> T.Optional[str]:
        return self.custom_install_dir

    def get_custom_install_mode(self) -> T.Optional['FileMode']:
        return self.custom_install_mode


class Man:

    def __init__(self, sources: T.List[File], install_dir: T.Optional[str],
                 install_mode: T.Optional['FileMode'], subproject: str,
                 locale: T.Optional[str]):
        self.sources = sources
        self.custom_install_dir = install_dir
        self.custom_install_mode = install_mode
        self.subproject = subproject
        self.locale = locale

    def get_custom_install_dir(self) -> T.Optional[str]:
        return self.custom_install_dir

    def get_custom_install_mode(self) -> T.Optional['FileMode']:
        return self.custom_install_mode

    def get_sources(self) -> T.List['File']:
        return self.sources


class InstallDir:

    def __init__(self, src_subdir: str, inst_subdir: str, install_dir: str,
                 install_mode: T.Optional['FileMode'],
                 exclude: T.Tuple[T.Set[str], T.Set[str]],
                 strip_directory: bool, subproject: str,
                 from_source_dir: bool = True):
        self.source_subdir = src_subdir
        self.installable_subdir = inst_subdir
        self.install_dir = install_dir
        self.install_mode = install_mode
        self.exclude = exclude
        self.strip_directory = strip_directory
        self.from_source_dir = from_source_dir
        self.subproject = subproject


class Build:
    """A class that holds the status of one build including
    all dependencies and so on.
    """

    def __init__(self, environment: environment.Environment):
        self.project_name = 'name of master project'
        self.project_version = None
        self.environment = environment
        self.projects = {}
        self.targets: T.MutableMapping[str, 'Target'] = OrderedDict()
        self.run_target_names: T.Set[T.Tuple[str, str]] = set()
        self.global_args: PerMachine[T.Dict[str, T.List[str]]] = PerMachine({}, {})
        self.projects_args: PerMachine[T.Dict[str, T.List[str]]] = PerMachine({}, {})
        self.global_link_args: PerMachine[T.Dict[str, T.List[str]]] = PerMachine({}, {})
        self.projects_link_args: PerMachine[T.Dict[str, T.List[str]]] = PerMachine({}, {})
        self.tests: T.List['Test'] = []
        self.benchmarks: T.List['Test'] = []
        self.headers: T.List[Headers] = []
        self.man: T.List[Man] = []
        self.data: T.List[Data] = []
        self.static_linker: PerMachine[StaticLinker] = PerMachine(None, None)
        self.subprojects = {}
        self.subproject_dir = ''
        self.install_scripts = []
        self.postconf_scripts = []
        self.dist_scripts = []
        self.install_dirs: T.List[InstallDir] = []
        self.dep_manifest_name = None
        self.dep_manifest = {}
        self.stdlibs = PerMachine({}, {})
        self.test_setups: T.Dict[str, TestSetup] = {}
        self.test_setup_default_name = None
        self.find_overrides = {}
        self.searched_programs = set() # The list of all programs that have been searched for.
        self.dependency_overrides = PerMachine({}, {})
        self.devenv: T.List[EnvironmentVariables] = []

    def get_build_targets(self):
        build_targets = OrderedDict()
        for name, t in self.targets.items():
            if isinstance(t, BuildTarget):
                build_targets[name] = t
        return build_targets

    def get_custom_targets(self):
        custom_targets = OrderedDict()
        for name, t in self.targets.items():
            if isinstance(t, CustomTarget):
                custom_targets[name] = t
        return custom_targets

    def copy(self):
        other = Build(self.environment)
        for k, v in self.__dict__.items():
            if isinstance(v, (list, dict, set, OrderedDict)):
                other.__dict__[k] = v.copy()
            else:
                other.__dict__[k] = v
        return other

    def merge(self, other):
        for k, v in other.__dict__.items():
            self.__dict__[k] = v

    def ensure_static_linker(self, compiler):
        if self.static_linker[compiler.for_machine] is None and compiler.needs_static_linker():
            self.static_linker[compiler.for_machine] = self.environment.detect_static_linker(compiler)

    def get_project(self):
        return self.projects['']

    def get_subproject_dir(self):
        return self.subproject_dir

    def get_targets(self) -> T.Dict[str, 'Target']:
        return self.targets

    def get_tests(self) -> T.List['Test']:
        return self.tests

    def get_benchmarks(self) -> T.List['Test']:
        return self.benchmarks

    def get_headers(self):
        return self.headers

    def get_man(self):
        return self.man

    def get_data(self):
        return self.data

    def get_install_subdirs(self):
        return self.install_dirs

    def get_global_args(self, compiler, for_machine):
        d = self.global_args[for_machine]
        return d.get(compiler.get_language(), [])

    def get_project_args(self, compiler, project, for_machine):
        d = self.projects_args[for_machine]
        args = d.get(project)
        if not args:
            return []
        return args.get(compiler.get_language(), [])

    def get_global_link_args(self, compiler, for_machine):
        d = self.global_link_args[for_machine]
        return d.get(compiler.get_language(), [])

    def get_project_link_args(self, compiler, project, for_machine):
        d = self.projects_link_args[for_machine]

        link_args = d.get(project)
        if not link_args:
            return []

        return link_args.get(compiler.get_language(), [])

class IncludeDirs:
    def __init__(self, curdir, dirs, is_system, extra_build_dirs=None):
        self.curdir = curdir
        self.incdirs = dirs
        self.is_system = is_system
        # Interpreter has validated that all given directories
        # actually exist.
        if extra_build_dirs is None:
            self.extra_build_dirs = []
        else:
            self.extra_build_dirs = extra_build_dirs

    def __repr__(self):
        r = '<{} {}/{}>'
        return r.format(self.__class__.__name__, self.curdir, self.incdirs)

    def get_curdir(self):
        return self.curdir

    def get_incdirs(self):
        return self.incdirs

    def get_extra_build_dirs(self):
        return self.extra_build_dirs

    def to_string_list(self, sourcedir: str) -> T.List[str]:
        """Convert IncludeDirs object to a list of strings."""
        strlist: T.List[str] = []
        for idir in self.incdirs:
            strlist.append(os.path.join(sourcedir, self.curdir, idir))
        return strlist

class ExtractedObjects:
    '''
    Holds a list of sources for which the objects must be extracted
    '''
    def __init__(self, target, srclist=None, genlist=None, objlist=None, recursive=True):
        self.target = target
        self.recursive = recursive
        self.srclist = srclist if srclist is not None else []
        self.genlist = genlist if genlist is not None else []
        self.objlist = objlist if objlist is not None else []
        if self.target.is_unity:
            self.check_unity_compatible()

    def __repr__(self):
        r = '<{0} {1!r}: {2}>'
        return r.format(self.__class__.__name__, self.target.name, self.srclist)

    def classify_all_sources(self, sources, generated_sources):
        # Merge sources and generated sources
        sources = list(sources)
        for gensrc in generated_sources:
            for s in gensrc.get_outputs():
                # We cannot know the path where this source will be generated,
                # but all we need here is the file extension to determine the
                # compiler.
                sources.append(s)

        # Filter out headers and all non-source files
        sources = [s for s in sources if environment.is_source(s) and not environment.is_header(s)]

        return classify_unity_sources(self.target.compilers.values(), sources)

    def check_unity_compatible(self):
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

    def get_outputs(self, backend):
        # TODO: Consider if we need to handle genlist here
        return [
            backend.object_filename_from_source(self.target, source)
            for source in self.srclist
        ]

class EnvironmentVariables:
    def __init__(self) -> None:
        self.envvars = []
        # The set of all env vars we have operations for. Only used for self.has_name()
        self.varnames = set()

    def __repr__(self):
        repr_str = "<{0}: {1}>"
        return repr_str.format(self.__class__.__name__, self.envvars)

    def has_name(self, name: str) -> bool:
        return name in self.varnames

    def set(self, name: str, values: T.List[str], separator: str = os.pathsep) -> None:
        self.varnames.add(name)
        self.envvars.append((self._set, name, values, separator))

    def append(self, name: str, values: T.List[str], separator: str = os.pathsep) -> None:
        self.varnames.add(name)
        self.envvars.append((self._append, name, values, separator))

    def prepend(self, name: str, values: T.List[str], separator: str = os.pathsep) -> None:
        self.varnames.add(name)
        self.envvars.append((self._prepend, name, values, separator))

    def _set(self, env: T.Dict[str, str], name: str, values: T.List[str], separator: str) -> str:
        return separator.join(values)

    def _append(self, env: T.Dict[str, str], name: str, values: T.List[str], separator: str) -> str:
        curr = env.get(name)
        return separator.join(values if curr is None else [curr] + values)

    def _prepend(self, env: T.Dict[str, str], name: str, values: T.List[str], separator: str) -> str:
        curr = env.get(name)
        return separator.join(values if curr is None else values + [curr])

    def get_env(self, full_env: T.Dict[str, str]) -> T.Dict[str, str]:
        env = full_env.copy()
        for method, name, values, separator in self.envvars:
            env[name] = method(env, name, values, separator)
        return env

class Target:

    # TODO: should Target be an abc.ABCMeta?

    def __init__(self, name: str, subdir: str, subproject: str, build_by_default: bool, for_machine: MachineChoice):
        if has_path_sep(name):
            # Fix failing test 53 when this becomes an error.
            mlog.warning('''Target "{}" has a path separator in its name.
This is not supported, it can cause unexpected failures and will become
a hard error in the future.'''.format(name))
        self.name = name
        self.subdir = subdir
        self.subproject = subproject
        self.build_by_default = build_by_default
        self.for_machine = for_machine
        self.install = False
        self.build_always_stale = False
        self.option_overrides_base: T.Dict[OptionKey, str] = {}
        self.option_overrides_compiler: T.Dict[OptionKey, str] = {}
        self.extra_files = []  # type: T.List[File]
        if not hasattr(self, 'typename'):
            raise RuntimeError('Target type is not set for target class "{}". This is a bug'.format(type(self).__name__))

    def __lt__(self, other: object) -> bool:
        if not hasattr(other, 'get_id') and not callable(other.get_id):
            return NotImplemented
        return self.get_id() < other.get_id()

    def __le__(self, other: object) -> bool:
        if not hasattr(other, 'get_id') and not callable(other.get_id):
            return NotImplemented
        return self.get_id() <= other.get_id()

    def __gt__(self, other: object) -> bool:
        if not hasattr(other, 'get_id') and not callable(other.get_id):
            return NotImplemented
        return self.get_id() > other.get_id()

    def __ge__(self, other: object) -> bool:
        if not hasattr(other, 'get_id') and not callable(other.get_id):
            return NotImplemented
        return self.get_id() >= other.get_id()

    def get_default_install_dir(self, env: environment.Environment) -> str:
        raise NotImplementedError

    def get_install_dir(self, environment: environment.Environment) -> T.Tuple[T.Any, bool]:
        # Find the installation directory.
        default_install_dir = self.get_default_install_dir(environment)
        outdirs = self.get_custom_install_dir()
        if outdirs[0] is not None and outdirs[0] != default_install_dir and outdirs[0] is not True:
            # Either the value is set to a non-default value, or is set to
            # False (which means we want this specific output out of many
            # outputs to not be installed).
            custom_install_dir = True
        else:
            custom_install_dir = False
            outdirs[0] = default_install_dir
        return outdirs, custom_install_dir

    def get_basename(self) -> str:
        return self.name

    def get_subdir(self) -> str:
        return self.subdir

    def get_typename(self) -> str:
        return self.typename

    @staticmethod
    def _get_id_hash(target_id):
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
            self.subdir, self.name, self.type_suffix())

    def process_kwargs_base(self, kwargs: T.Dict[str, T.Any]) -> None:
        if 'build_by_default' in kwargs:
            self.build_by_default = kwargs['build_by_default']
            if not isinstance(self.build_by_default, bool):
                raise InvalidArguments('build_by_default must be a boolean value.')
        elif kwargs.get('install', False):
            # For backward compatibility, if build_by_default is not explicitly
            # set, use the value of 'install' if it's enabled.
            self.build_by_default = True

        option_overrides = self.parse_overrides(kwargs)

        for k, v in option_overrides.items():
            if k.lang:
                self.option_overrides_compiler[k.evolve(machine=self.for_machine)] = v
                continue
            self.option_overrides_base[k] = v

    @staticmethod
    def parse_overrides(kwargs: T.Dict[str, T.Any]) -> T.Dict[OptionKey, str]:
        result: T.Dict[OptionKey, str] = {}
        overrides = stringlistify(kwargs.get('override_options', []))
        for o in overrides:
            if '=' not in o:
                raise InvalidArguments('Overrides must be of form "key=value"')
            k, v = o.split('=', 1)
            key = OptionKey.from_string(k.strip())
            v = v.strip()
            result[key] = v
        return result

    def is_linkable_target(self) -> bool:
        return False

    def get_outputs(self) -> T.List[str]:
        return []

    def should_install(self) -> bool:
        return False

class BuildTarget(Target):
    known_kwargs = known_build_target_kwargs

    def __init__(self, name: str, subdir: str, subproject: str, for_machine: MachineChoice,
                 sources: T.List[File], objects, environment: environment.Environment, kwargs):
        super().__init__(name, subdir, subproject, True, for_machine)
        unity_opt = environment.coredata.get_option(OptionKey('unity'))
        self.is_unity = unity_opt == 'on' or (unity_opt == 'subprojects' and subproject != '')
        self.environment = environment
        self.sources: T.List[File] = []
        self.compilers = OrderedDict() # type: OrderedDict[str, Compiler]
        self.objects = []
        self.external_deps = []
        self.include_dirs = []
        self.link_language = kwargs.get('link_language')
        self.link_targets: T.List[BuildTarget] = []
        self.link_whole_targets = []
        self.link_depends = []
        self.added_deps = set()
        self.name_prefix_set = False
        self.name_suffix_set = False
        self.filename = 'no_name'
        # The list of all files outputted by this target. Useful in cases such
        # as Vala which generates .vapi and .h besides the compiled output.
        self.outputs = [self.filename]
        self.need_install = False
        self.pch = {}
        self.extra_args: T.Dict[str, T.List['FileOrString']] = {}
        self.generated: T.Sequence[T.Union[GeneratedList, CustomTarget, CustomTargetIndex]] = []
        self.d_features = {}
        self.pic = False
        self.pie = False
        # Track build_rpath entries so we can remove them at install time
        self.rpath_dirs_to_remove: T.Set[bytes] = set()
        # Sources can be:
        # 1. Pre-existing source files in the source tree
        # 2. Pre-existing sources generated by configure_file in the build tree
        # 3. Sources files generated by another target or a Generator
        self.process_sourcelist(sources)
        # Objects can be:
        # 1. Pre-existing objects provided by the user with the `objects:` kwarg
        # 2. Compiled objects created by and extracted from another target
        self.process_objectlist(objects)
        self.process_kwargs(kwargs, environment)
        self.check_unknown_kwargs(kwargs)
        self.process_compilers()
        if not any([self.sources, self.generated, self.objects, self.link_whole]):
            raise InvalidArguments(f'Build target {name} has no sources.')
        self.process_compilers_late()
        self.validate_sources()
        self.validate_install(environment)
        self.check_module_linking()

    def __repr__(self):
        repr_str = "<{0} {1}: {2}>"
        return repr_str.format(self.__class__.__name__, self.get_id(), self.filename)

    def __str__(self):
        return f"{self.name}"

    def validate_install(self, environment):
        if self.for_machine is MachineChoice.BUILD and self.need_install:
            if environment.is_cross_build():
                raise InvalidArguments('Tried to install a target for the build machine in a cross build.')
            else:
                mlog.warning('Installing target build for the build machine. This will fail in a cross build.')

    def check_unknown_kwargs(self, kwargs):
        # Override this method in derived classes that have more
        # keywords.
        self.check_unknown_kwargs_int(kwargs, self.known_kwargs)

    def check_unknown_kwargs_int(self, kwargs, known_kwargs):
        unknowns = []
        for k in kwargs:
            if k not in known_kwargs:
                unknowns.append(k)
        if len(unknowns) > 0:
            mlog.warning('Unknown keyword argument(s) in target {}: {}.'.format(self.name, ', '.join(unknowns)))

    def process_objectlist(self, objects):
        assert(isinstance(objects, list))
        for s in unholder(objects):
            if isinstance(s, (str, File, ExtractedObjects)):
                self.objects.append(s)
            elif isinstance(s, (GeneratedList, CustomTarget)):
                msg = 'Generated files are not allowed in the \'objects\' kwarg ' + \
                    f'for target {self.name!r}.\nIt is meant only for ' + \
                    'pre-built object files that are shipped with the\nsource ' + \
                    'tree. Try adding it in the list of sources.'
                raise InvalidArguments(msg)
            else:
                msg = 'Bad object of type {!r} in target {!r}.'.format(type(s).__name__, self.name)
                raise InvalidArguments(msg)

    def process_sourcelist(self, sources):
        sources = listify(sources)
        added_sources = {} # If the same source is defined multiple times, use it only once.
        for s in unholder(sources):
            if isinstance(s, File):
                if s not in added_sources:
                    self.sources.append(s)
                    added_sources[s] = True
            elif isinstance(s, (GeneratedList, CustomTarget, CustomTargetIndex)):
                self.generated.append(s)
            else:
                msg = 'Bad source of type {!r} in target {!r}.'.format(type(s).__name__, self.name)
                raise InvalidArguments(msg)

    @staticmethod
    def can_compile_remove_sources(compiler, sources):
        removed = False
        for s in sources[:]:
            if compiler.can_compile(s):
                sources.remove(s)
                removed = True
        return removed

    def process_compilers_late(self):
        """Processes additional compilers after kwargs have been evaluated.

        This can add extra compilers that might be required by keyword
        arguments, such as link_with or dependencies. It will also try to guess
        which compiler to use if one hasn't been selected already.
        """
        # Populate list of compilers
        compilers = self.environment.coredata.compilers[self.for_machine]

        # did user override clink_langs for this target?
        link_langs = [self.link_language] if self.link_language else clink_langs

        # If this library is linked against another library we need to consider
        # the languages of those libraries as well.
        if self.link_targets or self.link_whole_targets:
            extra = set()
            for t in itertools.chain(self.link_targets, self.link_whole_targets):
                if isinstance(t, CustomTarget) or isinstance(t, CustomTargetIndex):
                    continue # We can't know anything about these.
                for name, compiler in t.compilers.items():
                    if name in link_langs:
                        extra.add((name, compiler))
            for name, compiler in sorted(extra, key=lambda p: sort_clink(p[0])):
                self.compilers[name] = compiler

        if not self.compilers:
            # No source files or parent targets, target consists of only object
            # files of unknown origin. Just add the first clink compiler
            # that we have and hope that it can link these objects
            for lang in link_langs:
                if lang in compilers:
                    self.compilers[lang] = compilers[lang]
                    break

    def process_compilers(self):
        '''
        Populate self.compilers, which is the list of compilers that this
        target will use for compiling all its sources.
        We also add compilers that were used by extracted objects to simplify
        dynamic linker determination.
        '''
        if not self.sources and not self.generated and not self.objects:
            return
        # Populate list of compilers
        compilers = self.environment.coredata.compilers[self.for_machine]
        # Pre-existing sources
        sources = list(self.sources)
        # All generated sources
        for gensrc in self.generated:
            for s in gensrc.get_outputs():
                # Generated objects can't be compiled, so don't use them for
                # compiler detection. If our target only has generated objects,
                # we will fall back to using the first c-like compiler we find,
                # which is what we need.
                if not is_object(s):
                    sources.append(s)
        for d in unholder(self.external_deps):
            for s in d.sources:
                if isinstance(s, (str, File)):
                    sources.append(s)

        # Sources that were used to create our extracted objects
        for o in self.objects:
            if not isinstance(o, ExtractedObjects):
                continue
            for s in o.srclist:
                # Don't add Vala sources since that will pull in the Vala
                # compiler even though we will never use it since we are
                # dealing with compiled C code.
                if not s.endswith(lang_suffixes['vala']):
                    sources.append(s)
        if sources:
            # For each source, try to add one compiler that can compile it.
            #
            # If it has a suffix that belongs to a known language, we must have
            # a compiler for that language.
            #
            # Otherwise, it's ok if no compilers can compile it, because users
            # are expected to be able to add arbitrary non-source files to the
            # sources list
            for s in sources:
                for lang, compiler in compilers.items():
                    if compiler.can_compile(s):
                        if lang not in self.compilers:
                            self.compilers[lang] = compiler
                        break
                else:
                    if is_known_suffix(s):
                        raise MesonException('No {} machine compiler for "{}"'.
                                             format(self.for_machine.get_lower_case_name(), s))

            # Re-sort according to clink_langs
            self.compilers = OrderedDict(sorted(self.compilers.items(),
                                                key=lambda t: sort_clink(t[0])))

        # If all our sources are Vala, our target also needs the C compiler but
        # it won't get added above.
        if 'vala' in self.compilers and 'c' not in self.compilers:
            self.compilers['c'] = compilers['c']

    def validate_sources(self):
        if not self.sources:
            return
        for lang in ('cs', 'java'):
            if lang in self.compilers:
                check_sources = list(self.sources)
                compiler = self.compilers[lang]
                if not self.can_compile_remove_sources(compiler, check_sources):
                    m = f'No {lang} sources found in target {self.name!r}'
                    raise InvalidArguments(m)
                if check_sources:
                    m = '{0} targets can only contain {0} files:\n'.format(lang.capitalize())
                    m += '\n'.join([repr(c) for c in check_sources])
                    raise InvalidArguments(m)
                # CSharp and Java targets can't contain any other file types
                assert(len(self.compilers) == 1)
                return

    def process_link_depends(self, sources, environment):
        """Process the link_depends keyword argument.

        This is designed to handle strings, Files, and the output of Custom
        Targets. Notably it doesn't handle generator() returned objects, since
        adding them as a link depends would inherently cause them to be
        generated twice, since the output needs to be passed to the ld_args and
        link_depends.
        """
        sources = listify(sources)
        for s in unholder(sources):
            if isinstance(s, File):
                self.link_depends.append(s)
            elif isinstance(s, str):
                self.link_depends.append(
                    File.from_source_file(environment.source_dir, self.subdir, s))
            elif hasattr(s, 'get_outputs'):
                self.link_depends.extend(
                    [File.from_built_file(s.get_subdir(), p) for p in s.get_outputs()])
            else:
                raise InvalidArguments(
                    'Link_depends arguments must be strings, Files, '
                    'or a Custom Target, or lists thereof.')

    def get_original_kwargs(self):
        return self.kwargs

    def unpack_holder(self, d):
        d = listify(d)
        newd = []
        for i in d:
            if isinstance(i, list):
                i = self.unpack_holder(i)
            elif hasattr(i, 'held_object'):
                i = i.held_object
            for t in ['dependencies', 'link_with', 'include_directories', 'sources']:
                if hasattr(i, t):
                    setattr(i, t, self.unpack_holder(getattr(i, t)))
            newd.append(i)
        return newd

    def copy_kwargs(self, kwargs):
        self.kwargs = copy.copy(kwargs)
        # This sucks quite badly. Arguments
        # are holders but they can't be pickled
        # so unpack those known.
        for k, v in self.kwargs.items():
            if isinstance(v, list):
                self.kwargs[k] = self.unpack_holder(v)
            if hasattr(v, 'held_object'):
                self.kwargs[k] = v.held_object
        for t in ['dependencies', 'link_with', 'include_directories', 'sources']:
            if t in self.kwargs:
                self.kwargs[t] = self.unpack_holder(self.kwargs[t])

    def extract_objects(self, srclist):
        obj_src = []
        sources_set = set(self.sources)
        for src in srclist:
            if isinstance(src, str):
                src = File(False, self.subdir, src)
            elif isinstance(src, File):
                FeatureNew.single_use('File argument for extract_objects', '0.50.0', self.subproject)
            else:
                raise MesonException('Object extraction arguments must be strings or Files.')
            # FIXME: It could be a generated source
            if src not in sources_set:
                raise MesonException(f'Tried to extract unknown source {src}.')
            obj_src.append(src)
        return ExtractedObjects(self, obj_src)

    def extract_all_objects(self, recursive=True):
        return ExtractedObjects(self, self.sources, self.generated, self.objects,
                                recursive)

    def get_all_link_deps(self):
        return self.get_transitive_link_deps()

    @lru_cache(maxsize=None)
    def get_transitive_link_deps(self):
        result = []
        for i in self.link_targets:
            result += i.get_all_link_deps()
        return result

    def get_link_deps_mapping(self, prefix, environment):
        return self.get_transitive_link_deps_mapping(prefix, environment)

    @lru_cache(maxsize=None)
    def get_transitive_link_deps_mapping(self, prefix, environment):
        result = {}
        for i in self.link_targets:
            mapping = i.get_link_deps_mapping(prefix, environment)
            #we are merging two dictionaries, while keeping the earlier one dominant
            result_tmp = mapping.copy()
            result_tmp.update(result)
            result = result_tmp
        return result

    @lru_cache(maxsize=None)
    def get_link_dep_subdirs(self):
        result = OrderedSet()
        for i in self.link_targets:
            if not isinstance(i, StaticLibrary):
                result.add(i.get_subdir())
            result.update(i.get_link_dep_subdirs())
        return result

    def get_default_install_dir(self, environment: environment.Environment) -> str:
        return environment.get_libdir()

    def get_custom_install_dir(self):
        return self.install_dir

    def get_custom_install_mode(self):
        return self.install_mode

    def process_kwargs(self, kwargs, environment):
        self.process_kwargs_base(kwargs)
        self.copy_kwargs(kwargs)
        kwargs.get('modules', [])
        self.need_install = kwargs.get('install', self.need_install)
        llist = extract_as_list(kwargs, 'link_with')
        for linktarget in unholder(llist):
            if isinstance(linktarget, dependencies.ExternalLibrary):
                raise MesonException('''An external library was used in link_with keyword argument, which
is reserved for libraries built as part of this project. External
libraries must be passed using the dependencies keyword argument
instead, because they are conceptually "external dependencies",
just like those detected with the dependency() function.''')
            self.link(linktarget)
        lwhole = extract_as_list(kwargs, 'link_whole')
        for linktarget in lwhole:
            self.link_whole(linktarget)

        c_pchlist, cpp_pchlist, clist, cpplist, cudalist, cslist, valalist, objclist, objcpplist, fortranlist, rustlist, ziglist \
            = [extract_as_list(kwargs, c) for c in ['c_pch', 'cpp_pch', 'c_args', 'cpp_args', 'cuda_args', 'cs_args', 'vala_args', 'objc_args', 'objcpp_args', 'fortran_args', 'rust_args', 'zig_args']]

        self.add_pch('c', c_pchlist)
        self.add_pch('cpp', cpp_pchlist)
        compiler_args = {
            'c': clist,
            'cpp': cpplist,
            'cuda': cudalist,
            'cs': cslist,
            'vala': valalist,
            'objc': objclist,
            'objcpp': objcpplist,
            'fortran': fortranlist,
            'rust': rustlist,
            'zig': ziglist
        }
        for key, value in compiler_args.items():
            self.add_compiler_args(key, value)

        if not isinstance(self, Executable) or 'export_dynamic' in kwargs:
            self.vala_header = kwargs.get('vala_header', self.name + '.h')
            self.vala_vapi = kwargs.get('vala_vapi', self.name + '.vapi')
            self.vala_gir = kwargs.get('vala_gir', None)

        dlist = stringlistify(kwargs.get('d_args', []))
        self.add_compiler_args('d', dlist)
        dfeatures = dict()
        dfeature_unittest = kwargs.get('d_unittest', False)
        if dfeature_unittest:
            dfeatures['unittest'] = dfeature_unittest
        dfeature_versions = kwargs.get('d_module_versions', [])
        if dfeature_versions:
            dfeatures['versions'] = dfeature_versions
        dfeature_debug = kwargs.get('d_debug', [])
        if dfeature_debug:
            dfeatures['debug'] = dfeature_debug
        if 'd_import_dirs' in kwargs:
            dfeature_import_dirs = unholder(extract_as_list(kwargs, 'd_import_dirs'))
            for d in dfeature_import_dirs:
                if not isinstance(d, IncludeDirs):
                    raise InvalidArguments('Arguments to d_import_dirs must be include_directories.')
            dfeatures['import_dirs'] = dfeature_import_dirs
        if dfeatures:
            self.d_features = dfeatures

        self.link_args = extract_as_list(kwargs, 'link_args')
        for i in self.link_args:
            if not isinstance(i, str):
                raise InvalidArguments('Link_args arguments must be strings.')
        for l in self.link_args:
            if '-Wl,-rpath' in l or l.startswith('-rpath'):
                mlog.warning('''Please do not define rpath with a linker argument, use install_rpath or build_rpath properties instead.
This will become a hard error in a future Meson release.''')
        self.process_link_depends(kwargs.get('link_depends', []), environment)
        # Target-specific include dirs must be added BEFORE include dirs from
        # internal deps (added inside self.add_deps()) to override them.
        inclist = extract_as_list(kwargs, 'include_directories')
        self.add_include_dirs(inclist)
        # Add dependencies (which also have include_directories)
        deplist = extract_as_list(kwargs, 'dependencies')
        self.add_deps(deplist)
        # If an item in this list is False, the output corresponding to
        # the list index of that item will not be installed
        self.install_dir = typeslistify(kwargs.get('install_dir', [None]),
                                        (str, bool))
        self.install_mode = kwargs.get('install_mode', None)
        main_class = kwargs.get('main_class', '')
        if not isinstance(main_class, str):
            raise InvalidArguments('Main class must be a string')
        self.main_class = main_class
        if isinstance(self, Executable):
            # This kwarg is deprecated. The value of "none" means that the kwarg
            # was not specified and win_subsystem should be used instead.
            self.gui_app = None
            if 'gui_app' in kwargs:
                if 'win_subsystem' in kwargs:
                    raise InvalidArguments('Can specify only gui_app or win_subsystem for a target, not both.')
                self.gui_app = kwargs['gui_app']
                if not isinstance(self.gui_app, bool):
                    raise InvalidArguments('Argument gui_app must be boolean.')
            self.win_subsystem = self.validate_win_subsystem(kwargs.get('win_subsystem', 'console'))
        elif 'gui_app' in kwargs:
            raise InvalidArguments('Argument gui_app can only be used on executables.')
        elif 'win_subsystem' in kwargs:
            raise InvalidArguments('Argument win_subsystem can only be used on executables.')
        extra_files = extract_as_list(kwargs, 'extra_files')
        for i in extra_files:
            assert(isinstance(i, File))
            trial = os.path.join(environment.get_source_dir(), i.subdir, i.fname)
            if not(os.path.isfile(trial)):
                raise InvalidArguments(f'Tried to add non-existing extra file {i}.')
        self.extra_files = extra_files
        self.install_rpath: str = kwargs.get('install_rpath', '')
        if not isinstance(self.install_rpath, str):
            raise InvalidArguments('Install_rpath is not a string.')
        self.build_rpath = kwargs.get('build_rpath', '')
        if not isinstance(self.build_rpath, str):
            raise InvalidArguments('Build_rpath is not a string.')
        resources = extract_as_list(kwargs, 'resources')
        for r in resources:
            if not isinstance(r, str):
                raise InvalidArguments('Resource argument is not a string.')
            trial = os.path.join(environment.get_source_dir(), self.subdir, r)
            if not os.path.isfile(trial):
                raise InvalidArguments(f'Tried to add non-existing resource {r}.')
        self.resources = resources
        if 'name_prefix' in kwargs:
            name_prefix = kwargs['name_prefix']
            if isinstance(name_prefix, list):
                if name_prefix:
                    raise InvalidArguments('name_prefix array must be empty to signify default.')
            else:
                if not isinstance(name_prefix, str):
                    raise InvalidArguments('name_prefix must be a string.')
                self.prefix = name_prefix
                self.name_prefix_set = True
        if 'name_suffix' in kwargs:
            name_suffix = kwargs['name_suffix']
            if isinstance(name_suffix, list):
                if name_suffix:
                    raise InvalidArguments('name_suffix array must be empty to signify default.')
            else:
                if not isinstance(name_suffix, str):
                    raise InvalidArguments('name_suffix must be a string.')
                if name_suffix == '':
                    raise InvalidArguments('name_suffix should not be an empty string. '
                                           'If you want meson to use the default behaviour '
                                           'for each platform pass `[]` (empty array)')
                self.suffix = name_suffix
                self.name_suffix_set = True
        if isinstance(self, StaticLibrary):
            # You can't disable PIC on OS X. The compiler ignores -fno-PIC.
            # PIC is always on for Windows (all code is position-independent
            # since library loading is done differently)
            m = self.environment.machines[self.for_machine]
            if m.is_darwin() or m.is_windows():
                self.pic = True
            else:
                self.pic = self._extract_pic_pie(kwargs, 'pic', environment, 'b_staticpic')
        if isinstance(self, Executable) or (isinstance(self, StaticLibrary) and not self.pic):
            # Executables must be PIE on Android
            if self.environment.machines[self.for_machine].is_android():
                self.pie = True
            else:
                self.pie = self._extract_pic_pie(kwargs, 'pie', environment, 'b_pie')
        self.implicit_include_directories = kwargs.get('implicit_include_directories', True)
        if not isinstance(self.implicit_include_directories, bool):
            raise InvalidArguments('Implicit_include_directories must be a boolean.')
        self.gnu_symbol_visibility = kwargs.get('gnu_symbol_visibility', '')
        if not isinstance(self.gnu_symbol_visibility, str):
            raise InvalidArguments('GNU symbol visibility must be a string.')
        if self.gnu_symbol_visibility != '':
            permitted = ['default', 'internal', 'hidden', 'protected', 'inlineshidden']
            if self.gnu_symbol_visibility not in permitted:
                raise InvalidArguments('GNU symbol visibility arg {} not one of: {}'.format(self.symbol_visibility, ', '.join(permitted)))

    def validate_win_subsystem(self, value: str) -> str:
        value = value.lower()
        if re.fullmatch(r'(boot_application|console|efi_application|efi_boot_service_driver|efi_rom|efi_runtime_driver|native|posix|windows)(,\d+(\.\d+)?)?', value) is None:
            raise InvalidArguments(f'Invalid value for win_subsystem: {value}.')
        return value

    def _extract_pic_pie(self, kwargs, arg: str, environment, option: str):
        # Check if we have -fPIC, -fpic, -fPIE, or -fpie in cflags
        all_flags = self.extra_args['c'] + self.extra_args['cpp']
        if '-f' + arg.lower() in all_flags or '-f' + arg.upper() in all_flags:
            mlog.warning("Use the '{}' kwarg instead of passing '{}' manually to {!r}".format(arg, '-f' + arg, self.name))
            return True

        k = OptionKey(option)
        if arg in kwargs:
            val = kwargs[arg]
        elif k in environment.coredata.options:
            val = environment.coredata.options[k].value
        else:
            val = False

        if not isinstance(val, bool):
            raise InvalidArguments(f'Argument {arg} to {self.name!r} must be boolean')
        return val

    def get_filename(self):
        return self.filename

    def get_outputs(self) -> T.List[str]:
        return self.outputs

    def get_extra_args(self, language):
        return self.extra_args.get(language, [])

    def get_dependencies(self, exclude=None):
        transitive_deps = []
        if exclude is None:
            exclude = []
        for t in itertools.chain(self.link_targets, self.link_whole_targets):
            if t in transitive_deps or t in exclude:
                continue
            transitive_deps.append(t)
            if isinstance(t, StaticLibrary):
                transitive_deps += t.get_dependencies(transitive_deps + exclude)
        return transitive_deps

    def get_source_subdir(self):
        return self.subdir

    def get_sources(self):
        return self.sources

    def get_objects(self):
        return self.objects

    def get_generated_sources(self):
        return self.generated

    def should_install(self) -> bool:
        return self.need_install

    def has_pch(self):
        return len(self.pch) > 0

    def get_pch(self, language):
        try:
            return self.pch[language]
        except KeyError:
            return[]

    def get_include_dirs(self):
        return self.include_dirs

    def add_deps(self, deps):
        deps = listify(deps)
        for dep in unholder(deps):
            if dep in self.added_deps:
                continue
            if isinstance(dep, dependencies.InternalDependency):
                # Those parts that are internal.
                self.process_sourcelist(dep.sources)
                self.add_include_dirs(dep.include_directories, dep.get_include_type())
                for l in dep.libraries:
                    self.link(l)
                for l in dep.whole_libraries:
                    self.link_whole(l)
                if dep.get_compile_args() or dep.get_link_args():
                    # Those parts that are external.
                    extpart = dependencies.InternalDependency('undefined',
                                                              [],
                                                              dep.get_compile_args(),
                                                              dep.get_link_args(),
                                                              [], [], [], [], {})
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
                # This is a bit of a hack. We do not want Build to know anything
                # about the interpreter so we can't import it and use isinstance.
                # This should be reliable enough.
                if hasattr(dep, 'project_args_frozen') or hasattr(dep, 'global_args_frozen'):
                    raise InvalidArguments('Tried to use subproject object as a dependency.\n'
                                           'You probably wanted to use a dependency declared in it instead.\n'
                                           'Access it by calling get_variable() on the subproject object.')
                raise InvalidArguments('Argument is of an unacceptable type {!r}.\nMust be '
                                       'either an external dependency (returned by find_library() or '
                                       'dependency()) or an internal dependency (returned by '
                                       'declare_dependency()).'.format(type(dep).__name__))
            self.added_deps.add(dep)

    def get_external_deps(self):
        return self.external_deps

    def is_internal(self):
        return isinstance(self, StaticLibrary) and not self.need_install

    def link(self, target):
        for t in unholder(listify(target)):
            if isinstance(self, StaticLibrary) and self.need_install:
                if isinstance(t, (CustomTarget, CustomTargetIndex)):
                    if not t.should_install():
                        mlog.warning('Try to link an installed static library target {} with a custom target '
                                     'that is not installed, this might cause problems when you try to use '
                                     'this static library'.format(self.name))
                elif t.is_internal():
                    # When we're a static library and we link_with to an
                    # internal/convenience library, promote to link_whole.
                    return self.link_whole(t)
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
            self.link_targets.append(t)

    def link_whole(self, target):
        for t in unholder(listify(target)):
            if isinstance(t, (CustomTarget, CustomTargetIndex)):
                if not t.is_linkable_target():
                    raise InvalidArguments(f'Custom target {t!r} is not linkable.')
                if not t.get_filename().endswith('.a'):
                    raise InvalidArguments('Can only link_whole custom targets that are .a archives.')
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
            self.link_whole_targets.append(t)

    def extract_all_objects_recurse(self):
        objs = [self.extract_all_objects()]
        for t in self.link_targets:
            if t.is_internal():
                objs += t.extract_all_objects_recurse()
        return objs

    def add_pch(self, language, pchlist):
        if not pchlist:
            return
        elif len(pchlist) == 1:
            if not environment.is_header(pchlist[0]):
                raise InvalidArguments('PCH argument {} is not a header.'.format(pchlist[0]))
        elif len(pchlist) == 2:
            if environment.is_header(pchlist[0]):
                if not environment.is_source(pchlist[1]):
                    raise InvalidArguments('PCH definition must contain one header and at most one source.')
            elif environment.is_source(pchlist[0]):
                if not environment.is_header(pchlist[1]):
                    raise InvalidArguments('PCH definition must contain one header and at most one source.')
                pchlist = [pchlist[1], pchlist[0]]
            else:
                raise InvalidArguments('PCH argument {} is of unknown type.'.format(pchlist[0]))

            if (os.path.dirname(pchlist[0]) != os.path.dirname(pchlist[1])):
                raise InvalidArguments('PCH files must be stored in the same folder.')

            mlog.warning('PCH source files are deprecated, only a single header file should be used.')
        elif len(pchlist) > 2:
            raise InvalidArguments('PCH definition may have a maximum of 2 files.')
        for f in pchlist:
            if not isinstance(f, str):
                raise MesonException('PCH arguments must be strings.')
            if not os.path.isfile(os.path.join(self.environment.source_dir, self.subdir, f)):
                raise MesonException(f'File {f} does not exist.')
        self.pch[language] = pchlist

    def add_include_dirs(self, args, set_is_system: T.Optional[str] = None):
        ids = []
        for a in unholder(args):
            if not isinstance(a, IncludeDirs):
                raise InvalidArguments('Include directory to be added is not an include directory object.')
            ids.append(a)
        if set_is_system is None:
            set_is_system = 'preserve'
        if set_is_system != 'preserve':
            is_system = set_is_system == 'system'
            ids = [IncludeDirs(x.get_curdir(), x.get_incdirs(), is_system, x.get_extra_build_dirs()) for x in ids]
        self.include_dirs += ids

    def add_compiler_args(self, language: str, args: T.List['FileOrString']) -> None:
        args = listify(args)
        for a in args:
            if not isinstance(a, (str, File)):
                raise InvalidArguments('A non-string passed to compiler args.')
        if language in self.extra_args:
            self.extra_args[language] += args
        else:
            self.extra_args[language] = args

    def get_aliases(self) -> T.Dict[str, str]:
        return {}

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
        for link_target in itertools.chain(self.link_targets, self.link_whole_targets):
            if isinstance(link_target, (CustomTarget, CustomTargetIndex)):
                continue
            for language in link_target.compilers:
                if language not in langs:
                    langs.append(language)

        return langs

    def get_prelinker(self):
        all_compilers = self.environment.coredata.compilers[self.for_machine]
        if self.link_language:
            comp = all_compilers[self.link_language]
            return comp
        for l in clink_langs:
            if l in self.compilers:
                try:
                    prelinker = all_compilers[l]
                except KeyError:
                    raise MesonException(
                        'Could not get a prelinker linker for build target {!r}. '
                        'Requires a compiler for language "{}", but that is not '
                        'a project language.'.format(self.name, l))
                return prelinker
        raise MesonException(f'Could not determine prelinker for {self.name!r}.')

    def get_clink_dynamic_linker_and_stdlibs(self):
        '''
        We use the order of languages in `clink_langs` to determine which
        linker to use in case the target has sources compiled with multiple
        compilers. All languages other than those in this list have their own
        linker.
        Note that Vala outputs C code, so Vala sources can use any linker
        that can link compiled C. We don't actually need to add an exception
        for Vala here because of that.
        '''
        # Populate list of all compilers, not just those being used to compile
        # sources in this target
        all_compilers = self.environment.coredata.compilers[self.for_machine]

        # If the user set the link_language, just return that.
        if self.link_language:
            comp = all_compilers[self.link_language]
            return comp, comp.language_stdlib_only_link_flags()

        # Languages used by dependencies
        dep_langs = self.get_langs_used_by_deps()
        # Pick a compiler based on the language priority-order
        for l in clink_langs:
            if l in self.compilers or l in dep_langs:
                try:
                    linker = all_compilers[l]
                except KeyError:
                    raise MesonException(
                        'Could not get a dynamic linker for build target {!r}. '
                        'Requires a linker for language "{}", but that is not '
                        'a project language.'.format(self.name, l))
                stdlib_args = []
                added_languages = set()
                for dl in itertools.chain(self.compilers, dep_langs):
                    if dl != linker.language:
                        stdlib_args += all_compilers[dl].language_stdlib_only_link_flags()
                        added_languages.add(dl)
                # Type of var 'linker' is Compiler.
                # Pretty hard to fix because the return value is passed everywhere
                return linker, stdlib_args

        m = 'Could not get a dynamic linker for build target {!r}'
        raise AssertionError(m.format(self.name))

    def uses_rust(self) -> bool:
        """Is this target a rust target."""
        if self.sources:
            first_file = self.sources[0]
            if first_file.fname.endswith('.rs'):
                return True
        elif self.generated:
            if self.generated[0].get_outputs()[0].endswith('.rs'):
                return True
        return False

    def get_using_msvc(self):
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
            compiler = self.environment.coredata.compilers[self.for_machine]['rust']
        else:
            compiler, _ = self.get_clink_dynamic_linker_and_stdlibs()
        # Mixing many languages with MSVC is not supported yet so ignore stdlibs.
        return compiler and compiler.get_linker_id() in {'link', 'lld-link', 'xilink', 'optlink'}

    def check_module_linking(self):
        '''
        Warn if shared modules are linked with target: (link_with) #2865
        '''
        for link_target in self.link_targets:
            if isinstance(link_target, SharedModule):
                if self.environment.machines[self.for_machine].is_darwin():
                    raise MesonException(
                        'target links against shared modules. This is not permitted on OSX')
                else:
                    mlog.warning('target links against shared modules. This '
                                 'is not recommended as it is not supported on some '
                                 'platforms')
                return

class Generator:
    def __init__(self, args, kwargs):
        if len(args) != 1:
            raise InvalidArguments('Generator requires exactly one positional argument: the executable')
        exe = unholder(args[0])
        if not isinstance(exe, (Executable, programs.ExternalProgram)):
            raise InvalidArguments('First generator argument must be an executable.')
        self.exe = exe
        self.depfile = None
        self.capture = False
        self.depends = []
        self.process_kwargs(kwargs)

    def __repr__(self):
        repr_str = "<{0}: {1}>"
        return repr_str.format(self.__class__.__name__, self.exe)

    def get_exe(self):
        return self.exe

    def process_kwargs(self, kwargs):
        if 'arguments' not in kwargs:
            raise InvalidArguments('Generator must have "arguments" keyword argument.')
        args = kwargs['arguments']
        if isinstance(args, str):
            args = [args]
        if not isinstance(args, list):
            raise InvalidArguments('"Arguments" keyword argument must be a string or a list of strings.')
        for a in args:
            if not isinstance(a, str):
                raise InvalidArguments('A non-string object in "arguments" keyword argument.')
        self.arglist = args
        if 'output' not in kwargs:
            raise InvalidArguments('Generator must have "output" keyword argument.')
        outputs = listify(kwargs['output'])
        for rule in outputs:
            if not isinstance(rule, str):
                raise InvalidArguments('"output" may only contain strings.')
            if '@BASENAME@' not in rule and '@PLAINNAME@' not in rule:
                raise InvalidArguments('Every element of "output" must contain @BASENAME@ or @PLAINNAME@.')
            if has_path_sep(rule):
                raise InvalidArguments('"outputs" must not contain a directory separator.')
        if len(outputs) > 1:
            for o in outputs:
                if '@OUTPUT@' in o:
                    raise InvalidArguments('Tried to use @OUTPUT@ in a rule with more than one output.')
        self.outputs = outputs
        if 'depfile' in kwargs:
            depfile = kwargs['depfile']
            if not isinstance(depfile, str):
                raise InvalidArguments('Depfile must be a string.')
            if os.path.basename(depfile) != depfile:
                raise InvalidArguments('Depfile must be a plain filename without a subdirectory.')
            self.depfile = depfile
        if 'capture' in kwargs:
            capture = kwargs['capture']
            if not isinstance(capture, bool):
                raise InvalidArguments('Capture must be boolean.')
            self.capture = capture
        if 'depends' in kwargs:
            depends = unholder(listify(kwargs['depends']))
            for d in depends:
                if not (isinstance(d, (BuildTarget, CustomTarget))):
                    raise InvalidArguments('Depends entries must be build targets.')
                self.depends.append(d)

    def get_base_outnames(self, inname):
        plainname = os.path.basename(inname)
        basename = os.path.splitext(plainname)[0]
        bases = [x.replace('@BASENAME@', basename).replace('@PLAINNAME@', plainname) for x in self.outputs]
        return bases

    def get_dep_outname(self, inname):
        if self.depfile is None:
            raise InvalidArguments('Tried to get dep name for rule that does not have dependency file defined.')
        plainname = os.path.basename(inname)
        basename = os.path.splitext(plainname)[0]
        return self.depfile.replace('@BASENAME@', basename).replace('@PLAINNAME@', plainname)

    def get_arglist(self, inname):
        plainname = os.path.basename(inname)
        basename = os.path.splitext(plainname)[0]
        return [x.replace('@BASENAME@', basename).replace('@PLAINNAME@', plainname) for x in self.arglist]

    def is_parent_path(self, parent, trial):
        relpath = pathlib.PurePath(trial).relative_to(parent)
        return relpath.parts[0] != '..' # For subdirs we can only go "down".

    def process_files(self, name, files, state, preserve_path_from=None, extra_args=None):
        new = False
        output = GeneratedList(self, state.subdir, preserve_path_from, extra_args=extra_args if extra_args is not None else [])
        #XXX
        for e in unholder(files):
            fs = [e]
            if isinstance(e, CustomTarget):
                output.depends.add(e)
            if isinstance(e, CustomTargetIndex):
                output.depends.add(e.target)
            if isinstance(e, (CustomTarget, CustomTargetIndex, GeneratedList)):
                self.depends.append(e) # BUG: this should go in the GeneratedList object, not this object.
                fs = []
                for f in e.get_outputs():
                    fs.append(File.from_built_file(state.subdir, f))
                new = True
            elif isinstance(e, str):
                fs = [File.from_source_file(state.environment.source_dir, state.subdir, e)]
            elif not isinstance(e, File):
                raise InvalidArguments(f'{name} arguments must be strings, files or CustomTargets, not {e!r}.')

            for f in fs:
                if preserve_path_from:
                    abs_f = f.absolute_path(state.environment.source_dir, state.environment.build_dir)
                    if not self.is_parent_path(preserve_path_from, abs_f):
                        raise InvalidArguments('generator.process: When using preserve_path_from, all input files must be in a subdirectory of the given dir.')
                output.add_file(f, state)
        if new:
            FeatureNew.single_use(
                f'Calling "{name}" with CustomTaget or Index of CustomTarget.',
                '0.57.0', state.subproject)
        return output


class GeneratedList:
    def __init__(self, generator, subdir, preserve_path_from=None, extra_args=None):
        self.generator = unholder(generator)
        self.name = self.generator.exe
        self.depends = set() # Things this target depends on (because e.g. a custom target was used as input)
        self.subdir = subdir
        self.infilelist = []
        self.outfilelist = []
        self.outmap = {}
        self.extra_depends = []
        self.depend_files = []
        self.preserve_path_from = preserve_path_from
        self.extra_args = extra_args if extra_args is not None else []
        if isinstance(self.generator.exe, programs.ExternalProgram):
            if not self.generator.exe.found():
                raise InvalidArguments('Tried to use not-found external program as generator')
            path = self.generator.exe.get_path()
            if os.path.isabs(path):
                # Can only add a dependency on an external program which we
                # know the absolute path of
                self.depend_files.append(File.from_absolute_file(path))

    def add_preserved_path_segment(self, infile, outfiles, state):
        result = []
        in_abs = infile.absolute_path(state.environment.source_dir, state.environment.build_dir)
        assert(os.path.isabs(self.preserve_path_from))
        rel = os.path.relpath(in_abs, self.preserve_path_from)
        path_segment = os.path.dirname(rel)
        for of in outfiles:
            result.append(os.path.join(path_segment, of))
        return result

    def add_file(self, newfile, state):
        self.infilelist.append(newfile)
        outfiles = self.generator.get_base_outnames(newfile.fname)
        if self.preserve_path_from:
            outfiles = self.add_preserved_path_segment(newfile, outfiles, state)
        self.outfilelist += outfiles
        self.outmap[newfile] = outfiles

    def get_inputs(self):
        return self.infilelist

    def get_outputs(self) -> T.List[str]:
        return self.outfilelist

    def get_outputs_for(self, filename):
        return self.outmap[filename]

    def get_generator(self):
        return self.generator

    def get_extra_args(self):
        return self.extra_args

class Executable(BuildTarget):
    known_kwargs = known_exe_kwargs

    def __init__(self, name: str, subdir: str, subproject: str, for_machine: MachineChoice,
                 sources: T.List[File], objects, environment: environment.Environment, kwargs):
        self.typename = 'executable'
        key = OptionKey('b_pie')
        if 'pie' not in kwargs and key in environment.coredata.options:
            kwargs['pie'] = environment.coredata.options[key].value
        super().__init__(name, subdir, subproject, for_machine, sources, objects, environment, kwargs)
        # Unless overridden, executables have no suffix or prefix. Except on
        # Windows and with C#/Mono executables where the suffix is 'exe'
        if not hasattr(self, 'prefix'):
            self.prefix = ''
        if not hasattr(self, 'suffix'):
            machine = environment.machines[for_machine]
            # Executable for Windows or C#/Mono
            if machine.is_windows() or machine.is_cygwin() or 'cs' in self.compilers:
                self.suffix = 'exe'
            elif machine.system.startswith('wasm') or machine.system == 'emscripten':
                self.suffix = 'js'
            elif ('c' in self.compilers and self.compilers['c'].get_id().startswith('arm') or
                  'cpp' in self.compilers and self.compilers['cpp'].get_id().startswith('arm')):
                self.suffix = 'axf'
            elif ('c' in self.compilers and self.compilers['c'].get_id().startswith('ccrx') or
                  'cpp' in self.compilers and self.compilers['cpp'].get_id().startswith('ccrx')):
                self.suffix = 'abs'
            elif ('c' in self.compilers and self.compilers['c'].get_id().startswith('xc16')):
                self.suffix = 'elf'
            elif ('c' in self.compilers and self.compilers['c'].get_id().startswith('c2000') or
                  'cpp' in self.compilers and self.compilers['cpp'].get_id().startswith('c2000')):
                self.suffix = 'out'
            else:
                self.suffix = environment.machines[for_machine].get_exe_suffix()
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

        # Check for export_dynamic
        self.export_dynamic = False
        if kwargs.get('export_dynamic'):
            if not isinstance(kwargs['export_dynamic'], bool):
                raise InvalidArguments('"export_dynamic" keyword argument must be a boolean')
            self.export_dynamic = True
        if kwargs.get('implib'):
            self.export_dynamic = True
        if self.export_dynamic and kwargs.get('implib') is False:
            raise InvalidArguments('"implib" keyword argument must not be false for if "export_dynamic" is true')

        m = environment.machines[for_machine]

        # If using export_dynamic, set the import library name
        if self.export_dynamic:
            implib_basename = self.name + '.exe'
            if not isinstance(kwargs.get('implib', False), bool):
                implib_basename = kwargs['implib']
            if m.is_windows() or m.is_cygwin():
                self.vs_import_filename = f'{implib_basename}.lib'
                self.gcc_import_filename = f'lib{implib_basename}.a'
                if self.get_using_msvc():
                    self.import_filename = self.vs_import_filename
                else:
                    self.import_filename = self.gcc_import_filename

        if m.is_windows() and ('cs' in self.compilers or
                               self.uses_rust() or
                               self.get_using_msvc()):
            self.debug_filename = self.name + '.pdb'

        # Only linkwithable if using export_dynamic
        self.is_linkwithable = self.export_dynamic

        if 'link_script' in self.kwargs:
            raise MesonException('boom')

    def get_default_install_dir(self, environment: environment.Environment) -> str:
        return environment.get_bindir()

    def description(self):
        '''Human friendly description of the executable'''
        return self.name

    def type_suffix(self):
        return "@exe"

    def get_import_filename(self):
        """
        The name of the import library that will be outputted by the compiler

        Returns None if there is no import library required for this platform
        """
        return self.import_filename

    def get_import_filenameslist(self):
        if self.import_filename:
            return [self.vs_import_filename, self.gcc_import_filename]
        return []

    def get_debug_filename(self):
        """
        The name of debuginfo file that will be created by the compiler

        Returns None if the build won't create any debuginfo file
        """
        return self.debug_filename

    def is_linkable_target(self):
        return self.is_linkwithable

class StaticLibrary(BuildTarget):
    known_kwargs = known_stlib_kwargs

    def __init__(self, name, subdir, subproject, for_machine: MachineChoice, sources, objects, environment, kwargs):
        self.typename = 'static library'
        super().__init__(name, subdir, subproject, for_machine, sources, objects, environment, kwargs)
        if 'cs' in self.compilers:
            raise InvalidArguments('Static libraries not supported for C#.')
        if 'rust' in self.compilers:
            # If no crate type is specified, or it's the generic lib type, use rlib
            if not hasattr(self, 'rust_crate_type') or self.rust_crate_type == 'lib':
                mlog.debug('Defaulting Rust static library target crate type to rlib')
                self.rust_crate_type = 'rlib'
            # Don't let configuration proceed with a non-static crate type
            elif self.rust_crate_type not in ['rlib', 'staticlib']:
                raise InvalidArguments(f'Crate type "{self.rust_crate_type}" invalid for static libraries; must be "rlib" or "staticlib"')
        # By default a static library is named libfoo.a even on Windows because
        # MSVC does not have a consistent convention for what static libraries
        # are called. The MSVC CRT uses libfoo.lib syntax but nothing else uses
        # it and GCC only looks for static libraries called foo.lib and
        # libfoo.a. However, we cannot use foo.lib because that's the same as
        # the import library. Using libfoo.a is ok because people using MSVC
        # always pass the library filename while linking anyway.
        if not hasattr(self, 'prefix'):
            self.prefix = 'lib'
        if not hasattr(self, 'suffix'):
            if 'rust' in self.compilers:
                if not hasattr(self, 'rust_crate_type') or self.rust_crate_type == 'rlib':
                    # default Rust static library suffix
                    self.suffix = 'rlib'
                elif self.rust_crate_type == 'staticlib':
                    self.suffix = 'a'
            else:
                self.suffix = 'a'
        self.filename = self.prefix + self.name + '.' + self.suffix
        self.outputs = [self.filename]
        self.prelink = kwargs.get('prelink', False)
        if not isinstance(self.prelink, bool):
            raise InvalidArguments('Prelink keyword argument must be a boolean.')

    def get_link_deps_mapping(self, prefix, environment):
        return {}

    def get_default_install_dir(self, environment):
        return environment.get_static_lib_dir()

    def type_suffix(self):
        return "@sta"

    def process_kwargs(self, kwargs, environment):
        super().process_kwargs(kwargs, environment)
        if 'rust_crate_type' in kwargs:
            rust_crate_type = kwargs['rust_crate_type']
            if isinstance(rust_crate_type, str):
                self.rust_crate_type = rust_crate_type
            else:
                raise InvalidArguments(f'Invalid rust_crate_type "{rust_crate_type}": must be a string.')

    def is_linkable_target(self):
        return True

class SharedLibrary(BuildTarget):
    known_kwargs = known_shlib_kwargs

    def __init__(self, name, subdir, subproject, for_machine: MachineChoice, sources, objects, environment, kwargs):
        self.typename = 'shared library'
        self.soversion = None
        self.ltversion = None
        # Max length 2, first element is compatibility_version, second is current_version
        self.darwin_versions = []
        self.vs_module_defs = None
        # The import library this target will generate
        self.import_filename = None
        # The import library that Visual Studio would generate (and accept)
        self.vs_import_filename = None
        # The import library that GCC would generate (and prefer)
        self.gcc_import_filename = None
        # The debugging information file this target will generate
        self.debug_filename = None
        super().__init__(name, subdir, subproject, for_machine, sources, objects, environment, kwargs)
        if 'rust' in self.compilers:
            # If no crate type is specified, or it's the generic lib type, use dylib
            if not hasattr(self, 'rust_crate_type') or self.rust_crate_type == 'lib':
                mlog.debug('Defaulting Rust dynamic library target crate type to "dylib"')
                self.rust_crate_type = 'dylib'
            # Don't let configuration proceed with a non-dynamic crate type
            elif self.rust_crate_type not in ['dylib', 'cdylib']:
                raise InvalidArguments(f'Crate type "{self.rust_crate_type}" invalid for dynamic libraries; must be "dylib" or "cdylib"')
        if not hasattr(self, 'prefix'):
            self.prefix = None
        if not hasattr(self, 'suffix'):
            self.suffix = None
        self.basic_filename_tpl = '{0.prefix}{0.name}.{0.suffix}'
        self.determine_filenames(environment)

    def get_link_deps_mapping(self, prefix, environment) -> T.Dict[str, str]:
        result: T.Dict[str, str] = {}
        mappings = self.get_transitive_link_deps_mapping(prefix, environment)
        old = get_target_macos_dylib_install_name(self)
        if old not in mappings:
            fname = self.get_filename()
            outdirs, _ = self.get_install_dir(self.environment)
            new = os.path.join(prefix, outdirs[0], fname)
            result.update({old: new})
        mappings.update(result)
        return mappings

    def get_default_install_dir(self, environment):
        return environment.get_shared_lib_dir()

    def determine_filenames(self, env):
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
        elif env.machines[self.for_machine].is_windows():
            suffix = 'dll'
            self.vs_import_filename = '{}{}.lib'.format(self.prefix if self.prefix is not None else '', self.name)
            self.gcc_import_filename = '{}{}.dll.a'.format(self.prefix if self.prefix is not None else 'lib', self.name)
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
        elif env.machines[self.for_machine].is_cygwin():
            suffix = 'dll'
            self.gcc_import_filename = '{}{}.dll.a'.format(self.prefix if self.prefix is not None else 'lib', self.name)
            # Shared library is of the form cygfoo.dll
            # (ld --dll-search-prefix=cyg is the default)
            prefix = 'cyg'
            # Import library is called libfoo.dll.a
            self.import_filename = self.gcc_import_filename
            if self.soversion:
                self.filename_tpl = '{0.prefix}{0.name}-{0.soversion}.{0.suffix}'
            else:
                self.filename_tpl = '{0.prefix}{0.name}.{0.suffix}'
        elif env.machines[self.for_machine].is_darwin():
            prefix = 'lib'
            suffix = 'dylib'
            # On macOS, the filename can only contain the major version
            if self.soversion:
                # libfoo.X.dylib
                self.filename_tpl = '{0.prefix}{0.name}.{0.soversion}.{0.suffix}'
            else:
                # libfoo.dylib
                self.filename_tpl = '{0.prefix}{0.name}.{0.suffix}'
        elif env.machines[self.for_machine].is_android():
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
        if self.prefix is None:
            self.prefix = prefix
        if self.suffix is None:
            self.suffix = suffix
        self.filename = self.filename_tpl.format(self)
        self.outputs = [self.filename]
        if create_debug_file:
            self.debug_filename = os.path.splitext(self.filename)[0] + '.pdb'

    @staticmethod
    def _validate_darwin_versions(darwin_versions):
        try:
            if isinstance(darwin_versions, int):
                darwin_versions = str(darwin_versions)
            if isinstance(darwin_versions, str):
                darwin_versions = 2 * [darwin_versions]
            if not isinstance(darwin_versions, list):
                raise InvalidArguments('Shared library darwin_versions: must be a string, integer,'
                                       'or a list, not {!r}'.format(darwin_versions))
            if len(darwin_versions) > 2:
                raise InvalidArguments('Shared library darwin_versions: list must contain 2 or fewer elements')
            if len(darwin_versions) == 1:
                darwin_versions = 2 * darwin_versions
            for i, v in enumerate(darwin_versions[:]):
                if isinstance(v, int):
                    v = str(v)
                if not isinstance(v, str):
                    raise InvalidArguments('Shared library darwin_versions: list elements '
                                           'must be strings or integers, not {!r}'.format(v))
                if not re.fullmatch(r'[0-9]+(\.[0-9]+){0,2}', v):
                    raise InvalidArguments('Shared library darwin_versions: must be X.Y.Z where '
                                           'X, Y, Z are numbers, and Y and Z are optional')
                parts = v.split('.')
                if len(parts) in (1, 2, 3) and int(parts[0]) > 65535:
                    raise InvalidArguments('Shared library darwin_versions: must be X.Y.Z '
                                           'where X is [0, 65535] and Y, Z are optional')
                if len(parts) in (2, 3) and int(parts[1]) > 255:
                    raise InvalidArguments('Shared library darwin_versions: must be X.Y.Z '
                                           'where Y is [0, 255] and Y, Z are optional')
                if len(parts) == 3 and int(parts[2]) > 255:
                    raise InvalidArguments('Shared library darwin_versions: must be X.Y.Z '
                                           'where Z is [0, 255] and Y, Z are optional')
                darwin_versions[i] = v
        except ValueError:
            raise InvalidArguments('Shared library darwin_versions: value is invalid')
        return darwin_versions

    def process_kwargs(self, kwargs, environment):
        super().process_kwargs(kwargs, environment)

        if not self.environment.machines[self.for_machine].is_android():
            supports_versioning = True
        else:
            supports_versioning = False

        if supports_versioning:
            # Shared library version
            if 'version' in kwargs:
                self.ltversion = kwargs['version']
                if not isinstance(self.ltversion, str):
                    raise InvalidArguments('Shared library version needs to be a string, not ' + type(self.ltversion).__name__)
                if not re.fullmatch(r'[0-9]+(\.[0-9]+){0,2}', self.ltversion):
                    raise InvalidArguments(f'Invalid Shared library version "{self.ltversion}". Must be of the form X.Y.Z where all three are numbers. Y and Z are optional.')
            # Try to extract/deduce the soversion
            if 'soversion' in kwargs:
                self.soversion = kwargs['soversion']
                if isinstance(self.soversion, int):
                    self.soversion = str(self.soversion)
                if not isinstance(self.soversion, str):
                    raise InvalidArguments('Shared library soversion is not a string or integer.')
            elif self.ltversion:
                # library version is defined, get the soversion from that
                # We replicate what Autotools does here and take the first
                # number of the version by default.
                self.soversion = self.ltversion.split('.')[0]
            # macOS, iOS and tvOS dylib compatibility_version and current_version
            if 'darwin_versions' in kwargs:
                self.darwin_versions = self._validate_darwin_versions(kwargs['darwin_versions'])
            elif self.soversion:
                # If unspecified, pick the soversion
                self.darwin_versions = 2 * [self.soversion]

        # Visual Studio module-definitions file
        if 'vs_module_defs' in kwargs:
            path = unholder(kwargs['vs_module_defs'])
            if isinstance(path, str):
                if os.path.isabs(path):
                    self.vs_module_defs = File.from_absolute_file(path)
                else:
                    self.vs_module_defs = File.from_source_file(environment.source_dir, self.subdir, path)
                self.link_depends.append(self.vs_module_defs)
            elif isinstance(path, File):
                # When passing a generated file.
                self.vs_module_defs = path
                self.link_depends.append(path)
            elif hasattr(path, 'get_filename'):
                # When passing output of a Custom Target
                path = File.from_built_file(path.subdir, path.get_filename())
                self.vs_module_defs = path
                self.link_depends.append(path)
            else:
                raise InvalidArguments(
                    'Shared library vs_module_defs must be either a string, '
                    'a file object or a Custom Target')
        if 'rust_crate_type' in kwargs:
            rust_crate_type = kwargs['rust_crate_type']
            if isinstance(rust_crate_type, str):
                self.rust_crate_type = rust_crate_type
            else:
                raise InvalidArguments(f'Invalid rust_crate_type "{rust_crate_type}": must be a string.')

    def get_import_filename(self):
        """
        The name of the import library that will be outputted by the compiler

        Returns None if there is no import library required for this platform
        """
        return self.import_filename

    def get_debug_filename(self):
        """
        The name of debuginfo file that will be created by the compiler

        Returns None if the build won't create any debuginfo file
        """
        return self.debug_filename

    def get_import_filenameslist(self):
        if self.import_filename:
            return [self.vs_import_filename, self.gcc_import_filename]
        return []

    def get_all_link_deps(self):
        return [self] + self.get_transitive_link_deps()

    def get_aliases(self) -> T.Dict[str, str]:
        """
        If the versioned library name is libfoo.so.0.100.0, aliases are:
        * libfoo.so.0 (soversion) -> libfoo.so.0.100.0
        * libfoo.so (unversioned; for linking) -> libfoo.so.0
        Same for dylib:
        * libfoo.dylib (unversioned; for linking) -> libfoo.0.dylib
        """
        aliases: T.Dict[str, str] = {}
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
            aliases[ltversion_filename] = self.filename
        # libfoo.so.0/libfoo.0.dylib is the actual library
        else:
            ltversion_filename = self.filename
        # Unversioned alias:
        #  libfoo.so -> libfoo.so.0
        #  libfoo.dylib -> libfoo.0.dylib
        aliases[self.basic_filename_tpl.format(self)] = ltversion_filename
        return aliases

    def type_suffix(self):
        return "@sha"

    def is_linkable_target(self):
        return True

# A shared library that is meant to be used with dlopen rather than linking
# into something else.
class SharedModule(SharedLibrary):
    known_kwargs = known_shmod_kwargs

    def __init__(self, name, subdir, subproject, for_machine: MachineChoice, sources, objects, environment, kwargs):
        if 'version' in kwargs:
            raise MesonException('Shared modules must not specify the version kwarg.')
        if 'soversion' in kwargs:
            raise MesonException('Shared modules must not specify the soversion kwarg.')
        super().__init__(name, subdir, subproject, for_machine, sources, objects, environment, kwargs)
        self.typename = 'shared module'

    def get_default_install_dir(self, environment):
        return environment.get_shared_module_dir()

class CommandBase:
    def flatten_command(self, cmd):
        cmd = unholder(listify(cmd))
        final_cmd = []
        for c in cmd:
            if isinstance(c, str):
                final_cmd.append(c)
            elif isinstance(c, File):
                self.depend_files.append(c)
                final_cmd.append(c)
            elif isinstance(c, programs.ExternalProgram):
                if not c.found():
                    raise InvalidArguments('Tried to use not-found external program in "command"')
                path = c.get_path()
                if os.path.isabs(path):
                    # Can only add a dependency on an external program which we
                    # know the absolute path of
                    self.depend_files.append(File.from_absolute_file(path))
                final_cmd += c.get_command()
            elif isinstance(c, (BuildTarget, CustomTarget)):
                self.dependencies.append(c)
                final_cmd.append(c)
            elif isinstance(c, list):
                final_cmd += self.flatten_command(c)
            else:
                raise InvalidArguments(f'Argument {c!r} in "command" is invalid')
        return final_cmd

class CustomTarget(Target, CommandBase):
    known_kwargs = {
        'input',
        'output',
        'command',
        'capture',
        'install',
        'install_dir',
        'install_mode',
        'build_always',
        'build_always_stale',
        'depends',
        'depend_files',
        'depfile',
        'build_by_default',
        'override_options',
        'console',
        'env',
    }

    def __init__(self, name: str, subdir: str, subproject: str, kwargs: T.Dict[str, T.Any],
                 absolute_paths: bool = False, backend: T.Optional['Backend'] = None):
        self.typename = 'custom'
        # TODO expose keyword arg to make MachineChoice.HOST configurable
        super().__init__(name, subdir, subproject, False, MachineChoice.HOST)
        self.dependencies = []
        self.extra_depends = []
        self.depend_files = [] # Files that this target depends on but are not on the command line.
        self.depfile = None
        self.process_kwargs(kwargs, backend)
        # Whether to use absolute paths for all files on the commandline
        self.absolute_paths = absolute_paths
        unknowns = []
        for k in kwargs:
            if k not in CustomTarget.known_kwargs:
                unknowns.append(k)
        if unknowns:
            mlog.warning('Unknown keyword arguments in target {}: {}'.format(self.name, ', '.join(unknowns)))

    def get_default_install_dir(self, environment):
        return None

    def __repr__(self):
        repr_str = "<{0} {1}: {2}>"
        return repr_str.format(self.__class__.__name__, self.get_id(), self.command)

    def get_target_dependencies(self):
        deps = self.dependencies[:]
        deps += self.extra_depends
        for c in unholder(self.sources):
            if isinstance(c, (BuildTarget, CustomTarget)):
                deps.append(c)
        return deps

    def get_transitive_build_target_deps(self):
        '''
        Recursively fetch the build targets that this custom target depends on,
        whether through `command:`, `depends:`, or `sources:` The recursion is
        only performed on custom targets.
        This is useful for setting PATH on Windows for finding required DLLs.
        F.ex, if you have a python script that loads a C module that links to
        other DLLs in your project.
        '''
        bdeps = set()
        deps = self.get_target_dependencies()
        for d in deps:
            if isinstance(d, BuildTarget):
                bdeps.add(d)
            elif isinstance(d, CustomTarget):
                bdeps.update(d.get_transitive_build_target_deps())
        return bdeps

    def process_kwargs(self, kwargs, backend):
        self.process_kwargs_base(kwargs)
        self.sources = unholder(extract_as_list(kwargs, 'input'))
        if 'output' not in kwargs:
            raise InvalidArguments('Missing keyword argument "output".')
        self.outputs = listify(kwargs['output'])
        # This will substitute values from the input into output and return it.
        inputs = get_sources_string_names(self.sources, backend)
        values = get_filenames_templates_dict(inputs, [])
        for i in self.outputs:
            if not(isinstance(i, str)):
                raise InvalidArguments('Output argument not a string.')
            if i == '':
                raise InvalidArguments('Output must not be empty.')
            if i.strip() == '':
                raise InvalidArguments('Output must not consist only of whitespace.')
            if has_path_sep(i):
                raise InvalidArguments(f'Output {i!r} must not contain a path segment.')
            if '@INPUT@' in i or '@INPUT0@' in i:
                m = 'Output cannot contain @INPUT@ or @INPUT0@, did you ' \
                    'mean @PLAINNAME@ or @BASENAME@?'
                raise InvalidArguments(m)
            # We already check this during substitution, but the error message
            # will be unclear/confusing, so check it here.
            if len(inputs) != 1 and ('@PLAINNAME@' in i or '@BASENAME@' in i):
                m = "Output cannot contain @PLAINNAME@ or @BASENAME@ when " \
                    "there is more than one input (we can't know which to use)"
                raise InvalidArguments(m)
        self.outputs = substitute_values(self.outputs, values)
        self.capture = kwargs.get('capture', False)
        if self.capture and len(self.outputs) != 1:
            raise InvalidArguments('Capturing can only output to a single file.')
        self.console = kwargs.get('console', False)
        if not isinstance(self.console, bool):
            raise InvalidArguments('"console" kwarg only accepts booleans')
        if self.capture and self.console:
            raise InvalidArguments("Can't both capture output and output to console")
        if 'command' not in kwargs:
            raise InvalidArguments('Missing keyword argument "command".')
        if 'depfile' in kwargs:
            depfile = kwargs['depfile']
            if not isinstance(depfile, str):
                raise InvalidArguments('Depfile must be a string.')
            if os.path.basename(depfile) != depfile:
                raise InvalidArguments('Depfile must be a plain filename without a subdirectory.')
            self.depfile = depfile
        self.command = self.flatten_command(kwargs['command'])
        if self.capture:
            for c in self.command:
                if isinstance(c, str) and '@OUTPUT@' in c:
                    raise InvalidArguments('@OUTPUT@ is not allowed when capturing output.')
        if 'install' in kwargs:
            self.install = kwargs['install']
            if not isinstance(self.install, bool):
                raise InvalidArguments('"install" must be boolean.')
            if self.install:
                if 'install_dir' not in kwargs:
                    raise InvalidArguments('"install_dir" must be specified '
                                           'when installing a target')

                if isinstance(kwargs['install_dir'], list):
                    FeatureNew.single_use('multiple install_dir for custom_target', '0.40.0', self.subproject)
                # If an item in this list is False, the output corresponding to
                # the list index of that item will not be installed
                self.install_dir = typeslistify(kwargs['install_dir'], (str, bool))
                self.install_mode = kwargs.get('install_mode', None)
        else:
            self.install = False
            self.install_dir = [None]
            self.install_mode = None
        if 'build_always' in kwargs and 'build_always_stale' in kwargs:
            raise InvalidArguments('build_always and build_always_stale are mutually exclusive. Combine build_by_default and build_always_stale.')
        elif 'build_always' in kwargs:
            if 'build_by_default' not in kwargs:
                self.build_by_default = kwargs['build_always']
            self.build_always_stale = kwargs['build_always']
        elif 'build_always_stale' in kwargs:
            self.build_always_stale = kwargs['build_always_stale']
        if not isinstance(self.build_always_stale, bool):
            raise InvalidArguments('Argument build_always_stale must be a boolean.')
        extra_deps, depend_files = [extract_as_list(kwargs, c, pop=False) for c in ['depends', 'depend_files']]
        for ed in unholder(extra_deps):
            if not isinstance(ed, (CustomTarget, BuildTarget)):
                raise InvalidArguments('Can only depend on toplevel targets: custom_target or build_target (executable or a library) got: {}({})'
                                       .format(type(ed), ed))
            self.extra_depends.append(ed)
        for i in depend_files:
            if isinstance(i, (File, str)):
                self.depend_files.append(i)
            else:
                mlog.debug(i)
                raise InvalidArguments('Unknown type {!r} in depend_files.'.format(type(i).__name__))
        self.env = kwargs.get('env')

    def get_dependencies(self):
        return self.dependencies

    def should_install(self) -> bool:
        return self.install

    def get_custom_install_dir(self):
        return self.install_dir

    def get_custom_install_mode(self):
        return self.install_mode

    def get_outputs(self) -> T.List[str]:
        return self.outputs

    def get_filename(self):
        return self.outputs[0]

    def get_sources(self):
        return self.sources

    def get_generated_lists(self):
        genlists = []
        for c in unholder(self.sources):
            if isinstance(c, GeneratedList):
                genlists.append(c)
        return genlists

    def get_generated_sources(self):
        return self.get_generated_lists()

    def get_dep_outname(self, infilenames):
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

    def is_linkable_target(self):
        if len(self.outputs) != 1:
            return False
        suf = os.path.splitext(self.outputs[0])[-1]
        if suf == '.a' or suf == '.dll' or suf == '.lib' or suf == '.so' or suf == '.dylib':
            return True

    def get_link_deps_mapping(self, prefix, environment):
        return {}

    def get_link_dep_subdirs(self):
        return OrderedSet()

    def get_all_link_deps(self):
        return []

    def is_internal(self) -> bool:
        if not self.should_install():
            return True
        for out in self.get_outputs():
            # Can't check if this is a static library, so try to guess
            if not out.endswith(('.a', '.lib')):
                return False
        return True

    def extract_all_objects_recurse(self):
        return self.get_outputs()

    def type_suffix(self):
        return "@cus"

    def __getitem__(self, index):
        return CustomTargetIndex(self, self.outputs[index])

    def __setitem__(self, index, value):
        raise NotImplementedError

    def __delitem__(self, index):
        raise NotImplementedError

    def __iter__(self):
        for i in self.outputs:
            yield CustomTargetIndex(self, i)

class RunTarget(Target, CommandBase):
    def __init__(self, name, command, dependencies, subdir, subproject, env=None):
        self.typename = 'run'
        # These don't produce output artifacts
        super().__init__(name, subdir, subproject, False, MachineChoice.BUILD)
        self.dependencies = dependencies
        self.depend_files = []
        self.command = self.flatten_command(command)
        self.absolute_paths = False
        self.env = env

    def __repr__(self):
        repr_str = "<{0} {1}: {2}>"
        return repr_str.format(self.__class__.__name__, self.get_id(), self.command[0])

    def process_kwargs(self, kwargs):
        return self.process_kwargs_base(kwargs)

    def get_dependencies(self):
        return self.dependencies

    def get_generated_sources(self):
        return []

    def get_sources(self):
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

    def type_suffix(self):
        return "@run"

class AliasTarget(RunTarget):
    def __init__(self, name, dependencies, subdir, subproject):
        super().__init__(name, [], dependencies, subdir, subproject)

class Jar(BuildTarget):
    known_kwargs = known_jar_kwargs

    def __init__(self, name, subdir, subproject, for_machine: MachineChoice, sources, objects, environment, kwargs):
        self.typename = 'jar'
        super().__init__(name, subdir, subproject, for_machine, sources, objects, environment, kwargs)
        for s in self.sources:
            if not s.endswith('.java'):
                raise InvalidArguments(f'Jar source {s} is not a java file.')
        for t in self.link_targets:
            if not isinstance(t, Jar):
                raise InvalidArguments(f'Link target {t} is not a jar target.')
        self.filename = self.name + '.jar'
        self.outputs = [self.filename]
        self.java_args = kwargs.get('java_args', [])

    def get_main_class(self):
        return self.main_class

    def type_suffix(self):
        return "@jar"

    def get_java_args(self):
        return self.java_args

    def validate_install(self, environment):
        # All jar targets are installable.
        pass

    def is_linkable_target(self):
        return True

    def get_classpath_args(self):
        cp_paths = [os.path.join(l.get_subdir(), l.get_filename()) for l in self.link_targets]
        cp_string = os.pathsep.join(cp_paths)
        if cp_string:
            return ['-cp', os.pathsep.join(cp_paths)]
        return []

class CustomTargetIndex:

    """A special opaque object returned by indexing a CustomTarget. This object
    exists in Meson, but acts as a proxy in the backends, making targets depend
    on the CustomTarget it's derived from, but only adding one source file to
    the sources.
    """

    def __init__(self, target, output):
        self.typename = 'custom'
        self.target = target
        self.output = output
        self.for_machine = target.for_machine

    def __repr__(self):
        return '<CustomTargetIndex: {!r}[{}]>'.format(
            self.target, self.target.get_outputs().index(self.output))

    def get_outputs(self) -> T.List[str]:
        return [self.output]

    def get_subdir(self):
        return self.target.get_subdir()

    def get_filename(self):
        return self.output

    def get_id(self):
        return self.target.get_id()

    def get_all_link_deps(self):
        return self.target.get_all_link_deps()

    def get_link_deps_mapping(self, prefix, environment):
        return self.target.get_link_deps_mapping(prefix, environment)

    def get_link_dep_subdirs(self):
        return self.target.get_link_dep_subdirs()

    def is_linkable_target(self):
        suf = os.path.splitext(self.output)[-1]
        if suf == '.a' or suf == '.dll' or suf == '.lib' or suf == '.so':
            return True

    def should_install(self) -> bool:
        return self.target.should_install()

    def is_internal(self) -> bool:
        return self.target.is_internal()

    def extract_all_objects_recurse(self):
        return self.target.extract_all_objects_recurse()

    def get_custom_install_dir(self):
        return self.target.get_custom_install_dir()

class ConfigurationData:
    def __init__(self) -> None:
        super().__init__()
        self.values = {}  # T.Dict[str, T.Union[str, int, bool]]

    def __repr__(self):
        return repr(self.values)

    def __contains__(self, value: str) -> bool:
        return value in self.values

    def get(self, name: str) -> T.Tuple[T.Union[str, int, bool], T.Optional[str]]:
        return self.values[name] # (val, desc)

    def keys(self) -> T.Iterator[str]:
        return self.values.keys()

# A bit poorly named, but this represents plain data files to copy
# during install.
class Data:
    def __init__(self, sources: T.List[File], install_dir: str,
                 install_mode: T.Optional['FileMode'], subproject: str,
                 rename: T.List[str] = None):
        self.sources = sources
        self.install_dir = install_dir
        self.install_mode = install_mode
        if rename is None:
            self.rename = [os.path.basename(f.fname) for f in self.sources]
        else:
            self.rename = rename
        self.subproject = subproject

class TestSetup:
    def __init__(self, exe_wrapper: T.Optional[T.List[str]], gdb: bool,
                 timeout_multiplier: int, env: EnvironmentVariables,
                 exclude_suites: T.List[str]):
        self.exe_wrapper = exe_wrapper
        self.gdb = gdb
        self.timeout_multiplier = timeout_multiplier
        self.env = env
        self.exclude_suites = exclude_suites

def get_sources_string_names(sources, backend):
    '''
    For the specified list of @sources which can be strings, Files, or targets,
    get all the output basenames.
    '''
    names = []
    for s in unholder(sources):
        if isinstance(s, str):
            names.append(s)
        elif isinstance(s, (BuildTarget, CustomTarget, CustomTargetIndex, GeneratedList)):
            names += s.get_outputs()
        elif isinstance(s, ExtractedObjects):
            names += s.get_outputs(backend)
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
            "Build data file {!r} references functions or classes that don't "
            "exist. This probably means that it was generated with an old "
            "version of meson. Try running from the source directory "
            "meson {} --wipe".format(filename, build_dir))
    if not isinstance(obj, Build):
        raise MesonException(load_fail_msg)
    return obj

def save(obj: Build, filename: str) -> None:
    with open(filename, 'wb') as f:
        pickle.dump(obj, f)
