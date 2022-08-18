# Copyright 2018 The Meson development team

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
from pathlib import Path
import functools
import json
import os
import shutil
import typing as T

from . import ExtensionModule, ModuleInfo
from .. import build
from .. import mesonlib
from .. import mlog
from ..coredata import UserFeatureOption
from ..dependencies import DependencyMethods, PkgConfigDependency, NotFoundDependency, SystemDependency, ExtraFrameworkDependency
from ..dependencies.base import process_method_kw
from ..dependencies.detect import get_dep_identifier
from ..environment import detect_cpu_family
from ..interpreter import ExternalProgramHolder, extract_required_kwarg, permitted_dependency_kwargs
from ..interpreter.type_checking import PRESERVE_PATH_KW, SHARED_MOD_KWS, NoneType
from ..interpreterbase import (
    noPosargs, noKwargs, permittedKwargs, ContainerTypeInfo,
    InvalidArguments, typed_pos_args, typed_kwargs, KwargInfo,
    FeatureNew, FeatureNewKwargs, disablerIfNotFound
)
from ..mesonlib import MachineChoice
from ..programs import ExternalProgram, NonExistingExternalProgram

if T.TYPE_CHECKING:
    from typing_extensions import TypedDict

    from . import ModuleState
    from ..build import SharedModule, Data
    from ..dependencies import ExternalDependency, Dependency
    from ..dependencies.factory import DependencyGenerator
    from ..environment import Environment
    from ..interpreter import Interpreter
    from ..interpreter.interpreter import BuildTargetSource
    from ..interpreter.kwargs import ExtractRequired, SharedModule as _SharedModuleKW, BuildTarget
    from ..interpreterbase.interpreterbase import TYPE_var, TYPE_kwargs

    class PythonIntrospectionDict(TypedDict):

        install_paths: T.Dict[str, str]
        is_pypy: bool
        is_venv: bool
        link_libpython: bool
        sysconfig_paths: T.Dict[str, str]
        paths: T.Dict[str, str]
        platform: str
        suffix: str
        variables: T.Dict[str, str]
        version: str

    class PyInstallKw(TypedDict):

        pure: bool
        subdir: str
        install_tag: T.Optional[str]

    class FindInstallationKw(ExtractRequired):

        disabler: bool
        modules: T.List[str]

    class ExtensionModuleKw(_SharedModuleKW):

        subdir: str

    _Base = ExternalDependency
else:
    _Base = object


_PURE_KW = KwargInfo('pure', bool, default=True)
_SUBDIR_KW = KwargInfo('subdir', str, default='')

_MOD_KWARGS = [k for k in SHARED_MOD_KWS if k.name not in {'name_prefix', 'name_suffix'}]
_MOD_KWARGS.append(_SUBDIR_KW)


class _PythonDependencyBase(_Base):

    def __init__(self, python_holder: 'PythonInstallation', embed: bool):
        self.name = 'python'  # override the name from the "real" dependency lookup
        self.embed = embed
        self.version: str = python_holder.version
        self.platform = python_holder.platform
        self.variables = python_holder.variables
        self.paths = python_holder.paths
        self.link_libpython = python_holder.link_libpython
        self.info: T.Optional[T.Dict[str, str]] = None
        if mesonlib.version_compare(self.version, '>= 3.0'):
            self.major_version = 3
        else:
            self.major_version = 2


class PythonPkgConfigDependency(PkgConfigDependency, _PythonDependencyBase):

    def __init__(self, name: str, environment: 'Environment',
                 kwargs: T.Dict[str, T.Any], installation: 'PythonInstallation',
                 libpc: bool = False):
        if libpc:
            mlog.debug(f'Searching for {name!r} via pkgconfig lookup in LIBPC')
        else:
            mlog.debug(f'Searching for {name!r} via fallback pkgconfig lookup in default paths')

        PkgConfigDependency.__init__(self, name, environment, kwargs)
        _PythonDependencyBase.__init__(self, installation, kwargs.get('embed', False))

        if libpc and not self.is_found:
            mlog.debug(f'"python-{self.version}" could not be found in LIBPC, this is likely due to a relocated python installation')


class PythonFrameworkDependency(ExtraFrameworkDependency, _PythonDependencyBase):

    def __init__(self, name: str, environment: 'Environment',
                 kwargs: T.Dict[str, T.Any], installation: 'PythonInstallation'):
        ExtraFrameworkDependency.__init__(self, name, environment, kwargs)
        _PythonDependencyBase.__init__(self, installation, kwargs.get('embed', False))


class PythonSystemDependency(SystemDependency, _PythonDependencyBase):

    def __init__(self, name: str, environment: 'Environment',
                 kwargs: T.Dict[str, T.Any], installation: 'PythonInstallation'):
        SystemDependency.__init__(self, name, environment, kwargs)
        _PythonDependencyBase.__init__(self, installation, kwargs.get('embed', False))

        if mesonlib.is_windows():
            self._find_libpy_windows(environment)
        else:
            self._find_libpy(installation, environment)

    def _find_libpy(self, python_holder: 'PythonInstallation', environment: 'Environment') -> None:
        if python_holder.is_pypy:
            if self.major_version == 3:
                libname = 'pypy3-c'
            else:
                libname = 'pypy-c'
            libdir = os.path.join(self.variables.get('base'), 'bin')
            libdirs = [libdir]
        else:
            libname = f'python{self.version}'
            if 'DEBUG_EXT' in self.variables:
                libname += self.variables['DEBUG_EXT']
            if 'ABIFLAGS' in self.variables:
                libname += self.variables['ABIFLAGS']
            libdirs = []

        largs = self.clib_compiler.find_library(libname, environment, libdirs)
        if largs is not None:
            self.link_args = largs

        self.is_found = largs is not None or not self.link_libpython

        inc_paths = mesonlib.OrderedSet([
            self.variables.get('INCLUDEPY'),
            self.paths.get('include'),
            self.paths.get('platinclude')])

        self.compile_args += ['-I' + path for path in inc_paths if path]

    def _get_windows_python_arch(self) -> T.Optional[str]:
        if self.platform == 'mingw':
            pycc = self.variables.get('CC')
            if pycc.startswith('x86_64'):
                return '64'
            elif pycc.startswith(('i686', 'i386')):
                return '32'
            else:
                mlog.log(f'MinGW Python built with unknown CC {pycc!r}, please file a bug')
                return None
        elif self.platform == 'win32':
            return '32'
        elif self.platform in ('win64', 'win-amd64'):
            return '64'
        mlog.log(f'Unknown Windows Python platform {self.platform!r}')
        return None

    def _get_windows_link_args(self) -> T.Optional[T.List[str]]:
        if self.platform.startswith('win'):
            vernum = self.variables.get('py_version_nodot')
            verdot = self.variables.get('py_version_short')
            imp_lower = self.variables.get('implementation_lower', 'python')
            if self.static:
                libpath = Path('libs') / f'libpython{vernum}.a'
            else:
                comp = self.get_compiler()
                if comp.id == "gcc":
                    if imp_lower == 'pypy' and verdot == '3.8':
                        # The naming changed between 3.8 and 3.9
                        libpath = Path('libpypy3-c.dll')
                    elif imp_lower == 'pypy':
                        libpath = Path(f'libpypy{verdot}-c.dll')
                    else:
                        libpath = Path(f'python{vernum}.dll')
                else:
                    libpath = Path('libs') / f'python{vernum}.lib'
            # base_prefix to allow for virtualenvs.
            lib = Path(self.variables.get('base_prefix')) / libpath
        elif self.platform == 'mingw':
            if self.static:
                libname = self.variables.get('LIBRARY')
            else:
                libname = self.variables.get('LDLIBRARY')
            lib = Path(self.variables.get('LIBDIR')) / libname
        else:
            raise mesonlib.MesonBugException(
                'On a Windows path, but the OS doesn\'t appear to be Windows or MinGW.')
        if not lib.exists():
            mlog.log('Could not find Python3 library {!r}'.format(str(lib)))
            return None
        return [str(lib)]

    def _find_libpy_windows(self, env: 'Environment') -> None:
        '''
        Find python3 libraries on Windows and also verify that the arch matches
        what we are building for.
        '''
        pyarch = self._get_windows_python_arch()
        if pyarch is None:
            self.is_found = False
            return
        arch = detect_cpu_family(env.coredata.compilers.host)
        if arch == 'x86':
            arch = '32'
        elif arch == 'x86_64':
            arch = '64'
        else:
            # We can't cross-compile Python 3 dependencies on Windows yet
            mlog.log(f'Unknown architecture {arch!r} for',
                     mlog.bold(self.name))
            self.is_found = False
            return
        # Pyarch ends in '32' or '64'
        if arch != pyarch:
            mlog.log('Need', mlog.bold(self.name), f'for {arch}-bit, but found {pyarch}-bit')
            self.is_found = False
            return
        # This can fail if the library is not found
        largs = self._get_windows_link_args()
        if largs is None:
            self.is_found = False
            return
        self.link_args = largs
        # Compile args
        inc_paths = mesonlib.OrderedSet([
            self.variables.get('INCLUDEPY'),
            self.paths.get('include'),
            self.paths.get('platinclude')])

        self.compile_args += ['-I' + path for path in inc_paths if path]

        # https://sourceforge.net/p/mingw-w64/mailman/message/30504611/
        if pyarch == '64' and self.major_version == 2:
            self.compile_args += ['-DMS_WIN64']

        self.is_found = True


def python_factory(env: 'Environment', for_machine: 'MachineChoice',
                   kwargs: T.Dict[str, T.Any], methods: T.List[DependencyMethods],
                   installation: 'PythonInstallation') -> T.List['DependencyGenerator']:
    # We can't use the factory_methods decorator here, as we need to pass the
    # extra installation argument
    embed = kwargs.get('embed', False)
    candidates: T.List['DependencyGenerator'] = []
    pkg_version = installation.variables.get('LDVERSION') or installation.version

    if DependencyMethods.PKGCONFIG in methods:
        pkg_libdir = installation.variables.get('LIBPC')
        pkg_embed = '-embed' if embed and mesonlib.version_compare(installation.version, '>=3.8') else ''
        pkg_name = f'python-{pkg_version}{pkg_embed}'

        # If python-X.Y.pc exists in LIBPC, we will try to use it
        def wrap_in_pythons_pc_dir(name: str, env: 'Environment', kwargs: T.Dict[str, T.Any],
                                   installation: 'PythonInstallation') -> 'ExternalDependency':
            if not pkg_libdir:
                # there is no LIBPC, so we can't search in it
                return NotFoundDependency('python', env)

            old_pkg_libdir = os.environ.pop('PKG_CONFIG_LIBDIR', None)
            old_pkg_path = os.environ.pop('PKG_CONFIG_PATH', None)
            os.environ['PKG_CONFIG_LIBDIR'] = pkg_libdir
            try:
                return PythonPkgConfigDependency(name, env, kwargs, installation, True)
            finally:
                def set_env(name, value):
                    if value is not None:
                        os.environ[name] = value
                    elif name in os.environ:
                        del os.environ[name]
                set_env('PKG_CONFIG_LIBDIR', old_pkg_libdir)
                set_env('PKG_CONFIG_PATH', old_pkg_path)

        candidates.append(functools.partial(wrap_in_pythons_pc_dir, pkg_name, env, kwargs, installation))
        # We only need to check both, if a python install has a LIBPC. It might point to the wrong location,
        # e.g. relocated / cross compilation, but the presence of LIBPC indicates we should definitely look for something.
        if pkg_libdir is not None:
            candidates.append(functools.partial(PythonPkgConfigDependency, pkg_name, env, kwargs, installation))

    if DependencyMethods.SYSTEM in methods:
        candidates.append(functools.partial(PythonSystemDependency, 'python', env, kwargs, installation))

    if DependencyMethods.EXTRAFRAMEWORK in methods:
        nkwargs = kwargs.copy()
        if mesonlib.version_compare(pkg_version, '>= 3'):
            # There is a python in /System/Library/Frameworks, but that's python 2.x,
            # Python 3 will always be in /Library
            nkwargs['paths'] = ['/Library/Frameworks']
        candidates.append(functools.partial(PythonFrameworkDependency, 'Python', env, nkwargs, installation))

    return candidates


INTROSPECT_COMMAND = '''\
import os.path
import sysconfig
import json
import sys
import distutils.command.install

def get_distutils_paths(scheme=None, prefix=None):
    import distutils.dist
    distribution = distutils.dist.Distribution()
    install_cmd = distribution.get_command_obj('install')
    if prefix is not None:
        install_cmd.prefix = prefix
    if scheme:
        install_cmd.select_scheme(scheme)
    install_cmd.finalize_options()
    return {
        'data': install_cmd.install_data,
        'include': os.path.dirname(install_cmd.install_headers),
        'platlib': install_cmd.install_platlib,
        'purelib': install_cmd.install_purelib,
        'scripts': install_cmd.install_scripts,
    }

# On Debian derivatives, the Python interpreter shipped by the distribution uses
# a custom install scheme, deb_system, for the system install, and changes the
# default scheme to a custom one pointing to /usr/local and replacing
# site-packages with dist-packages.
# See https://github.com/mesonbuild/meson/issues/8739.
# XXX: We should be using sysconfig, but Debian only patches distutils.

if 'deb_system' in distutils.command.install.INSTALL_SCHEMES:
    paths = get_distutils_paths(scheme='deb_system')
    install_paths = get_distutils_paths(scheme='deb_system', prefix='')
else:
    paths = sysconfig.get_paths()
    empty_vars = {'base': '', 'platbase': '', 'installed_base': ''}
    install_paths = sysconfig.get_paths(vars=empty_vars)

def links_against_libpython():
    from distutils.core import Distribution, Extension
    cmd = Distribution().get_command_obj('build_ext')
    cmd.ensure_finalized()
    return bool(cmd.get_libraries(Extension('dummy', [])))

variables = sysconfig.get_config_vars()
variables.update({'base_prefix': getattr(sys, 'base_prefix', sys.prefix)})

print(json.dumps({
  'variables': variables,
  'paths': paths,
  'sysconfig_paths': sysconfig.get_paths(),
  'install_paths': install_paths,
  'version': sysconfig.get_python_version(),
  'platform': sysconfig.get_platform(),
  'is_pypy': '__pypy__' in sys.builtin_module_names,
  'is_venv': sys.prefix != variables['base_prefix'],
  'link_libpython': links_against_libpython(),
}))
'''


class PythonExternalProgram(ExternalProgram):
    def __init__(self, name: str, command: T.Optional[T.List[str]] = None,
                 ext_prog: T.Optional[ExternalProgram] = None):
        if ext_prog is None:
            super().__init__(name, command=command, silent=True)
        else:
            self.name = name
            self.command = ext_prog.command
            self.path = ext_prog.path

        # We want strong key values, so we always populate this with bogus data.
        # Otherwise to make the type checkers happy we'd have to do .get() for
        # everycall, even though we know that the introspection data will be
        # complete
        self.info: 'PythonIntrospectionDict' = {
            'install_paths': {},
            'is_pypy': False,
            'is_venv': False,
            'link_libpython': False,
            'sysconfig_paths': {},
            'paths': {},
            'platform': 'sentinal',
            'variables': {},
            'version': '0.0',
        }

    def _check_version(self, version: str) -> bool:
        if self.name == 'python2':
            return mesonlib.version_compare(version, '< 3.0')
        elif self.name == 'python3':
            return mesonlib.version_compare(version, '>= 3.0')
        return True

    def sanity(self, state: T.Optional['ModuleState'] = None) -> bool:
        # Sanity check, we expect to have something that at least quacks in tune
        from tempfile import NamedTemporaryFile
        with NamedTemporaryFile(suffix='.py', delete=False, mode='w', encoding='utf-8') as tf:
            tmpfilename = tf.name
            tf.write(INTROSPECT_COMMAND)
        cmd = self.get_command() + [tmpfilename]
        p, stdout, stderr = mesonlib.Popen_safe(cmd)
        os.unlink(tmpfilename)
        try:
            info = json.loads(stdout)
        except json.JSONDecodeError:
            info = None
            mlog.debug('Could not introspect Python (%s): exit code %d' % (str(p.args), p.returncode))
            mlog.debug('Program stdout:\n')
            mlog.debug(stdout)
            mlog.debug('Program stderr:\n')
            mlog.debug(stderr)

        if info is not None and self._check_version(info['version']):
            variables = info['variables']
            info['suffix'] = variables.get('EXT_SUFFIX') or variables.get('SO') or variables.get('.so')
            self.info = T.cast('PythonIntrospectionDict', info)
            self.platlib = self._get_path(state, 'platlib')
            self.purelib = self._get_path(state, 'purelib')
            return True
        else:
            return False

    def _get_path(self, state: T.Optional['ModuleState'], key: str) -> None:
        rel_path = self.info['install_paths'][key][1:]
        if not state:
            # This happens only from run_project_tests.py
            return rel_path
        value = state.get_option(f'{key}dir', module='python')
        if value:
            if state.is_user_defined_option('install_env', module='python'):
                raise mesonlib.MesonException(f'python.{key}dir and python.install_env are mutually exclusive')
            return value

        install_env = state.get_option('install_env', module='python')
        if install_env == 'auto':
            install_env = 'venv' if self.info['is_venv'] else 'system'

        if install_env == 'system':
            rel_path = os.path.join(self.info['variables']['prefix'], rel_path)
        elif install_env == 'venv':
            if not self.info['is_venv']:
                raise mesonlib.MesonException('python.install_env cannot be set to "venv" unless you are in a venv!')
            # inside a venv, deb_system is *never* active hence info['paths'] may be wrong
            rel_path = self.info['sysconfig_paths'][key]

        return rel_path


class PythonInstallation(ExternalProgramHolder):
    def __init__(self, python: 'PythonExternalProgram', interpreter: 'Interpreter'):
        ExternalProgramHolder.__init__(self, python, interpreter)
        info = python.info
        prefix = self.interpreter.environment.coredata.get_option(mesonlib.OptionKey('prefix'))
        assert isinstance(prefix, str), 'for mypy'
        self.variables = info['variables']
        self.suffix = info['suffix']
        self.paths = info['paths']
        self.platlib_install_path = os.path.join(prefix, python.platlib)
        self.purelib_install_path = os.path.join(prefix, python.purelib)
        self.version = info['version']
        self.platform = info['platform']
        self.is_pypy = info['is_pypy']
        self.link_libpython = info['link_libpython']
        self.methods.update({
            'extension_module': self.extension_module_method,
            'dependency': self.dependency_method,
            'install_sources': self.install_sources_method,
            'get_install_dir': self.get_install_dir_method,
            'language_version': self.language_version_method,
            'found': self.found_method,
            'has_path': self.has_path_method,
            'get_path': self.get_path_method,
            'has_variable': self.has_variable_method,
            'get_variable': self.get_variable_method,
            'path': self.path_method,
        })

    @typed_pos_args('python.extension_module', str, varargs=(str, mesonlib.File, build.CustomTarget, build.CustomTargetIndex, build.GeneratedList))
    @typed_kwargs('python.extension_module', *_MOD_KWARGS)
    def extension_module_method(self, args: T.Tuple[str, T.List[BuildTargetSource]],
                                kwargs: ExtensionModuleKw) -> 'SharedModule':
        # Create a copy of the keyword arguments, but as a SharedModule acrugment dictionary
        n_kwargs = T.cast('BuildTarget', kwargs.copy())
        del n_kwargs['subdir']  # type: ignore

        if kwargs['install_dir'] and kwargs['subdir']:
            raise InvalidArguments('"subdir" and "install_dir" are mutually exclusive')
        elif not kwargs['install_dir']:
            subdir = kwargs['subdir']
            n_kwargs['install_dir'] = [os.path.join(self.platlib_install_path, subdir)]

        new_deps = []
        has_pydep = False
        for dep in kwargs['dependencies']:
            if isinstance(dep, _PythonDependencyBase):
                has_pydep = True
                # On macOS and some Linux distros (Debian) distutils doesn't link
                # extensions against libpython. We call into distutils and mirror its
                # behavior. See https://github.com/mesonbuild/meson/issues/4117
                if not self.link_libpython:
                    dep = dep.get_partial_dependency(compile_args=True)
            new_deps.append(dep)
        if not has_pydep:
            pydep = self._dependency_method_impl({})
            if not pydep.found():
                raise mesonlib.MesonException('Python dependency not found')
            new_deps.append(pydep)
            FeatureNew.single_use('python_installation.extension_module with implicit dependency on python',
                                  '0.63.0', self.subproject, 'use python_installation.dependency()',
                                  self.current_node)
        n_kwargs['dependencies'] = new_deps

        # msys2's python3 has "-cpython-36m.dll", we have to be clever
        # FIXME: explain what the specific cleverness is here
        split, suffix = self.suffix.rsplit('.', 1)
        name = args[0] + split

        n_kwargs['name_suffix'] = suffix
        n_kwargs['name_prefix'] = ''

        if 'gnu_symbol_visibility' not in kwargs and \
                (self.is_pypy or mesonlib.version_compare(self.version, '>=3.9')):
            n_kwargs['gnu_symbol_visibility'] = 'inlineshidden'

        return self.interpreter.build_target(
            self.current_node, (name, args[1]), n_kwargs, build.SharedModule)

    def _dependency_method_impl(self, kwargs: TYPE_kwargs) -> Dependency:
        for_machine = self.interpreter.machine_from_native_kwarg(kwargs)
        identifier = get_dep_identifier(self._full_path(), kwargs)

        dep = self.interpreter.coredata.deps[for_machine].get(identifier)
        if dep is not None:
            return dep

        new_kwargs = kwargs.copy()
        new_kwargs['required'] = False
        methods = process_method_kw({DependencyMethods.PKGCONFIG, DependencyMethods.SYSTEM}, kwargs)
        # it's theoretically (though not practically) possible to not bind dep, let's ensure it is.
        dep: Dependency = NotFoundDependency('python', self.interpreter.environment)
        for d in python_factory(self.interpreter.environment, for_machine, new_kwargs, methods, self):
            dep = d()
            if dep.found():
                break

        self.interpreter.coredata.deps[for_machine].put(identifier, dep)
        return dep

    @disablerIfNotFound
    @permittedKwargs(permitted_dependency_kwargs | {'embed'})
    @FeatureNewKwargs('python_installation.dependency', '0.53.0', ['embed'])
    @noPosargs
    def dependency_method(self, args: T.List['TYPE_var'], kwargs: 'TYPE_kwargs') -> 'Dependency':
        disabled, required, feature = extract_required_kwarg(kwargs, self.subproject)
        if disabled:
            mlog.log('Dependency', mlog.bold('python'), 'skipped: feature', mlog.bold(feature), 'disabled')
            return NotFoundDependency('python', self.interpreter.environment)
        else:
            dep = self._dependency_method_impl(kwargs)
            if required and not dep.found():
                raise mesonlib.MesonException('Python dependency not found')
            return dep

    @typed_pos_args('install_data', varargs=(str, mesonlib.File))
    @typed_kwargs(
        'python_installation.install_sources',
        _PURE_KW,
        _SUBDIR_KW,
        PRESERVE_PATH_KW,
        KwargInfo('install_tag', (str, NoneType), since='0.60.0')
    )
    def install_sources_method(self, args: T.Tuple[T.List[T.Union[str, mesonlib.File]]],
                               kwargs: 'PyInstallKw') -> 'Data':
        tag = kwargs['install_tag'] or 'runtime'
        return self.interpreter.install_data_impl(
            self.interpreter.source_strings_to_files(args[0]),
            self._get_install_dir_impl(kwargs['pure'], kwargs['subdir']),
            mesonlib.FileMode(), rename=None, tag=tag, install_data_type='python',
            install_dir_name=self._get_install_dir_name_impl(kwargs['pure'], kwargs['subdir']),
            preserve_path=kwargs['preserve_path'])

    @noPosargs
    @typed_kwargs('python_installation.install_dir', _PURE_KW, _SUBDIR_KW)
    def get_install_dir_method(self, args: T.List['TYPE_var'], kwargs: 'PyInstallKw') -> str:
        return self._get_install_dir_impl(kwargs['pure'], kwargs['subdir'])

    def _get_install_dir_impl(self, pure: bool, subdir: str) -> str:
        return os.path.join(
            self.purelib_install_path if pure else self.platlib_install_path, subdir)

    def _get_install_dir_name_impl(self, pure: bool, subdir: str) -> str:
        return os.path.join('{py_purelib}' if pure else '{py_platlib}', subdir)

    @noPosargs
    @noKwargs
    def language_version_method(self, args: T.List['TYPE_var'], kwargs: 'TYPE_kwargs') -> str:
        return self.version

    @typed_pos_args('python_installation.has_path', str)
    @noKwargs
    def has_path_method(self, args: T.Tuple[str], kwargs: 'TYPE_kwargs') -> bool:
        return args[0] in self.paths

    @typed_pos_args('python_installation.get_path', str, optargs=[object])
    @noKwargs
    def get_path_method(self, args: T.Tuple[str, T.Optional['TYPE_var']], kwargs: 'TYPE_kwargs') -> 'TYPE_var':
        path_name, fallback = args
        try:
            return self.paths[path_name]
        except KeyError:
            if fallback is not None:
                return fallback
            raise InvalidArguments(f'{path_name} is not a valid path name')

    @typed_pos_args('python_installation.has_variable', str)
    @noKwargs
    def has_variable_method(self, args: T.Tuple[str], kwargs: 'TYPE_kwargs') -> bool:
        return args[0] in self.variables

    @typed_pos_args('python_installation.get_variable', str, optargs=[object])
    @noKwargs
    def get_variable_method(self, args: T.Tuple[str, T.Optional['TYPE_var']], kwargs: 'TYPE_kwargs') -> 'TYPE_var':
        var_name, fallback = args
        try:
            return self.variables[var_name]
        except KeyError:
            if fallback is not None:
                return fallback
            raise InvalidArguments(f'{var_name} is not a valid variable name')

    @noPosargs
    @noKwargs
    @FeatureNew('Python module path method', '0.50.0')
    def path_method(self, args: T.List['TYPE_var'], kwargs: 'TYPE_kwargs') -> str:
        return super().path_method(args, kwargs)


class PythonModule(ExtensionModule):

    INFO = ModuleInfo('python', '0.46.0')

    def __init__(self, interpreter: 'Interpreter') -> None:
        super().__init__(interpreter)
        self.installations: T.Dict[str, ExternalProgram] = {}
        self.methods.update({
            'find_installation': self.find_installation,
        })

    # https://www.python.org/dev/peps/pep-0397/
    @staticmethod
    def _get_win_pythonpath(name_or_path: str) -> T.Optional[str]:
        if name_or_path not in ['python2', 'python3']:
            return None
        if not shutil.which('py'):
            # program not installed, return without an exception
            return None
        ver = {'python2': '-2', 'python3': '-3'}[name_or_path]
        cmd = ['py', ver, '-c', "import sysconfig; print(sysconfig.get_config_var('BINDIR'))"]
        _, stdout, _ = mesonlib.Popen_safe(cmd)
        directory = stdout.strip()
        if os.path.exists(directory):
            return os.path.join(directory, 'python')
        else:
            return None

    def _find_installation_impl(self, state: 'ModuleState', display_name: str, name_or_path: str, required: bool) -> ExternalProgram:
        if not name_or_path:
            python = PythonExternalProgram('python3', mesonlib.python_command)
        else:
            tmp_python = ExternalProgram.from_entry(display_name, name_or_path)
            python = PythonExternalProgram(display_name, ext_prog=tmp_python)

            if not python.found() and mesonlib.is_windows():
                pythonpath = self._get_win_pythonpath(name_or_path)
                if pythonpath is not None:
                    name_or_path = pythonpath
                    python = PythonExternalProgram(name_or_path)

            # Last ditch effort, python2 or python3 can be named python
            # on various platforms, let's not give up just yet, if an executable
            # named python is available and has a compatible version, let's use
            # it
            if not python.found() and name_or_path in ['python2', 'python3']:
                python = PythonExternalProgram('python')

        if python.found():
            if python.sanity(state):
                return python
            else:
                sanitymsg = f'{python} is not a valid python or it is missing distutils'
                if required:
                    raise mesonlib.MesonException(sanitymsg)
                else:
                    mlog.warning(sanitymsg, location=state.current_node)

        return NonExistingExternalProgram()

    @disablerIfNotFound
    @typed_pos_args('python.find_installation', optargs=[str])
    @typed_kwargs(
        'python.find_installation',
        KwargInfo('required', (bool, UserFeatureOption), default=True),
        KwargInfo('disabler', bool, default=False, since='0.49.0'),
        KwargInfo('modules', ContainerTypeInfo(list, str), listify=True, default=[], since='0.51.0'),
    )
    def find_installation(self, state: 'ModuleState', args: T.Tuple[T.Optional[str]],
                          kwargs: 'FindInstallationKw') -> ExternalProgram:
        feature_check = FeatureNew('Passing "feature" option to find_installation', '0.48.0')
        disabled, required, feature = extract_required_kwarg(kwargs, state.subproject, feature_check)

        # FIXME: this code is *full* of sharp corners. It assumes that it's
        # going to get a string value (or now a list of length 1), of `python2`
        # or `python3` which is completely nonsense.  On windows the value could
        # easily be `['py', '-3']`, or `['py', '-3.7']` to get a very specific
        # version of python. On Linux we might want a python that's not in
        # $PATH, or that uses a wrapper of some kind.
        np: T.List[str] = state.environment.lookup_binary_entry(MachineChoice.HOST, 'python') or []
        fallback = args[0]
        display_name = fallback or 'python'
        if not np and fallback is not None:
            np = [fallback]
        name_or_path = np[0] if np else None

        if disabled:
            mlog.log('Program', name_or_path or 'python', 'found:', mlog.red('NO'), '(disabled by:', mlog.bold(feature), ')')
            return NonExistingExternalProgram()

        python = self.installations.get(name_or_path)
        if not python:
            python = self._find_installation_impl(state, display_name, name_or_path, required)
            self.installations[name_or_path] = python

        want_modules = kwargs['modules']
        found_modules: T.List[str] = []
        missing_modules: T.List[str] = []
        if python.found() and want_modules:
            # Python 3.8.x or later require add_dll_directory() to be called on Windows if
            # the needed modules require external DLLs that are not bundled with the modules.
            # Simplify things by calling add_dll_directory() on the paths in %PATH%
            add_paths_cmd = ''
            if hasattr(os, 'add_dll_directory'):
                add_paths_cmds = []
                paths = os.environ['PATH'].split(os.pathsep)
                for path in paths:
                    if path != '' and os.path.isdir(path):
                        add_paths_cmds.append(f'os.add_dll_directory({path!r})')
                add_paths_cmd = 'import os;' + ';'.join(reversed(add_paths_cmds)) + ';'

            for mod in want_modules:
                p, *_ = mesonlib.Popen_safe(
                    python.command +
                    ['-c', f'{add_paths_cmd}import {mod}'])
                if p.returncode != 0:
                    missing_modules.append(mod)
                else:
                    found_modules.append(mod)

        msg: T.List['mlog.TV_Loggable'] = ['Program', python.name]
        if want_modules:
            msg.append('({})'.format(', '.join(want_modules)))
        msg.append('found:')
        if python.found() and not missing_modules:
            msg.extend([mlog.green('YES'), '({})'.format(' '.join(python.command))])
        else:
            msg.append(mlog.red('NO'))
        if found_modules:
            msg.append('modules:')
            msg.append(', '.join(found_modules))

        mlog.log(*msg)

        if not python.found():
            if required:
                raise mesonlib.MesonException('{} not found'.format(name_or_path or 'python'))
            return NonExistingExternalProgram()
        elif missing_modules:
            if required:
                raise mesonlib.MesonException('{} is missing modules: {}'.format(name_or_path or 'python', ', '.join(missing_modules)))
            return NonExistingExternalProgram()
        else:
            return python

        raise mesonlib.MesonBugException('Unreachable code was reached (PythonModule.find_installation).')


def initialize(interpreter: 'Interpreter') -> PythonModule:
    mod = PythonModule(interpreter)
    mod.interpreter.append_holder_map(PythonExternalProgram, PythonInstallation)
    return mod
