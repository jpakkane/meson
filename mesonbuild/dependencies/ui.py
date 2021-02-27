# Copyright 2013-2017 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This file contains the detection logic for external dependencies that
# are UI-related.
import os
import re
import subprocess
import typing as T
from collections import OrderedDict

from .. import mlog
from .. import mesonlib
from ..mesonlib import (
    MesonException, Popen_safe, extract_as_list, version_compare_many
)
from ..environment import detect_cpu_family

from .base import DependencyException, DependencyMethods
from .base import ExternalDependency, NonExistingExternalProgram
from .base import ExtraFrameworkDependency, PkgConfigDependency, CMakeDependency
from .base import ConfigToolDependency, DependencyFactory
from .base import find_external_program

if T.TYPE_CHECKING:
    from ..environment import Environment
    from .base import ExternalProgram


class GLDependencySystem(ExternalDependency):
    def __init__(self, name: str, environment, kwargs):
        super().__init__(name, environment, kwargs)

        if self.env.machines[self.for_machine].is_darwin():
            self.is_found = True
            # FIXME: Use AppleFrameworks dependency
            self.link_args = ['-framework', 'OpenGL']
            # FIXME: Detect version using self.clib_compiler
            return
        if self.env.machines[self.for_machine].is_windows():
            self.is_found = True
            # FIXME: Use self.clib_compiler.find_library()
            self.link_args = ['-lopengl32']
            # FIXME: Detect version using self.clib_compiler
            return

    @staticmethod
    def get_methods():
        if mesonlib.is_osx() or mesonlib.is_windows():
            return [DependencyMethods.PKGCONFIG, DependencyMethods.SYSTEM]
        else:
            return [DependencyMethods.PKGCONFIG]

    def log_tried(self):
        return 'system'

class GnuStepDependency(ConfigToolDependency):

    tools = ['gnustep-config']
    tool_name = 'gnustep-config'

    def __init__(self, environment, kwargs):
        super().__init__('gnustep', environment, kwargs, language='objc')
        if not self.is_found:
            return
        self.modules = kwargs.get('modules', [])
        self.compile_args = self.filter_args(
            self.get_config_value(['--objc-flags'], 'compile_args'))
        self.link_args = self.weird_filter(self.get_config_value(
            ['--gui-libs' if 'gui' in self.modules else '--base-libs'],
            'link_args'))

    def find_config(self, versions=None, returncode: int = 0):
        tool = [self.tools[0]]
        try:
            p, out = Popen_safe(tool + ['--help'])[:2]
        except (FileNotFoundError, PermissionError):
            return (None, None)
        if p.returncode != returncode:
            return (None, None)
        self.config = tool
        found_version = self.detect_version()
        if versions and not version_compare_many(found_version, versions)[0]:
            return (None, found_version)

        return (tool, found_version)

    def weird_filter(self, elems):
        """When building packages, the output of the enclosing Make is
        sometimes mixed among the subprocess output. I have no idea why. As a
        hack filter out everything that is not a flag.
        """
        return [e for e in elems if e.startswith('-')]

    def filter_args(self, args):
        """gnustep-config returns a bunch of garbage args such as -O2 and so
        on. Drop everything that is not needed.
        """
        result = []
        for f in args:
            if f.startswith('-D') \
                    or f.startswith('-f') \
                    or f.startswith('-I') \
                    or f == '-pthread' \
                    or (f.startswith('-W') and not f == '-Wall'):
                result.append(f)
        return result

    def detect_version(self):
        gmake = self.get_config_value(['--variable=GNUMAKE'], 'variable')[0]
        makefile_dir = self.get_config_value(['--variable=GNUSTEP_MAKEFILES'], 'variable')[0]
        # This Makefile has the GNUStep version set
        base_make = os.path.join(makefile_dir, 'Additional', 'base.make')
        # Print the Makefile variable passed as the argument. For instance, if
        # you run the make target `print-SOME_VARIABLE`, this will print the
        # value of the variable `SOME_VARIABLE`.
        printver = "print-%:\n\t@echo '$($*)'"
        env = os.environ.copy()
        # See base.make to understand why this is set
        env['FOUNDATION_LIB'] = 'gnu'
        p, o, e = Popen_safe([gmake, '-f', '-', '-f', base_make,
                              'print-GNUSTEP_BASE_VERSION'],
                             env=env, write=printver, stdin=subprocess.PIPE)
        version = o.strip()
        if not version:
            mlog.debug("Couldn't detect GNUStep version, falling back to '1'")
            # Fallback to setting some 1.x version
            version = '1'
        return version


def _qt_get_private_includes(mod_inc_dir, module, mod_version):
    # usually Qt5 puts private headers in /QT_INSTALL_HEADERS/module/VERSION/module/private
    # except for at least QtWebkit and Enginio where the module version doesn't match Qt version
    # as an example with Qt 5.10.1 on linux you would get:
    # /usr/include/qt5/QtCore/5.10.1/QtCore/private/
    # /usr/include/qt5/QtWidgets/5.10.1/QtWidgets/private/
    # /usr/include/qt5/QtWebKit/5.212.0/QtWebKit/private/

    # on Qt4 when available private folder is directly in module folder
    # like /usr/include/QtCore/private/
    if int(mod_version.split('.')[0]) < 5:
        return tuple()

    private_dir = os.path.join(mod_inc_dir, mod_version)
    # fallback, let's try to find a directory with the latest version
    if not os.path.exists(private_dir):
        dirs = [filename for filename in os.listdir(mod_inc_dir)
                if os.path.isdir(os.path.join(mod_inc_dir, filename))]
        dirs.sort(reverse=True)

        for dirname in dirs:
            if len(dirname.split('.')) == 3:
                private_dir = dirname
                break
    return (private_dir,
            os.path.join(private_dir, 'Qt' + module))

class QtExtraFrameworkDependency(ExtraFrameworkDependency):
    def __init__(self, name, env, kwargs, language: T.Optional[str] = None):
        super().__init__(name, env, kwargs, language=language)
        self.mod_name = name[2:]

    def get_compile_args(self, with_private_headers=False, qt_version="0"):
        if self.found():
            mod_inc_dir = os.path.join(self.framework_path, 'Headers')
            args = ['-I' + mod_inc_dir]
            if with_private_headers:
                args += ['-I' + dirname for dirname in _qt_get_private_includes(mod_inc_dir, self.mod_name, qt_version)]
            return args
        return []

class QtBaseDependency(ExternalDependency):
    def __init__(self, name, env, kwargs):
        super().__init__(name, env, kwargs, language='cpp')
        self.qtname = name.capitalize()
        self.qtver = name[-1]
        if self.qtver == "4":
            self.qtpkgname = 'Qt'
        else:
            self.qtpkgname = self.qtname
        self.root = '/usr'
        self.bindir = None
        self.private_headers = kwargs.get('private_headers', False)
        mods = extract_as_list(kwargs, 'modules')
        self.requested_modules = mods
        if not mods:
            raise DependencyException('No ' + self.qtname + '  modules specified.')
        self.from_text = 'pkg-config'

        self.qtmain = kwargs.get('main', False)
        if not isinstance(self.qtmain, bool):
            raise DependencyException('"main" argument must be a boolean')

        # Keep track of the detection methods used, for logging purposes.
        methods = []
        # Prefer pkg-config, then fallback to `qmake -query`
        #if DependencyMethods.PKGCONFIG in self.methods:
        #    mlog.debug('Trying to find qt with pkg-config')
        #    self._pkgconfig_detect(mods, kwargs)
        #    methods.append('pkgconfig')
        if not self.is_found and DependencyMethods.CMAKE in self.methods:
            mlog.debug('Trying to find qt with cmake')
            self._cmake_detect(mods, kwargs)
            self.from_text = 'cmake'
            methods.append('cmake')
        #if not self.is_found and DependencyMethods.QMAKE in self.methods:
        #    mlog.debug('Trying to find qt with qmake')
        #    self.from_text = self._qmake_detect(mods, kwargs)
        #    methods.append('qmake-' + self.name)
        #    methods.append('qmake')
        if not self.is_found:
            # Reset compile args and link args
            self.compile_args = []
            self.link_args = []
            self.from_text = mlog.format_list(methods)
            self.version = None

    def compilers_detect(self, interp_obj):
        "Detect Qt (4 or 5) moc, uic, rcc in the specified bindir or in PATH"
        # It is important that this list does not change order as the order of
        # the returned ExternalPrograms will change as well
        bins = ['moc', 'uic', 'rcc', 'lrelease']
        found = {b: NonExistingExternalProgram(name='{}-{}'.format(b, self.name))
                 for b in bins}
        wanted = '== {}'.format(self.version)

        def gen_bins():
            for b in bins:
                if self.bindir:
                    yield os.path.join(self.bindir, b), b
                # prefer the <tool>-qt<version> of the tool to the plain one, as we
                # don't know what the unsuffixed one points to without calling it.
                yield '{}-{}'.format(b, self.name), b
                yield b, b

        for b, name in gen_bins():
            if found[name].found():
                continue

            if name == 'lrelease':
                arg = ['-version']
            elif mesonlib.version_compare(self.version, '>= 5'):
                arg = ['--version']
            else:
                arg = ['-v']

            # Ensure that the version of qt and each tool are the same
            def get_version(p):
                _, out, err = mesonlib.Popen_safe(p.get_command() + arg)
                if b.startswith('lrelease') or not self.version.startswith('4'):
                    care = out
                else:
                    care = err
                return care.split(' ')[-1].replace(')', '').strip()

            p = interp_obj.find_program_impl([b], required=False,
                                             version_func=get_version,
                                             wanted=wanted).held_object
            if p.found():
                found[name] = p

        return tuple([found[b] for b in bins])

    def _pkgconfig_detect(self, mods, kwargs):
        # We set the value of required to False so that we can try the
        # qmake-based fallback if pkg-config fails.
        kwargs['required'] = False
        modules = OrderedDict()
        for module in mods:
            modules[module] = PkgConfigDependency(self.qtpkgname + module, self.env,
                                                  kwargs, language=self.language)
        for m_name, m in modules.items():
            if not m.found():
                self.is_found = False
                return
            self.compile_args += m.get_compile_args()
            if self.private_headers:
                qt_inc_dir = m.get_pkgconfig_variable('includedir', dict())
                mod_private_dir = os.path.join(qt_inc_dir, 'Qt' + m_name)
                if not os.path.isdir(mod_private_dir):
                    # At least some versions of homebrew don't seem to set this
                    # up correctly. /usr/local/opt/qt/include/Qt + m_name is a
                    # symlink to /usr/local/opt/qt/include, but the pkg-config
                    # file points to /usr/local/Cellar/qt/x.y.z/Headers/, and
                    # the Qt + m_name there is not a symlink, it's a file
                    mod_private_dir = qt_inc_dir
                mod_private_inc = _qt_get_private_includes(mod_private_dir, m_name, m.version)
                for directory in mod_private_inc:
                    self.compile_args.append('-I' + directory)
            self.link_args += m.get_link_args()

        if 'Core' in modules:
            core = modules['Core']
        else:
            corekwargs = {'required': 'false', 'silent': 'true'}
            core = PkgConfigDependency(self.qtpkgname + 'Core', self.env, corekwargs,
                                       language=self.language)
            modules['Core'] = core

        if self.env.machines[self.for_machine].is_windows() and self.qtmain:
            # Check if we link with debug binaries
            debug_lib_name = self.qtpkgname + 'Core' + self._get_modules_lib_suffix(True)
            is_debug = False
            for arg in core.get_link_args():
                if arg == '-l%s' % debug_lib_name or arg.endswith('%s.lib' % debug_lib_name) or arg.endswith('%s.a' % debug_lib_name):
                    is_debug = True
                    break
            libdir = core.get_pkgconfig_variable('libdir', {})
            if not self._link_with_qtmain(is_debug, libdir):
                self.is_found = False
                return

        self.is_found = True
        self.version = m.version
        self.pcdep = list(modules.values())
        # Try to detect moc, uic, rcc
        # Used by self.compilers_detect()
        self.bindir = self.get_pkgconfig_host_bins(core)
        if not self.bindir:
            # If exec_prefix is not defined, the pkg-config file is broken
            prefix = core.get_pkgconfig_variable('exec_prefix', {})
            if prefix:
                self.bindir = os.path.join(prefix, 'bin')

    def _cmake_detect(self, mods, kwargs):
        # We set the value of required to False so that we can try the
        # qmake-based fallback if pkg-config fails.
        kwargs['required'] = False
        modules = OrderedDict()
        for module in mods:
            kwargs['components'] = [module]
            kwargs['modules'] = ["Qt::" + module]
            modules[module] = CMakeDependency(self.qtpkgname, self.env,
                                              kwargs, language=self.language)
        for m_name, m in modules.items():
            if not m.found():
                self.is_found = False
                return
            self.compile_args += m.get_compile_args()
            # TODO self.private_headers
            self.link_args += m.get_link_args()

        self.is_found = True
        self.version = m.version

    def search_qmake(self) -> T.Generator['ExternalProgram', None, None]:
        for qmake in ('qmake-' + self.name, 'qmake'):
            yield from find_external_program(self.env, self.for_machine, qmake, 'QMake', [qmake])

    def _qmake_detect(self, mods, kwargs):
        for qmake in self.search_qmake():
            if not qmake.found():
                continue
            # Check that the qmake is for qt5
            pc, stdo = Popen_safe(qmake.get_command() + ['-v'])[0:2]
            if pc.returncode != 0:
                continue
            if not 'Qt version ' + self.qtver in stdo:
                mlog.log('QMake is not for ' + self.qtname)
                continue
            # Found qmake for Qt5!
            self.qmake = qmake
            break
        else:
            # Didn't find qmake :(
            self.is_found = False
            return
        self.version = re.search(self.qtver + r'(\.\d+)+', stdo).group(0)
        # Query library path, header path, and binary path
        mlog.log("Found qmake:", mlog.bold(self.qmake.get_path()), '(%s)' % self.version)
        stdo = Popen_safe(self.qmake.get_command() + ['-query'])[1]
        qvars = {}
        for line in stdo.split('\n'):
            line = line.strip()
            if line == '':
                continue
            (k, v) = tuple(line.split(':', 1))
            qvars[k] = v
        # Qt on macOS uses a framework, but Qt for iOS/tvOS does not
        xspec = qvars.get('QMAKE_XSPEC', '')
        if self.env.machines.host.is_darwin() and not any(s in xspec for s in ['ios', 'tvos']):
            mlog.debug("Building for macOS, looking for framework")
            self._framework_detect(qvars, mods, kwargs)
            # Sometimes Qt is built not as a framework (for instance, when using conan pkg manager)
            # skip and fall back to normal procedure then
            if self.is_found:
                return self.qmake.name
            else:
                mlog.debug("Building for macOS, couldn't find framework, falling back to library search")
        incdir = qvars['QT_INSTALL_HEADERS']
        self.compile_args.append('-I' + incdir)
        libdir = qvars['QT_INSTALL_LIBS']
        # Used by self.compilers_detect()
        self.bindir = self.get_qmake_host_bins(qvars)
        self.is_found = True

        # Use the buildtype by default, but look at the b_vscrt option if the
        # compiler supports it.
        is_debug = self.env.coredata.get_option(mesonlib.OptionKey('buildtype')) == 'debug'
        if mesonlib.OptionKey('b_vscrt') in self.env.coredata.options:
            if self.env.coredata.options[mesonlib.OptionKey('b_vscrt')].value in {'mdd', 'mtd'}:
                is_debug = True
        modules_lib_suffix = self._get_modules_lib_suffix(is_debug)

        for module in mods:
            mincdir = os.path.join(incdir, 'Qt' + module)
            self.compile_args.append('-I' + mincdir)

            if module == 'QuickTest':
                define_base = 'QMLTEST'
            elif module == 'Test':
                define_base = 'TESTLIB'
            else:
                define_base = module.upper()
            self.compile_args.append('-DQT_%s_LIB' % define_base)

            if self.private_headers:
                priv_inc = self.get_private_includes(mincdir, module)
                for directory in priv_inc:
                    self.compile_args.append('-I' + directory)
            libfile = self.clib_compiler.find_library(self.qtpkgname + module + modules_lib_suffix,
                                                      self.env,
                                                      libdir)
            if libfile:
                libfile = libfile[0]
            else:
                mlog.log("Could not find:", module,
                         self.qtpkgname + module + modules_lib_suffix,
                         'in', libdir)
                self.is_found = False
                break
            self.link_args.append(libfile)

        if self.env.machines[self.for_machine].is_windows() and self.qtmain:
            if not self._link_with_qtmain(is_debug, libdir):
                self.is_found = False

        return self.qmake.name

    def _get_modules_lib_suffix(self, is_debug):
        suffix = ''
        if self.env.machines[self.for_machine].is_windows():
            if is_debug:
                suffix += 'd'
            if self.qtver == '4':
                suffix += '4'
        if self.env.machines[self.for_machine].is_darwin():
            if is_debug:
                suffix += '_debug'
        if mesonlib.version_compare(self.version, '>= 5.14.0'):
            if self.env.machines[self.for_machine].is_android():
                cpu_family = self.env.machines[self.for_machine].cpu_family
                if cpu_family == 'x86':
                    suffix += '_x86'
                elif cpu_family == 'x86_64':
                    suffix += '_x86_64'
                elif cpu_family == 'arm':
                    suffix += '_armeabi-v7a'
                elif cpu_family == 'aarch64':
                    suffix += '_arm64-v8a'
                else:
                    mlog.warning('Android target arch {!r} for Qt5 is unknown, '
                                 'module detection may not work'.format(cpu_family))
        return suffix

    def _link_with_qtmain(self, is_debug, libdir):
        base_name = 'qtmaind' if is_debug else 'qtmain'
        qtmain = self.clib_compiler.find_library(base_name, self.env, libdir)
        if qtmain:
            self.link_args.append(qtmain[0])
            return True
        return False

    def _framework_detect(self, qvars, modules, kwargs):
        libdir = qvars['QT_INSTALL_LIBS']

        # ExtraFrameworkDependency doesn't support any methods
        fw_kwargs = kwargs.copy()
        fw_kwargs.pop('method', None)
        fw_kwargs['paths'] = [libdir]

        for m in modules:
            fname = 'Qt' + m
            mlog.debug('Looking for qt framework ' + fname)
            fwdep = QtExtraFrameworkDependency(fname, self.env, fw_kwargs, language=self.language)
            if fwdep.found():
                self.compile_args.append('-F' + libdir)
                self.compile_args += fwdep.get_compile_args(with_private_headers=self.private_headers,
                                                            qt_version=self.version)
                self.link_args += fwdep.get_link_args()
            else:
                break
        else:
            self.is_found = True
            # Used by self.compilers_detect()
            self.bindir = self.get_qmake_host_bins(qvars)

    def get_qmake_host_bins(self, qvars):
        # Prefer QT_HOST_BINS (qt5, correct for cross and native compiling)
        # but fall back to QT_INSTALL_BINS (qt4)
        if 'QT_HOST_BINS' in qvars:
            return qvars['QT_HOST_BINS']
        else:
            return qvars['QT_INSTALL_BINS']

    @staticmethod
    def get_methods():
        return [DependencyMethods.PKGCONFIG, DependencyMethods.CMAKE, DependencyMethods.QMAKE]

    def get_exe_args(self, compiler):
        # Originally this was -fPIE but nowadays the default
        # for upstream and distros seems to be -reduce-relocations
        # which requires -fPIC. This may cause a performance
        # penalty when using self-built Qt or on platforms
        # where -fPIC is not required. If this is an issue
        # for you, patches are welcome.
        return compiler.get_pic_args()

    def get_private_includes(self, mod_inc_dir, module):
        return tuple()

    def log_details(self):
        module_str = ', '.join(self.requested_modules)
        return 'modules: ' + module_str

    def log_info(self):
        return '{}'.format(self.from_text)

    def log_tried(self):
        return self.from_text


class Qt4Dependency(QtBaseDependency):
    def __init__(self, env, kwargs):
        QtBaseDependency.__init__(self, 'qt4', env, kwargs)

    def get_pkgconfig_host_bins(self, core):
        # Only return one bins dir, because the tools are generally all in one
        # directory for Qt4, in Qt5, they must all be in one directory. Return
        # the first one found among the bin variables, in case one tool is not
        # configured to be built.
        applications = ['moc', 'uic', 'rcc', 'lupdate', 'lrelease']
        for application in applications:
            try:
                return os.path.dirname(core.get_pkgconfig_variable('%s_location' % application, {}))
            except MesonException:
                pass


class Qt5Dependency(QtBaseDependency):
    def __init__(self, env, kwargs):
        QtBaseDependency.__init__(self, 'qt5', env, kwargs)

    def get_pkgconfig_host_bins(self, core):
        return core.get_pkgconfig_variable('host_bins', {})

    def get_private_includes(self, mod_inc_dir, module):
        return _qt_get_private_includes(mod_inc_dir, module, self.version)


class Qt6Dependency(QtBaseDependency):
    def __init__(self, env, kwargs):
        QtBaseDependency.__init__(self, 'qt6', env, kwargs)

    def get_pkgconfig_host_bins(self, core):
        return core.get_pkgconfig_variable('host_bins', {})

    def get_private_includes(self, mod_inc_dir, module):
        return _qt_get_private_includes(mod_inc_dir, module, self.version)


class SDL2DependencyConfigTool(ConfigToolDependency):

    tools = ['sdl2-config']
    tool_name = 'sdl2-config'

    def __init__(self, name: str, environment: 'Environment', kwargs: T.Dict[str, T.Any]):
        super().__init__(name, environment, kwargs)
        if not self.is_found:
            return
        self.compile_args = self.get_config_value(['--cflags'], 'compile_args')
        self.link_args = self.get_config_value(['--libs'], 'link_args')

    @staticmethod
    def get_methods():
        if mesonlib.is_osx():
            return [DependencyMethods.PKGCONFIG, DependencyMethods.CONFIG_TOOL, DependencyMethods.EXTRAFRAMEWORK]
        else:
            return [DependencyMethods.PKGCONFIG, DependencyMethods.CONFIG_TOOL]


class WxDependency(ConfigToolDependency):

    tools = ['wx-config-3.0', 'wx-config', 'wx-config-gtk3']
    tool_name = 'wx-config'

    def __init__(self, environment: 'Environment', kwargs: T.Dict[str, T.Any]):
        super().__init__('WxWidgets', environment, kwargs, language='cpp')
        if not self.is_found:
            return
        self.requested_modules = self.get_requested(kwargs)

        extra_args = []
        if self.static:
            extra_args.append('--static=yes')

            # Check to make sure static is going to work
            err = Popen_safe(self.config + extra_args)[2]
            if 'No config found to match' in err:
                mlog.debug('WxWidgets is missing static libraries.')
                self.is_found = False
                return

        # wx-config seems to have a cflags as well but since it requires C++,
        # this should be good, at least for now.
        self.compile_args = self.get_config_value(['--cxxflags'] + extra_args + self.requested_modules, 'compile_args')
        self.link_args = self.get_config_value(['--libs'] + extra_args + self.requested_modules, 'link_args')

    @staticmethod
    def get_requested(kwargs: T.Dict[str, T.Any]) -> T.List[str]:
        if 'modules' not in kwargs:
            return []
        candidates = extract_as_list(kwargs, 'modules')
        for c in candidates:
            if not isinstance(c, str):
                raise DependencyException('wxwidgets module argument is not a string')
        return candidates


class VulkanDependencySystem(ExternalDependency):

    def __init__(self, name: str, environment, kwargs, language: T.Optional[str] = None):
        super().__init__(name, environment, kwargs, language=language)

        try:
            self.vulkan_sdk = os.environ['VULKAN_SDK']
            if not os.path.isabs(self.vulkan_sdk):
                raise DependencyException('VULKAN_SDK must be an absolute path.')
        except KeyError:
            self.vulkan_sdk = None

        if self.vulkan_sdk:
            # TODO: this config might not work on some platforms, fix bugs as reported
            # we should at least detect other 64-bit platforms (e.g. armv8)
            lib_name = 'vulkan'
            lib_dir = 'lib'
            inc_dir = 'include'
            if mesonlib.is_windows():
                lib_name = 'vulkan-1'
                lib_dir = 'Lib32'
                inc_dir = 'Include'
                if detect_cpu_family(self.env.coredata.compilers.host) == 'x86_64':
                    lib_dir = 'Lib'

            # make sure header and lib are valid
            inc_path = os.path.join(self.vulkan_sdk, inc_dir)
            header = os.path.join(inc_path, 'vulkan', 'vulkan.h')
            lib_path = os.path.join(self.vulkan_sdk, lib_dir)
            find_lib = self.clib_compiler.find_library(lib_name, environment, lib_path)

            if not find_lib:
                raise DependencyException('VULKAN_SDK point to invalid directory (no lib)')

            if not os.path.isfile(header):
                raise DependencyException('VULKAN_SDK point to invalid directory (no include)')

            self.type_name = 'vulkan_sdk'
            self.is_found = True
            self.compile_args.append('-I' + inc_path)
            self.link_args.append('-L' + lib_path)
            self.link_args.append('-l' + lib_name)

            # TODO: find a way to retrieve the version from the sdk?
            # Usually it is a part of the path to it (but does not have to be)
            return
        else:
            # simply try to guess it, usually works on linux
            libs = self.clib_compiler.find_library('vulkan', environment, [])
            if libs is not None and self.clib_compiler.has_header('vulkan/vulkan.h', '', environment, disable_cache=True)[0]:
                self.type_name = 'system'
                self.is_found = True
                for lib in libs:
                    self.link_args.append(lib)
                return

    @staticmethod
    def get_methods():
        return [DependencyMethods.SYSTEM]

    def log_tried(self):
        return 'system'

gl_factory = DependencyFactory(
    'gl',
    [DependencyMethods.PKGCONFIG, DependencyMethods.SYSTEM],
    system_class=GLDependencySystem,
)

sdl2_factory = DependencyFactory(
    'sdl2',
    [DependencyMethods.PKGCONFIG, DependencyMethods.CONFIG_TOOL, DependencyMethods.EXTRAFRAMEWORK],
    configtool_class=SDL2DependencyConfigTool,
)

vulkan_factory = DependencyFactory(
    'vulkan',
    [DependencyMethods.PKGCONFIG, DependencyMethods.SYSTEM],
    system_class=VulkanDependencySystem,
)
