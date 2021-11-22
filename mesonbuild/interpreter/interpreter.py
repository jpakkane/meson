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

from .. import mparser
from .. import environment
from .. import coredata
from .. import dependencies
from .. import mlog
from .. import build
from .. import optinterpreter
from .. import compilers
from .. import envconfig
from ..wrap import wrap, WrapMode
from .. import mesonlib
from ..mesonlib import MesonBugException, HoldableObject, FileMode, MachineChoice, OptionKey, listify, extract_as_list, has_path_sep
from ..programs import ExternalProgram, NonExistingExternalProgram
from ..dependencies import Dependency
from ..depfile import DepFile
from ..interpreterbase import ContainerTypeInfo, InterpreterBase, KwargInfo, typed_kwargs, typed_pos_args
from ..interpreterbase import noPosargs, noKwargs, permittedKwargs, noArgsFlattening, noSecondLevelHolderResolving, unholder_return
from ..interpreterbase import InterpreterException, InvalidArguments, InvalidCode, SubdirDoneRequest
from ..interpreterbase import Disabler, disablerIfNotFound
from ..interpreterbase import FeatureNew, FeatureDeprecated, FeatureNewKwargs, FeatureDeprecatedKwargs
from ..interpreterbase import ObjectHolder
from ..interpreterbase.baseobjects import TYPE_nkwargs, TYPE_nvar, TYPE_var, TYPE_kwargs
from ..modules import ExtensionModule, ModuleObject, MutableModuleObject, NewExtensionModule, NotFoundExtensionModule
from ..cmake import CMakeInterpreter
from ..backend.backends import Backend, ExecutableSerialisation

from . import interpreterobjects as OBJ
from . import compiler as compilerOBJ
from .mesonmain import MesonMain
from .dependencyfallbacks import DependencyFallbacksHolder
from .interpreterobjects import (
    SubprojectHolder,
    ConfigurationDataObject,
    Test,
    RunProcess,
    extract_required_kwarg,
    extract_search_dirs,
    NullSubprojectInterpreter,
)
from .type_checking import (
    COMMAND_KW,
    CT_BUILD_BY_DEFAULT,
    CT_INPUT_KW,
    CT_INSTALL_DIR_KW,
    CT_OUTPUT_KW,
    DEPENDS_KW,
    DEPEND_FILES_KW,
    DEPFILE_KW,
    ENV_KW,
    INSTALL_KW,
    INSTALL_MODE_KW,
    CT_INSTALL_TAG_KW,
    LANGUAGE_KW,
    NATIVE_KW, OVERRIDE_OPTIONS_KW,
    REQUIRED_KW,
    NoneType,
    in_set_validator,
)
from . import primitives as P_OBJ

from pathlib import Path
import os
import shutil
import uuid
import re
import stat
import collections
import typing as T
import textwrap
import importlib

if T.TYPE_CHECKING:
    import argparse

    from . import kwargs
    from ..programs import OverrideProgram

    # Input source types passed to Targets
    SourceInputs = T.Union[mesonlib.File, build.GeneratedList, build.BuildTarget, build.BothLibraries,
                           build.CustomTargetIndex, build.CustomTarget, build.GeneratedList, str]
    # Input source types passed to the build.Target5 classes
    SourceOutputs = T.Union[mesonlib.File, build.GeneratedList,
                            build.BuildTarget, build.CustomTargetIndex, build.CustomTarget,
                            build.GeneratedList]


def stringifyUserArguments(args, quote=False):
    if isinstance(args, list):
        return '[%s]' % ', '.join([stringifyUserArguments(x, True) for x in args])
    elif isinstance(args, dict):
        return '{%s}' % ', '.join(['{} : {}'.format(stringifyUserArguments(k, True), stringifyUserArguments(v, True)) for k, v in args.items()])
    elif isinstance(args, bool):
        return 'true' if args else 'false'
    elif isinstance(args, int):
        return str(args)
    elif isinstance(args, str):
        return f"'{args}'" if quote else args
    raise InvalidArguments('Function accepts only strings, integers, bools, lists, dictionaries and lists thereof.')

class Summary:
    def __init__(self, project_name, project_version):
        self.project_name = project_name
        self.project_version = project_version
        self.sections = collections.defaultdict(dict)
        self.max_key_len = 0

    def add_section(self, section, values, kwargs, subproject):
        bool_yn = kwargs.get('bool_yn', False)
        if not isinstance(bool_yn, bool):
            raise InterpreterException('bool_yn keyword argument must be boolean')
        list_sep = kwargs.get('list_sep')
        if list_sep is not None and not isinstance(list_sep, str):
            raise InterpreterException('list_sep keyword argument must be string')
        for k, v in values.items():
            if k in self.sections[section]:
                raise InterpreterException(f'Summary section {section!r} already have key {k!r}')
            formatted_values = []
            for i in listify(v):
                if isinstance(i, bool) and bool_yn:
                    formatted_values.append(mlog.green('YES') if i else mlog.red('NO'))
                elif isinstance(i, (str, int, bool)):
                    formatted_values.append(str(i))
                elif isinstance(i, (ExternalProgram, Dependency)):
                    FeatureNew.single_use('dependency or external program in summary', '0.57.0', subproject)
                    formatted_values.append(i.summary_value())
                elif isinstance(i, coredata.UserOption):
                    FeatureNew.single_use('feature option in summary', '0.58.0', subproject)
                    formatted_values.append(i.printable_value())
                else:
                    m = 'Summary value in section {!r}, key {!r}, must be string, integer, boolean, dependency or external program'
                    raise InterpreterException(m.format(section, k))
            self.sections[section][k] = (formatted_values, list_sep)
            self.max_key_len = max(self.max_key_len, len(k))

    def dump(self):
        mlog.log(self.project_name, mlog.normal_cyan(self.project_version))
        for section, values in self.sections.items():
            mlog.log('')  # newline
            if section:
                mlog.log(' ', mlog.bold(section))
            for k, v in values.items():
                v, list_sep = v
                padding = self.max_key_len - len(k)
                end = ' ' if v else ''
                mlog.log(' ' * 3, k + ' ' * padding + ':', end=end)
                indent = self.max_key_len + 6
                self.dump_value(v, list_sep, indent)
        mlog.log('')  # newline

    def dump_value(self, arr, list_sep, indent):
        lines_sep = '\n' + ' ' * indent
        if list_sep is None:
            mlog.log(*arr, sep=lines_sep)
            return
        max_len = shutil.get_terminal_size().columns
        line = []
        line_len = indent
        lines_sep = list_sep.rstrip() + lines_sep
        for v in arr:
            v_len = len(v) + len(list_sep)
            if line and line_len + v_len > max_len:
                mlog.log(*line, sep=list_sep, end=lines_sep)
                line_len = indent
                line = []
            line.append(v)
            line_len += v_len
        mlog.log(*line, sep=list_sep)

known_library_kwargs = (
    build.known_shlib_kwargs |
    build.known_stlib_kwargs
)

known_build_target_kwargs = (
    known_library_kwargs |
    build.known_exe_kwargs |
    build.known_jar_kwargs |
    build.known_objs_kwargs |
    {'target_type'}
)

TEST_KWARGS: T.List[KwargInfo] = [
    KwargInfo('args', ContainerTypeInfo(list, (str, mesonlib.File, build.BuildTarget, build.CustomTarget)),
              listify=True, default=[]),
    KwargInfo('should_fail', bool, default=False),
    KwargInfo('timeout', int, default=30),
    KwargInfo('workdir', (str, NoneType), default=None,
              validator=lambda x: 'must be an absolute path' if not os.path.isabs(x) else None),
    KwargInfo('protocol', str,
              default='exitcode',
              validator=in_set_validator({'exitcode', 'tap', 'gtest', 'rust'}),
              since_values={'gtest': '0.55.0', 'rust': '0.57.0'}),
    KwargInfo('depends', ContainerTypeInfo(list, (build.CustomTarget, build.BuildTarget)),
              listify=True, default=[], since='0.46.0'),
    KwargInfo('priority', int, default=0, since='0.52.0'),
    # TODO: env needs reworks of the way the environment variable holder itself works probably
    ENV_KW,
    KwargInfo('suite', ContainerTypeInfo(list, str), listify=True, default=['']),  # yes, a list of empty string
]

permitted_dependency_kwargs = {
    'allow_fallback',
    'cmake_args',
    'cmake_module_path',
    'cmake_package_version',
    'components',
    'default_options',
    'fallback',
    'include_type',
    'language',
    'main',
    'method',
    'modules',
    'native',
    'not_found_message',
    'optional_modules',
    'private_headers',
    'required',
    'static',
    'version',
}

implicit_check_false_warning = """You should add the boolean check kwarg to the run_command call.
         It currently defaults to false,
         but it will default to true in future releases of meson.
         See also: https://github.com/mesonbuild/meson/issues/9300"""
class Interpreter(InterpreterBase, HoldableObject):

    def __init__(
                self,
                _build: build.Build,
                backend: T.Optional[Backend] = None,
                subproject: str = '',
                subdir: str = '',
                subproject_dir: str = 'subprojects',
                default_project_options: T.Optional[T.Dict[str, str]] = None,
                mock: bool = False,
                ast: T.Optional[mparser.CodeBlockNode] = None,
                is_translated: bool = False,
                user_defined_options: T.Optional['argparse.Namespace'] = None,
            ) -> None:
        super().__init__(_build.environment.get_source_dir(), subdir, subproject)
        self.active_projectname = ''
        self.build = _build
        self.environment = self.build.environment
        self.coredata = self.environment.get_coredata()
        self.backend = backend
        self.summary = {}
        self.modules = {}
        # Subproject directory is usually the name of the subproject, but can
        # be different for dependencies provided by wrap files.
        self.subproject_directory_name = subdir.split(os.path.sep)[-1]
        self.subproject_dir = subproject_dir
        self.option_file = os.path.join(self.source_root, self.subdir, 'meson_options.txt')
        if not mock and ast is None:
            self.load_root_meson_file()
            self.sanity_check_ast()
        elif ast is not None:
            self.ast = ast
            self.sanity_check_ast()
        self.builtin.update({'meson': MesonMain(self.build, self)})
        self.generators: T.List[build.Generator] = []
        self.processed_buildfiles = set() # type: T.Set[str]
        self.project_args_frozen = False
        self.global_args_frozen = False  # implies self.project_args_frozen
        self.subprojects: T.Dict[str, SubprojectHolder] = {}
        self.subproject_stack = []
        self.configure_file_outputs = {}
        # Passed from the outside, only used in subprojects.
        if default_project_options:
            self.default_project_options = default_project_options.copy()
        else:
            self.default_project_options = {}
        self.project_default_options = {}
        self.build_func_dict()
        self.build_holder_map()
        self.user_defined_options = user_defined_options

        # build_def_files needs to be defined before parse_project is called
        #
        # For non-meson subprojects, we'll be using the ast. Even if it does
        # exist we don't want to add a dependency on it, it's autogenerated
        # from the actual build files, and is just for reference.
        self.build_def_files = []
        build_filename = os.path.join(self.subdir, environment.build_filename)
        if not is_translated:
            self.build_def_files.append(build_filename)
        if not mock:
            self.parse_project()
        self._redetect_machines()

    def __getnewargs_ex__(self) -> T.Tuple[T.Tuple[object], T.Dict[str, object]]:
        raise MesonBugException('This class is unpicklable')

    def _redetect_machines(self):
        # Re-initialize machine descriptions. We can do a better job now because we
        # have the compilers needed to gain more knowledge, so wipe out old
        # inference and start over.
        machines = self.build.environment.machines.miss_defaulting()
        machines.build = environment.detect_machine_info(self.coredata.compilers.build)
        self.build.environment.machines = machines.default_missing()
        assert self.build.environment.machines.build.cpu is not None
        assert self.build.environment.machines.host.cpu is not None
        assert self.build.environment.machines.target.cpu is not None

        self.builtin['build_machine'] = \
            OBJ.MachineHolder(self.build.environment.machines.build, self)
        self.builtin['host_machine'] = \
            OBJ.MachineHolder(self.build.environment.machines.host, self)
        self.builtin['target_machine'] = \
            OBJ.MachineHolder(self.build.environment.machines.target, self)

    def build_func_dict(self):
        self.funcs.update({'add_global_arguments': self.func_add_global_arguments,
                           'add_project_arguments': self.func_add_project_arguments,
                           'add_global_link_arguments': self.func_add_global_link_arguments,
                           'add_project_link_arguments': self.func_add_project_link_arguments,
                           'add_test_setup': self.func_add_test_setup,
                           'add_languages': self.func_add_languages,
                           'alias_target': self.func_alias_target,
                           'assert': self.func_assert,
                           'benchmark': self.func_benchmark,
                           'build_target': self.func_build_target,
                           'configuration_data': self.func_configuration_data,
                           'configure_file': self.func_configure_file,
                           'custom_target': self.func_custom_target,
                           'declare_dependency': self.func_declare_dependency,
                           'dependency': self.func_dependency,
                           'disabler': self.func_disabler,
                           'environment': self.func_environment,
                           'error': self.func_error,
                           'executable': self.func_executable,
                           'generator': self.func_generator,
                           'gettext': self.func_gettext,
                           'get_option': self.func_get_option,
                           'get_variable': self.func_get_variable,
                           'files': self.func_files,
                           'find_library': self.func_find_library,
                           'find_program': self.func_find_program,
                           'include_directories': self.func_include_directories,
                           'import': self.func_import,
                           'install_data': self.func_install_data,
                           'install_headers': self.func_install_headers,
                           'install_man': self.func_install_man,
                           'install_emptydir': self.func_install_emptydir,
                           'install_subdir': self.func_install_subdir,
                           'is_disabler': self.func_is_disabler,
                           'is_variable': self.func_is_variable,
                           'jar': self.func_jar,
                           'join_paths': self.func_join_paths,
                           'library': self.func_library,
                           'message': self.func_message,
                           'warning': self.func_warning,
                           'option': self.func_option,
                           'project': self.func_project,
                           'run_target': self.func_run_target,
                           'run_command': self.func_run_command,
                           'set_variable': self.func_set_variable,
                           'subdir': self.func_subdir,
                           'subdir_done': self.func_subdir_done,
                           'subproject': self.func_subproject,
                           'summary': self.func_summary,
                           'compiled_objects': self.func_compiled_objects,
                           'shared_library': self.func_shared_lib,
                           'shared_module': self.func_shared_module,
                           'static_library': self.func_static_lib,
                           'both_libraries': self.func_both_lib,
                           'test': self.func_test,
                           'unset_variable': self.func_unset_variable,
                           'vcs_tag': self.func_vcs_tag,
                           'range': self.func_range,
                           })
        if 'MESON_UNIT_TEST' in os.environ:
            self.funcs.update({'exception': self.func_exception})

    def build_holder_map(self) -> None:
        '''
            Build a mapping of `HoldableObject` types to their corresponding
            `ObjectHolder`s. This mapping is used in `InterpreterBase` to automatically
            holderify all returned values from methods and functions.
        '''
        self.holder_map.update({
            # Primitives
            list: P_OBJ.ArrayHolder,
            dict: P_OBJ.DictHolder,
            int: P_OBJ.IntegerHolder,
            bool: P_OBJ.BooleanHolder,
            str: P_OBJ.StringHolder,
            P_OBJ.MesonVersionString: P_OBJ.MesonVersionStringHolder,

            # Meson types
            mesonlib.File: OBJ.FileHolder,
            build.SharedLibrary: OBJ.SharedLibraryHolder,
            build.StaticLibrary: OBJ.StaticLibraryHolder,
            build.BothLibraries: OBJ.BothLibrariesHolder,
            build.SharedModule: OBJ.SharedModuleHolder,
            build.CompiledObjects: OBJ.CompiledObjectsHolder,
            build.Executable: OBJ.ExecutableHolder,
            build.Jar: OBJ.JarHolder,
            build.CustomTarget: OBJ.CustomTargetHolder,
            build.CustomTargetIndex: OBJ.CustomTargetIndexHolder,
            build.Generator: OBJ.GeneratorHolder,
            build.GeneratedList: OBJ.GeneratedListHolder,
            build.ExtractedObjects: OBJ.GeneratedObjectsHolder,
            build.RunTarget: OBJ.RunTargetHolder,
            build.AliasTarget: OBJ.AliasTargetHolder,
            build.Headers: OBJ.HeadersHolder,
            build.Man: OBJ.ManHolder,
            build.EmptyDir: OBJ.EmptyDirHolder,
            build.Data: OBJ.DataHolder,
            build.InstallDir: OBJ.InstallDirHolder,
            build.IncludeDirs: OBJ.IncludeDirsHolder,
            build.EnvironmentVariables: OBJ.EnvironmentVariablesHolder,
            compilers.RunResult: compilerOBJ.TryRunResultHolder,
            dependencies.ExternalLibrary: OBJ.ExternalLibraryHolder,
            coredata.UserFeatureOption: OBJ.FeatureOptionHolder,
            envconfig.MachineInfo: OBJ.MachineHolder,
        })

        '''
            Build a mapping of `HoldableObject` base classes to their
            corresponding `ObjectHolder`s. The difference to `self.holder_map`
            is that the keys here define an upper bound instead of requiring an
            exact match.

            The mappings defined here are only used when there was no direct hit
            found in `self.holder_map`.
        '''
        self.bound_holder_map.update({
            dependencies.Dependency: OBJ.DependencyHolder,
            ExternalProgram: OBJ.ExternalProgramHolder,
            compilers.Compiler: compilerOBJ.CompilerHolder,
            ModuleObject: OBJ.ModuleObjectHolder,
            MutableModuleObject: OBJ.MutableModuleObjectHolder,
        })

    def append_holder_map(self, held_type: T.Type[mesonlib.HoldableObject], holder_type: T.Type[ObjectHolder]) -> None:
        '''
            Adds one additional mapping to the `holder_map`.

            The intended use for this function is in the `initialize` method of
            modules to register custom object holders.
        '''
        self.holder_map.update({
            held_type: holder_type
        })

    def process_new_values(self, invalues: T.List[T.Union[TYPE_var, ExecutableSerialisation]]) -> None:
        invalues = listify(invalues)
        for v in invalues:
            if isinstance(v, ObjectHolder):
                raise InterpreterException('Modules must not return ObjectHolders')
            if isinstance(v, (build.BuildTarget, build.CustomTarget, build.RunTarget)):
                self.add_target(v.name, v)
            elif isinstance(v, list):
                self.process_new_values(v)
            elif isinstance(v, ExecutableSerialisation):
                v.subproject = self.subproject
                self.build.install_scripts.append(v)
            elif isinstance(v, build.Data):
                self.build.data.append(v)
            elif isinstance(v, dependencies.InternalDependency):
                # FIXME: This is special cased and not ideal:
                # The first source is our new VapiTarget, the rest are deps
                self.process_new_values(v.sources[0])
            elif isinstance(v, build.InstallDir):
                self.build.install_dirs.append(v)
            elif isinstance(v, Test):
                self.build.tests.append(v)
            elif isinstance(v, (int, str, bool, Disabler, ObjectHolder, build.GeneratedList,
                                ExternalProgram)):
                pass
            else:
                raise InterpreterException(f'Module returned a value of unknown type {v!r}.')

    def get_build_def_files(self) -> T.List[str]:
        return self.build_def_files

    def add_build_def_file(self, f: mesonlib.FileOrString) -> None:
        # Use relative path for files within source directory, and absolute path
        # for system files. Skip files within build directory. Also skip not regular
        # files (e.g. /dev/stdout) Normalize the path to avoid duplicates, this
        # is especially important to convert '/' to '\' on Windows.
        if isinstance(f, mesonlib.File):
            if f.is_built:
                return
            f = os.path.normpath(f.relative_name())
        elif os.path.isfile(f) and not f.startswith('/dev'):
            srcdir = Path(self.environment.get_source_dir())
            builddir = Path(self.environment.get_build_dir())
            try:
                f = Path(f).resolve()
            except OSError:
                f = Path(f)
                s = f.stat()
                if (hasattr(s, 'st_file_attributes') and
                        s.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT != 0 and
                        s.st_reparse_tag == stat.IO_REPARSE_TAG_APPEXECLINK):
                    # This is a Windows Store link which we can't
                    # resolve, so just do our best otherwise.
                    f = f.parent.resolve() / f.name
                else:
                    raise
            if builddir in f.parents:
                return
            if srcdir in f.parents:
                f = f.relative_to(srcdir)
            f = str(f)
        else:
            return
        if f not in self.build_def_files:
            self.build_def_files.append(f)

    def get_variables(self):
        return self.variables

    def check_stdlibs(self):
        machine_choices = [MachineChoice.HOST]
        if self.coredata.is_cross_build():
            machine_choices.append(MachineChoice.BUILD)
        for for_machine in machine_choices:
            props = self.build.environment.properties[for_machine]
            for l in self.coredata.compilers[for_machine].keys():
                try:
                    di = mesonlib.stringlistify(props.get_stdlib(l))
                except KeyError:
                    continue
                if len(di) == 1:
                    FeatureNew.single_use('stdlib without variable name', '0.56.0', self.subproject)
                kwargs = {'native': for_machine is MachineChoice.BUILD,
                          }
                name = l + '_stdlib'
                df = DependencyFallbacksHolder(self, [name])
                df.set_fallback(di)
                dep = df.lookup(kwargs, force_fallback=True)
                self.build.stdlibs[for_machine][l] = dep

    def _import_module(self, modname: str, required: bool) -> T.Union[ExtensionModule, NewExtensionModule, NotFoundExtensionModule]:
        if modname in self.modules:
            return self.modules[modname]
        try:
            module = importlib.import_module('mesonbuild.modules.' + modname)
        except ImportError:
            if required:
                raise InvalidArguments(f'Module "{modname}" does not exist')
            ext_module = NotFoundExtensionModule()
        else:
            ext_module = module.initialize(self)
            assert isinstance(ext_module, (ExtensionModule, NewExtensionModule))
            self.build.modules.append(modname)
        self.modules[modname] = ext_module
        return ext_module

    @typed_pos_args('import', str)
    @typed_kwargs(
        'import',
        REQUIRED_KW.evolve(since='0.59.0'),
        KwargInfo('disabler', bool, default=False, since='0.59.0'),
    )
    @disablerIfNotFound
    def func_import(self, node: mparser.BaseNode, args: T.Tuple[str],
                    kwargs: 'kwargs.FuncImportModule') -> T.Union[ExtensionModule, NewExtensionModule, NotFoundExtensionModule]:
        modname = args[0]
        disabled, required, _ = extract_required_kwarg(kwargs, self.subproject)
        if disabled:
            return NotFoundExtensionModule()

        if modname.startswith('unstable-'):
            plainname = modname.split('-', 1)[1]
            try:
                # check if stable module exists
                mod = self._import_module(plainname, required)
                # XXX: this is actually not helpful, since it doesn't do a version check
                mlog.warning(f'Module {modname} is now stable, please use the {plainname} module instead.')
                return mod
            except InvalidArguments:
                mlog.warning(f'Module {modname} has no backwards or forwards compatibility and might not exist in future releases.', location=node)
                modname = 'unstable_' + plainname
        return self._import_module(modname, required)

    @typed_pos_args('files', varargs=str)
    @noKwargs
    def func_files(self, node: mparser.FunctionNode, args: T.Tuple[T.List[str]], kwargs: 'TYPE_kwargs') -> T.List[mesonlib.File]:
        return [mesonlib.File.from_source_file(self.environment.source_dir, self.subdir, fname) for fname in args[0]]

    # Used by declare_dependency() and pkgconfig.generate()
    def extract_variables(self, kwargs, argname='variables', list_new=False, dict_new=False):
        variables = kwargs.get(argname, {})
        if isinstance(variables, dict):
            if dict_new and variables:
                FeatureNew.single_use('variables as dictionary', '0.56.0', self.subproject)
        else:
            varlist = mesonlib.stringlistify(variables)
            if list_new:
                FeatureNew.single_use('variables as list of strings', '0.56.0', self.subproject)
            variables = collections.OrderedDict()
            for v in varlist:
                try:
                    (key, value) = v.split('=', 1)
                except ValueError:
                    raise InterpreterException(f'Variable {v!r} must have a value separated by equals sign.')
                variables[key.strip()] = value.strip()
        for k, v in variables.items():
            if not k or not v:
                raise InterpreterException('Empty variable name or value')
            if any(c.isspace() for c in k):
                raise InterpreterException(f'Invalid whitespace in variable name "{k}"')
            if not isinstance(v, str):
                raise InterpreterException('variables values must be strings.')
        return variables

    @FeatureNewKwargs('declare_dependency', '0.46.0', ['link_whole'])
    @FeatureNewKwargs('declare_dependency', '0.54.0', ['variables'])
    @permittedKwargs({'include_directories', 'link_with', 'sources', 'dependencies',
                      'compile_args', 'link_args', 'link_whole', 'version',
                      'variables'})
    @noPosargs
    def func_declare_dependency(self, node, args, kwargs):
        version = kwargs.get('version', self.project_version)
        if not isinstance(version, str):
            raise InterpreterException('Version must be a string.')
        incs = self.extract_incdirs(kwargs)
        libs = extract_as_list(kwargs, 'link_with')
        libs_whole = extract_as_list(kwargs, 'link_whole')
        sources = extract_as_list(kwargs, 'sources')
        sources = listify(self.source_strings_to_files(sources))
        deps = extract_as_list(kwargs, 'dependencies')
        compile_args = mesonlib.stringlistify(kwargs.get('compile_args', []))
        link_args = mesonlib.stringlistify(kwargs.get('link_args', []))
        variables = self.extract_variables(kwargs, list_new=True)
        final_deps = []
        for d in deps:
            if not isinstance(d, (dependencies.Dependency, dependencies.ExternalLibrary, dependencies.InternalDependency)):
                raise InterpreterException('Dependencies must be external deps')
            final_deps.append(d)
        for l in libs:
            if isinstance(l, dependencies.Dependency):
                raise InterpreterException('''Entries in "link_with" may only be self-built targets,
external dependencies (including libraries) must go to "dependencies".''')
        dep = dependencies.InternalDependency(version, incs, compile_args,
                                              link_args, libs, libs_whole, sources, final_deps,
                                              variables)
        return dep

    @typed_pos_args('assert', bool, optargs=[str])
    @noKwargs
    def func_assert(self, node: mparser.FunctionNode, args: T.Tuple[bool, T.Optional[str]],
                    kwargs: 'TYPE_kwargs') -> None:
        value, message = args
        if message is None:
            FeatureNew.single_use('assert function without message argument', '0.53.0', self.subproject)

        if not value:
            if message is None:
                from ..ast import AstPrinter
                printer = AstPrinter()
                node.args.arguments[0].accept(printer)
                message = printer.result
            raise InterpreterException('Assert failed: ' + message)

    def validate_arguments(self, args, argcount, arg_types):
        if argcount is not None:
            if argcount != len(args):
                raise InvalidArguments(f'Expected {argcount} arguments, got {len(args)}.')
        for actual, wanted in zip(args, arg_types):
            if wanted is not None:
                if not isinstance(actual, wanted):
                    raise InvalidArguments('Incorrect argument type.')

    @FeatureNewKwargs('run_command', '0.50.0', ['env'])
    @FeatureNewKwargs('run_command', '0.47.0', ['check', 'capture'])
    @permittedKwargs({'check', 'capture', 'env'})
    def func_run_command(self, node, args, kwargs):
        return self.run_command_impl(node, args, kwargs)

    def run_command_impl(self,
                         node: mparser.BaseNode,
                         args: T.Sequence[TYPE_nvar],
                         kwargs: TYPE_nkwargs,
                         in_builddir: bool = False) -> RunProcess:
        if len(args) < 1:
            raise InterpreterException('Not enough arguments')
        cmd, *cargs = args
        capture = kwargs.get('capture', True)
        srcdir = self.environment.get_source_dir()
        builddir = self.environment.get_build_dir()

        check = kwargs.get('check')
        if check is None:
            mlog.warning(implicit_check_false_warning, once=True)
            check = False

        if not isinstance(check, bool):
            raise InterpreterException('Check must be boolean.')

        env = self.unpack_env_kwarg(kwargs)

        m = 'must be a string, or the output of find_program(), files() '\
            'or configure_file(), or a compiler object; not {!r}'
        expanded_args = []
        if isinstance(cmd, build.Executable):
            progname = node.args.arguments[0].value
            msg = 'Program {!r} was overridden with the compiled executable {!r}'\
                    ' and therefore cannot be used during configuration'
            raise InterpreterException(msg.format(progname, cmd.description()))
        if isinstance(cmd, ExternalProgram):
            if not cmd.found():
                raise InterpreterException(f'command {cmd.get_name()!r} not found or not executable')
        elif isinstance(cmd, compilers.Compiler):
            exelist = cmd.get_exelist()
            cmd = exelist[0]
            prog = ExternalProgram(cmd, silent=True)
            if not prog.found():
                raise InterpreterException(f'Program {cmd!r} not found or not executable')
            cmd = prog
            expanded_args = exelist[1:]
        else:
            if isinstance(cmd, mesonlib.File):
                cmd = cmd.absolute_path(srcdir, builddir)
            elif not isinstance(cmd, str):
                raise InterpreterException('First argument ' + m.format(cmd))
            # Prefer scripts in the current source directory
            search_dir = os.path.join(srcdir, self.subdir)
            prog = ExternalProgram(cmd, silent=True, search_dir=search_dir)
            if not prog.found():
                raise InterpreterException(f'Program or command {cmd!r} not found or not executable')
            cmd = prog
        for a in listify(cargs):
            if isinstance(a, str):
                expanded_args.append(a)
            elif isinstance(a, mesonlib.File):
                expanded_args.append(a.absolute_path(srcdir, builddir))
            elif isinstance(a, ExternalProgram):
                expanded_args.append(a.get_path())
            else:
                raise InterpreterException('Arguments ' + m.format(a))
        # If any file that was used as an argument to the command
        # changes, we must re-run the configuration step.
        self.add_build_def_file(cmd.get_path())
        for a in expanded_args:
            if not os.path.isabs(a):
                a = os.path.join(builddir if in_builddir else srcdir, self.subdir, a)
            self.add_build_def_file(a)
        return RunProcess(cmd, expanded_args, env, srcdir, builddir, self.subdir,
                          self.environment.get_build_command() + ['introspect'],
                          in_builddir=in_builddir, check=check, capture=capture)

    def func_gettext(self, nodes, args, kwargs):
        raise InterpreterException('Gettext() function has been moved to module i18n. Import it and use i18n.gettext() instead')

    def func_option(self, nodes, args, kwargs):
        raise InterpreterException('Tried to call option() in build description file. All options must be in the option file.')

    @FeatureNewKwargs('subproject', '0.38.0', ['default_options'])
    @permittedKwargs({'version', 'default_options', 'required'})
    @typed_pos_args('subproject', str)
    def func_subproject(self, nodes: mparser.BaseNode, args: T.Tuple[str], kwargs: 'TYPE_kwargs') -> SubprojectHolder:
        return self.do_subproject(args[0], 'meson', kwargs)

    def disabled_subproject(self, subp_name, disabled_feature=None, exception=None):
        sub = SubprojectHolder(NullSubprojectInterpreter(), os.path.join(self.subproject_dir, subp_name),
                               disabled_feature=disabled_feature, exception=exception)
        self.subprojects[subp_name] = sub
        self.coredata.initialized_subprojects.add(subp_name)
        return sub

    def do_subproject(self, subp_name: str, method: str, kwargs):
        disabled, required, feature = extract_required_kwarg(kwargs, self.subproject)
        if disabled:
            mlog.log('Subproject', mlog.bold(subp_name), ':', 'skipped: feature', mlog.bold(feature), 'disabled')
            return self.disabled_subproject(subp_name, disabled_feature=feature)

        default_options = mesonlib.stringlistify(kwargs.get('default_options', []))
        default_options = coredata.create_options_dict(default_options, subp_name)

        if subp_name == '':
            raise InterpreterException('Subproject name must not be empty.')
        if subp_name[0] == '.':
            raise InterpreterException('Subproject name must not start with a period.')
        if '..' in subp_name:
            raise InterpreterException('Subproject name must not contain a ".." path segment.')
        if os.path.isabs(subp_name):
            raise InterpreterException('Subproject name must not be an absolute path.')
        if has_path_sep(subp_name):
            mlog.warning('Subproject name has a path separator. This may cause unexpected behaviour.',
                         location=self.current_node)
        if subp_name in self.subproject_stack:
            fullstack = self.subproject_stack + [subp_name]
            incpath = ' => '.join(fullstack)
            raise InvalidCode(f'Recursive include of subprojects: {incpath}.')
        if subp_name in self.subprojects:
            subproject = self.subprojects[subp_name]
            if required and not subproject.found():
                raise InterpreterException(f'Subproject "{subproject.subdir}" required but not found.')
            return subproject

        r = self.environment.wrap_resolver
        try:
            subdir = r.resolve(subp_name, method)
        except wrap.WrapException as e:
            if not required:
                mlog.log(e)
                mlog.log('Subproject ', mlog.bold(subp_name), 'is buildable:', mlog.red('NO'), '(disabling)')
                return self.disabled_subproject(subp_name, exception=e)
            raise e

        subdir_abs = os.path.join(self.environment.get_source_dir(), subdir)
        os.makedirs(os.path.join(self.build.environment.get_build_dir(), subdir), exist_ok=True)
        self.global_args_frozen = True

        stack = ':'.join(self.subproject_stack + [subp_name])
        m = ['\nExecuting subproject', mlog.bold(stack)]
        if method != 'meson':
            m += ['method', mlog.bold(method)]
        mlog.log(*m, '\n', nested=False)

        try:
            if method == 'meson':
                return self._do_subproject_meson(subp_name, subdir, default_options, kwargs)
            elif method == 'cmake':
                return self._do_subproject_cmake(subp_name, subdir, subdir_abs, default_options, kwargs)
            else:
                raise mesonlib.MesonBugException(f'The method {method} is invalid for the subproject {subp_name}')
        # Invalid code is always an error
        except InvalidCode:
            raise
        except Exception as e:
            if not required:
                with mlog.nested(subp_name):
                    # Suppress the 'ERROR:' prefix because this exception is not
                    # fatal and VS CI treat any logs with "ERROR:" as fatal.
                    mlog.exception(e, prefix=mlog.yellow('Exception:'))
                mlog.log('\nSubproject', mlog.bold(subdir), 'is buildable:', mlog.red('NO'), '(disabling)')
                return self.disabled_subproject(subp_name, exception=e)
            raise e

    def _do_subproject_meson(self, subp_name: str, subdir: str, default_options, kwargs,
                             ast: T.Optional[mparser.CodeBlockNode] = None,
                             build_def_files: T.Optional[T.List[str]] = None,
                             is_translated: bool = False) -> SubprojectHolder:
        with mlog.nested(subp_name):
            new_build = self.build.copy()
            subi = Interpreter(new_build, self.backend, subp_name, subdir, self.subproject_dir,
                               default_options, ast=ast, is_translated=is_translated)
            # Those lists are shared by all interpreters. That means that
            # even if the subproject fails, any modification that the subproject
            # made to those lists will affect the parent project.
            subi.subprojects = self.subprojects
            subi.modules = self.modules
            subi.holder_map = self.holder_map
            subi.bound_holder_map = self.bound_holder_map
            subi.summary = self.summary

            subi.subproject_stack = self.subproject_stack + [subp_name]
            current_active = self.active_projectname
            current_warnings_counter = mlog.log_warnings_counter
            mlog.log_warnings_counter = 0
            subi.run()
            subi_warnings = mlog.log_warnings_counter
            mlog.log_warnings_counter = current_warnings_counter

            mlog.log('Subproject', mlog.bold(subp_name), 'finished.')

        mlog.log()

        if 'version' in kwargs:
            pv = subi.project_version
            wanted = kwargs['version']
            if pv == 'undefined' or not mesonlib.version_compare_many(pv, wanted)[0]:
                raise InterpreterException(f'Subproject {subp_name} version is {pv} but {wanted} required.')
        self.active_projectname = current_active
        self.subprojects.update(subi.subprojects)
        self.subprojects[subp_name] = SubprojectHolder(subi, subdir, warnings=subi_warnings)
        # Duplicates are possible when subproject uses files from project root
        if build_def_files:
            self.build_def_files = list(set(self.build_def_files + build_def_files))
        # We always need the subi.build_def_files, to propgate sub-sub-projects
        self.build_def_files = list(set(self.build_def_files + subi.build_def_files))
        self.build.merge(subi.build)
        self.build.subprojects[subp_name] = subi.project_version
        self.coredata.initialized_subprojects.add(subp_name)
        return self.subprojects[subp_name]

    def _do_subproject_cmake(self, subp_name, subdir, subdir_abs, default_options, kwargs):
        with mlog.nested(subp_name):
            new_build = self.build.copy()
            prefix = self.coredata.options[OptionKey('prefix')].value

            from ..modules.cmake import CMakeSubprojectOptions
            options = kwargs.get('options', CMakeSubprojectOptions())
            if not isinstance(options, CMakeSubprojectOptions):
                raise InterpreterException('"options" kwarg must be CMakeSubprojectOptions'
                                           ' object (created by cmake.subproject_options())')

            cmake_options = mesonlib.stringlistify(kwargs.get('cmake_options', []))
            cmake_options += options.cmake_options
            cm_int = CMakeInterpreter(new_build, Path(subdir), Path(subdir_abs), Path(prefix), new_build.environment, self.backend)
            cm_int.initialise(cmake_options)
            cm_int.analyse()

            # Generate a meson ast and execute it with the normal do_subproject_meson
            ast = cm_int.pretend_to_be_meson(options.target_options)

            mlog.log()
            with mlog.nested('cmake-ast'):
                mlog.log('Processing generated meson AST')

                # Debug print the generated meson file
                from ..ast import AstIndentationGenerator, AstPrinter
                printer = AstPrinter()
                ast.accept(AstIndentationGenerator())
                ast.accept(printer)
                printer.post_process()
                meson_filename = os.path.join(self.build.environment.get_build_dir(), subdir, 'meson.build')
                with open(meson_filename, "w", encoding='utf-8') as f:
                    f.write(printer.result)

                mlog.log('Build file:', meson_filename)
                mlog.cmd_ci_include(meson_filename)
                mlog.log()

            result = self._do_subproject_meson(subp_name, subdir, default_options, kwargs, ast, cm_int.bs_files, is_translated=True)
            result.cm_interpreter = cm_int

        mlog.log()
        return result

    def get_option_internal(self, optname: str):
        key = OptionKey.from_string(optname).evolve(subproject=self.subproject)

        if not key.is_project():
            for opts in [self.coredata.options, compilers.base_options]:
                v = opts.get(key)
                if v is None or v.yielding:
                    v = opts.get(key.as_root())
                if v is not None:
                    return v

        try:
            opt = self.coredata.options[key]
            if opt.yielding and key.subproject and key.as_root() in self.coredata.options:
                popt = self.coredata.options[key.as_root()]
                if type(opt) is type(popt):
                    opt = popt
                else:
                    # Get class name, then option type as a string
                    opt_type = opt.__class__.__name__[4:][:-6].lower()
                    popt_type = popt.__class__.__name__[4:][:-6].lower()
                    # This is not a hard error to avoid dependency hell, the workaround
                    # when this happens is to simply set the subproject's option directly.
                    mlog.warning('Option {0!r} of type {1!r} in subproject {2!r} cannot yield '
                                 'to parent option of type {3!r}, ignoring parent value. '
                                 'Use -D{2}:{0}=value to set the value for this option manually'
                                 '.'.format(optname, opt_type, self.subproject, popt_type),
                                 location=self.current_node)
            return opt
        except KeyError:
            pass

        raise InterpreterException(f'Tried to access unknown option {optname!r}.')

    @typed_pos_args('get_option', str)
    @noKwargs
    def func_get_option(self, nodes: mparser.BaseNode, args: T.Tuple[str],
                        kwargs: 'TYPE_kwargs') -> T.Union[coredata.UserOption, 'TYPE_var']:
        optname = args[0]
        if ':' in optname:
            raise InterpreterException('Having a colon in option name is forbidden, '
                                       'projects are not allowed to directly access '
                                       'options of other subprojects.')
        opt = self.get_option_internal(optname)
        if isinstance(opt, coredata.UserFeatureOption):
            opt.name = optname
            return opt
        elif isinstance(opt, coredata.UserOption):
            return opt.value
        return opt

    @typed_pos_args('configuration_data', optargs=[dict])
    @noKwargs
    def func_configuration_data(self, node: mparser.BaseNode, args: T.Optional[dict], kwargs: 'TYPE_kwargs') -> ConfigurationDataObject:
        initial_values = args[0]
        if initial_values is not None:
            FeatureNew.single_use('configuration_data dictionary', '0.49.0', self.subproject)
        else:
            initial_values = {}
        return ConfigurationDataObject(self.subproject, initial_values)

    def set_backend(self):
        # The backend is already set when parsing subprojects
        if self.backend is not None:
            return
        backend = self.coredata.get_option(OptionKey('backend'))
        from ..backend import backends
        self.backend = backends.get_backend_from_name(backend, self.build, self)

        if self.backend is None:
            raise InterpreterException(f'Unknown backend "{backend}".')
        if backend != self.backend.name:
            if self.backend.name.startswith('vs'):
                mlog.log('Auto detected Visual Studio backend:', mlog.bold(self.backend.name))
            self.coredata.set_option(OptionKey('backend'), self.backend.name)

        # Only init backend options on first invocation otherwise it would
        # override values previously set from command line.
        if self.environment.first_invocation:
            self.coredata.init_backend_options(backend)

        options = {k: v for k, v in self.environment.options.items() if k.is_backend()}
        self.coredata.set_options(options)

    @permittedKwargs({'version', 'meson_version', 'default_options', 'license', 'subproject_dir'})
    @typed_pos_args('project', str, varargs=str)
    def func_project(self, node: mparser.FunctionNode, args: T.Tuple[str, T.List[str]], kwargs: 'TYPE_kwargs') -> None:
        proj_name, proj_langs = args
        if ':' in proj_name:
            raise InvalidArguments(f"Project name {proj_name!r} must not contain ':'")

        # This needs to be evaluated as early as possible, as meson uses this
        # for things like deprecation testing.
        if 'meson_version' in kwargs:
            cv = coredata.version
            pv = kwargs['meson_version']
            if not mesonlib.version_compare(cv, pv):
                raise InterpreterException(f'Meson version is {cv} but project requires {pv}')
            mesonlib.project_meson_versions[self.subproject] = kwargs['meson_version']

        if os.path.exists(self.option_file):
            oi = optinterpreter.OptionInterpreter(self.subproject)
            oi.process(self.option_file)
            self.coredata.update_project_options(oi.options)
            self.add_build_def_file(self.option_file)

        # Do not set default_options on reconfigure otherwise it would override
        # values previously set from command line. That means that changing
        # default_options in a project will trigger a reconfigure but won't
        # have any effect.
        self.project_default_options = mesonlib.stringlistify(kwargs.get('default_options', []))
        self.project_default_options = coredata.create_options_dict(self.project_default_options, self.subproject)

        # If this is the first invocation we always need to initialize
        # builtins, if this is a subproject that is new in a re-invocation we
        # need to initialize builtins for that
        if self.environment.first_invocation or (self.subproject != '' and self.subproject not in self.coredata.initialized_subprojects):
            default_options = self.project_default_options.copy()
            default_options.update(self.default_project_options)
            self.coredata.init_builtins(self.subproject)
        else:
            default_options = {}
        self.coredata.set_default_options(default_options, self.subproject, self.environment)

        if not self.is_subproject():
            self.build.project_name = proj_name
        self.active_projectname = proj_name
        version = kwargs.get('version', 'undefined')
        if isinstance(version, list):
            if len(version) != 1:
                raise InvalidCode('Version argument is an array with more than one entry.')
            version = version[0]
        if isinstance(version, mesonlib.File):
            FeatureNew.single_use('version from file', '0.57.0', self.subproject)
            self.add_build_def_file(version)
            ifname = version.absolute_path(self.environment.source_dir,
                                           self.environment.build_dir)
            try:
                ver_data = Path(ifname).read_text(encoding='utf-8').split('\n')
            except FileNotFoundError:
                raise InterpreterException('Version file not found.')
            if len(ver_data) == 2 and ver_data[1] == '':
                ver_data = ver_data[0:1]
            if len(ver_data) != 1:
                raise InterpreterException('Version file must contain exactly one line of text.')
            self.project_version = ver_data[0]
        elif isinstance(version, str):
            self.project_version = version
        else:
            raise InvalidCode('The version keyword argument must be a string or a file.')
        if self.build.project_version is None:
            self.build.project_version = self.project_version
        proj_license = mesonlib.stringlistify(kwargs.get('license', 'unknown'))
        self.build.dep_manifest[proj_name] = build.DepManifest(self.project_version, proj_license)
        if self.subproject in self.build.projects:
            raise InvalidCode('Second call to project().')

        # spdirname is the subproject_dir for this project, relative to self.subdir.
        # self.subproject_dir is the subproject_dir for the main project, relative to top source dir.
        spdirname = kwargs.get('subproject_dir')
        if spdirname:
            if not isinstance(spdirname, str):
                raise InterpreterException('Subproject_dir must be a string')
            if os.path.isabs(spdirname):
                raise InterpreterException('Subproject_dir must not be an absolute path.')
            if spdirname.startswith('.'):
                raise InterpreterException('Subproject_dir must not begin with a period.')
            if '..' in spdirname:
                raise InterpreterException('Subproject_dir must not contain a ".." segment.')
            if not self.is_subproject():
                self.subproject_dir = spdirname
        else:
            spdirname = 'subprojects'
        self.build.subproject_dir = self.subproject_dir

        # Load wrap files from this (sub)project.
        wrap_mode = self.coredata.get_option(OptionKey('wrap_mode'))
        if not self.is_subproject() or wrap_mode != WrapMode.nopromote:
            subdir = os.path.join(self.subdir, spdirname)
            r = wrap.Resolver(self.environment.get_source_dir(), subdir, self.subproject, wrap_mode)
            if self.is_subproject():
                self.environment.wrap_resolver.merge_wraps(r)
            else:
                self.environment.wrap_resolver = r

        self.build.projects[self.subproject] = proj_name
        mlog.log('Project name:', mlog.bold(proj_name))
        mlog.log('Project version:', mlog.bold(self.project_version))

        if not self.is_subproject():
            # We have to activate VS before adding languages and before calling
            # self.set_backend() otherwise it wouldn't be able to detect which
            # vs backend version we need. But after setting default_options in case
            # the project sets vs backend by default.
            backend = self.coredata.get_option(OptionKey('backend'))
            force_vsenv = self.user_defined_options.vsenv or backend.startswith('vs')
            if mesonlib.setup_vsenv(force_vsenv):
                self.build.need_vsenv = True

        self.add_languages(proj_langs, True, MachineChoice.HOST)
        self.add_languages(proj_langs, False, MachineChoice.BUILD)

        self.set_backend()
        if not self.is_subproject():
            self.check_stdlibs()

    @typed_kwargs('add_languages', KwargInfo('native', (bool, NoneType), since='0.54.0'), REQUIRED_KW)
    @typed_pos_args('add_languages', varargs=str)
    def func_add_languages(self, node: mparser.FunctionNode, args: T.Tuple[T.List[str]], kwargs: 'kwargs.FuncAddLanguages') -> bool:
        langs = args[0]
        disabled, required, feature = extract_required_kwarg(kwargs, self.subproject)
        native = kwargs['native']

        if disabled:
            for lang in sorted(langs, key=compilers.sort_clink):
                mlog.log('Compiler for language', mlog.bold(lang), 'skipped: feature', mlog.bold(feature), 'disabled')
            return False
        if native is not None:
            return self.add_languages(langs, required, self.machine_from_native_kwarg(kwargs))
        else:
            # absent 'native' means 'both' for backwards compatibility
            tv = FeatureNew.get_target_version(self.subproject)
            if FeatureNew.check_version(tv, '0.54.0'):
                mlog.warning('add_languages is missing native:, assuming languages are wanted for both host and build.',
                             location=self.current_node)

            success = self.add_languages(langs, False, MachineChoice.BUILD)
            success &= self.add_languages(langs, required, MachineChoice.HOST)
            return success

    @noArgsFlattening
    @noKwargs
    def func_message(self, node, args, kwargs):
        if len(args) > 1:
            FeatureNew.single_use('message with more than one argument', '0.54.0', self.subproject)
        args_str = [stringifyUserArguments(i) for i in args]
        self.message_impl(args_str)

    def message_impl(self, args):
        mlog.log(mlog.bold('Message:'), *args)

    @noArgsFlattening
    @FeatureNewKwargs('summary', '0.54.0', ['list_sep'])
    @permittedKwargs({'section', 'bool_yn', 'list_sep'})
    @FeatureNew('summary', '0.53.0')
    def func_summary(self, node, args, kwargs):
        if len(args) == 1:
            if not isinstance(args[0], dict):
                raise InterpreterException('Summary first argument must be dictionary.')
            values = args[0]
        elif len(args) == 2:
            if not isinstance(args[0], str):
                raise InterpreterException('Summary first argument must be string.')
            values = {args[0]: args[1]}
        else:
            raise InterpreterException('Summary accepts at most 2 arguments.')
        section = kwargs.get('section', '')
        if not isinstance(section, str):
            raise InterpreterException('Summary\'s section keyword argument must be string.')
        self.summary_impl(section, values, kwargs)

    def summary_impl(self, section, values, kwargs):
        if self.subproject not in self.summary:
            self.summary[self.subproject] = Summary(self.active_projectname, self.project_version)
        self.summary[self.subproject].add_section(section, values, kwargs, self.subproject)

    def _print_summary(self):
        # Add automatic 'Supbrojects' section in main project.
        all_subprojects = collections.OrderedDict()
        for name, subp in sorted(self.subprojects.items()):
            value = subp.found()
            if subp.disabled_feature:
                value = [value, f'Feature {subp.disabled_feature!r} disabled']
            elif subp.exception:
                value = [value, str(subp.exception)]
            elif subp.warnings > 0:
                value = [value, f'{subp.warnings} warnings']
            all_subprojects[name] = value
        if all_subprojects:
            self.summary_impl('Subprojects', all_subprojects,
                              {'bool_yn': True,
                               'list_sep': ' ',
                              })
        # Add automatic section with all user defined options
        if self.user_defined_options:
            values = collections.OrderedDict()
            if self.user_defined_options.cross_file:
                values['Cross files'] = self.user_defined_options.cross_file
            if self.user_defined_options.native_file:
                values['Native files'] = self.user_defined_options.native_file
            sorted_options = sorted(self.user_defined_options.cmd_line_options.items())
            values.update({str(k): v for k, v in sorted_options})
            if values:
                self.summary_impl('User defined options', values, {})
        # Print all summaries, main project last.
        mlog.log('')  # newline
        main_summary = self.summary.pop('', None)
        for subp_name, summary in sorted(self.summary.items()):
            if self.subprojects[subp_name].found():
                summary.dump()
        if main_summary:
            main_summary.dump()

    @noArgsFlattening
    @FeatureNew('warning', '0.44.0')
    @noKwargs
    def func_warning(self, node, args, kwargs):
        if len(args) > 1:
            FeatureNew.single_use('warning with more than one argument', '0.54.0', self.subproject)
        args_str = [stringifyUserArguments(i) for i in args]
        mlog.warning(*args_str, location=node)

    @noArgsFlattening
    @noKwargs
    def func_error(self, node, args, kwargs):
        if len(args) > 1:
            FeatureNew.single_use('error with more than one argument', '0.58.0', self.subproject)
        args_str = [stringifyUserArguments(i) for i in args]
        raise InterpreterException('Problem encountered: ' + ' '.join(args_str))

    @noKwargs
    @noPosargs
    def func_exception(self, node, args, kwargs):
        raise Exception()

    def add_languages(self, args: T.Sequence[str], required: bool, for_machine: MachineChoice) -> bool:
        success = self.add_languages_for(args, required, for_machine)
        if not self.coredata.is_cross_build():
            self.coredata.copy_build_options_from_regular_ones()
        self._redetect_machines()
        return success

    def should_skip_sanity_check(self, for_machine: MachineChoice) -> bool:
        should = self.environment.properties.host.get('skip_sanity_check', False)
        if not isinstance(should, bool):
            raise InterpreterException('Option skip_sanity_check must be a boolean.')
        if for_machine != MachineChoice.HOST and not should:
            return False
        if not self.environment.is_cross_build() and not should:
            return False
        return should

    def add_languages_for(self, args: T.List[str], required: bool, for_machine: MachineChoice) -> None:
        args = [a.lower() for a in args]
        langs = set(self.coredata.compilers[for_machine].keys())
        langs.update(args)
        # We'd really like to add cython's default language here, but it can't
        # actually be done because the cython compiler hasn't been initialized,
        # so we can't actually get the option yet. Because we can't know what
        # compiler to add by default, and we don't want to add unnecessary
        # compilers we don't add anything for cython here, and instead do it
        # When the first cython target using a particular language is used.
        if 'vala' in langs and 'c' not in langs:
            FeatureNew.single_use('Adding Vala language without C', '0.59.0', self.subproject)
            args.append('c')

        success = True
        for lang in sorted(args, key=compilers.sort_clink):
            clist = self.coredata.compilers[for_machine]
            machine_name = for_machine.get_lower_case_name()
            if lang in clist:
                comp = clist[lang]
            else:
                try:
                    comp = compilers.detect_compiler_for(self.environment, lang, for_machine)
                    if comp is None:
                        raise InvalidArguments(f'Tried to use unknown language "{lang}".')
                    if self.should_skip_sanity_check(for_machine):
                        mlog.log_once('Cross compiler sanity tests disabled via the cross file.')
                    else:
                        comp.sanity_check(self.environment.get_scratch_dir(), self.environment)
                except Exception:
                    if not required:
                        mlog.log('Compiler for language',
                                 mlog.bold(lang), 'for the', machine_name,
                                 'machine not found.')
                        success = False
                        continue
                    else:
                        raise

            if for_machine == MachineChoice.HOST or self.environment.is_cross_build():
                logger_fun = mlog.log
            else:
                logger_fun = mlog.debug
            logger_fun(comp.get_display_language(), 'compiler for the', machine_name, 'machine:',
                       mlog.bold(' '.join(comp.get_exelist())), comp.get_version_string())
            if comp.linker is not None:
                logger_fun(comp.get_display_language(), 'linker for the', machine_name, 'machine:',
                           mlog.bold(' '.join(comp.linker.get_exelist())), comp.linker.id, comp.linker.version)
            self.build.ensure_static_linker(comp)

        return success

    def program_from_file_for(self, for_machine, prognames):
        for p in prognames:
            if isinstance(p, mesonlib.File):
                continue # Always points to a local (i.e. self generated) file.
            if not isinstance(p, str):
                raise InterpreterException('Executable name must be a string')
            prog = ExternalProgram.from_bin_list(self.environment, for_machine, p)
            if prog.found():
                return prog
        return None

    def program_from_system(self, args, search_dirs, extra_info):
        # Search for scripts relative to current subdir.
        # Do not cache found programs because find_program('foobar')
        # might give different results when run from different source dirs.
        source_dir = os.path.join(self.environment.get_source_dir(), self.subdir)
        for exename in args:
            if isinstance(exename, mesonlib.File):
                if exename.is_built:
                    search_dir = os.path.join(self.environment.get_build_dir(),
                                              exename.subdir)
                else:
                    search_dir = os.path.join(self.environment.get_source_dir(),
                                              exename.subdir)
                exename = exename.fname
                extra_search_dirs = []
            elif isinstance(exename, str):
                search_dir = source_dir
                extra_search_dirs = search_dirs
            else:
                raise InvalidArguments(f'find_program only accepts strings and files, not {exename!r}')
            extprog = ExternalProgram(exename, search_dir=search_dir,
                                      extra_search_dirs=extra_search_dirs,
                                      silent=True)
            if extprog.found():
                extra_info.append(f"({' '.join(extprog.get_command())})")
                return extprog

    def program_from_overrides(self, command_names: T.List[str], extra_info: T.List['mlog.TV_Loggable']) -> \
            T.Optional[T.Union[ExternalProgram, 'OverrideProgram', 'build.Executable']]:
        for name in command_names:
            if not isinstance(name, str):
                continue
            if name in self.build.find_overrides:
                exe = self.build.find_overrides[name]
                extra_info.append(mlog.blue('(overridden)'))
                return exe
        return None

    def store_name_lookups(self, command_names):
        for name in command_names:
            if isinstance(name, str):
                self.build.searched_programs.add(name)

    def add_find_program_override(self, name: str, exe: T.Union[build.Executable, ExternalProgram, 'OverrideProgram']) -> None:
        if name in self.build.searched_programs:
            raise InterpreterException(f'Tried to override finding of executable "{name}" which has already been found.')
        if name in self.build.find_overrides:
            raise InterpreterException(f'Tried to override executable "{name}" which has already been overridden.')
        self.build.find_overrides[name] = exe

    def notfound_program(self, args):
        return NonExistingExternalProgram(' '.join(args))

    # TODO update modules to always pass `for_machine`. It is bad-form to assume
    # the host machine.
    def find_program_impl(self, args, for_machine: MachineChoice = MachineChoice.HOST,
                          required=True, silent=True, wanted='', search_dirs=None,
                          version_func=None):
        args = mesonlib.listify(args)

        extra_info = []
        progobj = self.program_lookup(args, for_machine, required, search_dirs, extra_info)
        if progobj is None:
            progobj = self.notfound_program(args)

        if isinstance(progobj, ExternalProgram) and not progobj.found():
            mlog.log('Program', mlog.bold(progobj.get_name()), 'found:', mlog.red('NO'))
            if required:
                m = 'Program {!r} not found'
                raise InterpreterException(m.format(progobj.get_name()))
            return progobj

        if wanted:
            if version_func:
                version = version_func(progobj)
            elif isinstance(progobj, build.Executable):
                interp = self
                if progobj.subproject:
                    interp = self.subprojects[progobj.subproject].held_object
                    assert isinstance(interp, Interpreter)
                version = interp.project_version
            elif isinstance(progobj, ExternalProgram):
                version = progobj.get_version(self)
            is_found, not_found, found = mesonlib.version_compare_many(version, wanted)
            if not is_found:
                mlog.log('Program', mlog.bold(progobj.name), 'found:', mlog.red('NO'),
                         'found', mlog.normal_cyan(version), 'but need:',
                         mlog.bold(', '.join([f"'{e}'" for e in not_found])), *extra_info)
                if required:
                    m = 'Invalid version of program, need {!r} {!r} found {!r}.'
                    raise InterpreterException(m.format(progobj.name, not_found, version))
                return self.notfound_program(args)
            extra_info.insert(0, mlog.normal_cyan(version))

        # Only store successful lookups
        self.store_name_lookups(args)
        mlog.log('Program', mlog.bold(progobj.name), 'found:', mlog.green('YES'), *extra_info)
        if isinstance(progobj, build.Executable):
            progobj.was_returned_by_find_program = True
        return progobj

    def program_lookup(self, args, for_machine, required, search_dirs, extra_info):
        progobj = self.program_from_overrides(args, extra_info)
        if progobj:
            return progobj

        fallback = None
        wrap_mode = self.coredata.get_option(OptionKey('wrap_mode'))
        if wrap_mode != WrapMode.nofallback and self.environment.wrap_resolver:
            fallback = self.environment.wrap_resolver.find_program_provider(args)
        if fallback and wrap_mode == WrapMode.forcefallback:
            return self.find_program_fallback(fallback, args, required, extra_info)

        progobj = self.program_from_file_for(for_machine, args)
        if progobj is None:
            progobj = self.program_from_system(args, search_dirs, extra_info)
        if progobj is None and args[0].endswith('python3'):
            prog = ExternalProgram('python3', mesonlib.python_command, silent=True)
            progobj = prog if prog.found() else None
        if progobj is None and fallback and required:
            progobj = self.find_program_fallback(fallback, args, required, extra_info)

        return progobj

    def find_program_fallback(self, fallback, args, required, extra_info):
        mlog.log('Fallback to subproject', mlog.bold(fallback), 'which provides program',
                 mlog.bold(' '.join(args)))
        sp_kwargs = {'required': required}
        self.do_subproject(fallback, 'meson', sp_kwargs)
        return self.program_from_overrides(args, extra_info)

    @FeatureNewKwargs('find_program', '0.53.0', ['dirs'])
    @FeatureNewKwargs('find_program', '0.52.0', ['version'])
    @FeatureNewKwargs('find_program', '0.49.0', ['disabler'])
    @disablerIfNotFound
    @permittedKwargs({'required', 'native', 'version', 'dirs'})
    def func_find_program(self, node, args, kwargs) -> T.Union['build.Executable', ExternalProgram, 'OverrideProgram']:
        if not args:
            raise InterpreterException('No program name specified.')

        disabled, required, feature = extract_required_kwarg(kwargs, self.subproject)
        if disabled:
            mlog.log('Program', mlog.bold(' '.join(args)), 'skipped: feature', mlog.bold(feature), 'disabled')
            return self.notfound_program(args)

        search_dirs = extract_search_dirs(kwargs)
        wanted = mesonlib.stringlistify(kwargs.get('version', []))
        for_machine = self.machine_from_native_kwarg(kwargs)
        return self.find_program_impl(args, for_machine, required=required,
                                      silent=False, wanted=wanted,
                                      search_dirs=search_dirs)

    def func_find_library(self, node, args, kwargs):
        raise InvalidCode('find_library() is removed, use meson.get_compiler(\'name\').find_library() instead.\n'
                          'Look here for documentation: http://mesonbuild.com/Reference-manual.html#compiler-object\n'
                          'Look here for example: http://mesonbuild.com/howtox.html#add-math-library-lm-portably\n'
                          )

    # When adding kwargs, please check if they make sense in dependencies.get_dep_identifier()
    @FeatureNewKwargs('dependency', '0.57.0', ['cmake_package_version'])
    @FeatureNewKwargs('dependency', '0.56.0', ['allow_fallback'])
    @FeatureNewKwargs('dependency', '0.54.0', ['components'])
    @FeatureNewKwargs('dependency', '0.52.0', ['include_type'])
    @FeatureNewKwargs('dependency', '0.50.0', ['not_found_message', 'cmake_module_path', 'cmake_args'])
    @FeatureNewKwargs('dependency', '0.49.0', ['disabler'])
    @FeatureNewKwargs('dependency', '0.40.0', ['method'])
    @FeatureNewKwargs('dependency', '0.38.0', ['default_options'])
    @disablerIfNotFound
    @permittedKwargs(permitted_dependency_kwargs)
    @typed_pos_args('dependency', varargs=str, min_varargs=1)
    def func_dependency(self, node, args, kwargs):
        # Replace '' by empty list of names
        names = [n for n in args[0] if n]
        if len(names) > 1:
            FeatureNew('dependency with more than one name', '0.60.0').use(self.subproject)
        allow_fallback = kwargs.get('allow_fallback')
        if allow_fallback is not None and not isinstance(allow_fallback, bool):
            raise InvalidArguments('"allow_fallback" argument must be boolean')
        fallback = kwargs.get('fallback')
        default_options = kwargs.get('default_options')
        df = DependencyFallbacksHolder(self, names, allow_fallback, default_options)
        df.set_fallback(fallback)
        not_found_message = kwargs.get('not_found_message', '')
        if not isinstance(not_found_message, str):
            raise InvalidArguments('The not_found_message must be a string.')
        try:
            d = df.lookup(kwargs)
        except Exception:
            if not_found_message:
                self.message_impl([not_found_message])
            raise
        assert isinstance(d, Dependency)
        if not d.found() and not_found_message:
            self.message_impl([not_found_message])
            self.message_impl([not_found_message])
        # Ensure the correct include type
        if 'include_type' in kwargs:
            wanted = kwargs['include_type']
            if not isinstance(wanted, str):
                raise InvalidArguments('The `include_type` kwarg must be a string')
            actual = d.get_include_type()
            if wanted != actual:
                mlog.debug(f'Current include type of {args[0]} is {actual}. Converting to requested {wanted}')
                d = d.generate_system_dependency(wanted)
        return d

    @FeatureNew('disabler', '0.44.0')
    @noKwargs
    @noPosargs
    def func_disabler(self, node, args, kwargs):
        return Disabler()

    @FeatureNewKwargs('executable', '0.42.0', ['implib'])
    @FeatureNewKwargs('executable', '0.56.0', ['win_subsystem'])
    @FeatureDeprecatedKwargs('executable', '0.56.0', ['gui_app'], extra_message="Use 'win_subsystem' instead.")
    @permittedKwargs(build.known_exe_kwargs)
    def func_executable(self, node, args, kwargs):
        return self.build_target(node, args, kwargs, build.Executable)

    # TODO: adjust to release
    @FeatureNew('compiled_objects', '0.61.0')
    @permittedKwargs(build.known_objs_kwargs)
    def func_compiled_objects(self, node, args, kwargs):
        return self.build_target(node, args, kwargs, build.CompiledObjects)

    @permittedKwargs(build.known_stlib_kwargs)
    def func_static_lib(self, node, args, kwargs):
        return self.build_target(node, args, kwargs, build.StaticLibrary)

    @permittedKwargs(build.known_shlib_kwargs)
    def func_shared_lib(self, node, args, kwargs):
        holder = self.build_target(node, args, kwargs, build.SharedLibrary)
        holder.shared_library_only = True
        return holder

    @permittedKwargs(known_library_kwargs)
    def func_both_lib(self, node, args, kwargs):
        return self.build_both_libraries(node, args, kwargs)

    @FeatureNew('shared_module', '0.37.0')
    @permittedKwargs(build.known_shmod_kwargs)
    def func_shared_module(self, node, args, kwargs):
        return self.build_target(node, args, kwargs, build.SharedModule)

    @permittedKwargs(known_library_kwargs)
    def func_library(self, node, args, kwargs):
        return self.build_library(node, args, kwargs)

    @permittedKwargs(build.known_jar_kwargs)
    def func_jar(self, node, args, kwargs):
        return self.build_target(node, args, kwargs, build.Jar)

    @FeatureNewKwargs('build_target', '0.40.0', ['link_whole', 'override_options'])
    @permittedKwargs(known_build_target_kwargs)
    def func_build_target(self, node, args, kwargs):
        if 'target_type' not in kwargs:
            raise InterpreterException('Missing target_type keyword argument')
        target_type = kwargs.pop('target_type')
        if target_type == 'executable':
            return self.build_target(node, args, kwargs, build.Executable)
        elif target_type == 'objects':
            # TODO: adjust to release
            FeatureNew.single_use('build_target(target_type: \'objects\')',
                   '0.61.0', self.subproject)
            return self.build_target(node, args, kwargs, build.CompiledObjects)
        elif target_type == 'shared_library':
            return self.build_target(node, args, kwargs, build.SharedLibrary)
        elif target_type == 'shared_module':
            FeatureNew.single_use('build_target(target_type: \'shared_module\')',
                       '0.51.0', self.subproject)
            return self.build_target(node, args, kwargs, build.SharedModule)
        elif target_type == 'static_library':
            return self.build_target(node, args, kwargs, build.StaticLibrary)
        elif target_type == 'both_libraries':
            return self.build_both_libraries(node, args, kwargs)
        elif target_type == 'library':
            return self.build_library(node, args, kwargs)
        elif target_type == 'jar':
            return self.build_target(node, args, kwargs, build.Jar)
        else:
            raise InterpreterException('Unknown target_type.')

    @permittedKwargs({'input', 'output', 'fallback', 'command', 'replace_string'})
    @FeatureDeprecatedKwargs('custom_target', '0.47.0', ['build_always'],
                             'combine build_by_default and build_always_stale instead.')
    @noPosargs
    def func_vcs_tag(self, node, args, kwargs):
        if 'input' not in kwargs or 'output' not in kwargs:
            raise InterpreterException('Keyword arguments input and output must exist')
        if 'fallback' not in kwargs:
            FeatureNew.single_use('Optional fallback in vcs_tag', '0.41.0', self.subproject)
        fallback = kwargs.pop('fallback', self.project_version)
        if not isinstance(fallback, str):
            raise InterpreterException('Keyword argument fallback must be a string.')
        replace_string = kwargs.pop('replace_string', '@VCS_TAG@')
        regex_selector = '(.*)' # default regex selector for custom command: use complete output
        vcs_cmd = kwargs.get('command', None)
        if vcs_cmd and not isinstance(vcs_cmd, list):
            vcs_cmd = [vcs_cmd]
        source_dir = os.path.normpath(os.path.join(self.environment.get_source_dir(), self.subdir))
        if vcs_cmd:
            # Is the command an executable in path or maybe a script in the source tree?
            vcs_cmd[0] = shutil.which(vcs_cmd[0]) or os.path.join(source_dir, vcs_cmd[0])
        else:
            vcs = mesonlib.detect_vcs(source_dir)
            if vcs:
                mlog.log('Found {} repository at {}'.format(vcs['name'], vcs['wc_dir']))
                vcs_cmd = vcs['get_rev'].split()
                regex_selector = vcs['rev_regex']
            else:
                vcs_cmd = [' '] # executing this cmd will fail in vcstagger.py and force to use the fallback string
        # vcstagger.py parameters: infile, outfile, fallback, source_dir, replace_string, regex_selector, command...
        kwargs['command'] = self.environment.get_build_command() + \
            ['--internal',
             'vcstagger',
             '@INPUT0@',
             '@OUTPUT0@',
             fallback,
             source_dir,
             replace_string,
             regex_selector] + vcs_cmd
        kwargs.setdefault('build_by_default', True)
        kwargs.setdefault('build_always_stale', True)
        return self._func_custom_target_impl(node, [kwargs['output']], kwargs)

    @FeatureNew('subdir_done', '0.46.0')
    @noPosargs
    @noKwargs
    def func_subdir_done(self, node, args, kwargs):
        raise SubdirDoneRequest()

    @typed_pos_args('custom_target', optargs=[str])
    @typed_kwargs(
        'custom_target',
        COMMAND_KW,
        CT_BUILD_BY_DEFAULT,
        CT_INPUT_KW,
        CT_INSTALL_DIR_KW,
        CT_INSTALL_TAG_KW,
        CT_OUTPUT_KW,
        DEPENDS_KW,
        DEPEND_FILES_KW,
        DEPFILE_KW,
        ENV_KW.evolve(since='0.57.0'),
        INSTALL_KW,
        INSTALL_MODE_KW.evolve(since='0.47.0'),
        OVERRIDE_OPTIONS_KW,
        KwargInfo('build_always', (bool, type(None)), deprecated='0.47.0'),
        KwargInfo('build_always_stale', (bool, type(None)), since='0.47.0'),
        KwargInfo('feed', bool, default=False, since='0.59.0'),
        KwargInfo('capture', bool, default=False),
        KwargInfo('console', bool, default=False, since='0.48.0'),
    )
    def func_custom_target(self, node: mparser.FunctionNode, args: T.Tuple[str],
                           kwargs: 'kwargs.CustomTarget') -> build.CustomTarget:
        if kwargs['depfile'] and ('@BASENAME@' in kwargs['depfile'] or '@PLAINNAME@' in kwargs['depfile']):
            FeatureNew.single_use('substitutions in custom_target depfile', '0.47.0', self.subproject)

        # Don't mutate the kwargs
        kwargs = kwargs.copy()

        # Remap build_always to build_by_default and build_always_stale
        if kwargs['build_always'] is not None and kwargs['build_always_stale'] is not None:
            raise InterpreterException('CustomTarget: "build_always" and "build_always_stale" are mutually exclusive')

        if kwargs['build_by_default'] is None and kwargs['install']:
            kwargs['build_by_default'] = True

        elif kwargs['build_always'] is not None:
            if kwargs['build_by_default'] is None:
                kwargs['build_by_default'] = kwargs['build_always']
            kwargs['build_always_stale'] = kwargs['build_by_default']

            # Set this to None to satisfy process_kwargs
            kwargs['build_always'] = None

        # These are are nullaable so that we can know whether they're explicitly
        # set or not. If they haven't been overwritten, set them to their true
        # default
        if kwargs['build_by_default'] is None:
            kwargs['build_by_default'] = False
        if kwargs['build_always_stale'] is None:
            kwargs['build_always_stale'] = False

        return self._func_custom_target_impl(node, args, kwargs)

    def _func_custom_target_impl(self, node, args, kwargs):
        'Implementation-only, without FeatureNew checks, for internal use'
        name = args[0]
        if name is None:
            # name will default to first output, but we cannot do that yet because
            # they could need substitutions (e.g. @BASENAME@) first. CustomTarget()
            # will take care of setting a proper default but name must be an empty
            # string in the meantime.
            FeatureNew('custom_target() with no name argument', '0.60.0', location=node).use(self.subproject)
            name = ''
        kwargs['install_mode'] = self._get_kwarg_install_mode(kwargs)
        if 'input' in kwargs:
            try:
                kwargs['input'] = self.source_strings_to_files(extract_as_list(kwargs, 'input'))
            except mesonlib.MesonException:
                mlog.warning(f'''Custom target input '{kwargs['input']}' can't be converted to File object(s).
This will become a hard error in the future.''', location=self.current_node)
        kwargs['env'] = self.unpack_env_kwarg(kwargs)
        if 'command' in kwargs and isinstance(kwargs['command'], list) and kwargs['command']:
            if isinstance(kwargs['command'][0], str):
                kwargs['command'][0] = self.func_find_program(node, kwargs['command'][0], {})
        tg = build.CustomTarget(name, self.subdir, self.subproject, kwargs, backend=self.backend)
        self.add_target(tg.name, tg)
        return tg

    @typed_pos_args('run_target', str)
    @typed_kwargs(
        'run_target',
        COMMAND_KW,
        DEPENDS_KW,
        ENV_KW.evolve(since='0.57.0'),
    )
    def func_run_target(self, node: mparser.FunctionNode, args: T.Tuple[str],
                        kwargs: 'kwargs.RunTarget') -> build.RunTarget:
        all_args = kwargs['command'].copy()

        for i in listify(all_args):
            if isinstance(i, ExternalProgram) and not i.found():
                raise InterpreterException(f'Tried to use non-existing executable {i.name!r}')
        if isinstance(all_args[0], str):
            all_args[0] = self.func_find_program(node, all_args[0], {})
        name = args[0]
        tg = build.RunTarget(name, all_args, kwargs['depends'], self.subdir, self.subproject, kwargs['env'])
        self.add_target(name, tg)
        full_name = (self.subproject, name)
        assert full_name not in self.build.run_target_names
        self.build.run_target_names.add(full_name)
        return tg

    @FeatureNew('alias_target', '0.52.0')
    @typed_pos_args('alias_target', str, varargs=build.Target, min_varargs=1)
    @noKwargs
    def func_alias_target(self, node: mparser.BaseNode, args: T.Tuple[str, T.List[build.Target]],
                          kwargs: 'TYPE_kwargs') -> build.AliasTarget:
        name, deps = args
        tg = build.AliasTarget(name, deps, self.subdir, self.subproject)
        self.add_target(name, tg)
        return tg

    @typed_pos_args('generator', (build.Executable, ExternalProgram))
    @typed_kwargs(
        'generator',
        KwargInfo('arguments', ContainerTypeInfo(list, str, allow_empty=False), required=True, listify=True),
        KwargInfo('output', ContainerTypeInfo(list, str, allow_empty=False), required=True, listify=True),
        DEPFILE_KW,
        KwargInfo('capture', bool, default=False, since='0.43.0'),
        KwargInfo('depends', ContainerTypeInfo(list, (build.BuildTarget, build.CustomTarget)), default=[], listify=True),
    )
    def func_generator(self, node: mparser.FunctionNode,
                       args: T.Tuple[T.Union[build.Executable, ExternalProgram]],
                       kwargs: 'kwargs.FuncGenerator') -> build.Generator:
        for rule in kwargs['output']:
            if '@BASENAME@' not in rule and '@PLAINNAME@' not in rule:
                raise InvalidArguments('Every element of "output" must contain @BASENAME@ or @PLAINNAME@.')
            if has_path_sep(rule):
                raise InvalidArguments('"output" must not contain a directory separator.')
        if len(kwargs['output']) > 1:
            for o in kwargs['output']:
                if '@OUTPUT@' in o:
                    raise InvalidArguments('Tried to use @OUTPUT@ in a rule with more than one output.')

        gen = build.Generator(args[0], **kwargs)
        self.generators.append(gen)
        return gen

    @typed_pos_args('benchmark', str, (build.Executable, build.Jar, ExternalProgram, mesonlib.File))
    @typed_kwargs('benchmark', *TEST_KWARGS)
    def func_benchmark(self, node: mparser.BaseNode,
                       args: T.Tuple[str, T.Union[build.Executable, build.Jar, ExternalProgram, mesonlib.File]],
                       kwargs: 'kwargs.FuncBenchmark') -> None:
        self.add_test(node, args, kwargs, False)

    @typed_pos_args('test', str, (build.Executable, build.Jar, ExternalProgram, mesonlib.File))
    @typed_kwargs('test', *TEST_KWARGS, KwargInfo('is_parallel', bool, default=True))
    def func_test(self, node: mparser.BaseNode,
                  args: T.Tuple[str, T.Union[build.Executable, build.Jar, ExternalProgram, mesonlib.File]],
                  kwargs: 'kwargs.FuncTest') -> None:
        self.add_test(node, args, kwargs, True)

    def unpack_env_kwarg(self, kwargs: T.Union[build.EnvironmentVariables, T.Dict[str, 'TYPE_var'], T.List['TYPE_var'], str]) -> build.EnvironmentVariables:
        envlist = kwargs.get('env')
        if envlist is None:
            return build.EnvironmentVariables()
        msg = ENV_KW.validator(envlist)
        if msg:
            raise InvalidArguments(f'"env": {msg}')
        return ENV_KW.convertor(envlist)

    def make_test(self, node: mparser.BaseNode,
                  args: T.Tuple[str, T.Union[build.Executable, build.Jar, ExternalProgram, mesonlib.File]],
                  kwargs: 'kwargs.BaseTest') -> Test:
        name = args[0]
        if ':' in name:
            mlog.deprecation(f'":" is not allowed in test name "{name}", it has been replaced with "_"',
                             location=node)
            name = name.replace(':', '_')
        exe = args[1]
        if isinstance(exe, mesonlib.File):
            exe = self.func_find_program(node, args[1], {})

        env = self.unpack_env_kwarg(kwargs)

        if kwargs['timeout'] <= 0:
            FeatureNew.single_use('test() timeout <= 0', '0.57.0', self.subproject)

        prj = self.subproject if self.is_subproject() else self.build.project_name

        suite: T.List[str] = []
        for s in kwargs['suite']:
            if s:
                s = ':' + s
            suite.append(prj.replace(' ', '_').replace(':', '_') + s)

        return Test(name,
                    prj,
                    suite,
                    exe,
                    kwargs['depends'],
                    kwargs.get('is_parallel', False),
                    kwargs['args'],
                    env,
                    kwargs['should_fail'],
                    kwargs['timeout'],
                    kwargs['workdir'],
                    kwargs['protocol'],
                    kwargs['priority'])

    def add_test(self, node: mparser.BaseNode, args: T.List, kwargs: T.Dict[str, T.Any], is_base_test: bool):
        t = self.make_test(node, args, kwargs)
        if is_base_test:
            self.build.tests.append(t)
            mlog.debug('Adding test', mlog.bold(t.name, True))
        else:
            self.build.benchmarks.append(t)
            mlog.debug('Adding benchmark', mlog.bold(t.name, True))

    @typed_pos_args('install_headers', varargs=(str, mesonlib.File))
    @typed_kwargs(
        'install_headers',
        KwargInfo('install_dir', (str, NoneType)),
        KwargInfo('subdir', (str, NoneType)),
        INSTALL_MODE_KW.evolve(since='0.47.0'),
    )
    def func_install_headers(self, node: mparser.BaseNode,
                             args: T.Tuple[T.List['mesonlib.FileOrString']],
                             kwargs: 'kwargs.FuncInstallHeaders') -> build.Headers:
        source_files = self.source_strings_to_files(args[0])
        install_subdir = kwargs['subdir']
        if install_subdir is not None and os.path.isabs(install_subdir):
            mlog.deprecation('Subdir keyword must not be an absolute path. This will be a hard error in the next release.')

        h = build.Headers(source_files, install_subdir, kwargs['install_dir'],
                          kwargs['install_mode'], self.subproject)
        self.build.headers.append(h)

        return h

    @typed_pos_args('install_man', varargs=(str, mesonlib.File))
    @typed_kwargs(
        'install_man',
        KwargInfo('install_dir', (str, NoneType)),
        KwargInfo('locale', (str, NoneType), since='0.58.0'),
        INSTALL_MODE_KW.evolve(since='0.47.0')
    )
    def func_install_man(self, node: mparser.BaseNode,
                         args: T.Tuple[T.List['mesonlib.FileOrString']],
                         kwargs: 'kwargs.FuncInstallMan') -> build.Man:
        # We just need to narrow this, because the input is limited to files and
        # Strings as inputs, so only Files will be returned
        sources = self.source_strings_to_files(args[0])
        for s in sources:
            try:
                num = int(s.rsplit('.', 1)[-1])
            except (IndexError, ValueError):
                num = 0
            if not 1 <= num <= 9:
                raise InvalidArguments('Man file must have a file extension of a number between 1 and 9')

        m = build.Man(sources, kwargs['install_dir'], kwargs['install_mode'],
                      self.subproject, kwargs['locale'])
        self.build.man.append(m)

        return m

    @FeatureNew('install_emptydir', '0.60.0')
    @typed_kwargs(
        'install_emptydir',
        INSTALL_MODE_KW
    )
    def func_install_emptydir(self, node: mparser.BaseNode, args: T.Tuple[str], kwargs) -> None:
        d = build.EmptyDir(args[0], kwargs['install_mode'], self.subproject)
        self.build.emptydir.append(d)

        return d

    @FeatureNewKwargs('subdir', '0.44.0', ['if_found'])
    @permittedKwargs({'if_found'})
    @typed_pos_args('subdir', str)
    def func_subdir(self, node: mparser.BaseNode, args: T.Tuple[str], kwargs: 'TYPE_kwargs') -> None:
        mesonlib.check_direntry_issues(args)
        if '..' in args[0]:
            raise InvalidArguments('Subdir contains ..')
        if self.subdir == '' and args[0] == self.subproject_dir:
            raise InvalidArguments('Must not go into subprojects dir with subdir(), use subproject() instead.')
        if self.subdir == '' and args[0].startswith('meson-'):
            raise InvalidArguments('The "meson-" prefix is reserved and cannot be used for top-level subdir().')
        for i in mesonlib.extract_as_list(kwargs, 'if_found'):
            if not hasattr(i, 'found'):
                raise InterpreterException('Object used in if_found does not have a found method.')
            if not i.found():
                return
        prev_subdir = self.subdir
        subdir = os.path.join(prev_subdir, args[0])
        if os.path.isabs(subdir):
            raise InvalidArguments('Subdir argument must be a relative path.')
        absdir = os.path.join(self.environment.get_source_dir(), subdir)
        symlinkless_dir = os.path.realpath(absdir)
        build_file = os.path.join(symlinkless_dir, 'meson.build')
        if build_file in self.processed_buildfiles:
            raise InvalidArguments(f'Tried to enter directory "{subdir}", which has already been visited.')
        self.processed_buildfiles.add(build_file)
        self.subdir = subdir
        os.makedirs(os.path.join(self.environment.build_dir, subdir), exist_ok=True)
        buildfilename = os.path.join(self.subdir, environment.build_filename)
        self.build_def_files.append(buildfilename)
        absname = os.path.join(self.environment.get_source_dir(), buildfilename)
        if not os.path.isfile(absname):
            self.subdir = prev_subdir
            raise InterpreterException(f"Non-existent build file '{buildfilename!s}'")
        with open(absname, encoding='utf-8') as f:
            code = f.read()
        assert isinstance(code, str)
        try:
            codeblock = mparser.Parser(code, absname).parse()
        except mesonlib.MesonException as me:
            me.file = absname
            raise me
        try:
            self.evaluate_codeblock(codeblock)
        except SubdirDoneRequest:
            pass
        self.subdir = prev_subdir

    def _get_kwarg_install_mode(self, kwargs: T.Dict[str, T.Any]) -> T.Optional[FileMode]:
        if kwargs.get('install_mode', None) is None:
            return None
        if isinstance(kwargs['install_mode'], FileMode):
            return kwargs['install_mode']
        install_mode: T.List[str] = []
        mode = mesonlib.typeslistify(kwargs.get('install_mode', []), (str, int))
        for m in mode:
            # We skip any arguments that are set to `false`
            if m is False:
                m = None
            install_mode.append(m)
        if len(install_mode) > 3:
            raise InvalidArguments('Keyword argument install_mode takes at '
                                   'most 3 arguments.')
        if len(install_mode) > 0 and install_mode[0] is not None and \
           not isinstance(install_mode[0], str):
            raise InvalidArguments('Keyword argument install_mode requires the '
                                   'permissions arg to be a string or false')
        return FileMode(*install_mode)

    @typed_pos_args('install_data', varargs=(str, mesonlib.File))
    @typed_kwargs(
        'install_data',
        KwargInfo('install_dir', (str, NoneType)),
        KwargInfo('sources', ContainerTypeInfo(list, (str, mesonlib.File)), listify=True, default=[]),
        KwargInfo('rename', ContainerTypeInfo(list, str), default=[], listify=True, since='0.46.0'),
        INSTALL_MODE_KW.evolve(since='0.38.0'),
        KwargInfo('install_tag', (str, NoneType), since='0.60.0'),
    )
    def func_install_data(self, node: mparser.BaseNode,
                          args: T.Tuple[T.List['mesonlib.FileOrString']],
                          kwargs: 'kwargs.FuncInstallData') -> build.Data:
        sources = self.source_strings_to_files(args[0] + kwargs['sources'])
        rename = kwargs['rename'] or None
        if rename:
            if len(rename) != len(sources):
                raise InvalidArguments(
                    '"rename" and "sources" argument lists must be the same length if "rename" is given. '
                    f'Rename has {len(rename)} elements and sources has {len(sources)}.')

        install_dir_name = kwargs['install_dir']
        if install_dir_name:
            if not os.path.isabs(install_dir_name):
                install_dir_name = os.path.join('{datadir}', install_dir_name)
        else:
            install_dir_name = '{datadir}'
        return self.install_data_impl(sources, kwargs['install_dir'], kwargs['install_mode'],
                                      rename, kwargs['install_tag'], install_dir_name)

    def install_data_impl(self, sources: T.List[mesonlib.File], install_dir: str,
                          install_mode: FileMode, rename: T.Optional[str],
                          tag: T.Optional[str],
                          install_dir_name: T.Optional[str] = None,
                          install_data_type: T.Optional[str] = None) -> build.Data:

        """Just the implementation with no validation."""
        data = build.Data(sources, install_dir, install_dir_name or install_dir, install_mode,
                          self.subproject, rename, tag, install_data_type)
        self.build.data.append(data)
        return data

    @typed_pos_args('install_subdir', str)
    @typed_kwargs(
        'install_subdir',
        KwargInfo('install_dir', str, required=True),
        KwargInfo('install_tag', (str, NoneType), since='0.60.0'),
        KwargInfo('strip_directory', bool, default=False),
        KwargInfo('exclude_files', ContainerTypeInfo(list, str),
                  default=[], listify=True, since='0.42.0',
                  validator=lambda x: 'cannot be absolute' if any(os.path.isabs(d) for d in x) else None),
        KwargInfo('exclude_directories', ContainerTypeInfo(list, str),
                  default=[], listify=True, since='0.42.0',
                  validator=lambda x: 'cannot be absolute' if any(os.path.isabs(d) for d in x) else None),
        INSTALL_MODE_KW.evolve(since='0.38.0'),
    )
    def func_install_subdir(self, node: mparser.BaseNode, args: T.Tuple[str],
                            kwargs: 'kwargs.FuncInstallSubdir') -> build.InstallDir:
        exclude = (set(kwargs['exclude_files']), set(kwargs['exclude_directories']))
        idir = build.InstallDir(
            self.subdir,
            args[0],
            kwargs['install_dir'],
            kwargs['install_mode'],
            exclude,
            kwargs['strip_directory'],
            self.subproject,
            install_tag=kwargs['install_tag'])
        self.build.install_dirs.append(idir)
        return idir

    @FeatureNewKwargs('configure_file', '0.47.0', ['copy', 'output_format', 'install_mode', 'encoding'])
    @FeatureNewKwargs('configure_file', '0.46.0', ['format'])
    @FeatureNewKwargs('configure_file', '0.41.0', ['capture'])
    @FeatureNewKwargs('configure_file', '0.50.0', ['install'])
    @FeatureNewKwargs('configure_file', '0.52.0', ['depfile'])
    @FeatureNewKwargs('configure_file', '0.60.0', ['install_tag'])
    @permittedKwargs({'input', 'output', 'configuration', 'command', 'copy', 'depfile',
                      'install_dir', 'install_mode', 'capture', 'install', 'format',
                      'output_format', 'encoding', 'install_tag'})
    @noPosargs
    def func_configure_file(self, node, args, kwargs):
        if 'output' not in kwargs:
            raise InterpreterException('Required keyword argument "output" not defined.')
        actions = {'configuration', 'command', 'copy'}.intersection(kwargs.keys())
        if len(actions) == 0:
            raise InterpreterException('Must specify an action with one of these '
                                       'keyword arguments: \'configuration\', '
                                       '\'command\', or \'copy\'.')
        elif len(actions) == 2:
            raise InterpreterException('Must not specify both {!r} and {!r} '
                                       'keyword arguments since they are '
                                       'mutually exclusive.'.format(*actions))
        elif len(actions) == 3:
            raise InterpreterException('Must specify one of {!r}, {!r}, and '
                                       '{!r} keyword arguments since they are '
                                       'mutually exclusive.'.format(*actions))
        if 'capture' in kwargs:
            if not isinstance(kwargs['capture'], bool):
                raise InterpreterException('"capture" keyword must be a boolean.')
            if 'command' not in kwargs:
                raise InterpreterException('"capture" keyword requires "command" keyword.')

        if 'format' in kwargs:
            fmt = kwargs['format']
            if not isinstance(fmt, str):
                raise InterpreterException('"format" keyword must be a string.')
        else:
            fmt = 'meson'

        if fmt not in ('meson', 'cmake', 'cmake@'):
            raise InterpreterException('"format" possible values are "meson", "cmake" or "cmake@".')

        if 'output_format' in kwargs:
            output_format = kwargs['output_format']
            if not isinstance(output_format, str):
                raise InterpreterException('"output_format" keyword must be a string.')
        else:
            output_format = 'c'

        if output_format not in ('c', 'nasm'):
            raise InterpreterException('"format" possible values are "c" or "nasm".')

        if 'depfile' in kwargs:
            depfile = kwargs['depfile']
            if not isinstance(depfile, str):
                raise InterpreterException('depfile file name must be a string')
        else:
            depfile = None

        # Validate input
        inputs = self.source_strings_to_files(extract_as_list(kwargs, 'input'))
        inputs_abs = []
        for f in inputs:
            if isinstance(f, mesonlib.File):
                inputs_abs.append(f.absolute_path(self.environment.source_dir,
                                                  self.environment.build_dir))
                self.add_build_def_file(f)
            else:
                raise InterpreterException('Inputs can only be strings or file objects')
        # Validate output
        output = kwargs['output']
        if not isinstance(output, str):
            raise InterpreterException('Output file name must be a string')
        if inputs_abs:
            values = mesonlib.get_filenames_templates_dict(inputs_abs, None)
            outputs = mesonlib.substitute_values([output], values)
            output = outputs[0]
            if depfile:
                depfile = mesonlib.substitute_values([depfile], values)[0]
        ofile_rpath = os.path.join(self.subdir, output)
        if ofile_rpath in self.configure_file_outputs:
            mesonbuildfile = os.path.join(self.subdir, 'meson.build')
            current_call = f"{mesonbuildfile}:{self.current_lineno}"
            first_call = "{}:{}".format(mesonbuildfile, self.configure_file_outputs[ofile_rpath])
            mlog.warning('Output file', mlog.bold(ofile_rpath, True), 'for configure_file() at', current_call, 'overwrites configure_file() output at', first_call)
        else:
            self.configure_file_outputs[ofile_rpath] = self.current_lineno
        if os.path.dirname(output) != '':
            raise InterpreterException('Output file name must not contain a subdirectory.')
        (ofile_path, ofile_fname) = os.path.split(os.path.join(self.subdir, output))
        ofile_abs = os.path.join(self.environment.build_dir, ofile_path, ofile_fname)
        # Perform the appropriate action
        if 'configuration' in kwargs:
            conf = kwargs['configuration']
            if isinstance(conf, dict):
                FeatureNew.single_use('configure_file.configuration dictionary', '0.49.0', self.subproject)
                conf = ConfigurationDataObject(self.subproject, conf)
            elif not isinstance(conf, ConfigurationDataObject):
                raise InterpreterException('Argument "configuration" is not of type configuration_data')
            mlog.log('Configuring', mlog.bold(output), 'using configuration')
            if len(inputs) > 1:
                raise InterpreterException('At most one input file can given in configuration mode')
            if inputs:
                os.makedirs(os.path.join(self.environment.build_dir, self.subdir), exist_ok=True)
                file_encoding = kwargs.setdefault('encoding', 'utf-8')
                missing_variables, confdata_useless = \
                    mesonlib.do_conf_file(inputs_abs[0], ofile_abs, conf.conf_data,
                                          fmt, file_encoding)
                if missing_variables:
                    var_list = ", ".join(map(repr, sorted(missing_variables)))
                    mlog.warning(
                        f"The variable(s) {var_list} in the input file '{inputs[0]}' are not "
                        "present in the given configuration data.", location=node)
                if confdata_useless:
                    ifbase = os.path.basename(inputs_abs[0])
                    tv = FeatureNew.get_target_version(self.subproject)
                    if FeatureNew.check_version(tv, '0.47.0'):
                        mlog.warning('Got an empty configuration_data() object and found no '
                                     f'substitutions in the input file {ifbase!r}. If you want to '
                                     'copy a file to the build dir, use the \'copy:\' keyword '
                                     'argument added in 0.47.0', location=node)
            else:
                mesonlib.dump_conf_header(ofile_abs, conf.conf_data, output_format)
            conf.mark_used()
        elif 'command' in kwargs:
            if len(inputs) > 1:
                FeatureNew.single_use('multiple inputs in configure_file()', '0.52.0', self.subproject)
            # We use absolute paths for input and output here because the cwd
            # that the command is run from is 'unspecified', so it could change.
            # Currently it's builddir/subdir for in_builddir else srcdir/subdir.
            values = mesonlib.get_filenames_templates_dict(inputs_abs, [ofile_abs])
            if depfile:
                depfile = os.path.join(self.environment.get_scratch_dir(), depfile)
                values['@DEPFILE@'] = depfile
            # Substitute @INPUT@, @OUTPUT@, etc here.
            cmd = mesonlib.substitute_values(kwargs['command'], values)
            mlog.log('Configuring', mlog.bold(output), 'with command')
            res = self.run_command_impl(node, cmd,  {}, True)
            if res.returncode != 0:
                raise InterpreterException(f'Running configure command failed.\n{res.stdout}\n{res.stderr}')
            if 'capture' in kwargs and kwargs['capture']:
                dst_tmp = ofile_abs + '~'
                file_encoding = kwargs.setdefault('encoding', 'utf-8')
                with open(dst_tmp, 'w', encoding=file_encoding) as f:
                    f.writelines(res.stdout)
                if inputs_abs:
                    shutil.copymode(inputs_abs[0], dst_tmp)
                mesonlib.replace_if_different(ofile_abs, dst_tmp)
            if depfile:
                mlog.log('Reading depfile:', mlog.bold(depfile))
                with open(depfile, encoding='utf-8') as f:
                    df = DepFile(f.readlines())
                    deps = df.get_all_dependencies(ofile_fname)
                    for dep in deps:
                        self.add_build_def_file(dep)

        elif 'copy' in kwargs:
            if len(inputs_abs) != 1:
                raise InterpreterException('Exactly one input file must be given in copy mode')
            os.makedirs(os.path.join(self.environment.build_dir, self.subdir), exist_ok=True)
            shutil.copy2(inputs_abs[0], ofile_abs)
        else:
            # Not reachable
            raise AssertionError
        # Install file if requested, we check for the empty string
        # for backwards compatibility. That was the behaviour before
        # 0.45.0 so preserve it.
        idir = kwargs.get('install_dir', '')
        if idir is False:
            idir = ''
            FeatureDeprecated.single_use('configure_file install_dir: false', '0.50.0',
                                         self.subproject, 'Use the `install:` kwarg instead', location=node)
        if not isinstance(idir, str):
            if isinstance(idir, list) and len(idir) == 0:
                mlog.deprecation('install_dir: kwarg must be a string and not an empty array. '
                                 'Please use the install: kwarg to enable or disable installation. '
                                 'This will be a hard error in the next release.')
            else:
                raise InterpreterException('"install_dir" must be a string')
        install = kwargs.get('install', idir != '')
        if not isinstance(install, bool):
            raise InterpreterException('"install" must be a boolean')
        if install:
            if not idir:
                raise InterpreterException('"install_dir" must be specified '
                                           'when "install" in a configure_file '
                                           'is true')
            cfile = mesonlib.File.from_built_file(ofile_path, ofile_fname)
            install_mode = self._get_kwarg_install_mode(kwargs)
            install_tag = kwargs.get('install_tag')
            if install_tag is not None and not isinstance(install_tag, str):
                raise InvalidArguments('install_tag keyword argument must be string')
            self.build.data.append(build.Data([cfile], idir, idir, install_mode, self.subproject,
                                              install_tag=install_tag, data_type='configure'))
        return mesonlib.File.from_built_file(self.subdir, output)

    def extract_incdirs(self, kwargs):
        prospectives = extract_as_list(kwargs, 'include_directories')
        result = []
        for p in prospectives:
            if isinstance(p, build.IncludeDirs):
                result.append(p)
            elif isinstance(p, str):
                result.append(self.build_incdir_object([p]))
            else:
                raise InterpreterException('Include directory objects can only be created from strings or include directories.')
        return result

    @typed_pos_args('include_directories', varargs=str)
    @typed_kwargs('include_directories', KwargInfo('is_system', bool, default=False))
    def func_include_directories(self, node: mparser.BaseNode, args: T.Tuple[T.List[str]],
                                 kwargs: 'kwargs.FuncIncludeDirectories') -> build.IncludeDirs:
        return self.build_incdir_object(args[0], kwargs['is_system'])

    def build_incdir_object(self, incdir_strings: T.List[str], is_system: bool = False) -> build.IncludeDirs:
        if not isinstance(is_system, bool):
            raise InvalidArguments('Is_system must be boolean.')
        src_root = self.environment.get_source_dir()
        build_root = self.environment.get_build_dir()
        absbase_src = os.path.join(src_root, self.subdir)
        absbase_build = os.path.join(build_root, self.subdir)

        for a in incdir_strings:
            if a.startswith(src_root):
                raise InvalidArguments(textwrap.dedent('''\
                    Tried to form an absolute path to a source dir.
                    You should not do that but use relative paths instead.

                    To get include path to any directory relative to the current dir do

                    incdir = include_directories(dirname)

                    After this incdir will contain both the current source dir as well as the
                    corresponding build dir. It can then be used in any subdirectory and
                    Meson will take care of all the busywork to make paths work.

                    Dirname can even be '.' to mark the current directory. Though you should
                    remember that the current source and build directories are always
                    put in the include directories by default so you only need to do
                    include_directories('.') if you intend to use the result in a
                    different subdirectory.
                    '''))
            else:
                try:
                    self.validate_within_subproject(self.subdir, a)
                except InterpreterException:
                    mlog.warning('include_directories sandbox violation!')
                    print(textwrap.dedent(f'''\
                        The project is trying to access the directory {a} which belongs to a different
                        subproject. This is a problem as it hardcodes the relative paths of these two projects.
                        This makes it impossible to compile the project in any other directory layout and also
                        prevents the subproject from changing its own directory layout.

                        Instead of poking directly at the internals the subproject should be executed and
                        it should set a variable that the caller can then use. Something like:

                        # In subproject
                        some_dep = declare_dependency(include_directories: include_directories('include'))

                        # In subproject wrap file
                        [provide]
                        some = some_dep

                        # In parent project
                        some_dep = dependency('some')
                        executable(..., dependencies: [some_dep])

                        This warning will become a hard error in a future Meson release.
                        '''))
            absdir_src = os.path.join(absbase_src, a)
            absdir_build = os.path.join(absbase_build, a)
            if not os.path.isdir(absdir_src) and not os.path.isdir(absdir_build):
                raise InvalidArguments(f'Include dir {a} does not exist.')
        i = build.IncludeDirs(self.subdir, incdir_strings, is_system)
        return i

    @permittedKwargs({'exe_wrapper', 'gdb', 'timeout_multiplier', 'env', 'is_default',
                      'exclude_suites'})
    @typed_pos_args('add_test_setup', str)
    def func_add_test_setup(self, node: mparser.BaseNode, args: T.Tuple[str], kwargs: 'TYPE_kwargs') -> None:
        setup_name = args[0]
        if re.fullmatch('([_a-zA-Z][_0-9a-zA-Z]*:)?[_a-zA-Z][_0-9a-zA-Z]*', setup_name) is None:
            raise InterpreterException('Setup name may only contain alphanumeric characters.')
        if ":" not in setup_name:
            setup_name = (self.subproject if self.subproject else self.build.project_name) + ":" + setup_name
        try:
            inp = extract_as_list(kwargs, 'exe_wrapper')
            exe_wrapper = []
            for i in inp:
                if isinstance(i, str):
                    exe_wrapper.append(i)
                elif isinstance(i, ExternalProgram):
                    if not i.found():
                        raise InterpreterException('Tried to use non-found executable.')
                    exe_wrapper += i.get_command()
                else:
                    raise InterpreterException('Exe wrapper can only contain strings or external binaries.')
        except KeyError:
            exe_wrapper = None
        gdb = kwargs.get('gdb', False)
        if not isinstance(gdb, bool):
            raise InterpreterException('Gdb option must be a boolean')
        timeout_multiplier = kwargs.get('timeout_multiplier', 1)
        if not isinstance(timeout_multiplier, int):
            raise InterpreterException('Timeout multiplier must be a number.')
        if timeout_multiplier <= 0:
            FeatureNew('add_test_setup() timeout_multiplier <= 0', '0.57.0').use(self.subproject)
        is_default = kwargs.get('is_default', False)
        if not isinstance(is_default, bool):
            raise InterpreterException('is_default option must be a boolean')
        if is_default:
            if self.build.test_setup_default_name is not None:
                raise InterpreterException(f'{self.build.test_setup_default_name!r} is already set as default. '
                                           'is_default can be set to true only once')
            self.build.test_setup_default_name = setup_name
        exclude_suites = mesonlib.stringlistify(kwargs.get('exclude_suites', []))
        env = self.unpack_env_kwarg(kwargs)
        self.build.test_setups[setup_name] = build.TestSetup(exe_wrapper, gdb, timeout_multiplier, env,
                                                             exclude_suites)

    @typed_pos_args('add_global_arguments', varargs=str)
    @typed_kwargs('add_global_arguments', NATIVE_KW, LANGUAGE_KW)
    def func_add_global_arguments(self, node: mparser.FunctionNode, args: T.Tuple[T.List[str]], kwargs: 'kwargs.FuncAddProjectArgs') -> None:
        self._add_global_arguments(node, self.build.global_args[kwargs['native']], args[0], kwargs)

    @typed_pos_args('add_global_link_arguments', varargs=str)
    @typed_kwargs('add_global_arguments', NATIVE_KW, LANGUAGE_KW)
    def func_add_global_link_arguments(self, node: mparser.FunctionNode, args: T.Tuple[T.List[str]], kwargs: 'kwargs.FuncAddProjectArgs') -> None:
        self._add_global_arguments(node, self.build.global_link_args[kwargs['native']], args[0], kwargs)

    @typed_pos_args('add_project_arguments', varargs=str)
    @typed_kwargs('add_project_arguments', NATIVE_KW, LANGUAGE_KW)
    def func_add_project_arguments(self, node: mparser.FunctionNode, args: T.Tuple[T.List[str]], kwargs: 'kwargs.FuncAddProjectArgs') -> None:
        self._add_project_arguments(node, self.build.projects_args[kwargs['native']], args[0], kwargs)

    @typed_pos_args('add_project_link_arguments', varargs=str)
    @typed_kwargs('add_global_arguments', NATIVE_KW, LANGUAGE_KW)
    def func_add_project_link_arguments(self, node: mparser.FunctionNode, args: T.Tuple[T.List[str]], kwargs: 'kwargs.FuncAddProjectArgs') -> None:
        self._add_project_arguments(node, self.build.projects_link_args[kwargs['native']], args[0], kwargs)

    def _warn_about_builtin_args(self, args: T.List[str]) -> None:
        # -Wpedantic is deliberately not included, since some people want to use it but not use -Wextra
        # see e.g.
        # https://github.com/mesonbuild/meson/issues/3275#issuecomment-641354956
        # https://github.com/mesonbuild/meson/issues/3742
        warnargs = ('/W1', '/W2', '/W3', '/W4', '/Wall', '-Wall', '-Wextra')
        optargs = ('-O0', '-O2', '-O3', '-Os', '-Oz', '/O1', '/O2', '/Os')
        for arg in args:
            if arg in warnargs:
                mlog.warning(f'Consider using the built-in warning_level option instead of using "{arg}".',
                             location=self.current_node)
            elif arg in optargs:
                mlog.warning(f'Consider using the built-in optimization level instead of using "{arg}".',
                             location=self.current_node)
            elif arg == '-Werror':
                mlog.warning(f'Consider using the built-in werror option instead of using "{arg}".',
                             location=self.current_node)
            elif arg == '-g':
                mlog.warning(f'Consider using the built-in debug option instead of using "{arg}".',
                             location=self.current_node)
            elif arg.startswith('-fsanitize'):
                mlog.warning(f'Consider using the built-in option for sanitizers instead of using "{arg}".',
                             location=self.current_node)
            elif arg.startswith('-std=') or arg.startswith('/std:'):
                mlog.warning(f'Consider using the built-in option for language standard version instead of using "{arg}".',
                             location=self.current_node)

    def _add_global_arguments(self, node: mparser.FunctionNode, argsdict: T.Dict[str, T.List[str]],
                              args: T.List[str], kwargs: 'kwargs.FuncAddProjectArgs') -> None:
        if self.is_subproject():
            msg = f'Function \'{node.func_name}\' cannot be used in subprojects because ' \
                  'there is no way to make that reliable.\nPlease only call ' \
                  'this if is_subproject() returns false. Alternatively, ' \
                  'define a variable that\ncontains your language-specific ' \
                  'arguments and add it to the appropriate *_args kwarg ' \
                  'in each target.'
            raise InvalidCode(msg)
        frozen = self.project_args_frozen or self.global_args_frozen
        self._add_arguments(node, argsdict, frozen, args, kwargs)

    def _add_project_arguments(self, node: mparser.FunctionNode, argsdict: T.Dict[str, T.Dict[str, T.List[str]]],
                               args: T.List[str], kwargs: 'kwargs.FuncAddProjectArgs') -> None:
        if self.subproject not in argsdict:
            argsdict[self.subproject] = {}
        self._add_arguments(node, argsdict[self.subproject],
                            self.project_args_frozen, args, kwargs)

    def _add_arguments(self, node: mparser.FunctionNode, argsdict: T.Dict[str, T.List[str]],
                       args_frozen: bool, args: T.List[str], kwargs: 'kwargs.FuncAddProjectArgs') -> None:
        if args_frozen:
            msg = f'Tried to use \'{node.func_name}\' after a build target has been declared.\n' \
                  'This is not permitted. Please declare all arguments before your targets.'
            raise InvalidCode(msg)

        self._warn_about_builtin_args(args)

        for lang in kwargs['language']:
            argsdict[lang] = argsdict.get(lang, []) + args

    @noKwargs
    @noArgsFlattening
    @typed_pos_args('environment', optargs=[(str, list, dict)])
    def func_environment(self, node: mparser.FunctionNode, args: T.Tuple[T.Union[None, str, T.List['TYPE_var'], T.Dict[str, 'TYPE_var']]],
                         kwargs: 'TYPE_kwargs') -> build.EnvironmentVariables:
        init = args[0]
        if init is not None:
            FeatureNew.single_use('environment positional arguments', '0.52.0', self.subproject)
            msg = ENV_KW.validator(init)
            if msg:
                raise InvalidArguments(f'"environment": {msg}')
            return ENV_KW.convertor(init)
        return build.EnvironmentVariables()

    @typed_pos_args('join_paths', varargs=str, min_varargs=1)
    @noKwargs
    def func_join_paths(self, node: mparser.BaseNode, args: T.Tuple[T.List[str]], kwargs: 'TYPE_kwargs') -> str:
        return os.path.join(*args[0]).replace('\\', '/')

    def run(self) -> None:
        super().run()
        mlog.log('Build targets in project:', mlog.bold(str(len(self.build.targets))))
        FeatureNew.report(self.subproject)
        FeatureDeprecated.report(self.subproject)
        if not self.is_subproject():
            self.print_extra_warnings()
        if self.subproject == '':
            self._print_summary()

    def print_extra_warnings(self) -> None:
        # TODO cross compilation
        for c in self.coredata.compilers.host.values():
            if c.get_id() == 'clang':
                self.check_clang_asan_lundef()
                break

    def check_clang_asan_lundef(self) -> None:
        if OptionKey('b_lundef') not in self.coredata.options:
            return
        if OptionKey('b_sanitize') not in self.coredata.options:
            return
        if (self.coredata.options[OptionKey('b_lundef')].value and
                self.coredata.options[OptionKey('b_sanitize')].value != 'none'):
            mlog.warning('''Trying to use {} sanitizer on Clang with b_lundef.
This will probably not work.
Try setting b_lundef to false instead.'''.format(self.coredata.options[OptionKey('b_sanitize')].value),
                         location=self.current_node)

    # Check that the indicated file is within the same subproject
    # as we currently are. This is to stop people doing
    # nasty things like:
    #
    # f = files('../../master_src/file.c')
    #
    # Note that this is validated only when the file
    # object is generated. The result can be used in a different
    # subproject than it is defined in (due to e.g. a
    # declare_dependency).
    def validate_within_subproject(self, subdir, fname):
        srcdir = Path(self.environment.source_dir)
        norm = Path(srcdir, subdir, fname).resolve()
        if os.path.isdir(norm):
            inputtype = 'directory'
        else:
            inputtype = 'file'
        if srcdir not in norm.parents:
            # Grabbing files outside the source tree is ok.
            # This is for vendor stuff like:
            #
            # /opt/vendorsdk/src/file_with_license_restrictions.c
            return
        project_root = Path(srcdir, self.root_subdir)
        if norm == project_root:
            return
        if project_root not in norm.parents:
            raise InterpreterException(f'Sandbox violation: Tried to grab {inputtype} {norm.name} outside current (sub)project.')
        if project_root / self.subproject_dir in norm.parents:
            raise InterpreterException(f'Sandbox violation: Tried to grab {inputtype} {norm.name} from a nested subproject.')

    @T.overload
    def source_strings_to_files(self, sources: T.List['mesonlib.FileOrString']) -> T.List['mesonlib.File']: ...

    @T.overload
    def source_strings_to_files(self, sources: T.List['SourceInputs']) -> T.List['SourceOutputs']: ... # noqa: F811

    def source_strings_to_files(self, sources: T.List['SourceInputs']) -> T.List['SourceOutputs']: # noqa: F811
        """Lower inputs to a list of Targets and Files, replacing any strings.

        :param sources: A raw (Meson DSL) list of inputs (targets, files, and
            strings)
        :raises InterpreterException: if any of the inputs are of an invalid type
        :return: A list of Targets and Files
        """
        mesonlib.check_direntry_issues(sources)
        if not isinstance(sources, list):
            sources = [sources]
        results: T.List['SourceOutputs'] = []
        for s in sources:
            if isinstance(s, str):
                self.validate_within_subproject(self.subdir, s)
                results.append(mesonlib.File.from_source_file(self.environment.source_dir, self.subdir, s))
            elif isinstance(s, mesonlib.File):
                results.append(s)
            elif isinstance(s, (build.GeneratedList, build.BuildTarget,
                                build.CustomTargetIndex, build.CustomTarget,
                                build.GeneratedList)):
                results.append(s)
            else:
                raise InterpreterException(f'Source item is {s!r} instead of '
                                           'string or File-type object')
        return results

    def add_target(self, name, tobj):
        if name == '':
            raise InterpreterException('Target name must not be empty.')
        if name.strip() == '':
            raise InterpreterException('Target name must not consist only of whitespace.')
        if has_path_sep(name):
            pathseg = os.path.join(self.subdir, os.path.split(name)[0])
            if os.path.exists(os.path.join(self.source_root, pathseg)):
                raise InvalidArguments(textwrap.dedent(f'''\
                    Target "{name}" has a path segment pointing to directory "{pathseg}". This is an error.
                    To define a target that builds in that directory you must define it
                    in the meson.build file in that directory.
            '''))
        if name.startswith('meson-'):
            raise InvalidArguments("Target names starting with 'meson-' are reserved "
                                   "for Meson's internal use. Please rename.")
        if name in coredata.FORBIDDEN_TARGET_NAMES:
            raise InvalidArguments(f"Target name '{name}' is reserved for Meson's "
                                   "internal use. Please rename.")
        # To permit an executable and a shared library to have the
        # same name, such as "foo.exe" and "libfoo.a".
        idname = tobj.get_id()
        if idname in self.build.targets:
            raise InvalidCode(f'Tried to create target "{name}", but a target of that name already exists.')
        self.build.targets[idname] = tobj
        if idname not in self.coredata.target_guids:
            self.coredata.target_guids[idname] = str(uuid.uuid4()).upper()

    @FeatureNew('both_libraries', '0.46.0')
    def build_both_libraries(self, node, args, kwargs):
        shared_lib = self.build_target(node, args, kwargs, build.SharedLibrary)

        # Check if user forces non-PIC static library.
        pic = True
        key = OptionKey('b_staticpic')
        if 'pic' in kwargs:
            pic = kwargs['pic']
        elif key in self.environment.coredata.options:
            pic = self.environment.coredata.options[key].value

        if self.backend.name == 'xcode':
            # Xcode is a bit special in that you can't (at least for the moment)
            # form a library only from object file inputs. The simple but inefficient
            # solution is to use the sources directly. This will lead to them being
            # built twice. This is unfortunate and slow, but at least it works.
            # Feel free to submit patches to get this fixed if it is an
            # issue for you.
            reuse_object_files = False
        else:
            reuse_object_files = pic

        if reuse_object_files:
            # Exclude sources from args and kwargs to avoid building them twice
            static_args = [args[0]]
            static_kwargs = kwargs.copy()
            static_kwargs['sources'] = []
            static_kwargs['objects'] = shared_lib.extract_all_objects()
        else:
            static_args = args
            static_kwargs = kwargs

        static_lib = self.build_target(node, static_args, static_kwargs, build.StaticLibrary)

        return build.BothLibraries(shared_lib, static_lib)

    def build_library(self, node, args, kwargs):
        default_library = self.coredata.get_option(OptionKey('default_library', subproject=self.subproject))
        if default_library == 'shared':
            return self.build_target(node, args, kwargs, build.SharedLibrary)
        elif default_library == 'static':
            return self.build_target(node, args, kwargs, build.StaticLibrary)
        elif default_library == 'both':
            return self.build_both_libraries(node, args, kwargs)
        else:
            raise InterpreterException(f'Unknown default_library value: {default_library}.')

    def build_target(self, node, args, kwargs, targetclass):
        @FeatureNewKwargs('build target', '0.42.0', ['rust_crate_type', 'build_rpath', 'implicit_include_directories'])
        @FeatureNewKwargs('build target', '0.41.0', ['rust_args'])
        @FeatureNewKwargs('build target', '0.40.0', ['build_by_default'])
        @FeatureNewKwargs('build target', '0.48.0', ['gnu_symbol_visibility'])
        def build_target_decorator_caller(self, node, args, kwargs):
            return True

        build_target_decorator_caller(self, node, args, kwargs)

        if not args:
            raise InterpreterException('Target does not have a name.')
        name, *sources = args
        for_machine = self.machine_from_native_kwarg(kwargs)
        if 'sources' in kwargs:
            sources += listify(kwargs['sources'])
        sources = self.source_strings_to_files(sources)
        objs = extract_as_list(kwargs, 'objects')
        kwargs['dependencies'] = extract_as_list(kwargs, 'dependencies')
        kwargs['install_mode'] = self._get_kwarg_install_mode(kwargs)
        if 'extra_files' in kwargs:
            ef = extract_as_list(kwargs, 'extra_files')
            kwargs['extra_files'] = self.source_strings_to_files(ef)
        self.check_sources_exist(os.path.join(self.source_root, self.subdir), sources)
        if targetclass not in {build.Executable, build.CompiledObjects, build.SharedLibrary, build.SharedModule, build.StaticLibrary, build.Jar}:
            mlog.debug('Unknown target type:', str(targetclass))
            raise RuntimeError('Unreachable code')
        self.kwarg_strings_to_includedirs(kwargs)

        # Filter out kwargs from other target types. For example 'soversion'
        # passed to library() when default_library == 'static'.
        kwargs = {k: v for k, v in kwargs.items() if k in targetclass.known_kwargs}

        kwargs['include_directories'] = self.extract_incdirs(kwargs)
        target = targetclass(name, self.subdir, self.subproject, for_machine, sources, objs, self.environment, kwargs)
        target.project_version = self.project_version

        self.add_stdlib_info(target)
        self.add_target(name, target)
        self.project_args_frozen = True
        return target

    def kwarg_strings_to_includedirs(self, kwargs):
        if 'd_import_dirs' in kwargs:
            items = mesonlib.extract_as_list(kwargs, 'd_import_dirs')
            cleaned_items = []
            for i in items:
                if isinstance(i, str):
                    # BW compatibility. This was permitted so we must support it
                    # for a few releases so people can transition to "correct"
                    # path declarations.
                    if os.path.normpath(i).startswith(self.environment.get_source_dir()):
                        mlog.warning('''Building a path to the source dir is not supported. Use a relative path instead.
This will become a hard error in the future.''', location=self.current_node)
                        i = os.path.relpath(i, os.path.join(self.environment.get_source_dir(), self.subdir))
                        i = self.build_incdir_object([i])
                cleaned_items.append(i)
            kwargs['d_import_dirs'] = cleaned_items

    def get_used_languages(self, target):
        result = set()
        for i in target.sources:
            for lang, c in self.coredata.compilers[target.for_machine].items():
                if c.can_compile(i):
                    result.add(lang)
                    break
        return result

    def add_stdlib_info(self, target):
        for l in self.get_used_languages(target):
            dep = self.build.stdlibs[target.for_machine].get(l, None)
            if dep:
                target.add_deps(dep)

    def check_sources_exist(self, subdir, sources):
        for s in sources:
            if not isinstance(s, str):
                continue # This means a generated source and they always exist.
            fname = os.path.join(subdir, s)
            if not os.path.isfile(fname):
                raise InterpreterException(f'Tried to add non-existing source file {s}.')

    # Only permit object extraction from the same subproject
    def validate_extraction(self, buildtarget: mesonlib.HoldableObject) -> None:
        if self.subproject != buildtarget.subproject:
            raise InterpreterException('Tried to extract objects from a different subproject.')

    def is_subproject(self) -> bool:
        return self.subproject != ''

    @typed_pos_args('set_variable', str, object)
    @noKwargs
    @noArgsFlattening
    @noSecondLevelHolderResolving
    def func_set_variable(self, node: mparser.BaseNode, args: T.Tuple[str, object], kwargs: 'TYPE_kwargs') -> None:
        varname, value = args
        self.set_variable(varname, value, holderify=True)

    @typed_pos_args('get_variable', (str, Disabler), optargs=[object])
    @noKwargs
    @noArgsFlattening
    @unholder_return
    def func_get_variable(self, node: mparser.BaseNode, args: T.Tuple[T.Union[str, Disabler], T.Optional[object]],
                          kwargs: 'TYPE_kwargs') -> 'TYPE_var':
        varname, fallback = args
        if isinstance(varname, Disabler):
            return varname

        try:
            return self.variables[varname]
        except KeyError:
            if fallback is not None:
                return self._holderify(fallback)
        raise InterpreterException(f'Tried to get unknown variable "{varname}".')

    @typed_pos_args('is_variable', str)
    @noKwargs
    def func_is_variable(self, node: mparser.BaseNode, args: T.Tuple[str], kwargs: 'TYPE_kwargs') -> bool:
        return args[0] in self.variables

    @FeatureNew('unset_variable', '0.60.0')
    @typed_pos_args('unset_variable', str)
    @noKwargs
    def func_unset_variable(self, node: mparser.BaseNode, args: T.Tuple[str], kwargs: 'TYPE_kwargs') -> None:
        varname = args[0]
        try:
            del self.variables[varname]
        except KeyError:
            raise InterpreterException(f'Tried to unset unknown variable "{varname}".')

    @staticmethod
    def machine_from_native_kwarg(kwargs: T.Dict[str, T.Any]) -> MachineChoice:
        native = kwargs.get('native', False)
        if not isinstance(native, bool):
            raise InvalidArguments('Argument to "native" must be a boolean.')
        return MachineChoice.BUILD if native else MachineChoice.HOST

    @FeatureNew('is_disabler', '0.52.0')
    @typed_pos_args('is_disabler', object)
    @noKwargs
    def func_is_disabler(self, node: mparser.BaseNode, args: T.Tuple[object], kwargs: 'TYPE_kwargs') -> bool:
        return isinstance(args[0], Disabler)

    @noKwargs
    @FeatureNew('range', '0.58.0')
    @typed_pos_args('range', int, optargs=[int, int])
    def func_range(self, node, args: T.Tuple[int, T.Optional[int], T.Optional[int]], kwargs: T.Dict[str, T.Any]) -> P_OBJ.RangeHolder:
        start, stop, step = args
        # Just like Python's range, we allow range(stop), range(start, stop), or
        # range(start, stop, step)
        if stop is None:
            stop = start
            start = 0
        if step is None:
            step = 1
        # This is more strict than Python's range()
        if start < 0:
            raise InterpreterException('start cannot be negative')
        if stop < start:
            raise InterpreterException('stop cannot be less than start')
        if step < 1:
            raise InterpreterException('step must be >=1')
        return P_OBJ.RangeHolder(start, stop, step, subproject=self.subproject)
