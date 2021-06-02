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
from ..wrap import wrap, WrapMode
from .. import mesonlib
from ..mesonlib import FileMode, MachineChoice, OptionKey, listify, extract_as_list, has_path_sep, unholder
from ..programs import ExternalProgram, NonExistingExternalProgram
from ..dependencies import Dependency, NotFoundDependency, DependencyException
from ..depfile import DepFile
from ..interpreterbase import InterpreterBase, typed_pos_args
from ..interpreterbase import noPosargs, noKwargs, stringArgs, permittedKwargs, noArgsFlattening
from ..interpreterbase import InterpreterException, InvalidArguments, InvalidCode, SubdirDoneRequest
from ..interpreterbase import InterpreterObject, Disabler, disablerIfNotFound
from ..interpreterbase import FeatureNew, FeatureDeprecated, FeatureNewKwargs, FeatureDeprecatedKwargs
from ..interpreterbase import ObjectHolder, RangeHolder
from ..modules import ModuleObject, MutableModuleObject
from ..cmake import CMakeInterpreter
from ..backend.backends import Backend, ExecutableSerialisation

from .mesonmain import MesonMain
from .compiler import CompilerHolder
from .interpreterobjects import (SubprojectHolder, MachineHolder, EnvironmentVariablesHolder,
                                 FeatureOptionHolder, ExternalProgramHolder, CustomTargetHolder,
                                 RunTargetHolder, IncludeDirsHolder, ConfigurationDataHolder,
                                 DependencyHolder, ModuleObjectHolder, GeneratedListHolder,
                                 TargetHolder, CustomTargetIndexHolder, GeneratedObjectsHolder,
                                 StaticLibraryHolder, ExecutableHolder, SharedLibraryHolder,
                                 SharedModuleHolder, HeadersHolder, BothLibrariesHolder,
                                 BuildTargetHolder, DataHolder, JarHolder, Test, RunProcess,
                                 ManHolder, GeneratorHolder, InstallDirHolder, extract_required_kwarg,
                                 extract_search_dirs, MutableModuleObjectHolder)

from pathlib import Path
import os
import shutil
import uuid
import re
import stat
import collections
import typing as T

import importlib

if T.TYPE_CHECKING:
    from ..compilers import Compiler
    from ..envconfig import MachineInfo
    from ..environment import Environment

    # Input source types passed to Targets
    SourceInputs = T.Union[mesonlib.File, GeneratedListHolder, TargetHolder,
                           CustomTargetIndexHolder, GeneratedObjectsHolder, str]
    # Input source types passed to the build.Target5 classes
    SourceOutputs = T.Union[mesonlib.File, build.GeneratedList,
                            build.BuildTarget, build.CustomTargetIndex,
                            build.GeneratedList]

def stringifyUserArguments(args, quote=False):
    if isinstance(args, list):
        return '[%s]' % ', '.join([stringifyUserArguments(x, True) for x in args])
    elif isinstance(args, dict):
        return '{%s}' % ', '.join(['{} : {}'.format(stringifyUserArguments(k, True), stringifyUserArguments(v, True)) for k, v in args.items()])
    elif isinstance(args, int):
        return str(args)
    elif isinstance(args, str):
        return f"'{args}'" if quote else args
    raise InvalidArguments('Function accepts only strings, integers, lists, dictionaries and lists thereof.')

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
                i = unholder(i)
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
    {'target_type'}
)

permitted_test_kwargs = {
    'args',
    'depends',
    'env',
    'priority',
    'protocol',
    'should_fail',
    'suite',
    'timeout',
    'workdir',
}

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

class Interpreter(InterpreterBase):

    def __init__(
                self,
                build: build.Build,
                backend: T.Optional[Backend] = None,
                subproject: str = '',
                subdir: str = '',
                subproject_dir: str = 'subprojects',
                modules: T.Optional[T.Dict[str, ModuleObject]] = None,
                default_project_options: T.Optional[T.Dict[str, str]] = None,
                mock: bool = False,
                ast: T.Optional[mparser.CodeBlockNode] = None,
                is_translated: bool = False,
            ) -> None:
        super().__init__(build.environment.get_source_dir(), subdir, subproject)
        self.an_unpicklable_object = mesonlib.an_unpicklable_object
        self.build = build
        self.environment = build.environment
        self.coredata = self.environment.get_coredata()
        self.backend = backend
        self.summary = {}
        if modules is None:
            self.modules = {}
        else:
            self.modules = modules
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
        self.builtin.update({'meson': MesonMain(build, self)})
        self.generators = []
        self.processed_buildfiles = set() # type: T.Set[str]
        self.project_args_frozen = False
        self.global_args_frozen = False  # implies self.project_args_frozen
        self.subprojects = {}
        self.subproject_stack = []
        self.configure_file_outputs = {}
        # Passed from the outside, only used in subprojects.
        if default_project_options:
            self.default_project_options = default_project_options.copy()
        else:
            self.default_project_options = {}
        self.project_default_options = {}
        self.build_func_dict()

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
            MachineHolder(self.build.environment.machines.build)
        self.builtin['host_machine'] = \
            MachineHolder(self.build.environment.machines.host)
        self.builtin['target_machine'] = \
            MachineHolder(self.build.environment.machines.target)

    # TODO: Why is this in interpreter.py and not CoreData or Environment?
    def get_non_matching_default_options(self) -> T.Iterator[T.Tuple[str, str, coredata.UserOption]]:
        for def_opt_name, def_opt_value in self.project_default_options.items():
            cur_opt_value = self.coredata.options.get(def_opt_name)
            try:
                if cur_opt_value is not None and cur_opt_value.validate_value(def_opt_value) != cur_opt_value.value:
                    yield (str(def_opt_name), def_opt_value, cur_opt_value)
            except mesonlib.MesonException:
                # Since the default value does not validate, it cannot be in use
                # Report the user-specified value as non-matching
                yield (str(def_opt_name), def_opt_value, cur_opt_value)

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
                           'shared_library': self.func_shared_lib,
                           'shared_module': self.func_shared_module,
                           'static_library': self.func_static_lib,
                           'both_libraries': self.func_both_lib,
                           'test': self.func_test,
                           'vcs_tag': self.func_vcs_tag,
                           'range': self.func_range,
                           })
        if 'MESON_UNIT_TEST' in os.environ:
            self.funcs.update({'exception': self.func_exception})

    def holderify(self, item):
        if isinstance(item, list):
            return [self.holderify(x) for x in item]
        if isinstance(item, dict):
            return {k: self.holderify(v) for k, v in item.items()}

        if isinstance(item, build.CustomTarget):
            return CustomTargetHolder(item, self)
        elif isinstance(item, (int, str, bool, Disabler, InterpreterObject, mesonlib.File)) or item is None:
            return item
        elif isinstance(item, build.Executable):
            return ExecutableHolder(item, self)
        elif isinstance(item, build.GeneratedList):
            return GeneratedListHolder(item)
        elif isinstance(item, build.RunTarget):
            raise RuntimeError('This is not a pipe.')
        elif isinstance(item, ExecutableSerialisation):
            raise RuntimeError('Do not do this.')
        elif isinstance(item, build.Data):
            return DataHolder(item)
        elif isinstance(item, dependencies.Dependency):
            return DependencyHolder(item, self.subproject)
        elif isinstance(item, ExternalProgram):
            return ExternalProgramHolder(item, self.subproject)
        elif isinstance(item, MutableModuleObject):
            return MutableModuleObjectHolder(item, self)
        elif isinstance(item, ModuleObject):
            return ModuleObjectHolder(item, self)
        elif isinstance(item, (InterpreterObject, ObjectHolder)):
            return item
        else:
            raise InterpreterException('Module returned a value of unknown type.')

    def process_new_values(self, invalues):
        invalues = listify(invalues)
        for v in invalues:
            if isinstance(v, (RunTargetHolder, CustomTargetHolder, BuildTargetHolder)):
                v = v.held_object

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
                raise InterpreterException('Module returned a value of unknown type.')

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
                kwargs = {'fallback': di,
                          'native': for_machine is MachineChoice.BUILD,
                          }
                name = display_name = l + '_stdlib'
                dep = self.dependency_impl(name, display_name, kwargs, force_fallback=True)
                self.build.stdlibs[for_machine][l] = dep

    def import_module(self, modname):
        if modname in self.modules:
            return
        try:
            module = importlib.import_module('mesonbuild.modules.' + modname)
        except ImportError:
            raise InvalidArguments(f'Module "{modname}" does not exist')
        ext_module = module.initialize(self)
        assert isinstance(ext_module, ModuleObject)
        self.modules[modname] = ext_module

    @stringArgs
    @noKwargs
    def func_import(self, node, args, kwargs):
        if len(args) != 1:
            raise InvalidCode('Import takes one argument.')
        modname = args[0]
        if modname.startswith('unstable-'):
            plainname = modname.split('-', 1)[1]
            try:
                # check if stable module exists
                self.import_module(plainname)
                mlog.warning(f'Module {modname} is now stable, please use the {plainname} module instead.')
                modname = plainname
            except InvalidArguments:
                mlog.warning('Module %s has no backwards or forwards compatibility and might not exist in future releases.' % modname, location=node)
                modname = 'unstable_' + plainname
        self.import_module(modname)
        return ModuleObjectHolder(self.modules[modname], self)

    @stringArgs
    @noKwargs
    def func_files(self, node, args, kwargs):
        return [mesonlib.File.from_source_file(self.environment.source_dir, self.subdir, fname) for fname in args]

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
                      'variables' })
    @noPosargs
    def func_declare_dependency(self, node, args, kwargs):
        version = kwargs.get('version', self.project_version)
        if not isinstance(version, str):
            raise InterpreterException('Version must be a string.')
        incs = self.extract_incdirs(kwargs)
        libs = unholder(extract_as_list(kwargs, 'link_with'))
        libs_whole = unholder(extract_as_list(kwargs, 'link_whole'))
        sources = extract_as_list(kwargs, 'sources')
        sources = unholder(listify(self.source_strings_to_files(sources)))
        deps = unholder(extract_as_list(kwargs, 'dependencies'))
        compile_args = mesonlib.stringlistify(kwargs.get('compile_args', []))
        link_args = mesonlib.stringlistify(kwargs.get('link_args', []))
        variables = self.extract_variables(kwargs, list_new=True)
        final_deps = []
        for d in deps:
            try:
                d = d.held_object
            except Exception:
                pass
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
        return DependencyHolder(dep, self.subproject)

    @noKwargs
    def func_assert(self, node, args, kwargs):
        if len(args) == 1:
            FeatureNew.single_use('assert function without message argument', '0.53.0', self.subproject)
            value = args[0]
            message = None
        elif len(args) == 2:
            value, message = args
            if not isinstance(message, str):
                raise InterpreterException('Assert message not a string.')
        else:
            raise InterpreterException('Assert takes between one and two arguments')
        if not isinstance(value, bool):
            raise InterpreterException('Assert value not bool.')
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
                raise InvalidArguments('Expected %d arguments, got %d.' %
                                       (argcount, len(args)))
        for actual, wanted in zip(args, arg_types):
            if wanted is not None:
                if not isinstance(actual, wanted):
                    raise InvalidArguments('Incorrect argument type.')

    @FeatureNewKwargs('run_command', '0.50.0', ['env'])
    @FeatureNewKwargs('run_command', '0.47.0', ['check', 'capture'])
    @permittedKwargs({'check', 'capture', 'env'})
    def func_run_command(self, node, args, kwargs):
        return self.run_command_impl(node, args, kwargs)

    def run_command_impl(self, node, args, kwargs, in_builddir=False):
        if len(args) < 1:
            raise InterpreterException('Not enough arguments')
        cmd, *cargs = args
        capture = kwargs.get('capture', True)
        srcdir = self.environment.get_source_dir()
        builddir = self.environment.get_build_dir()

        check = kwargs.get('check', False)
        if not isinstance(check, bool):
            raise InterpreterException('Check must be boolean.')

        env = self.unpack_env_kwarg(kwargs)

        m = 'must be a string, or the output of find_program(), files() '\
            'or configure_file(), or a compiler object; not {!r}'
        expanded_args = []
        if isinstance(cmd, ExternalProgramHolder):
            cmd = cmd.held_object
            if isinstance(cmd, build.Executable):
                progname = node.args.arguments[0].value
                msg = 'Program {!r} was overridden with the compiled executable {!r}'\
                      ' and therefore cannot be used during configuration'
                raise InterpreterException(msg.format(progname, cmd.description()))
            if not cmd.found():
                raise InterpreterException(f'command {cmd.get_name()!r} not found or not executable')
        elif isinstance(cmd, CompilerHolder):
            exelist = cmd.compiler.get_exelist()
            cmd = exelist[0]
            prog = ExternalProgram(cmd, silent=True)
            if not prog.found():
                raise InterpreterException('Program {!r} not found '
                                           'or not executable'.format(cmd))
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
                raise InterpreterException('Program or command {!r} not found '
                                           'or not executable'.format(cmd))
            cmd = prog
        for a in listify(cargs):
            if isinstance(a, str):
                expanded_args.append(a)
            elif isinstance(a, mesonlib.File):
                expanded_args.append(a.absolute_path(srcdir, builddir))
            elif isinstance(a, ExternalProgramHolder):
                expanded_args.append(a.held_object.get_path())
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

    @stringArgs
    def func_gettext(self, nodes, args, kwargs):
        raise InterpreterException('Gettext() function has been moved to module i18n. Import it and use i18n.gettext() instead')

    def func_option(self, nodes, args, kwargs):
        raise InterpreterException('Tried to call option() in build description file. All options must be in the option file.')

    @FeatureNewKwargs('subproject', '0.38.0', ['default_options'])
    @permittedKwargs({'version', 'default_options', 'required'})
    @stringArgs
    def func_subproject(self, nodes, args, kwargs):
        if len(args) != 1:
            raise InterpreterException('Subproject takes exactly one argument')
        subp_name = args[0]
        return self.do_subproject(subp_name, 'meson', kwargs)

    def disabled_subproject(self, subp_name, disabled_feature=None, exception=None):
        sub = SubprojectHolder(None, os.path.join(self.subproject_dir, subp_name),
                               disabled_feature=disabled_feature, exception=exception)
        self.subprojects[subp_name] = sub
        self.coredata.initialized_subprojects.add(subp_name)
        return sub

    def get_subproject(self, subp_name):
        sub = self.subprojects.get(subp_name)
        if sub and sub.found():
            return sub
        return None

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
            raise InvalidCode('Recursive include of subprojects: %s.' % incpath)
        if subp_name in self.subprojects:
            subproject = self.subprojects[subp_name]
            if required and not subproject.found():
                raise InterpreterException('Subproject "%s" required but not found.' % (subproject.subdir))
            return subproject

        r = self.environment.wrap_resolver
        try:
            subdir = r.resolve(subp_name, method, self.subproject)
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
        mlog.log(*m,'\n', nested=False)

        try:
            if method == 'meson':
                return self._do_subproject_meson(subp_name, subdir, default_options, kwargs)
            elif method == 'cmake':
                return self._do_subproject_cmake(subp_name, subdir, subdir_abs, default_options, kwargs)
            else:
                raise InterpreterException(f'The method {method} is invalid for the subproject {subp_name}')
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
                               self.modules, default_options, ast=ast, is_translated=is_translated)
            subi.subprojects = self.subprojects

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
        self.summary.update(subi.summary)
        return self.subprojects[subp_name]

    def _do_subproject_cmake(self, subp_name, subdir, subdir_abs, default_options, kwargs):
        with mlog.nested(subp_name):
            new_build = self.build.copy()
            prefix = self.coredata.options[OptionKey('prefix')].value

            from ..modules.cmake import CMakeSubprojectOptions
            options = unholder(kwargs.get('options', CMakeSubprojectOptions()))
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
                with open(meson_filename, "w") as f:
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

        maybe_v = self.environment.overrides.value_if_overridden(optname, self.subproject)
        if maybe_v is not None:
            return maybe_v

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

        raise InterpreterException('Tried to access unknown option "%s".' % optname)

    @stringArgs
    @noKwargs
    def func_get_option(self, nodes, args, kwargs):
        if len(args) != 1:
            raise InterpreterException('Argument required for get_option.')
        optname = args[0]
        if ':' in optname:
            raise InterpreterException('Having a colon in option name is forbidden, '
                                       'projects are not allowed to directly access '
                                       'options of other subprojects.')
        opt = self.get_option_internal(optname)
        if isinstance(opt, coredata.UserFeatureOption):
            return FeatureOptionHolder(self.environment, optname, opt)
        elif isinstance(opt, coredata.UserOption):
            return opt.value
        return opt

    @noKwargs
    def func_configuration_data(self, node, args, kwargs):
        if len(args) > 1:
            raise InterpreterException('configuration_data takes only one optional positional arguments')
        elif len(args) == 1:
            FeatureNew.single_use('configuration_data dictionary', '0.49.0', self.subproject)
            initial_values = args[0]
            if not isinstance(initial_values, dict):
                raise InterpreterException('configuration_data first argument must be a dictionary')
        else:
            initial_values = {}
        return ConfigurationDataHolder(self.subproject, initial_values)

    def set_backend(self):
        # The backend is already set when parsing subprojects
        if self.backend is not None:
            return
        backend = self.coredata.get_option(OptionKey('backend'))
        from ..backend import backends
        self.backend = backends.get_backend_from_name(backend, self.build, self)

        if self.backend is None:
            raise InterpreterException('Unknown backend "%s".' % backend)
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

    @stringArgs
    @permittedKwargs({'version', 'meson_version', 'default_options', 'license', 'subproject_dir'})
    def func_project(self, node, args, kwargs):
        if len(args) < 1:
            raise InvalidArguments('Not enough arguments to project(). Needs at least the project name.')
        proj_name, *proj_langs = args
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

        # If this is the first invocation we alway sneed to initialize
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
        self.build.dep_manifest[proj_name] = {'version': self.project_version,
                                              'license': proj_license}
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
            r = wrap.Resolver(self.environment.get_source_dir(), subdir, wrap_mode)
            if self.is_subproject():
                self.environment.wrap_resolver.merge_wraps(r)
            else:
                self.environment.wrap_resolver = r

        self.build.projects[self.subproject] = proj_name
        mlog.log('Project name:', mlog.bold(proj_name))
        mlog.log('Project version:', mlog.bold(self.project_version))

        self.add_languages(proj_langs, True, MachineChoice.HOST)
        self.add_languages(proj_langs, False, MachineChoice.BUILD)

        self.set_backend()
        if not self.is_subproject():
            self.check_stdlibs()

    @FeatureNewKwargs('add_languages', '0.54.0', ['native'])
    @permittedKwargs({'required', 'native'})
    @stringArgs
    def func_add_languages(self, node, args, kwargs):
        disabled, required, feature = extract_required_kwarg(kwargs, self.subproject)
        if disabled:
            for lang in sorted(args, key=compilers.sort_clink):
                mlog.log('Compiler for language', mlog.bold(lang), 'skipped: feature', mlog.bold(feature), 'disabled')
            return False
        if 'native' in kwargs:
            return self.add_languages(args, required, self.machine_from_native_kwarg(kwargs))
        else:
            # absent 'native' means 'both' for backwards compatibility
            tv = FeatureNew.get_target_version(self.subproject)
            if FeatureNew.check_version(tv, '0.54.0'):
                mlog.warning('add_languages is missing native:, assuming languages are wanted for both host and build.',
                             location=self.current_node)

            success = self.add_languages(args, False, MachineChoice.BUILD)
            success &= self.add_languages(args, required, MachineChoice.HOST)
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
        # Print all summaries, main project last.
        mlog.log('')  # newline
        main_summary = self.summary.pop('', None)
        for _, summary in sorted(self.summary.items()):
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
        if 'vala' in langs and 'c' not in langs:
            FeatureNew('Adding Vala language without C', '0.59.0').use(self.subproject)
            args.append('c')

        success = True
        for lang in sorted(args, key=compilers.sort_clink):
            clist = self.coredata.compilers[for_machine]
            machine_name = for_machine.get_lower_case_name()
            if lang in clist:
                comp = clist[lang]
            else:
                try:
                    comp = self.environment.detect_compiler_for(lang, for_machine)
                    if comp is None:
                        raise InvalidArguments('Tried to use unknown language "%s".' % lang)
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
        for p in unholder(prognames):
            if isinstance(p, mesonlib.File):
                continue # Always points to a local (i.e. self generated) file.
            if not isinstance(p, str):
                raise InterpreterException('Executable name must be a string')
            prog = ExternalProgram.from_bin_list(self.environment, for_machine, p)
            if prog.found():
                return ExternalProgramHolder(prog, self.subproject)
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
                raise InvalidArguments('find_program only accepts strings and '
                                       'files, not {!r}'.format(exename))
            extprog = ExternalProgram(exename, search_dir=search_dir,
                                      extra_search_dirs=extra_search_dirs,
                                      silent=True)
            progobj = ExternalProgramHolder(extprog, self.subproject)
            if progobj.found():
                extra_info.append(f"({' '.join(progobj.get_command())})")
                return progobj

    def program_from_overrides(self, command_names, extra_info):
        for name in command_names:
            if not isinstance(name, str):
                continue
            if name in self.build.find_overrides:
                exe = self.build.find_overrides[name]
                extra_info.append(mlog.blue('(overridden)'))
                return ExternalProgramHolder(exe, self.subproject, self.backend)
        return None

    def store_name_lookups(self, command_names):
        for name in command_names:
            if isinstance(name, str):
                self.build.searched_programs.add(name)

    def add_find_program_override(self, name, exe):
        if name in self.build.searched_programs:
            raise InterpreterException('Tried to override finding of executable "%s" which has already been found.'
                                       % name)
        if name in self.build.find_overrides:
            raise InterpreterException('Tried to override executable "%s" which has already been overridden.'
                                       % name)
        self.build.find_overrides[name] = exe

    def notfound_program(self, args):
        return ExternalProgramHolder(NonExistingExternalProgram(' '.join(args)), self.subproject)

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

        if not progobj.found():
            mlog.log('Program', mlog.bold(progobj.get_name()), 'found:', mlog.red('NO'))
            if required:
                m = 'Program {!r} not found'
                raise InterpreterException(m.format(progobj.get_name()))
            return progobj

        if wanted:
            if version_func:
                version = version_func(progobj)
            else:
                version = progobj.get_version(self)
            is_found, not_found, found = mesonlib.version_compare_many(version, wanted)
            if not is_found:
                mlog.log('Program', mlog.bold(progobj.get_name()), 'found:', mlog.red('NO'),
                         'found', mlog.normal_cyan(version), 'but need:',
                         mlog.bold(', '.join([f"'{e}'" for e in not_found])), *extra_info)
                if required:
                    m = 'Invalid version of program, need {!r} {!r} found {!r}.'
                    raise InterpreterException(m.format(progobj.get_name(), not_found, version))
                return self.notfound_program(args)
            extra_info.insert(0, mlog.normal_cyan(version))

        # Only store successful lookups
        self.store_name_lookups(args)
        mlog.log('Program', mlog.bold(progobj.get_name()), 'found:', mlog.green('YES'), *extra_info)
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
            progobj = ExternalProgramHolder(prog, self.subproject) if prog.found() else None
        if progobj is None and fallback and required:
            progobj = self.find_program_fallback(fallback, args, required, extra_info)

        return progobj

    def find_program_fallback(self, fallback, args, required, extra_info):
        mlog.log('Fallback to subproject', mlog.bold(fallback), 'which provides program',
                 mlog.bold(' '.join(args)))
        sp_kwargs = { 'required': required }
        self.do_subproject(fallback, 'meson', sp_kwargs)
        return self.program_from_overrides(args, extra_info)

    @FeatureNewKwargs('find_program', '0.53.0', ['dirs'])
    @FeatureNewKwargs('find_program', '0.52.0', ['version'])
    @FeatureNewKwargs('find_program', '0.49.0', ['disabler'])
    @disablerIfNotFound
    @permittedKwargs({'required', 'native', 'version', 'dirs'})
    def func_find_program(self, node, args, kwargs):
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

    def _find_cached_dep(self, name, display_name, kwargs):
        # Check if we want this as a build-time / build machine or runt-time /
        # host machine dep.
        for_machine = self.machine_from_native_kwarg(kwargs)
        identifier = dependencies.get_dep_identifier(name, kwargs)
        wanted_vers = mesonlib.stringlistify(kwargs.get('version', []))

        override = self.build.dependency_overrides[for_machine].get(identifier)
        if override:
            info = [mlog.blue('(overridden)' if override.explicit else '(cached)')]
            cached_dep = override.dep
            # We don't implicitly override not-found dependencies, but user could
            # have explicitly called meson.override_dependency() with a not-found
            # dep.
            if not cached_dep.found():
                mlog.log('Dependency', mlog.bold(display_name),
                         'found:', mlog.red('NO'), *info)
                return identifier, cached_dep
            found_vers = cached_dep.get_version()
            if not self.check_version(wanted_vers, found_vers):
                mlog.log('Dependency', mlog.bold(name),
                         'found:', mlog.red('NO'),
                         'found', mlog.normal_cyan(found_vers), 'but need:',
                         mlog.bold(', '.join([f"'{e}'" for e in wanted_vers])),
                         *info)
                return identifier, NotFoundDependency(self.environment)
        else:
            info = [mlog.blue('(cached)')]
            cached_dep = self.coredata.deps[for_machine].get(identifier)
            if cached_dep:
                found_vers = cached_dep.get_version()
                if not self.check_version(wanted_vers, found_vers):
                    return identifier, None

        if cached_dep:
            if found_vers:
                info = [mlog.normal_cyan(found_vers), *info]
            mlog.log('Dependency', mlog.bold(display_name),
                     'found:', mlog.green('YES'), *info)
            return identifier, cached_dep

        return identifier, None

    @staticmethod
    def check_version(wanted, found):
        if not wanted:
            return True
        if found == 'undefined' or not mesonlib.version_compare_many(found, wanted)[0]:
            return False
        return True

    def notfound_dependency(self):
        return DependencyHolder(NotFoundDependency(self.environment), self.subproject)

    def verify_fallback_consistency(self, subp_name, varname, cached_dep):
        subi = self.get_subproject(subp_name)
        if not cached_dep or not varname or not subi or not cached_dep.found():
            return
        dep = subi.get_variable_method([varname], {})
        if dep.held_object != cached_dep:
            m = 'Inconsistency: Subproject has overridden the dependency with another variable than {!r}'
            raise DependencyException(m.format(varname))

    def get_subproject_dep(self, name, display_name, subp_name, varname, kwargs):
        required = kwargs.get('required', True)
        wanted = mesonlib.stringlistify(kwargs.get('version', []))
        dep = self.notfound_dependency()

        # Verify the subproject is found
        subproject = self.subprojects.get(subp_name)
        if not subproject or not subproject.found():
            mlog.log('Dependency', mlog.bold(display_name), 'from subproject',
                     mlog.bold(subproject.subdir), 'found:', mlog.red('NO'),
                     mlog.blue('(subproject failed to configure)'))
            if required:
                m = 'Subproject {} failed to configure for dependency {}'
                raise DependencyException(m.format(subproject.subdir, display_name))
            return dep

        extra_info = []
        try:
            # Check if the subproject overridden the dependency
            _, cached_dep = self._find_cached_dep(name, display_name, kwargs)
            if cached_dep:
                if varname:
                    self.verify_fallback_consistency(subp_name, varname, cached_dep)
                if required and not cached_dep.found():
                    m = 'Dependency {!r} is not satisfied'
                    raise DependencyException(m.format(display_name))
                return DependencyHolder(cached_dep, self.subproject)
            elif varname is None:
                mlog.log('Dependency', mlog.bold(display_name), 'from subproject',
                         mlog.bold(subproject.subdir), 'found:', mlog.red('NO'))
                if required:
                    m = 'Subproject {} did not override dependency {}'
                    raise DependencyException(m.format(subproject.subdir, display_name))
                return self.notfound_dependency()
            else:
                # The subproject did not override the dependency, but we know the
                # variable name to take.
                dep = subproject.get_variable_method([varname], {})
        except InvalidArguments:
            # This is raised by get_variable_method() if varname does no exist
            # in the subproject. Just add the reason in the not-found message
            # that will be printed later.
            extra_info.append(mlog.blue(f'(Variable {varname!r} not found)'))

        if not isinstance(dep, DependencyHolder):
            raise InvalidCode('Fetched variable {!r} in the subproject {!r} is '
                              'not a dependency object.'.format(varname, subp_name))

        if not dep.found():
            mlog.log('Dependency', mlog.bold(display_name), 'from subproject',
                     mlog.bold(subproject.subdir), 'found:', mlog.red('NO'), *extra_info)
            if required:
                raise DependencyException('Could not find dependency {} in subproject {}'
                                          ''.format(varname, subp_name))
            return dep

        found = dep.held_object.get_version()
        if not self.check_version(wanted, found):
            mlog.log('Dependency', mlog.bold(display_name), 'from subproject',
                     mlog.bold(subproject.subdir), 'found:', mlog.red('NO'),
                     'found', mlog.normal_cyan(found), 'but need:',
                     mlog.bold(', '.join([f"'{e}'" for e in wanted])))
            if required:
                raise DependencyException('Version {} of subproject dependency {} already '
                                          'cached, requested incompatible version {} for '
                                          'dep {}'.format(found, subp_name, wanted, display_name))
            return self.notfound_dependency()

        found = mlog.normal_cyan(found) if found else None
        mlog.log('Dependency', mlog.bold(display_name), 'from subproject',
                 mlog.bold(subproject.subdir), 'found:', mlog.green('YES'), found)
        return dep

    def _handle_featurenew_dependencies(self, name):
        'Do a feature check on dependencies used by this subproject'
        if name == 'mpi':
            FeatureNew.single_use('MPI Dependency', '0.42.0', self.subproject)
        elif name == 'pcap':
            FeatureNew.single_use('Pcap Dependency', '0.42.0', self.subproject)
        elif name == 'vulkan':
            FeatureNew.single_use('Vulkan Dependency', '0.42.0', self.subproject)
        elif name == 'libwmf':
            FeatureNew.single_use('LibWMF Dependency', '0.44.0', self.subproject)
        elif name == 'openmp':
            FeatureNew.single_use('OpenMP Dependency', '0.46.0', self.subproject)

    # When adding kwargs, please check if they make sense in dependencies.get_dep_identifier()
    @FeatureNewKwargs('dependency', '0.57.0', ['cmake_package_version'])
    @FeatureNewKwargs('dependency', '0.54.0', ['components'])
    @FeatureNewKwargs('dependency', '0.52.0', ['include_type'])
    @FeatureNewKwargs('dependency', '0.50.0', ['not_found_message', 'cmake_module_path', 'cmake_args'])
    @FeatureNewKwargs('dependency', '0.49.0', ['disabler'])
    @FeatureNewKwargs('dependency', '0.40.0', ['method'])
    @FeatureNewKwargs('dependency', '0.38.0', ['default_options'])
    @disablerIfNotFound
    @permittedKwargs(permitted_dependency_kwargs)
    def func_dependency(self, node, args, kwargs):
        self.validate_arguments(args, 1, [str])
        name = args[0]
        display_name = name if name else '(anonymous)'
        mods = extract_as_list(kwargs, 'modules')
        if mods:
            display_name += ' (modules: {})'.format(', '.join(str(i) for i in mods))
        not_found_message = kwargs.get('not_found_message', '')
        if not isinstance(not_found_message, str):
            raise InvalidArguments('The not_found_message must be a string.')
        try:
            d = self.dependency_impl(name, display_name, kwargs)
        except Exception:
            if not_found_message:
                self.message_impl([not_found_message])
            raise
        assert isinstance(d, DependencyHolder)
        if not d.found() and not_found_message:
            self.message_impl([not_found_message])
            self.message_impl([not_found_message])
        # Override this dependency to have consistent results in subsequent
        # dependency lookups.
        if name and d.found():
            for_machine = self.machine_from_native_kwarg(kwargs)
            identifier = dependencies.get_dep_identifier(name, kwargs)
            if identifier not in self.build.dependency_overrides[for_machine]:
                self.build.dependency_overrides[for_machine][identifier] = \
                    build.DependencyOverride(d.held_object, node, explicit=False)
        # Ensure the correct include type
        if 'include_type' in kwargs:
            wanted = kwargs['include_type']
            actual = d.include_type_method([], {})
            if wanted != actual:
                mlog.debug(f'Current include type of {name} is {actual}. Converting to requested {wanted}')
                d = d.as_system_method([wanted], {})
        return d

    def dependency_impl(self, name, display_name, kwargs, force_fallback=False):
        disabled, required, feature = extract_required_kwarg(kwargs, self.subproject)
        if disabled:
            mlog.log('Dependency', mlog.bold(display_name), 'skipped: feature', mlog.bold(feature), 'disabled')
            return self.notfound_dependency()

        fallback = kwargs.get('fallback', None)
        allow_fallback = kwargs.get('allow_fallback', None)
        if allow_fallback is not None:
            FeatureNew.single_use('"allow_fallback" keyword argument for dependency', '0.56.0', self.subproject)
            if fallback is not None:
                raise InvalidArguments('"fallback" and "allow_fallback" arguments are mutually exclusive')
            if not isinstance(allow_fallback, bool):
                raise InvalidArguments('"allow_fallback" argument must be boolean')

        wrap_mode = self.coredata.get_option(OptionKey('wrap_mode'))
        force_fallback_for = self.coredata.get_option(OptionKey('force_fallback_for'))
        force_fallback |= (wrap_mode == WrapMode.forcefallback or
                           name in force_fallback_for)

        # If "fallback" is absent, look for an implicit fallback.
        if name and fallback is None and allow_fallback is not False:
            # Add an implicit fallback if we have a wrap file or a directory with the same name,
            # but only if this dependency is required. It is common to first check for a pkg-config,
            # then fallback to use find_library() and only afterward check again the dependency
            # with a fallback. If the fallback has already been configured then we have to use it
            # even if the dependency is not required.
            provider = self.environment.wrap_resolver.find_dep_provider(name)
            if not provider and allow_fallback is True:
                raise InvalidArguments('Fallback wrap or subproject not found for dependency \'%s\'' % name)
            subp_name = mesonlib.listify(provider)[0]
            force_fallback |= subp_name in force_fallback_for
            if provider and (allow_fallback is True or required or self.get_subproject(subp_name) or force_fallback):
                fallback = provider

        if 'default_options' in kwargs and not fallback:
            mlog.warning('The "default_options" keyword argument does nothing without a fallback subproject.',
                         location=self.current_node)

        # writing just "dependency('')" is an error, because it can only fail
        if name == '' and required and not fallback:
            raise InvalidArguments('Dependency is both required and not-found')

        if '<' in name or '>' in name or '=' in name:
            raise InvalidArguments('Characters <, > and = are forbidden in dependency names. To specify'
                                   'version\n requirements use the \'version\' keyword argument instead.')

        identifier, cached_dep = self._find_cached_dep(name, display_name, kwargs)
        if cached_dep:
            if fallback:
                subp_name, varname = self.get_subproject_infos(fallback)
                self.verify_fallback_consistency(subp_name, varname, cached_dep)
            if required and not cached_dep.found():
                m = 'Dependency {!r} was already checked and was not found'
                raise DependencyException(m.format(display_name))
            return DependencyHolder(cached_dep, self.subproject)

        if fallback:
            # If the dependency has already been configured, possibly by
            # a higher level project, try to use it first.
            subp_name, varname = self.get_subproject_infos(fallback)
            if self.get_subproject(subp_name):
                return self.get_subproject_dep(name, display_name, subp_name, varname, kwargs)
            force_fallback |= subp_name in force_fallback_for

        if name != '' and (not fallback or not force_fallback):
            self._handle_featurenew_dependencies(name)
            kwargs['required'] = required and not fallback
            dep = dependencies.find_external_dependency(name, self.environment, kwargs)
            kwargs['required'] = required
            # Only store found-deps in the cache
            # Never add fallback deps to self.coredata.deps since we
            # cannot cache them. They must always be evaluated else
            # we won't actually read all the build files.
            if dep.found():
                for_machine = self.machine_from_native_kwarg(kwargs)
                self.coredata.deps[for_machine].put(identifier, dep)
                return DependencyHolder(dep, self.subproject)

        if fallback:
            return self.dependency_fallback(name, display_name, fallback, kwargs)

        return self.notfound_dependency()

    @FeatureNew('disabler', '0.44.0')
    @noKwargs
    @noPosargs
    def func_disabler(self, node, args, kwargs):
        return Disabler()

    def get_subproject_infos(self, fbinfo):
        fbinfo = mesonlib.stringlistify(fbinfo)
        if len(fbinfo) == 1:
            FeatureNew.single_use('Fallback without variable name', '0.53.0', self.subproject)
            return fbinfo[0], None
        elif len(fbinfo) != 2:
            raise InterpreterException('Fallback info must have one or two items.')
        return fbinfo

    def dependency_fallback(self, name, display_name, fallback, kwargs):
        subp_name, varname = self.get_subproject_infos(fallback)
        required = kwargs.get('required', True)

        # Explicitly listed fallback preferences for specific subprojects
        # take precedence over wrap-mode
        force_fallback_for = self.coredata.get_option(OptionKey('force_fallback_for'))
        if name in force_fallback_for or subp_name in force_fallback_for:
            mlog.log('Looking for a fallback subproject for the dependency',
                     mlog.bold(display_name), 'because:\nUse of fallback was forced for that specific subproject')
        elif self.coredata.get_option(OptionKey('wrap_mode')) == WrapMode.nofallback:
            mlog.log('Not looking for a fallback subproject for the dependency',
                     mlog.bold(display_name), 'because:\nUse of fallback '
                     'dependencies is disabled.')
            if required:
                m = 'Dependency {!r} not found and fallback is disabled'
                raise DependencyException(m.format(display_name))
            return self.notfound_dependency()
        elif self.coredata.get_option(OptionKey('wrap_mode')) == WrapMode.forcefallback:
            mlog.log('Looking for a fallback subproject for the dependency',
                     mlog.bold(display_name), 'because:\nUse of fallback dependencies is forced.')
        else:
            mlog.log('Looking for a fallback subproject for the dependency',
                     mlog.bold(display_name))
        sp_kwargs = {
            'default_options': kwargs.get('default_options', []),
            'required': required,
        }
        self.do_subproject(subp_name, 'meson', sp_kwargs)
        return self.get_subproject_dep(name, display_name, subp_name, varname, kwargs)

    @FeatureNewKwargs('executable', '0.42.0', ['implib'])
    @FeatureNewKwargs('executable', '0.56.0', ['win_subsystem'])
    @FeatureDeprecatedKwargs('executable', '0.56.0', ['gui_app'], extra_message="Use 'win_subsystem' instead.")
    @permittedKwargs(build.known_exe_kwargs)
    def func_executable(self, node, args, kwargs):
        return self.build_target(node, args, kwargs, ExecutableHolder)

    @permittedKwargs(build.known_stlib_kwargs)
    def func_static_lib(self, node, args, kwargs):
        return self.build_target(node, args, kwargs, StaticLibraryHolder)

    @permittedKwargs(build.known_shlib_kwargs)
    def func_shared_lib(self, node, args, kwargs):
        holder = self.build_target(node, args, kwargs, SharedLibraryHolder)
        holder.held_object.shared_library_only = True
        return holder

    @permittedKwargs(known_library_kwargs)
    def func_both_lib(self, node, args, kwargs):
        return self.build_both_libraries(node, args, kwargs)

    @FeatureNew('shared_module', '0.37.0')
    @permittedKwargs(build.known_shmod_kwargs)
    def func_shared_module(self, node, args, kwargs):
        return self.build_target(node, args, kwargs, SharedModuleHolder)

    @permittedKwargs(known_library_kwargs)
    def func_library(self, node, args, kwargs):
        return self.build_library(node, args, kwargs)

    @permittedKwargs(build.known_jar_kwargs)
    def func_jar(self, node, args, kwargs):
        return self.build_target(node, args, kwargs, JarHolder)

    @FeatureNewKwargs('build_target', '0.40.0', ['link_whole', 'override_options'])
    @permittedKwargs(known_build_target_kwargs)
    def func_build_target(self, node, args, kwargs):
        if 'target_type' not in kwargs:
            raise InterpreterException('Missing target_type keyword argument')
        target_type = kwargs.pop('target_type')
        if target_type == 'executable':
            return self.build_target(node, args, kwargs, ExecutableHolder)
        elif target_type == 'shared_library':
            return self.build_target(node, args, kwargs, SharedLibraryHolder)
        elif target_type == 'shared_module':
            FeatureNew('build_target(target_type: \'shared_module\')',
                       '0.51.0').use(self.subproject)
            return self.build_target(node, args, kwargs, SharedModuleHolder)
        elif target_type == 'static_library':
            return self.build_target(node, args, kwargs, StaticLibraryHolder)
        elif target_type == 'both_libraries':
            return self.build_both_libraries(node, args, kwargs)
        elif target_type == 'library':
            return self.build_library(node, args, kwargs)
        elif target_type == 'jar':
            return self.build_target(node, args, kwargs, JarHolder)
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

    @stringArgs
    @FeatureNewKwargs('custom_target', '0.57.0', ['env'])
    @FeatureNewKwargs('custom_target', '0.48.0', ['console'])
    @FeatureNewKwargs('custom_target', '0.47.0', ['install_mode', 'build_always_stale'])
    @FeatureNewKwargs('custom_target', '0.40.0', ['build_by_default'])
    @permittedKwargs({'input', 'output', 'command', 'install', 'install_dir', 'install_mode',
                      'build_always', 'capture', 'depends', 'depend_files', 'depfile',
                      'build_by_default', 'build_always_stale', 'console', 'env'})
    def func_custom_target(self, node, args, kwargs):
        if len(args) != 1:
            raise InterpreterException('custom_target: Only one positional argument is allowed, and it must be a string name')
        if 'depfile' in kwargs and ('@BASENAME@' in kwargs['depfile'] or '@PLAINNAME@' in kwargs['depfile']):
            FeatureNew.single_use('substitutions in custom_target depfile', '0.47.0', self.subproject)
        return self._func_custom_target_impl(node, args, kwargs)

    def _func_custom_target_impl(self, node, args, kwargs):
        'Implementation-only, without FeatureNew checks, for internal use'
        name = args[0]
        kwargs['install_mode'] = self._get_kwarg_install_mode(kwargs)
        if 'input' in kwargs:
            try:
                kwargs['input'] = self.source_strings_to_files(extract_as_list(kwargs, 'input'))
            except mesonlib.MesonException:
                mlog.warning('''Custom target input \'%s\' can\'t be converted to File object(s).
This will become a hard error in the future.''' % kwargs['input'], location=self.current_node)
        kwargs['env'] = self.unpack_env_kwarg(kwargs)
        if 'command' in kwargs and isinstance(kwargs['command'], list) and kwargs['command']:
            if isinstance(kwargs['command'][0], str):
                kwargs['command'][0] = self.func_find_program(node, kwargs['command'][0], {})
        tg = CustomTargetHolder(build.CustomTarget(name, self.subdir, self.subproject, kwargs, backend=self.backend), self)
        self.add_target(name, tg.held_object)
        return tg

    @FeatureNewKwargs('run_target', '0.57.0', ['env'])
    @permittedKwargs({'command', 'depends', 'env'})
    def func_run_target(self, node, args, kwargs):
        if len(args) > 1:
            raise InvalidCode('Run_target takes only one positional argument: the target name.')
        elif len(args) == 1:
            if 'command' not in kwargs:
                raise InterpreterException('Missing "command" keyword argument')
            all_args = extract_as_list(kwargs, 'command')
            deps = unholder(extract_as_list(kwargs, 'depends'))
        else:
            raise InterpreterException('Run_target needs at least one positional argument.')

        cleaned_args = []
        for i in unholder(listify(all_args)):
            if not isinstance(i, (str, build.BuildTarget, build.CustomTarget, ExternalProgram, mesonlib.File)):
                mlog.debug('Wrong type:', str(i))
                raise InterpreterException('Invalid argument to run_target.')
            if isinstance(i, ExternalProgram) and not i.found():
                raise InterpreterException(f'Tried to use non-existing executable {i.name!r}')
            cleaned_args.append(i)
        if isinstance(cleaned_args[0], str):
            cleaned_args[0] = self.func_find_program(node, cleaned_args[0], {})
        name = args[0]
        if not isinstance(name, str):
            raise InterpreterException('First argument must be a string.')
        cleaned_deps = []
        for d in deps:
            if not isinstance(d, (build.BuildTarget, build.CustomTarget)):
                raise InterpreterException('Depends items must be build targets.')
            cleaned_deps.append(d)
        env = self.unpack_env_kwarg(kwargs)
        tg = RunTargetHolder(build.RunTarget(name, cleaned_args, cleaned_deps, self.subdir, self.subproject, env), self)
        self.add_target(name, tg.held_object)
        full_name = (self.subproject, name)
        assert(full_name not in self.build.run_target_names)
        self.build.run_target_names.add(full_name)
        return tg

    @FeatureNew('alias_target', '0.52.0')
    @noKwargs
    def func_alias_target(self, node, args, kwargs):
        if len(args) < 2:
            raise InvalidCode('alias_target takes at least 2 arguments.')
        name = args[0]
        if not isinstance(name, str):
            raise InterpreterException('First argument must be a string.')
        deps = unholder(listify(args[1:]))
        for d in deps:
            if not isinstance(d, (build.BuildTarget, build.CustomTarget)):
                raise InterpreterException('Depends items must be build targets.')
        tg = RunTargetHolder(build.AliasTarget(name, deps, self.subdir, self.subproject), self)
        self.add_target(name, tg.held_object)
        return tg

    @permittedKwargs({'arguments', 'output', 'depends', 'depfile', 'capture',
                      'preserve_path_from'})
    def func_generator(self, node, args, kwargs):
        gen = GeneratorHolder(self, args, kwargs)
        self.generators.append(gen)
        return gen

    @FeatureNewKwargs('benchmark', '0.46.0', ['depends'])
    @FeatureNewKwargs('benchmark', '0.52.0', ['priority'])
    @permittedKwargs(permitted_test_kwargs)
    def func_benchmark(self, node, args, kwargs):
        # is_parallel isn't valid here, so make sure it isn't passed
        if 'is_parallel' in kwargs:
            del kwargs['is_parallel']
        self.add_test(node, args, kwargs, False)

    @FeatureNewKwargs('test', '0.46.0', ['depends'])
    @FeatureNewKwargs('test', '0.52.0', ['priority'])
    @permittedKwargs(permitted_test_kwargs | {'is_parallel'})
    def func_test(self, node, args, kwargs):
        if kwargs.get('protocol') == 'gtest':
            FeatureNew.single_use('"gtest" protocol for tests', '0.55.0', self.subproject)
        self.add_test(node, args, kwargs, True)

    def unpack_env_kwarg(self, kwargs) -> build.EnvironmentVariables:
        envlist = kwargs.get('env', EnvironmentVariablesHolder())
        if isinstance(envlist, EnvironmentVariablesHolder):
            env = envlist.held_object
        elif isinstance(envlist, dict):
            FeatureNew.single_use('environment dictionary', '0.52.0', self.subproject)
            env = EnvironmentVariablesHolder(envlist)
            env = env.held_object
        else:
            # Convert from array to environment object
            env = EnvironmentVariablesHolder(envlist)
            env = env.held_object
        return env

    def make_test(self, node: mparser.BaseNode, args: T.List, kwargs: T.Dict[str, T.Any]):
        if len(args) != 2:
            raise InterpreterException('test expects 2 arguments, {} given'.format(len(args)))
        name = args[0]
        if not isinstance(name, str):
            raise InterpreterException('First argument of test must be a string.')
        if ':' in name:
            mlog.deprecation(f'":" is not allowed in test name "{name}", it has been replaced with "_"',
                             location=node)
            name = name.replace(':', '_')
        exe = args[1]
        if not isinstance(exe, (ExecutableHolder, JarHolder, ExternalProgramHolder)):
            if isinstance(exe, mesonlib.File):
                exe = self.func_find_program(node, args[1], {})
            else:
                raise InterpreterException('Second argument must be executable.')
        par = kwargs.get('is_parallel', True)
        if not isinstance(par, bool):
            raise InterpreterException('Keyword argument is_parallel must be a boolean.')
        cmd_args = unholder(extract_as_list(kwargs, 'args'))
        for i in cmd_args:
            if not isinstance(i, (str, mesonlib.File, build.Target)):
                raise InterpreterException('Command line arguments must be strings, files or targets.')
        env = self.unpack_env_kwarg(kwargs)
        should_fail = kwargs.get('should_fail', False)
        if not isinstance(should_fail, bool):
            raise InterpreterException('Keyword argument should_fail must be a boolean.')
        timeout = kwargs.get('timeout', 30)
        if not isinstance(timeout, int):
            raise InterpreterException('Timeout must be an integer.')
        if timeout <= 0:
            FeatureNew('test() timeout <= 0', '0.57.0').use(self.subproject)
        if 'workdir' in kwargs:
            workdir = kwargs['workdir']
            if not isinstance(workdir, str):
                raise InterpreterException('Workdir keyword argument must be a string.')
            if not os.path.isabs(workdir):
                raise InterpreterException('Workdir keyword argument must be an absolute path.')
        else:
            workdir = None
        protocol = kwargs.get('protocol', 'exitcode')
        if protocol not in {'exitcode', 'tap', 'gtest', 'rust'}:
            raise InterpreterException('Protocol must be one of "exitcode", "tap", "gtest", or "rust".')
        suite = []
        prj = self.subproject if self.is_subproject() else self.build.project_name
        for s in mesonlib.stringlistify(kwargs.get('suite', '')):
            if len(s) > 0:
                s = ':' + s
            suite.append(prj.replace(' ', '_').replace(':', '_') + s)
        depends = unholder(extract_as_list(kwargs, 'depends'))
        for dep in depends:
            if not isinstance(dep, (build.CustomTarget, build.BuildTarget)):
                raise InterpreterException('Depends items must be build targets.')
        priority = kwargs.get('priority', 0)
        if not isinstance(priority, int):
            raise InterpreterException('Keyword argument priority must be an integer.')
        return Test(name, prj, suite, exe.held_object, depends, par, cmd_args,
                    env, should_fail, timeout, workdir, protocol, priority)

    def add_test(self, node: mparser.BaseNode, args: T.List, kwargs: T.Dict[str, T.Any], is_base_test: bool):
        t = self.make_test(node, args, kwargs)
        if is_base_test:
            self.build.tests.append(t)
            mlog.debug('Adding test', mlog.bold(t.name, True))
        else:
            self.build.benchmarks.append(t)
            mlog.debug('Adding benchmark', mlog.bold(t.name, True))

    @FeatureNewKwargs('install_headers', '0.47.0', ['install_mode'])
    @permittedKwargs({'install_dir', 'install_mode', 'subdir'})
    def func_install_headers(self, node, args, kwargs):
        source_files = self.source_strings_to_files(args)
        install_mode = self._get_kwarg_install_mode(kwargs)

        install_subdir = kwargs.get('subdir', '')
        if not isinstance(install_subdir, str):
            raise InterpreterException('subdir keyword argument must be a string')
        elif os.path.isabs(install_subdir):
            mlog.deprecation('Subdir keyword must not be an absolute path. This will be a hard error in the next release.')

        install_dir = kwargs.get('install_dir', None)
        if install_dir is not None and not isinstance(install_dir, str):
            raise InterpreterException('install_dir keyword argument must be a string if provided')

        h = build.Headers(source_files, install_subdir, install_dir, install_mode, self.subproject)
        self.build.headers.append(h)

        return HeadersHolder(h)

    @FeatureNewKwargs('install_man', '0.47.0', ['install_mode'])
    @FeatureNewKwargs('install_man', '0.58.0', ['locale'])
    @permittedKwargs({'install_dir', 'install_mode', 'locale'})
    def func_install_man(self, node, args, kwargs):
        sources = self.source_strings_to_files(args)
        for s in sources:
            try:
                num = int(s.split('.')[-1])
            except (IndexError, ValueError):
                num = 0
            if num < 1 or num > 8:
                raise InvalidArguments('Man file must have a file extension of a number between 1 and 8')
        custom_install_mode = self._get_kwarg_install_mode(kwargs)
        custom_install_dir = kwargs.get('install_dir', None)
        locale = kwargs.get('locale')
        if custom_install_dir is not None and not isinstance(custom_install_dir, str):
            raise InterpreterException('install_dir must be a string.')

        m = build.Man(sources, custom_install_dir, custom_install_mode, self.subproject, locale)
        self.build.man.append(m)

        return ManHolder(m)

    @FeatureNewKwargs('subdir', '0.44.0', ['if_found'])
    @permittedKwargs({'if_found'})
    def func_subdir(self, node, args, kwargs):
        self.validate_arguments(args, 1, [str])
        mesonlib.check_direntry_issues(args)
        if '..' in args[0]:
            raise InvalidArguments('Subdir contains ..')
        if self.subdir == '' and args[0] == self.subproject_dir:
            raise InvalidArguments('Must not go into subprojects dir with subdir(), use subproject() instead.')
        if self.subdir == '' and args[0].startswith('meson-'):
            raise InvalidArguments('The "meson-" prefix is reserved and cannot be used for top-level subdir().')
        for i in mesonlib.extract_as_list(kwargs, 'if_found'):
            if not hasattr(i, 'found_method'):
                raise InterpreterException('Object used in if_found does not have a found method.')
            if not i.found_method([], {}):
                return
        prev_subdir = self.subdir
        subdir = os.path.join(prev_subdir, args[0])
        if os.path.isabs(subdir):
            raise InvalidArguments('Subdir argument must be a relative path.')
        absdir = os.path.join(self.environment.get_source_dir(), subdir)
        symlinkless_dir = os.path.realpath(absdir)
        build_file = os.path.join(symlinkless_dir, 'meson.build')
        if build_file in self.processed_buildfiles:
            raise InvalidArguments('Tried to enter directory "%s", which has already been visited.'
                                   % subdir)
        self.processed_buildfiles.add(build_file)
        self.subdir = subdir
        os.makedirs(os.path.join(self.environment.build_dir, subdir), exist_ok=True)
        buildfilename = os.path.join(self.subdir, environment.build_filename)
        self.build_def_files.append(buildfilename)
        absname = os.path.join(self.environment.get_source_dir(), buildfilename)
        if not os.path.isfile(absname):
            self.subdir = prev_subdir
            raise InterpreterException(f"Non-existent build file '{buildfilename!s}'")
        with open(absname, encoding='utf8') as f:
            code = f.read()
        assert(isinstance(code, str))
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

    @FeatureNewKwargs('install_data', '0.46.0', ['rename'])
    @FeatureNewKwargs('install_data', '0.38.0', ['install_mode'])
    @permittedKwargs({'install_dir', 'install_mode', 'rename', 'sources'})
    def func_install_data(self, node, args: T.List, kwargs: T.Dict[str, T.Any]):
        kwsource = mesonlib.stringlistify(kwargs.get('sources', []))
        raw_sources = args + kwsource
        sources: T.List[mesonlib.File] = []
        source_strings: T.List[str] = []
        for s in raw_sources:
            if isinstance(s, mesonlib.File):
                sources.append(s)
            elif isinstance(s, str):
                source_strings.append(s)
            else:
                raise InvalidArguments('Argument must be string or file.')
        sources += self.source_strings_to_files(source_strings)
        install_dir: T.Optional[str] = kwargs.get('install_dir', None)
        if install_dir is not None and not isinstance(install_dir, str):
            raise InvalidArguments('Keyword argument install_dir not a string.')
        install_mode = self._get_kwarg_install_mode(kwargs)
        rename: T.Optional[T.List[str]] = kwargs.get('rename', None)
        if rename is not None:
            rename = mesonlib.stringlistify(rename)
            if len(rename) != len(sources):
                raise InvalidArguments(
                    '"rename" and "sources" argument lists must be the same length if "rename" is given. '
                    f'Rename has {len(rename)} elements and sources has {len(sources)}.')

        data = DataHolder(build.Data(sources, install_dir, install_mode, self.subproject, rename))
        self.build.data.append(data.held_object)
        return data

    @FeatureNewKwargs('install_subdir', '0.42.0', ['exclude_files', 'exclude_directories'])
    @FeatureNewKwargs('install_subdir', '0.38.0', ['install_mode'])
    @permittedKwargs({'exclude_files', 'exclude_directories', 'install_dir', 'install_mode', 'strip_directory'})
    @stringArgs
    def func_install_subdir(self, node, args, kwargs):
        if len(args) != 1:
            raise InvalidArguments('Install_subdir requires exactly one argument.')
        subdir: str = args[0]
        if not isinstance(subdir, str):
            raise InvalidArguments('install_subdir positional argument 1 must be a string.')
        if 'install_dir' not in kwargs:
            raise InvalidArguments('Missing keyword argument install_dir')
        install_dir: str = kwargs['install_dir']
        if not isinstance(install_dir, str):
            raise InvalidArguments('Keyword argument install_dir not a string.')
        if 'strip_directory' in kwargs:
            strip_directory: bool = kwargs['strip_directory']
            if not isinstance(strip_directory, bool):
                raise InterpreterException('"strip_directory" keyword must be a boolean.')
        else:
            strip_directory = False
        if 'exclude_files' in kwargs:
            exclude: T.List[str] = extract_as_list(kwargs, 'exclude_files')
            for f in exclude:
                if not isinstance(f, str):
                    raise InvalidArguments('Exclude argument not a string.')
                elif os.path.isabs(f):
                    raise InvalidArguments('Exclude argument cannot be absolute.')
            exclude_files: T.Set[str] = set(exclude)
        else:
            exclude_files = set()
        if 'exclude_directories' in kwargs:
            exclude: T.List[str] = extract_as_list(kwargs, 'exclude_directories')
            for d in exclude:
                if not isinstance(d, str):
                    raise InvalidArguments('Exclude argument not a string.')
                elif os.path.isabs(d):
                    raise InvalidArguments('Exclude argument cannot be absolute.')
            exclude_directories: T.Set[str] = set(exclude)
        else:
            exclude_directories = set()
        exclude = (exclude_files, exclude_directories)
        install_mode = self._get_kwarg_install_mode(kwargs)
        idir = build.InstallDir(self.subdir, subdir, install_dir, install_mode, exclude, strip_directory, self.subproject)
        self.build.install_dirs.append(idir)
        return InstallDirHolder(idir)

    @FeatureNewKwargs('configure_file', '0.47.0', ['copy', 'output_format', 'install_mode', 'encoding'])
    @FeatureNewKwargs('configure_file', '0.46.0', ['format'])
    @FeatureNewKwargs('configure_file', '0.41.0', ['capture'])
    @FeatureNewKwargs('configure_file', '0.50.0', ['install'])
    @FeatureNewKwargs('configure_file', '0.52.0', ['depfile'])
    @permittedKwargs({'input', 'output', 'configuration', 'command', 'copy', 'depfile',
                      'install_dir', 'install_mode', 'capture', 'install', 'format',
                      'output_format', 'encoding'})
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
                conf = ConfigurationDataHolder(self.subproject, conf)
            elif not isinstance(conf, ConfigurationDataHolder):
                raise InterpreterException('Argument "configuration" is not of type configuration_data')
            mlog.log('Configuring', mlog.bold(output), 'using configuration')
            if len(inputs) > 1:
                raise InterpreterException('At most one input file can given in configuration mode')
            if inputs:
                os.makedirs(os.path.join(self.environment.build_dir, self.subdir), exist_ok=True)
                file_encoding = kwargs.setdefault('encoding', 'utf-8')
                missing_variables, confdata_useless = \
                    mesonlib.do_conf_file(inputs_abs[0], ofile_abs, conf.held_object,
                                          fmt, file_encoding)
                if missing_variables:
                    var_list = ", ".join(map(repr, sorted(missing_variables)))
                    mlog.warning(
                        "The variable(s) %s in the input file '%s' are not "
                        "present in the given configuration data." % (
                            var_list, inputs[0]), location=node)
                if confdata_useless:
                    ifbase = os.path.basename(inputs_abs[0])
                    mlog.warning('Got an empty configuration_data() object and found no '
                                 'substitutions in the input file {!r}. If you want to '
                                 'copy a file to the build dir, use the \'copy:\' keyword '
                                 'argument added in 0.47.0'.format(ifbase), location=node)
            else:
                mesonlib.dump_conf_header(ofile_abs, conf.held_object, output_format)
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
                raise InterpreterException('Running configure command failed.\n%s\n%s' %
                                           (res.stdout, res.stderr))
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
                with open(depfile) as f:
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
            mlog.deprecation('Please use the new `install:` kwarg instead of passing '
                             '`false` to `install_dir:`', location=node)
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
            self.build.data.append(build.Data([cfile], idir, install_mode, self.subproject))
        return mesonlib.File.from_built_file(self.subdir, output)

    def extract_incdirs(self, kwargs):
        prospectives = unholder(extract_as_list(kwargs, 'include_directories'))
        result = []
        for p in prospectives:
            if isinstance(p, build.IncludeDirs):
                result.append(p)
            elif isinstance(p, str):
                result.append(self.build_incdir_object([p]).held_object)
            else:
                raise InterpreterException('Include directory objects can only be created from strings or include directories.')
        return result

    @permittedKwargs({'is_system'})
    @stringArgs
    def func_include_directories(self, node, args, kwargs):
        return self.build_incdir_object(args, kwargs.get('is_system', False))

    def build_incdir_object(self, incdir_strings, is_system=False):
        if not isinstance(is_system, bool):
            raise InvalidArguments('Is_system must be boolean.')
        src_root = self.environment.get_source_dir()
        build_root = self.environment.get_build_dir()
        absbase_src = os.path.join(src_root, self.subdir)
        absbase_build = os.path.join(build_root, self.subdir)

        for a in incdir_strings:
            if a.startswith(src_root):
                raise InvalidArguments('Tried to form an absolute path to a source dir. '
                                       'You should not do that but use relative paths instead.'
                                       '''

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
''')
            else:
                try:
                    self.validate_within_subproject(self.subdir, a)
                except InterpreterException:
                    mlog.warning('include_directories sandbox violation!')
                    print(f'''The project is trying to access the directory {a} which belongs to a different
subproject. This is a problem as it hardcodes the relative paths of these two projeccts.
This makes it impossible to compile the project in any other directory layout and also
prevents the subproject from changing its own directory layout.

Instead of poking directly at the internals the subproject should be executed and
it should set a variable that the caller can then use. Something like:

# In subproject
some_dep = declare_depencency(include_directories: include_directories('include'))

# In parent project
some_dep = depencency('some')
executable(..., dependencies: [some_dep])

This warning will become a hard error in a future Meson release.
''')
            absdir_src = os.path.join(absbase_src, a)
            absdir_build = os.path.join(absbase_build, a)
            if not os.path.isdir(absdir_src) and not os.path.isdir(absdir_build):
                raise InvalidArguments('Include dir %s does not exist.' % a)
        i = IncludeDirsHolder(build.IncludeDirs(self.subdir, incdir_strings, is_system))
        return i

    @permittedKwargs({'exe_wrapper', 'gdb', 'timeout_multiplier', 'env', 'is_default',
                      'exclude_suites'})
    @stringArgs
    def func_add_test_setup(self, node, args, kwargs):
        if len(args) != 1:
            raise InterpreterException('Add_test_setup needs one argument for the setup name.')
        setup_name = args[0]
        if re.fullmatch('([_a-zA-Z][_0-9a-zA-Z]*:)?[_a-zA-Z][_0-9a-zA-Z]*', setup_name) is None:
            raise InterpreterException('Setup name may only contain alphanumeric characters.')
        if ":" not in setup_name:
            setup_name = (self.subproject if self.subproject else self.build.project_name) + ":" + setup_name
        try:
            inp = unholder(extract_as_list(kwargs, 'exe_wrapper'))
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
                raise InterpreterException('\'%s\' is already set as default. '
                                           'is_default can be set to true only once' % self.build.test_setup_default_name)
            self.build.test_setup_default_name = setup_name
        exclude_suites = mesonlib.stringlistify(kwargs.get('exclude_suites', []))
        env = self.unpack_env_kwarg(kwargs)
        self.build.test_setups[setup_name] = build.TestSetup(exe_wrapper, gdb, timeout_multiplier, env,
                                                             exclude_suites)

    @permittedKwargs({'language', 'native'})
    @stringArgs
    def func_add_global_arguments(self, node, args, kwargs):
        for_machine = self.machine_from_native_kwarg(kwargs)
        self.add_global_arguments(node, self.build.global_args[for_machine], args, kwargs)

    @permittedKwargs({'language', 'native'})
    @stringArgs
    def func_add_global_link_arguments(self, node, args, kwargs):
        for_machine = self.machine_from_native_kwarg(kwargs)
        self.add_global_arguments(node, self.build.global_link_args[for_machine], args, kwargs)

    @permittedKwargs({'language', 'native'})
    @stringArgs
    def func_add_project_arguments(self, node, args, kwargs):
        for_machine = self.machine_from_native_kwarg(kwargs)
        self.add_project_arguments(node, self.build.projects_args[for_machine], args, kwargs)

    @permittedKwargs({'language', 'native'})
    @stringArgs
    def func_add_project_link_arguments(self, node, args, kwargs):
        for_machine = self.machine_from_native_kwarg(kwargs)
        self.add_project_arguments(node, self.build.projects_link_args[for_machine], args, kwargs)

    def warn_about_builtin_args(self, args):
        # -Wpedantic is deliberately not included, since some people want to use it but not use -Wextra
        # see e.g.
        # https://github.com/mesonbuild/meson/issues/3275#issuecomment-641354956
        # https://github.com/mesonbuild/meson/issues/3742
        warnargs = ('/W1', '/W2', '/W3', '/W4', '/Wall', '-Wall', '-Wextra')
        optargs = ('-O0', '-O2', '-O3', '-Os', '/O1', '/O2', '/Os')
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

    def add_global_arguments(self, node, argsdict, args, kwargs):
        if self.is_subproject():
            msg = 'Function \'{}\' cannot be used in subprojects because ' \
                  'there is no way to make that reliable.\nPlease only call ' \
                  'this if is_subproject() returns false. Alternatively, ' \
                  'define a variable that\ncontains your language-specific ' \
                  'arguments and add it to the appropriate *_args kwarg ' \
                  'in each target.'.format(node.func_name)
            raise InvalidCode(msg)
        frozen = self.project_args_frozen or self.global_args_frozen
        self.add_arguments(node, argsdict, frozen, args, kwargs)

    def add_project_arguments(self, node, argsdict, args, kwargs):
        if self.subproject not in argsdict:
            argsdict[self.subproject] = {}
        self.add_arguments(node, argsdict[self.subproject],
                           self.project_args_frozen, args, kwargs)

    def add_arguments(self, node, argsdict, args_frozen, args, kwargs):
        if args_frozen:
            msg = 'Tried to use \'{}\' after a build target has been declared.\n' \
                  'This is not permitted. Please declare all ' \
                  'arguments before your targets.'.format(node.func_name)
            raise InvalidCode(msg)

        if 'language' not in kwargs:
            raise InvalidCode(f'Missing language definition in {node.func_name}')

        self.warn_about_builtin_args(args)

        for lang in mesonlib.stringlistify(kwargs['language']):
            lang = lang.lower()
            argsdict[lang] = argsdict.get(lang, []) + args

    @noKwargs
    @noArgsFlattening
    def func_environment(self, node, args, kwargs):
        if len(args) > 1:
            raise InterpreterException('environment takes only one optional positional arguments')
        elif len(args) == 1:
            FeatureNew.single_use('environment positional arguments', '0.52.0', self.subproject)
            initial_values = args[0]
            if not isinstance(initial_values, dict) and not isinstance(initial_values, list):
                raise InterpreterException('environment first argument must be a dictionary or a list')
        else:
            initial_values = {}
        return EnvironmentVariablesHolder(initial_values, self.subproject)

    @stringArgs
    @noKwargs
    def func_join_paths(self, node, args, kwargs):
        return self.join_path_strings(args)

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

    def source_strings_to_files(self, sources: T.List['SourceInputs']) -> T.List['SourceOutputs']:
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
            elif isinstance(s, (GeneratedListHolder, TargetHolder,
                                CustomTargetIndexHolder,
                                GeneratedObjectsHolder)):
                results.append(unholder(s))
            else:
                raise InterpreterException(f'Source item is {s!r} instead of '
                                           'string or File-type object')
        return results

    def add_target(self, name, tobj):
        if name == '':
            raise InterpreterException('Target name must not be empty.')
        if name.strip() == '':
            raise InterpreterException('Target name must not consist only of whitespace.')
        if name.startswith('meson-'):
            raise InvalidArguments("Target names starting with 'meson-' are reserved "
                                   "for Meson's internal use. Please rename.")
        if name in coredata.FORBIDDEN_TARGET_NAMES:
            raise InvalidArguments("Target name '%s' is reserved for Meson's "
                                   "internal use. Please rename." % name)
        # To permit an executable and a shared library to have the
        # same name, such as "foo.exe" and "libfoo.a".
        idname = tobj.get_id()
        if idname in self.build.targets:
            raise InvalidCode('Tried to create target "%s", but a target of that name already exists.' % name)
        self.build.targets[idname] = tobj
        if idname not in self.coredata.target_guids:
            self.coredata.target_guids[idname] = str(uuid.uuid4()).upper()

    @FeatureNew('both_libraries', '0.46.0')
    def build_both_libraries(self, node, args, kwargs):
        shared_holder = self.build_target(node, args, kwargs, SharedLibraryHolder)

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
            static_kwargs['objects'] = shared_holder.held_object.extract_all_objects()
        else:
            static_args = args
            static_kwargs = kwargs

        static_holder = self.build_target(node, static_args, static_kwargs, StaticLibraryHolder)

        return BothLibrariesHolder(shared_holder, static_holder, self)

    def build_library(self, node, args, kwargs):
        default_library = self.coredata.get_option(OptionKey('default_library', subproject=self.subproject))
        if default_library == 'shared':
            return self.build_target(node, args, kwargs, SharedLibraryHolder)
        elif default_library == 'static':
            return self.build_target(node, args, kwargs, StaticLibraryHolder)
        elif default_library == 'both':
            return self.build_both_libraries(node, args, kwargs)
        else:
            raise InterpreterException('Unknown default_library value: %s.', default_library)

    def build_target(self, node, args, kwargs, targetholder):
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
        if targetholder == ExecutableHolder:
            targetclass = build.Executable
        elif targetholder == SharedLibraryHolder:
            targetclass = build.SharedLibrary
        elif targetholder == SharedModuleHolder:
            targetclass = build.SharedModule
        elif targetholder == StaticLibraryHolder:
            targetclass = build.StaticLibrary
        elif targetholder == JarHolder:
            targetclass = build.Jar
        else:
            mlog.debug('Unknown target type:', str(targetholder))
            raise RuntimeError('Unreachable code')
        self.kwarg_strings_to_includedirs(kwargs)

        # Filter out kwargs from other target types. For example 'soversion'
        # passed to library() when default_library == 'static'.
        kwargs = {k: v for k, v in kwargs.items() if k in targetclass.known_kwargs}

        kwargs['include_directories'] = self.extract_incdirs(kwargs)
        target = targetclass(name, self.subdir, self.subproject, for_machine, sources, objs, self.environment, kwargs)
        target.project_version = self.project_version

        self.add_stdlib_info(target)
        l = targetholder(target, self)
        self.add_target(name, l.held_object)
        self.project_args_frozen = True
        return l

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
                raise InterpreterException('Tried to add non-existing source file %s.' % s)

    # Only permit object extraction from the same subproject
    def validate_extraction(self, buildtarget: InterpreterObject) -> None:
        if self.subproject != buildtarget.subproject:
            raise InterpreterException('Tried to extract objects from a different subproject.')

    def is_subproject(self):
        return self.subproject != ''

    @noKwargs
    @noArgsFlattening
    def func_set_variable(self, node, args, kwargs):
        if len(args) != 2:
            raise InvalidCode('Set_variable takes two arguments.')
        varname, value = args
        self.set_variable(varname, value)

    @noKwargs
    @noArgsFlattening
    def func_get_variable(self, node, args, kwargs):
        if len(args) < 1 or len(args) > 2:
            raise InvalidCode('Get_variable takes one or two arguments.')
        varname = args[0]
        if isinstance(varname, Disabler):
            return varname
        if not isinstance(varname, str):
            raise InterpreterException('First argument must be a string.')
        try:
            return self.variables[varname]
        except KeyError:
            pass
        if len(args) == 2:
            return args[1]
        raise InterpreterException('Tried to get unknown variable "%s".' % varname)

    @stringArgs
    @noKwargs
    def func_is_variable(self, node, args, kwargs):
        if len(args) != 1:
            raise InvalidCode('Is_variable takes two arguments.')
        varname = args[0]
        return varname in self.variables

    @staticmethod
    def machine_from_native_kwarg(kwargs: T.Dict[str, T.Any]) -> MachineChoice:
        native = kwargs.get('native', False)
        if not isinstance(native, bool):
            raise InvalidArguments('Argument to "native" must be a boolean.')
        return MachineChoice.BUILD if native else MachineChoice.HOST

    @FeatureNew('is_disabler', '0.52.0')
    @noKwargs
    def func_is_disabler(self, node, args, kwargs):
        if len(args) != 1:
            raise InvalidCode('Is_disabler takes one argument.')
        varname = args[0]
        return isinstance(varname, Disabler)

    @noKwargs
    @FeatureNew('range', '0.58.0')
    @typed_pos_args('range', int, optargs=[int, int])
    def func_range(self, node, args: T.Tuple[int, T.Optional[int], T.Optional[int]], kwargs: T.Dict[str, T.Any]) -> RangeHolder:
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
        return RangeHolder(start, stop, step)
