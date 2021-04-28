# Copyright 2012-2020 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import itertools
import os, platform, re, sys, shutil, subprocess
import tempfile
import shlex
import typing as T
import collections

from . import coredata
from .linkers import ArLinker, ArmarLinker, VisualStudioLinker, DLinker, CcrxLinker, Xc16Linker, CompCertLinker, C2000Linker, IntelVisualStudioLinker, AIXArLinker
from . import mesonlib
from .mesonlib import (
    MesonException, EnvironmentException, MachineChoice, Popen_safe, PerMachine,
    PerMachineDefaultable, PerThreeMachineDefaultable, split_args, quote_arg, OptionKey
)
from . import mlog
from .programs import (
    ExternalProgram, EmptyExternalProgram
)

from .envconfig import (
    BinaryTable, MachineInfo, Properties, known_cpu_families, CMakeVariables,
)
from . import compilers
from .compilers import (
    Compiler,
    is_assembly,
    is_header,
    is_library,
    is_llvm_ir,
    is_object,
    is_source,
)
from .linkers import (
    AppleDynamicLinker,
    ArmClangDynamicLinker,
    ArmDynamicLinker,
    CcrxDynamicLinker,
    Xc16DynamicLinker,
    CompCertDynamicLinker,
    C2000DynamicLinker,
    ClangClDynamicLinker,
    DynamicLinker,
    GnuBFDDynamicLinker,
    GnuGoldDynamicLinker,
    LLVMDynamicLinker,
    QualcommLLVMDynamicLinker,
    MSVCDynamicLinker,
    OptlinkDynamicLinker,
    NvidiaHPC_DynamicLinker,
    NvidiaHPC_StaticLinker,
    PGIDynamicLinker,
    PGIStaticLinker,
    SolarisDynamicLinker,
    AIXDynamicLinker,
    XilinkDynamicLinker,
    CudaLinker,
    VisualStudioLikeLinkerMixin,
    WASMDynamicLinker,
)
from functools import lru_cache
from .compilers import (
    ArmCCompiler,
    ArmCPPCompiler,
    ArmclangCCompiler,
    ArmclangCPPCompiler,
    AppleClangCCompiler,
    AppleClangCPPCompiler,
    AppleClangObjCCompiler,
    AppleClangObjCPPCompiler,
    ClangCCompiler,
    ClangCPPCompiler,
    ClangObjCCompiler,
    ClangObjCPPCompiler,
    ClangClCCompiler,
    ClangClCPPCompiler,
    FlangFortranCompiler,
    G95FortranCompiler,
    GnuCCompiler,
    GnuCPPCompiler,
    GnuFortranCompiler,
    GnuObjCCompiler,
    GnuObjCPPCompiler,
    ElbrusCCompiler,
    ElbrusCPPCompiler,
    ElbrusFortranCompiler,
    EmscriptenCCompiler,
    EmscriptenCPPCompiler,
    IntelCCompiler,
    IntelClCCompiler,
    IntelCPPCompiler,
    IntelClCPPCompiler,
    IntelFortranCompiler,
    IntelClFortranCompiler,
    JavaCompiler,
    MonoCompiler,
    CudaCompiler,
    VisualStudioCsCompiler,
    NAGFortranCompiler,
    Open64FortranCompiler,
    PathScaleFortranCompiler,
    NvidiaHPC_CCompiler,
    NvidiaHPC_CPPCompiler,
    NvidiaHPC_FortranCompiler,
    PGICCompiler,
    PGICPPCompiler,
    PGIFortranCompiler,
    RustCompiler,
    CcrxCCompiler,
    CcrxCPPCompiler,
    Xc16CCompiler,
    CompCertCCompiler,
    C2000CCompiler,
    C2000CPPCompiler,
    SunFortranCompiler,
    ValaCompiler,
    VisualStudioCCompiler,
    VisualStudioCPPCompiler,
)
from mesonbuild import envconfig

if T.TYPE_CHECKING:
    from configparser import ConfigParser

    from .dependencies import ExternalProgram

build_filename = 'meson.build'

CompilersDict = T.Dict[str, Compiler]

if T.TYPE_CHECKING:
    import argparse


def _get_env_var(for_machine: MachineChoice, is_cross: bool, var_name: str) -> T.Optional[str]:
    """
    Returns the exact env var and the value.
    """
    candidates = PerMachine(
        # The prefixed build version takes priority, but if we are native
        # compiling we fall back on the unprefixed host version. This
        # allows native builds to never need to worry about the 'BUILD_*'
        # ones.
        ([var_name + '_FOR_BUILD'] if is_cross else [var_name]),
        # Always just the unprefixed host verions
        [var_name]
    )[for_machine]
    for var in candidates:
        value = os.environ.get(var)
        if value is not None:
            break
    else:
        formatted = ', '.join([f'{var!r}' for var in candidates])
        mlog.debug(f'None of {formatted} are defined in the environment, not changing global flags.')
        return None
    mlog.debug(f'Using {var!r} from environment with value: {value!r}')
    return value


def detect_gcovr(min_version='3.3', new_rootdir_version='4.2', log=False):
    gcovr_exe = 'gcovr'
    try:
        p, found = Popen_safe([gcovr_exe, '--version'])[0:2]
    except (FileNotFoundError, PermissionError):
        # Doesn't exist in PATH or isn't executable
        return None, None
    found = search_version(found)
    if p.returncode == 0 and mesonlib.version_compare(found, '>=' + min_version):
        if log:
            mlog.log('Found gcovr-{} at {}'.format(found, quote_arg(shutil.which(gcovr_exe))))
        return gcovr_exe, mesonlib.version_compare(found, '>=' + new_rootdir_version)
    return None, None

def detect_llvm_cov():
    tools = get_llvm_tool_names('llvm-cov')
    for tool in tools:
        if mesonlib.exe_exists([tool, '--version']):
            return tool
    return None

def find_coverage_tools() -> T.Tuple[T.Optional[str], T.Optional[str], T.Optional[str], T.Optional[str], T.Optional[str]]:
    gcovr_exe, gcovr_new_rootdir = detect_gcovr()

    llvm_cov_exe = detect_llvm_cov()

    lcov_exe = 'lcov'
    genhtml_exe = 'genhtml'

    if not mesonlib.exe_exists([lcov_exe, '--version']):
        lcov_exe = None
    if not mesonlib.exe_exists([genhtml_exe, '--version']):
        genhtml_exe = None

    return gcovr_exe, gcovr_new_rootdir, lcov_exe, genhtml_exe, llvm_cov_exe

def detect_ninja(version: str = '1.8.2', log: bool = False) -> T.List[str]:
    r = detect_ninja_command_and_version(version, log)
    return r[0] if r else None

def detect_ninja_command_and_version(version: str = '1.8.2', log: bool = False) -> (T.List[str], str):
    env_ninja = os.environ.get('NINJA', None)
    for n in [env_ninja] if env_ninja else ['ninja', 'ninja-build', 'samu']:
        prog = ExternalProgram(n, silent=True)
        if not prog.found():
            continue
        try:
            p, found = Popen_safe(prog.command + ['--version'])[0:2]
        except (FileNotFoundError, PermissionError):
            # Doesn't exist in PATH or isn't executable
            continue
        found = found.strip()
        # Perhaps we should add a way for the caller to know the failure mode
        # (not found or too old)
        if p.returncode == 0 and mesonlib.version_compare(found, '>=' + version):
            if log:
                name = os.path.basename(n)
                if name.endswith('-' + found):
                    name = name[0:-1 - len(found)]
                if name == 'ninja-build':
                    name = 'ninja'
                if name == 'samu':
                    name = 'samurai'
                mlog.log('Found {}-{} at {}'.format(name, found,
                         ' '.join([quote_arg(x) for x in prog.command])))
            return (prog.command, found)

def get_llvm_tool_names(tool: str) -> T.List[str]:
    # Ordered list of possible suffixes of LLVM executables to try. Start with
    # base, then try newest back to oldest (3.5 is arbitrary), and finally the
    # devel version. Please note that the development snapshot in Debian does
    # not have a distinct name. Do not move it to the beginning of the list
    # unless it becomes a stable release.
    suffixes = [
        '', # base (no suffix)
        '-10',  '100',
        '-9',   '90',
        '-8',   '80',
        '-7',   '70',
        '-6.0', '60',
        '-5.0', '50',
        '-4.0', '40',
        '-3.9', '39',
        '-3.8', '38',
        '-3.7', '37',
        '-3.6', '36',
        '-3.5', '35',
        '-11',    # Debian development snapshot
        '-devel', # FreeBSD development snapshot
    ]
    names = []
    for suffix in suffixes:
        names.append(tool + suffix)
    return names

def detect_scanbuild() -> T.List[str]:
    """ Look for scan-build binary on build platform

    First, if a SCANBUILD env variable has been provided, give it precedence
    on all platforms.

    For most platforms, scan-build is found is the PATH contains a binary
    named "scan-build". However, some distribution's package manager (FreeBSD)
    don't. For those, loop through a list of candidates to see if one is
    available.

    Return: a single-element list of the found scan-build binary ready to be
        passed to Popen()
    """
    exelist = []
    if 'SCANBUILD' in os.environ:
        exelist = split_args(os.environ['SCANBUILD'])

    else:
        tools = get_llvm_tool_names('scan-build')
        for tool in tools:
            if shutil.which(tool) is not None:
                exelist = [shutil.which(tool)]
                break

    if exelist:
        tool = exelist[0]
        if os.path.isfile(tool) and os.access(tool, os.X_OK):
            return [tool]
    return []

def detect_clangformat() -> T.List[str]:
    """ Look for clang-format binary on build platform

    Do the same thing as detect_scanbuild to find clang-format except it
    currently does not check the environment variable.

    Return: a single-element list of the found clang-format binary ready to be
        passed to Popen()
    """
    tools = get_llvm_tool_names('clang-format')
    for tool in tools:
        path = shutil.which(tool)
        if path is not None:
            return [path]
    return []

def detect_native_windows_arch():
    """
    The architecture of Windows itself: x86, amd64 or arm64
    """
    # These env variables are always available. See:
    # https://msdn.microsoft.com/en-us/library/aa384274(VS.85).aspx
    # https://blogs.msdn.microsoft.com/david.wang/2006/03/27/howto-detect-process-bitness/
    arch = os.environ.get('PROCESSOR_ARCHITEW6432', '').lower()
    if not arch:
        try:
            # If this doesn't exist, something is messing with the environment
            arch = os.environ['PROCESSOR_ARCHITECTURE'].lower()
        except KeyError:
            raise EnvironmentException('Unable to detect native OS architecture')
    return arch

def detect_windows_arch(compilers: CompilersDict) -> str:
    """
    Detecting the 'native' architecture of Windows is not a trivial task. We
    cannot trust that the architecture that Python is built for is the 'native'
    one because you can run 32-bit apps on 64-bit Windows using WOW64 and
    people sometimes install 32-bit Python on 64-bit Windows.

    We also can't rely on the architecture of the OS itself, since it's
    perfectly normal to compile and run 32-bit applications on Windows as if
    they were native applications. It's a terrible experience to require the
    user to supply a cross-info file to compile 32-bit applications on 64-bit
    Windows. Thankfully, the only way to compile things with Visual Studio on
    Windows is by entering the 'msvc toolchain' environment, which can be
    easily detected.

    In the end, the sanest method is as follows:
    1. Check environment variables that are set by Windows and WOW64 to find out
       if this is x86 (possibly in WOW64), if so use that as our 'native'
       architecture.
    2. If the compiler toolchain target architecture is x86, use that as our
      'native' architecture.
    3. Otherwise, use the actual Windows architecture

    """
    os_arch = detect_native_windows_arch()
    if os_arch == 'x86':
        return os_arch
    # If we're on 64-bit Windows, 32-bit apps can be compiled without
    # cross-compilation. So if we're doing that, just set the native arch as
    # 32-bit and pretend like we're running under WOW64. Else, return the
    # actual Windows architecture that we deduced above.
    for compiler in compilers.values():
        if compiler.id == 'msvc' and (compiler.target == 'x86' or compiler.target == '80x86'):
            return 'x86'
        if compiler.id == 'clang-cl' and compiler.target == 'x86':
            return 'x86'
        if compiler.id == 'gcc' and compiler.has_builtin_define('__i386__'):
            return 'x86'
    return os_arch

def any_compiler_has_define(compilers: CompilersDict, define):
    for c in compilers.values():
        try:
            if c.has_builtin_define(define):
                return True
        except mesonlib.MesonException:
            # Ignore compilers that do not support has_builtin_define.
            pass
    return False

def detect_cpu_family(compilers: CompilersDict) -> str:
    """
    Python is inconsistent in its platform module.
    It returns different values for the same cpu.
    For x86 it might return 'x86', 'i686' or somesuch.
    Do some canonicalization.
    """
    if mesonlib.is_windows():
        trial = detect_windows_arch(compilers)
    elif mesonlib.is_freebsd() or mesonlib.is_netbsd() or mesonlib.is_openbsd() or mesonlib.is_qnx() or mesonlib.is_aix():
        trial = platform.processor().lower()
    else:
        trial = platform.machine().lower()
    if trial.startswith('i') and trial.endswith('86'):
        trial = 'x86'
    elif trial == 'bepc':
        trial = 'x86'
    elif trial == 'arm64':
        trial = 'aarch64'
    elif trial.startswith('arm') or trial.startswith('earm'):
        trial = 'arm'
    elif trial.startswith(('powerpc64', 'ppc64')):
        trial = 'ppc64'
    elif trial.startswith(('powerpc', 'ppc')) or trial in {'macppc', 'power macintosh'}:
        trial = 'ppc'
    elif trial in ('amd64', 'x64', 'i86pc'):
        trial = 'x86_64'
    elif trial in {'sun4u', 'sun4v'}:
        trial = 'sparc64'
    elif trial.startswith('mips'):
        if '64' not in trial:
            trial = 'mips'
        else:
            trial = 'mips64'
    elif trial in {'ip30', 'ip35'}:
        trial = 'mips64'

    # On Linux (and maybe others) there can be any mixture of 32/64 bit code in
    # the kernel, Python, system, 32-bit chroot on 64-bit host, etc. The only
    # reliable way to know is to check the compiler defines.
    if trial == 'x86_64':
        if any_compiler_has_define(compilers, '__i386__'):
            trial = 'x86'
    elif trial == 'aarch64':
        if any_compiler_has_define(compilers, '__arm__'):
            trial = 'arm'
    # Add more quirks here as bugs are reported. Keep in sync with detect_cpu()
    # below.
    elif trial == 'parisc64':
        # ATM there is no 64 bit userland for PA-RISC. Thus always
        # report it as 32 bit for simplicity.
        trial = 'parisc'
    elif trial == 'ppc':
        # AIX always returns powerpc, check here for 64-bit
        if any_compiler_has_define(compilers, '__64BIT__'):
            trial = 'ppc64'

    if trial not in known_cpu_families:
        mlog.warning('Unknown CPU family {!r}, please report this at '
                     'https://github.com/mesonbuild/meson/issues/new with the '
                     'output of `uname -a` and `cat /proc/cpuinfo`'.format(trial))

    return trial

def detect_cpu(compilers: CompilersDict):
    if mesonlib.is_windows():
        trial = detect_windows_arch(compilers)
    elif mesonlib.is_freebsd() or mesonlib.is_netbsd() or mesonlib.is_openbsd() or mesonlib.is_aix():
        trial = platform.processor().lower()
    else:
        trial = platform.machine().lower()

    if trial in ('amd64', 'x64', 'i86pc'):
        trial = 'x86_64'
    if trial == 'x86_64':
        # Same check as above for cpu_family
        if any_compiler_has_define(compilers, '__i386__'):
            trial = 'i686' # All 64 bit cpus have at least this level of x86 support.
    elif trial == 'aarch64':
        # Same check as above for cpu_family
        if any_compiler_has_define(compilers, '__arm__'):
            trial = 'arm'
    elif trial.startswith('earm'):
        trial = 'arm'
    elif trial == 'e2k':
        # Make more precise CPU detection for Elbrus platform.
        trial = platform.processor().lower()
    elif trial.startswith('mips'):
        if '64' not in trial:
            trial = 'mips'
        else:
            trial = 'mips64'

    # Add more quirks here as bugs are reported. Keep in sync with
    # detect_cpu_family() above.
    return trial

def detect_system():
    if sys.platform == 'cygwin':
        return 'cygwin'
    return platform.system().lower()

def detect_msys2_arch():
    if 'MSYSTEM_CARCH' in os.environ:
        return os.environ['MSYSTEM_CARCH']
    return None

def detect_machine_info(compilers: T.Optional[CompilersDict] = None) -> MachineInfo:
    """Detect the machine we're running on

    If compilers are not provided, we cannot know as much. None out those
    fields to avoid accidentally depending on partial knowledge. The
    underlying ''detect_*'' method can be called to explicitly use the
    partial information.
    """
    return MachineInfo(
        detect_system(),
        detect_cpu_family(compilers) if compilers is not None else None,
        detect_cpu(compilers) if compilers is not None else None,
        sys.byteorder)

# TODO make this compare two `MachineInfo`s purely. How important is the
# `detect_cpu_family({})` distinction? It is the one impediment to that.
def machine_info_can_run(machine_info: MachineInfo):
    """Whether we can run binaries for this machine on the current machine.

    Can almost always run 32-bit binaries on 64-bit natively if the host
    and build systems are the same. We don't pass any compilers to
    detect_cpu_family() here because we always want to know the OS
    architecture, not what the compiler environment tells us.
    """
    if machine_info.system != detect_system():
        return False
    true_build_cpu_family = detect_cpu_family({})
    return \
        (machine_info.cpu_family == true_build_cpu_family) or \
        ((true_build_cpu_family == 'x86_64') and (machine_info.cpu_family == 'x86')) or \
        ((true_build_cpu_family == 'aarch64') and (machine_info.cpu_family == 'arm'))

def search_version(text: str) -> str:
    # Usually of the type 4.1.4 but compiler output may contain
    # stuff like this:
    # (Sourcery CodeBench Lite 2014.05-29) 4.8.3 20140320 (prerelease)
    # Limiting major version number to two digits seems to work
    # thus far. When we get to GCC 100, this will break, but
    # if we are still relevant when that happens, it can be
    # considered an achievement in itself.
    #
    # This regex is reaching magic levels. If it ever needs
    # to be updated, do not complexify but convert to something
    # saner instead.
    # We'll demystify it a bit with a verbose definition.
    version_regex = re.compile(r"""
    (?<!                # Zero-width negative lookbehind assertion
        (
            \d          # One digit
            | \.        # Or one period
        )               # One occurrence
    )
    # Following pattern must not follow a digit or period
    (
        \d{1,2}         # One or two digits
        (
            \.\d+       # Period and one or more digits
        )+              # One or more occurrences
        (
            -[a-zA-Z0-9]+   # Hyphen and one or more alphanumeric
        )?              # Zero or one occurrence
    )                   # One occurrence
    """, re.VERBOSE)
    match = version_regex.search(text)
    if match:
        return match.group(0)

    # try a simpler regex that has like "blah 2020.01.100 foo" or "blah 2020.01 foo"
    version_regex = re.compile(r"(\d{1,4}\.\d{1,4}\.?\d{0,4})")
    match = version_regex.search(text)
    if match:
        return match.group(0)

    return 'unknown version'

class Environment:
    private_dir = 'meson-private'
    log_dir = 'meson-logs'
    info_dir = 'meson-info'

    def __init__(self, source_dir: T.Optional[str], build_dir: T.Optional[str], options: 'argparse.Namespace') -> None:
        self.source_dir = source_dir
        self.build_dir = build_dir
        # Do not try to create build directories when build_dir is none.
        # This reduced mode is used by the --buildoptions introspector
        if build_dir is not None:
            self.scratch_dir = os.path.join(build_dir, Environment.private_dir)
            self.log_dir = os.path.join(build_dir, Environment.log_dir)
            self.info_dir = os.path.join(build_dir, Environment.info_dir)
            os.makedirs(self.scratch_dir, exist_ok=True)
            os.makedirs(self.log_dir, exist_ok=True)
            os.makedirs(self.info_dir, exist_ok=True)
            try:
                self.coredata = coredata.load(self.get_build_dir())  # type: coredata.CoreData
                self.first_invocation = False
            except FileNotFoundError:
                self.create_new_coredata(options)
            except coredata.MesonVersionMismatchException as e:
                # This is routine, but tell the user the update happened
                mlog.log('Regenerating configuration from scratch:', str(e))
                coredata.read_cmd_line_file(self.build_dir, options)
                self.create_new_coredata(options)
            except MesonException as e:
                # If we stored previous command line options, we can recover from
                # a broken/outdated coredata.
                if os.path.isfile(coredata.get_cmd_line_file(self.build_dir)):
                    mlog.warning('Regenerating configuration from scratch.')
                    mlog.log('Reason:', mlog.red(str(e)))
                    coredata.read_cmd_line_file(self.build_dir, options)
                    self.create_new_coredata(options)
                else:
                    raise e
        else:
            # Just create a fresh coredata in this case
            self.scratch_dir = ''
            self.create_new_coredata(options)

        ## locally bind some unfrozen configuration

        # Stores machine infos, the only *three* machine one because we have a
        # target machine info on for the user (Meson never cares about the
        # target machine.)
        machines: PerThreeMachineDefaultable[MachineInfo] = PerThreeMachineDefaultable()

        # Similar to coredata.compilers, but lower level in that there is no
        # meta data, only names/paths.
        binaries = PerMachineDefaultable()  # type: PerMachineDefaultable[BinaryTable]

        # Misc other properties about each machine.
        properties = PerMachineDefaultable()  # type: PerMachineDefaultable[Properties]

        # CMake toolchain variables
        cmakevars = PerMachineDefaultable()  # type: PerMachineDefaultable[CMakeVariables]

        ## Setup build machine defaults

        # Will be fully initialized later using compilers later.
        machines.build = detect_machine_info()

        # Just uses hard-coded defaults and environment variables. Might be
        # overwritten by a native file.
        binaries.build = BinaryTable()
        properties.build = Properties()

        # Options with the key parsed into an OptionKey type.
        #
        # Note that order matters because of 'buildtype', if it is after
        # 'optimization' and 'debug' keys, it override them.
        self.options: T.MutableMapping[OptionKey, T.Union[str, T.List[str]]] = collections.OrderedDict()

        ## Read in native file(s) to override build machine configuration

        if self.coredata.config_files is not None:
            config = coredata.parse_machine_files(self.coredata.config_files)
            binaries.build = BinaryTable(config.get('binaries', {}))
            properties.build = Properties(config.get('properties', {}))
            cmakevars.build = CMakeVariables(config.get('cmake', {}))
            self._load_machine_file_options(
                config, properties.build,
                MachineChoice.BUILD if self.coredata.cross_files else MachineChoice.HOST)

        ## Read in cross file(s) to override host machine configuration

        if self.coredata.cross_files:
            config = coredata.parse_machine_files(self.coredata.cross_files)
            properties.host = Properties(config.get('properties', {}))
            binaries.host = BinaryTable(config.get('binaries', {}))
            cmakevars.host = CMakeVariables(config.get('cmake', {}))
            if 'host_machine' in config:
                machines.host = MachineInfo.from_literal(config['host_machine'])
            if 'target_machine' in config:
                machines.target = MachineInfo.from_literal(config['target_machine'])
            # Keep only per machine options from the native file. The cross
            # file takes precedence over all other options.
            for key, value in list(self.options.items()):
                if self.coredata.is_per_machine_option(key):
                    self.options[key.as_build()] = value
            self._load_machine_file_options(config, properties.host, MachineChoice.HOST)


        ## "freeze" now initialized configuration, and "save" to the class.

        self.machines = machines.default_missing()
        self.binaries = binaries.default_missing()
        self.properties = properties.default_missing()
        self.cmakevars = cmakevars.default_missing()

        # Command line options override those from cross/native files
        self.options.update(options.cmd_line_options)

        # Take default value from env if not set in cross/native files or command line.
        self._set_default_options_from_env()
        self._set_default_binaries_from_env()
        self._set_default_properties_from_env()

        # Warn if the user is using two different ways of setting build-type
        # options that override each other
        bt = OptionKey('buildtype')
        db = OptionKey('debug')
        op = OptionKey('optimization')
        if bt in self.options and (db in self.options or op in self.options):
            mlog.warning('Recommend using either -Dbuildtype or -Doptimization + -Ddebug. '
                         'Using both is redundant since they override each other. '
                         'See: https://mesonbuild.com/Builtin-options.html#build-type-options')

        exe_wrapper = self.lookup_binary_entry(MachineChoice.HOST, 'exe_wrapper')
        if exe_wrapper is not None:
            self.exe_wrapper = ExternalProgram.from_bin_list(self, MachineChoice.HOST, 'exe_wrapper')
        else:
            self.exe_wrapper = None

        # List of potential compilers.
        if mesonlib.is_windows():
            # Intel C and C++ compiler is icl on Windows, but icc and icpc elsewhere.
            # Search for icl before cl, since Intel "helpfully" provides a
            # cl.exe that returns *exactly the same thing* that microsofts
            # cl.exe does, and if icl is present, it's almost certainly what
            # you want.
            self.default_c = ['icl', 'cl', 'cc', 'gcc', 'clang', 'clang-cl', 'pgcc']
            # There is currently no pgc++ for Windows, only for  Mac and Linux.
            self.default_cpp = ['icl', 'cl', 'c++', 'g++', 'clang++', 'clang-cl']
            self.default_fortran = ['ifort', 'gfortran', 'flang', 'pgfortran', 'g95']
            # Clang and clang++ are valid, but currently unsupported.
            self.default_objc = ['cc', 'gcc']
            self.default_objcpp = ['c++', 'g++']
            self.default_cs = ['csc', 'mcs']
        else:
            if platform.machine().lower() == 'e2k':
                # There are no objc or objc++ compilers for Elbrus,
                # and there's no clang which can build binaries for host.
                self.default_c = ['cc', 'gcc', 'lcc']
                self.default_cpp = ['c++', 'g++', 'l++']
                self.default_objc = []
                self.default_objcpp = []
            else:
                self.default_c = ['cc', 'gcc', 'clang', 'nvc', 'pgcc', 'icc']
                self.default_cpp = ['c++', 'g++', 'clang++', 'nvc++', 'pgc++', 'icpc']
                self.default_objc = ['cc', 'gcc', 'clang']
                self.default_objcpp = ['c++', 'g++', 'clang++']
            self.default_fortran = ['gfortran', 'flang', 'nvfortran', 'pgfortran', 'ifort', 'g95']
            self.default_cs = ['mcs', 'csc']
        self.default_d = ['ldc2', 'ldc', 'gdc', 'dmd']
        self.default_java = ['javac']
        self.default_cuda = ['nvcc']
        self.default_rust = ['rustc']
        self.default_swift = ['swiftc']
        self.default_vala = ['valac']
        self.default_zig = ['zig']
        self.default_static_linker = ['ar', 'gar']
        self.default_strip = ['strip']
        self.vs_static_linker = ['lib']
        self.clang_cl_static_linker = ['llvm-lib']
        self.cuda_static_linker = ['nvlink']
        self.gcc_static_linker = ['gcc-ar']
        self.clang_static_linker = ['llvm-ar']
        self.default_cmake = ['cmake']
        self.default_pkgconfig = ['pkg-config']
        self.wrap_resolver = None

    def _load_machine_file_options(self, config: 'ConfigParser', properties: Properties, machine: MachineChoice) -> None:
        """Read the contents of a Machine file and put it in the options store."""

        # Look for any options in the deprecated paths section, warn about
        # those, then assign them. They will be overwritten by the ones in the
        # "built-in options" section if they're in both sections.
        paths = config.get('paths')
        if paths:
            mlog.deprecation('The [paths] section is deprecated, use the [built-in options] section instead.')
            for k, v in paths.items():
                self.options[OptionKey.from_string(k).evolve(machine=machine)] = v

        # Next look for compiler options in the "properties" section, this is
        # also deprecated, and these will also be overwritten by the "built-in
        # options" section. We need to remove these from this section, as well.
        deprecated_properties: T.Set[str] = set()
        for lang in compilers.all_languages:
            deprecated_properties.add(lang + '_args')
            deprecated_properties.add(lang + '_link_args')
        for k, v in properties.properties.copy().items():
            if k in deprecated_properties:
                mlog.deprecation(f'{k} in the [properties] section of the machine file is deprecated, use the [built-in options] section.')
                self.options[OptionKey.from_string(k).evolve(machine=machine)] = v
                del properties.properties[k]

        for section, values in config.items():
            if ':' in section:
                subproject, section = section.split(':')
            else:
                subproject = ''
            if section == 'built-in options':
                for k, v in values.items():
                    key = OptionKey.from_string(k)
                    # If we're in the cross file, and there is a `build.foo` warn about that. Later we'll remove it.
                    if machine is MachineChoice.HOST and key.machine is not machine:
                        mlog.deprecation('Setting build machine options in cross files, please use a native file instead, this will be removed in meson 0.60', once=True)
                    if key.subproject:
                        raise MesonException('Do not set subproject options in [built-in options] section, use [subproject:built-in options] instead.')
                    self.options[key.evolve(subproject=subproject, machine=machine)] = v
            elif section == 'project options' and machine is MachineChoice.HOST:
                # Project options are only for the host machine, we don't want
                # to read these from the native file
                for k, v in values.items():
                    # Project options are always for the host machine
                    key = OptionKey.from_string(k)
                    if key.subproject:
                        raise MesonException('Do not set subproject options in [built-in options] section, use [subproject:built-in options] instead.')
                    self.options[key.evolve(subproject=subproject)] = v

    def _set_default_options_from_env(self) -> None:
        opts: T.List[T.Tuple[str, str]] = (
            [(v, f'{k}_args') for k, v in compilers.compilers.CFLAGS_MAPPING.items()] +
            [
                ('PKG_CONFIG_PATH', 'pkg_config_path'),
                ('CMAKE_PREFIX_PATH', 'cmake_prefix_path'),
                ('LDFLAGS', 'ldflags'),
                ('CPPFLAGS', 'cppflags'),
            ]
        )

        env_opts: T.DefaultDict[OptionKey, T.List[str]] = collections.defaultdict(list)

        for (evar, keyname), for_machine in itertools.product(opts, MachineChoice):
            p_env = _get_env_var(for_machine, self.is_cross_build(), evar)
            if p_env is not None:
                # these may contain duplicates, which must be removed, else
                # a duplicates-in-array-option warning arises.
                if keyname == 'cmake_prefix_path':
                    if self.machines[for_machine].is_windows():
                        # Cannot split on ':' on Windows because its in the drive letter
                        _p_env = p_env.split(os.pathsep)
                    else:
                        # https://github.com/mesonbuild/meson/issues/7294
                        _p_env = re.split(r':|;', p_env)
                    p_list = list(mesonlib.OrderedSet(_p_env))
                elif keyname == 'pkg_config_path':
                    p_list = list(mesonlib.OrderedSet(p_env.split(':')))
                else:
                    p_list = split_args(p_env)
                p_list = [e for e in p_list if e]  # filter out any empty elements

                # Take env vars only on first invocation, if the env changes when
                # reconfiguring it gets ignored.
                # FIXME: We should remember if we took the value from env to warn
                # if it changes on future invocations.
                if self.first_invocation:
                    if keyname == 'ldflags':
                        key = OptionKey('link_args', machine=for_machine, lang='c')  # needs a language to initialize properly
                        for lang in compilers.compilers.LANGUAGES_USING_LDFLAGS:
                            key = key.evolve(lang=lang)
                            env_opts[key].extend(p_list)
                    elif keyname == 'cppflags':
                        key = OptionKey('env_args', machine=for_machine, lang='c')
                        for lang in compilers.compilers.LANGUAGES_USING_CPPFLAGS:
                            key = key.evolve(lang=lang)
                            env_opts[key].extend(p_list)
                    else:
                        key = OptionKey.from_string(keyname).evolve(machine=for_machine)
                        if evar in compilers.compilers.CFLAGS_MAPPING.values():
                            # If this is an environment variable, we have to
                            # store it separately until the compiler is
                            # instantiated, as we don't know whether the
                            # compiler will want to use these arguments at link
                            # time and compile time (instead of just at compile
                            # time) until we're instantiating that `Compiler`
                            # object. This is required so that passing
                            # `-Dc_args=` on the command line and `$CFLAGS`
                            # have subtely differen behavior. `$CFLAGS` will be
                            # added to the linker command line if the compiler
                            # acts as a linker driver, `-Dc_args` will not.
                            #
                            # We stil use the original key as the base here, as
                            # we want to inhert the machine and the compiler
                            # language
                            key = key.evolve('env_args')
                        env_opts[key].extend(p_list)

        # Only store options that are not already in self.options,
        # otherwise we'd override the machine files
        for k, v in env_opts.items():
            if k not in self.options:
                self.options[k] = v

    def _set_default_binaries_from_env(self) -> None:
        """Set default binaries from the environment.

        For example, pkg-config can be set via PKG_CONFIG, or in the machine
        file. We want to set the default to the env variable.
        """
        opts = itertools.chain(envconfig.DEPRECATED_ENV_PROG_MAP.items(),
                               envconfig.ENV_VAR_PROG_MAP.items())

        for (name, evar), for_machine in itertools.product(opts, MachineChoice):
            p_env = _get_env_var(for_machine, self.is_cross_build(), evar)
            if p_env is not None:
                self.binaries[for_machine].binaries.setdefault(name, mesonlib.split_args(p_env))

    def _set_default_properties_from_env(self) -> None:
        """Properties which can also be set from the environment."""
        # name, evar, split
        opts: T.List[T.Tuple[str, T.List[str], bool]] = [
            ('boost_includedir', ['BOOST_INCLUDEDIR'], False),
            ('boost_librarydir', ['BOOST_LIBRARYDIR'], False),
            ('boost_root', ['BOOST_ROOT', 'BOOSTROOT'], True),
            ('java_home', ['JAVA_HOME'], False),
        ]

        for (name, evars, split), for_machine in itertools.product(opts, MachineChoice):
            for evar in evars:
                p_env = _get_env_var(for_machine, self.is_cross_build(), evar)
                if p_env is not None:
                    if split:
                        self.properties[for_machine].properties.setdefault(name, p_env.split(os.pathsep))
                    else:
                        self.properties[for_machine].properties.setdefault(name, p_env)
                    break

    def create_new_coredata(self, options: 'argparse.Namespace') -> None:
        # WARNING: Don't use any values from coredata in __init__. It gets
        # re-initialized with project options by the interpreter during
        # build file parsing.
        # meson_command is used by the regenchecker script, which runs meson
        self.coredata = coredata.CoreData(options, self.scratch_dir, mesonlib.get_meson_command())
        self.first_invocation = True

    def is_cross_build(self, when_building_for: MachineChoice = MachineChoice.HOST) -> bool:
        return self.coredata.is_cross_build(when_building_for)

    def dump_coredata(self) -> str:
        return coredata.save(self.coredata, self.get_build_dir())

    def get_log_dir(self) -> str:
        return self.log_dir

    def get_coredata(self) -> coredata.CoreData:
        return self.coredata

    def get_build_command(self, unbuffered=False):
        cmd = mesonlib.get_meson_command().copy()
        if unbuffered and 'python' in os.path.basename(cmd[0]):
            cmd.insert(1, '-u')
        return cmd

    def is_header(self, fname):
        return is_header(fname)

    def is_source(self, fname):
        return is_source(fname)

    def is_assembly(self, fname):
        return is_assembly(fname)

    def is_llvm_ir(self, fname):
        return is_llvm_ir(fname)

    def is_object(self, fname):
        return is_object(fname)

    @lru_cache(maxsize=None)
    def is_library(self, fname):
        return is_library(fname)

    def lookup_binary_entry(self, for_machine: MachineChoice, name: str) -> T.Optional[T.List[str]]:
        return self.binaries[for_machine].lookup_entry(name)

    @staticmethod
    def get_gnu_compiler_defines(compiler):
        """
        Detect GNU compiler platform type (Apple, MinGW, Unix)
        """
        # Arguments to output compiler pre-processor defines to stdout
        # gcc, g++, and gfortran all support these arguments
        args = compiler + ['-E', '-dM', '-']
        p, output, error = Popen_safe(args, write='', stdin=subprocess.PIPE)
        if p.returncode != 0:
            raise EnvironmentException('Unable to detect GNU compiler type:\n' + output + error)
        # Parse several lines of the type:
        # `#define ___SOME_DEF some_value`
        # and extract `___SOME_DEF`
        defines = {}
        for line in output.split('\n'):
            if not line:
                continue
            d, *rest = line.split(' ', 2)
            if d != '#define':
                continue
            if len(rest) == 1:
                defines[rest] = True
            if len(rest) == 2:
                defines[rest[0]] = rest[1]
        return defines

    @staticmethod
    def get_gnu_version_from_defines(defines):
        dot = '.'
        major = defines.get('__GNUC__', '0')
        minor = defines.get('__GNUC_MINOR__', '0')
        patch = defines.get('__GNUC_PATCHLEVEL__', '0')
        return dot.join((major, minor, patch))

    @staticmethod
    def get_lcc_version_from_defines(defines):
        dot = '.'
        generation_and_major = defines.get('__LCC__', '100')
        generation = generation_and_major[:1]
        major = generation_and_major[1:]
        minor = defines.get('__LCC_MINOR__', '0')
        return dot.join((generation, major, minor))

    @staticmethod
    def get_clang_compiler_defines(compiler):
        """
        Get the list of Clang pre-processor defines
        """
        args = compiler + ['-E', '-dM', '-']
        p, output, error = Popen_safe(args, write='', stdin=subprocess.PIPE)
        if p.returncode != 0:
            raise EnvironmentException('Unable to get clang pre-processor defines:\n' + output + error)
        defines = {}
        for line in output.split('\n'):
            if not line:
                continue
            d, *rest = line.split(' ', 2)
            if d != '#define':
                continue
            if len(rest) == 1:
                defines[rest] = True
            if len(rest) == 2:
                defines[rest[0]] = rest[1]
        return defines

    def _get_compilers(self, lang: str, for_machine: MachineChoice) -> T.Tuple[T.List[T.List[str]], T.List[str], T.Optional['ExternalProgram']]:
        '''
        The list of compilers is detected in the exact same way for
        C, C++, ObjC, ObjC++, Fortran, CS so consolidate it here.
        '''
        value = self.lookup_binary_entry(for_machine, lang)
        if value is not None:
            compilers, ccache = BinaryTable.parse_entry(value)
            # Return value has to be a list of compiler 'choices'
            compilers = [compilers]
        else:
            if not self.machines.matches_build_machine(for_machine):
                raise EnvironmentException(f'{lang!r} compiler binary not defined in cross or native file')
            compilers = getattr(self, 'default_' + lang)
            ccache = BinaryTable.detect_ccache()

        if self.machines.matches_build_machine(for_machine):
            exe_wrap = None
        else:
            exe_wrap = self.get_exe_wrapper()

        return compilers, ccache, exe_wrap

    def _handle_exceptions(self, exceptions, binaries, bintype='compiler'):
        errmsg = f'Unknown {bintype}(s): {binaries}'
        if exceptions:
            errmsg += '\nThe following exception(s) were encountered:'
            for (c, e) in exceptions.items():
                errmsg += f'\nRunning "{c}" gave "{e}"'
        raise EnvironmentException(errmsg)

    @staticmethod
    def __failed_to_detect_linker(compiler: T.List[str], args: T.List[str], stdout: str, stderr: str) -> 'T.NoReturn':
        msg = 'Unable to detect linker for compiler "{} {}"\nstdout: {}\nstderr: {}'.format(
            ' '.join(compiler), ' '.join(args), stdout, stderr)
        raise EnvironmentException(msg)

    def _guess_win_linker(self, compiler: T.List[str], comp_class: Compiler,
                          for_machine: MachineChoice, *,
                          use_linker_prefix: bool = True, invoked_directly: bool = True,
                          extra_args: T.Optional[T.List[str]] = None) -> 'DynamicLinker':
        self.coredata.add_lang_args(comp_class.language, comp_class, for_machine, self)

        # Explicitly pass logo here so that we can get the version of link.exe
        if not use_linker_prefix or comp_class.LINKER_PREFIX is None:
            check_args = ['/logo', '--version']
        elif isinstance(comp_class.LINKER_PREFIX, str):
            check_args = [comp_class.LINKER_PREFIX + '/logo', comp_class.LINKER_PREFIX + '--version']
        elif isinstance(comp_class.LINKER_PREFIX, list):
            check_args = comp_class.LINKER_PREFIX + ['/logo'] + comp_class.LINKER_PREFIX + ['--version']

        check_args += self.coredata.options[OptionKey('args', lang=comp_class.language, machine=for_machine)].value

        override = []  # type: T.List[str]
        value = self.lookup_binary_entry(for_machine, comp_class.language + '_ld')
        if value is not None:
            override = comp_class.use_linker_args(value[0])
            check_args += override

        if extra_args is not None:
            check_args.extend(extra_args)

        p, o, _ = Popen_safe(compiler + check_args)
        if o.startswith('LLD'):
            if '(compatible with GNU linkers)' in o:
                return LLVMDynamicLinker(
                    compiler, for_machine, comp_class.LINKER_PREFIX,
                    override, version=search_version(o))
            elif not invoked_directly:
                return ClangClDynamicLinker(
                    for_machine, override, exelist=compiler, prefix=comp_class.LINKER_PREFIX,
                    version=search_version(o), direct=False, machine=None)

        if value is not None and invoked_directly:
            compiler = value
            # We've already hanedled the non-direct case above

        p, o, e = Popen_safe(compiler + check_args)
        if o.startswith('LLD'):
            return ClangClDynamicLinker(
                for_machine, [],
                prefix=comp_class.LINKER_PREFIX if use_linker_prefix else [],
                exelist=compiler, version=search_version(o), direct=invoked_directly)
        elif 'OPTLINK' in o:
            # Opltink's stdout *may* beging with a \r character.
            return OptlinkDynamicLinker(compiler, for_machine, version=search_version(o))
        elif o.startswith('Microsoft') or e.startswith('Microsoft'):
            out = o or e
            match = re.search(r'.*(X86|X64|ARM|ARM64).*', out)
            if match:
                target = str(match.group(1))
            else:
                target = 'x86'

            return MSVCDynamicLinker(
                for_machine, [], machine=target, exelist=compiler,
                prefix=comp_class.LINKER_PREFIX if use_linker_prefix else [],
                version=search_version(out), direct=invoked_directly)
        elif 'GNU coreutils' in o:
            raise EnvironmentException(
                "Found GNU link.exe instead of MSVC link.exe. This link.exe "
                "is not a linker. You may need to reorder entries to your "
                "%PATH% variable to resolve this.")
        self.__failed_to_detect_linker(compiler, check_args, o, e)

    def _guess_nix_linker(self, compiler: T.List[str], comp_class: T.Type[Compiler],
                          for_machine: MachineChoice, *,
                          extra_args: T.Optional[T.List[str]] = None) -> 'DynamicLinker':
        """Helper for guessing what linker to use on Unix-Like OSes.

        :compiler: Invocation to use to get linker
        :comp_class: The Compiler Type (uninstantiated)
        :for_machine: which machine this linker targets
        :extra_args: Any additional arguments required (such as a source file)
        """
        self.coredata.add_lang_args(comp_class.language, comp_class, for_machine, self)
        extra_args = extra_args or []
        extra_args += self.coredata.options[OptionKey('args', lang=comp_class.language, machine=for_machine)].value

        if isinstance(comp_class.LINKER_PREFIX, str):
            check_args = [comp_class.LINKER_PREFIX + '--version'] + extra_args
        else:
            check_args = comp_class.LINKER_PREFIX + ['--version'] + extra_args

        override = []  # type: T.List[str]
        value = self.lookup_binary_entry(for_machine, comp_class.language + '_ld')
        if value is not None:
            override = comp_class.use_linker_args(value[0])
            check_args += override

        _, o, e = Popen_safe(compiler + check_args)
        v = search_version(o + e)
        if o.startswith('LLD'):
            linker = LLVMDynamicLinker(
                compiler, for_machine, comp_class.LINKER_PREFIX, override, version=v)  # type: DynamicLinker
        elif 'Snapdragon' in e and 'LLVM' in e:
            linker = QualcommLLVMDynamicLinker(
                compiler, for_machine, comp_class.LINKER_PREFIX, override, version=v)  # type: DynamicLinker
        elif e.startswith('lld-link: '):
            # The LLD MinGW frontend didn't respond to --version before version 9.0.0,
            # and produced an error message about failing to link (when no object
            # files were specified), instead of printing the version number.
            # Let's try to extract the linker invocation command to grab the version.

            _, o, e = Popen_safe(compiler + check_args + ['-v'])

            try:
                linker_cmd = re.match(r'.*\n(.*?)\nlld-link: ', e, re.DOTALL).group(1)
                linker_cmd = shlex.split(linker_cmd)[0]
            except (AttributeError, IndexError, ValueError):
                pass
            else:
                _, o, e = Popen_safe([linker_cmd, '--version'])
                v = search_version(o)

            linker = LLVMDynamicLinker(compiler, for_machine, comp_class.LINKER_PREFIX, override, version=v)
        # first is for apple clang, second is for real gcc, the third is icc
        elif e.endswith('(use -v to see invocation)\n') or 'macosx_version' in e or 'ld: unknown option:' in e:
            if isinstance(comp_class.LINKER_PREFIX, str):
                _, _, e = Popen_safe(compiler + [comp_class.LINKER_PREFIX + '-v'] + extra_args)
            else:
                _, _, e = Popen_safe(compiler + comp_class.LINKER_PREFIX + ['-v'] + extra_args)
            for line in e.split('\n'):
                if 'PROJECT:ld' in line:
                    v = line.split('-')[1]
                    break
            else:
                v = 'unknown version'
            linker = AppleDynamicLinker(compiler, for_machine, comp_class.LINKER_PREFIX, override, version=v)
        elif 'GNU' in o or 'GNU' in e:
            if 'gold' in o or 'gold' in e:
                cls = GnuGoldDynamicLinker
            else:
                cls = GnuBFDDynamicLinker
            linker = cls(compiler, for_machine, comp_class.LINKER_PREFIX, override, version=v)
        elif 'Solaris' in e or 'Solaris' in o:
            for line in (o+e).split('\n'):
                if 'ld: Software Generation Utilities' in line:
                    v = line.split(':')[2].lstrip()
                    break
            else:
                v = 'unknown version'
            linker = SolarisDynamicLinker(
                compiler, for_machine, comp_class.LINKER_PREFIX, override,
                version=v)
        elif 'ld: 0706-012 The -- flag is not recognized' in e:
            if isinstance(comp_class.LINKER_PREFIX, str):
                _, _, e = Popen_safe(compiler + [comp_class.LINKER_PREFIX + '-V'] + extra_args)
            else:
                _, _, e = Popen_safe(compiler + comp_class.LINKER_PREFIX + ['-V'] + extra_args)
            linker = AIXDynamicLinker(
                compiler, for_machine, comp_class.LINKER_PREFIX, override,
                version=search_version(e))
        else:
            self.__failed_to_detect_linker(compiler, check_args, o, e)
        return linker

    def _detect_c_or_cpp_compiler(self, lang: str, for_machine: MachineChoice, *, override_compiler: T.Optional[T.List[str]] = None) -> Compiler:
        """Shared implementation for finding the C or C++ compiler to use.

        the override_compiler option is provided to allow compilers which use
        the compiler (GCC or Clang usually) as their shared linker, to find
        the linker they need.
        """
        popen_exceptions = {}
        compilers, ccache, exe_wrap = self._get_compilers(lang, for_machine)
        if override_compiler is not None:
            compilers = [override_compiler]
        is_cross = self.is_cross_build(for_machine)
        info = self.machines[for_machine]

        for compiler in compilers:
            if isinstance(compiler, str):
                compiler = [compiler]
            compiler_name = os.path.basename(compiler[0])

            if not {'cl', 'cl.exe', 'clang-cl', 'clang-cl.exe'}.isdisjoint(compiler):
                # Watcom C provides it's own cl.exe clone that mimics an older
                # version of Microsoft's compiler. Since Watcom's cl.exe is
                # just a wrapper, we skip using it if we detect its presence
                # so as not to confuse Meson when configuring for MSVC.
                #
                # Additionally the help text of Watcom's cl.exe is paged, and
                # the binary will not exit without human intervention. In
                # practice, Meson will block waiting for Watcom's cl.exe to
                # exit, which requires user input and thus will never exit.
                if 'WATCOM' in os.environ:
                    def sanitize(p):
                        return os.path.normcase(os.path.abspath(p))

                    watcom_cls = [sanitize(os.path.join(os.environ['WATCOM'], 'BINNT', 'cl')),
                                  sanitize(os.path.join(os.environ['WATCOM'], 'BINNT', 'cl.exe'))]
                    found_cl = sanitize(shutil.which('cl'))
                    if found_cl in watcom_cls:
                        continue
                arg = '/?'
            elif 'armcc' in compiler_name:
                arg = '--vsn'
            elif 'ccrx' in compiler_name:
                arg = '-v'
            elif 'xc16' in compiler_name:
                arg = '--version'
            elif 'ccomp' in compiler_name:
                arg = '-version'
            elif 'cl2000' in compiler_name:
                arg = '-version'
            elif compiler_name in {'icl', 'icl.exe'}:
                # if you pass anything to icl you get stuck in a pager
                arg = ''
            else:
                arg = '--version'

            try:
                p, out, err = Popen_safe(compiler + [arg])
            except OSError as e:
                popen_exceptions[' '.join(compiler + [arg])] = e
                continue

            if 'ccrx' in compiler_name:
                out = err

            full_version = out.split('\n', 1)[0]
            version = search_version(out)

            guess_gcc_or_lcc = False
            if 'Free Software Foundation' in out or 'xt-' in out:
                guess_gcc_or_lcc = 'gcc'
            if 'e2k' in out and 'lcc' in out:
                guess_gcc_or_lcc = 'lcc'
            if 'Microchip Technology' in out:
                # this output has "Free Software Foundation" in its version
                guess_gcc_or_lcc = False

            if guess_gcc_or_lcc:
                defines = self.get_gnu_compiler_defines(compiler)
                if not defines:
                    popen_exceptions[' '.join(compiler)] = 'no pre-processor defines'
                    continue

                if guess_gcc_or_lcc == 'lcc':
                    version = self.get_lcc_version_from_defines(defines)
                    cls = ElbrusCCompiler if lang == 'c' else ElbrusCPPCompiler
                else:
                    version = self.get_gnu_version_from_defines(defines)
                    cls = GnuCCompiler if lang == 'c' else GnuCPPCompiler

                linker = self._guess_nix_linker(compiler, cls, for_machine)

                return cls(
                    ccache + compiler, version, for_machine, is_cross,
                    info, exe_wrap, defines=defines, full_version=full_version,
                    linker=linker)

            if 'Emscripten' in out:
                cls = EmscriptenCCompiler if lang == 'c' else EmscriptenCPPCompiler
                self.coredata.add_lang_args(cls.language, cls, for_machine, self)

                # emcc requires a file input in order to pass arguments to the
                # linker. It'll exit with an error code, but still print the
                # linker version. Old emcc versions ignore -Wl,--version completely,
                # however. We'll report "unknown version" in that case.
                with tempfile.NamedTemporaryFile(suffix='.c') as f:
                    cmd = compiler + [cls.LINKER_PREFIX + "--version", f.name]
                    _, o, _ = Popen_safe(cmd)

                linker = WASMDynamicLinker(
                    compiler, for_machine, cls.LINKER_PREFIX,
                    [], version=search_version(o))
                return cls(
                    ccache + compiler, version, for_machine, is_cross, info,
                    exe_wrap, linker=linker, full_version=full_version)

            if 'armclang' in out:
                # The compiler version is not present in the first line of output,
                # instead it is present in second line, startswith 'Component:'.
                # So, searching for the 'Component' in out although we know it is
                # present in second line, as we are not sure about the
                # output format in future versions
                arm_ver_str = re.search('.*Component.*', out)
                if arm_ver_str is None:
                    popen_exceptions[' '.join(compiler)] = 'version string not found'
                    continue
                arm_ver_str = arm_ver_str.group(0)
                # Override previous values
                version = search_version(arm_ver_str)
                full_version = arm_ver_str
                cls = ArmclangCCompiler if lang == 'c' else ArmclangCPPCompiler
                linker = ArmClangDynamicLinker(for_machine, version=version)
                self.coredata.add_lang_args(cls.language, cls, for_machine, self)
                return cls(
                    ccache + compiler, version, for_machine, is_cross, info,
                    exe_wrap, full_version=full_version, linker=linker)
            if 'CL.EXE COMPATIBILITY' in out:
                # if this is clang-cl masquerading as cl, detect it as cl, not
                # clang
                arg = '--version'
                try:
                    p, out, err = Popen_safe(compiler + [arg])
                except OSError as e:
                    popen_exceptions[' '.join(compiler + [arg])] = e
                version = search_version(out)
                match = re.search('^Target: (.*?)-', out, re.MULTILINE)
                if match:
                    target = match.group(1)
                else:
                    target = 'unknown target'
                cls = ClangClCCompiler if lang == 'c' else ClangClCPPCompiler
                linker = self._guess_win_linker(['lld-link'], cls, for_machine)
                return cls(
                    compiler, version, for_machine, is_cross, info, target,
                    exe_wrap, linker=linker)
            if 'clang' in out or 'Clang' in out:
                linker = None

                defines = self.get_clang_compiler_defines(compiler)

                # Even if the for_machine is darwin, we could be using vanilla
                # clang.
                if 'Apple' in out:
                    cls = AppleClangCCompiler if lang == 'c' else AppleClangCPPCompiler
                else:
                    cls = ClangCCompiler if lang == 'c' else ClangCPPCompiler

                if 'windows' in out or self.machines[for_machine].is_windows():
                    # If we're in a MINGW context this actually will use a gnu
                    # style ld, but for clang on "real" windows we'll use
                    # either link.exe or lld-link.exe
                    try:
                        linker = self._guess_win_linker(compiler, cls, for_machine, invoked_directly=False)
                    except MesonException:
                        pass
                if linker is None:
                    linker = self._guess_nix_linker(compiler, cls, for_machine)

                return cls(
                    ccache + compiler, version, for_machine, is_cross, info,
                    exe_wrap, defines=defines, full_version=full_version, linker=linker)

            if 'Intel(R) C++ Intel(R)' in err:
                version = search_version(err)
                target = 'x86' if 'IA-32' in err else 'x86_64'
                cls = IntelClCCompiler if lang == 'c' else IntelClCPPCompiler
                self.coredata.add_lang_args(cls.language, cls, for_machine, self)
                linker = XilinkDynamicLinker(for_machine, [], version=version)
                return cls(
                    compiler, version, for_machine, is_cross, info, target,
                    exe_wrap, linker=linker)
            if 'Microsoft' in out or 'Microsoft' in err:
                # Latest versions of Visual Studio print version
                # number to stderr but earlier ones print version
                # on stdout.  Why? Lord only knows.
                # Check both outputs to figure out version.
                for lookat in [err, out]:
                    version = search_version(lookat)
                    if version != 'unknown version':
                        break
                else:
                    m = 'Failed to detect MSVC compiler version: stderr was\n{!r}'
                    raise EnvironmentException(m.format(err))
                cl_signature = lookat.split('\n')[0]
                match = re.search(r'.*(x86|x64|ARM|ARM64)([^_A-Za-z0-9]|$)', cl_signature)
                if match:
                    target = match.group(1)
                else:
                    m = 'Failed to detect MSVC compiler target architecture: \'cl /?\' output is\n{}'
                    raise EnvironmentException(m.format(cl_signature))
                cls = VisualStudioCCompiler if lang == 'c' else VisualStudioCPPCompiler
                linker = self._guess_win_linker(['link'], cls, for_machine)
                return cls(
                    compiler, version, for_machine, is_cross, info, target,
                    exe_wrap, full_version=cl_signature, linker=linker)
            if 'PGI Compilers' in out:
                cls = PGICCompiler if lang == 'c' else PGICPPCompiler
                self.coredata.add_lang_args(cls.language, cls, for_machine, self)
                linker = PGIDynamicLinker(compiler, for_machine, cls.LINKER_PREFIX, [], version=version)
                return cls(
                    ccache + compiler, version, for_machine, is_cross,
                    info, exe_wrap, linker=linker)
            if 'NVIDIA Compilers and Tools' in out:
                cls = NvidiaHPC_CCompiler if lang == 'c' else NvidiaHPC_CPPCompiler
                self.coredata.add_lang_args(cls.language, cls, for_machine, self)
                linker = NvidiaHPC_DynamicLinker(compiler, for_machine, cls.LINKER_PREFIX, [], version=version)
                return cls(
                    ccache + compiler, version, for_machine, is_cross,
                    info, exe_wrap, linker=linker)
            if '(ICC)' in out:
                cls = IntelCCompiler if lang == 'c' else IntelCPPCompiler
                l = self._guess_nix_linker(compiler, cls, for_machine)
                return cls(
                    ccache + compiler, version, for_machine, is_cross, info,
                    exe_wrap, full_version=full_version, linker=l)
            if 'ARM' in out:
                cls = ArmCCompiler if lang == 'c' else ArmCPPCompiler
                self.coredata.add_lang_args(cls.language, cls, for_machine, self)
                linker = ArmDynamicLinker(for_machine, version=version)
                return cls(
                    ccache + compiler, version, for_machine, is_cross,
                    info, exe_wrap, full_version=full_version, linker=linker)
            if 'RX Family' in out:
                cls = CcrxCCompiler if lang == 'c' else CcrxCPPCompiler
                self.coredata.add_lang_args(cls.language, cls, for_machine, self)
                linker = CcrxDynamicLinker(for_machine, version=version)
                return cls(
                    ccache + compiler, version, for_machine, is_cross, info,
                    exe_wrap, full_version=full_version, linker=linker)

            if 'Microchip Technology' in out:
                cls = Xc16CCompiler if lang == 'c' else Xc16CCompiler
                self.coredata.add_lang_args(cls.language, cls, for_machine, self)
                linker = Xc16DynamicLinker(for_machine, version=version)
                return cls(
                    ccache + compiler, version, for_machine, is_cross, info,
                    exe_wrap, full_version=full_version, linker=linker)

            if 'CompCert' in out:
                cls = CompCertCCompiler
                self.coredata.add_lang_args(cls.language, cls, for_machine, self)
                linker = CompCertDynamicLinker(for_machine, version=version)
                return cls(
                    ccache + compiler, version, for_machine, is_cross, info,
                    exe_wrap, full_version=full_version, linker=linker)

            if 'TMS320C2000 C/C++' in out:
                cls = C2000CCompiler if lang == 'c' else C2000CPPCompiler
                self.coredata.add_lang_args(cls.language, cls, for_machine, self)
                linker = C2000DynamicLinker(for_machine, version=version)
                return cls(
                    ccache + compiler, version, for_machine, is_cross, info,
                    exe_wrap, full_version=full_version, linker=linker)


        self._handle_exceptions(popen_exceptions, compilers)

    def detect_c_compiler(self, for_machine):
        return self._detect_c_or_cpp_compiler('c', for_machine)

    def detect_cpp_compiler(self, for_machine):
        return self._detect_c_or_cpp_compiler('cpp', for_machine)

    def detect_cuda_compiler(self, for_machine):
        popen_exceptions = {}
        is_cross = self.is_cross_build(for_machine)
        compilers, ccache, exe_wrap = self._get_compilers('cuda', for_machine)
        info = self.machines[for_machine]
        for compiler in compilers:
            if isinstance(compiler, str):
                compiler = [compiler]
            arg = '--version'
            try:
                p, out, err = Popen_safe(compiler + [arg])
            except OSError as e:
                popen_exceptions[' '.join(compiler + [arg])] = e
                continue
            # Example nvcc printout:
            #
            #     nvcc: NVIDIA (R) Cuda compiler driver
            #     Copyright (c) 2005-2018 NVIDIA Corporation
            #     Built on Sat_Aug_25_21:08:01_CDT_2018
            #     Cuda compilation tools, release 10.0, V10.0.130
            #
            # search_version() first finds the "10.0" after "release",
            # rather than the more precise "10.0.130" after "V".
            # The patch version number is occasionally important; For
            # instance, on Linux,
            #    - CUDA Toolkit 8.0.44 requires NVIDIA Driver 367.48
            #    - CUDA Toolkit 8.0.61 requires NVIDIA Driver 375.26
            # Luckily, the "V" also makes it very simple to extract
            # the full version:
            version = out.strip().split('V')[-1]
            cpp_compiler = self.detect_cpp_compiler(for_machine)
            cls = CudaCompiler
            self.coredata.add_lang_args(cls.language, cls, for_machine, self)
            linker = CudaLinker(compiler, for_machine, CudaCompiler.LINKER_PREFIX, [], version=CudaLinker.parse_version())
            return cls(ccache + compiler, version, for_machine, is_cross, exe_wrap, host_compiler=cpp_compiler, info=info, linker=linker)
        raise EnvironmentException('Could not find suitable CUDA compiler: "' + ' '.join(compilers) + '"')

    def detect_fortran_compiler(self, for_machine: MachineChoice):
        popen_exceptions = {}
        compilers, ccache, exe_wrap = self._get_compilers('fortran', for_machine)
        is_cross = self.is_cross_build(for_machine)
        info = self.machines[for_machine]
        for compiler in compilers:
            if isinstance(compiler, str):
                compiler = [compiler]
            for arg in ['--version', '-V']:
                try:
                    p, out, err = Popen_safe(compiler + [arg])
                except OSError as e:
                    popen_exceptions[' '.join(compiler + [arg])] = e
                    continue

                version = search_version(out)
                full_version = out.split('\n', 1)[0]

                guess_gcc_or_lcc = False
                if 'GNU Fortran' in out:
                    guess_gcc_or_lcc = 'gcc'
                if 'e2k' in out and 'lcc' in out:
                    guess_gcc_or_lcc = 'lcc'

                if guess_gcc_or_lcc:
                    defines = self.get_gnu_compiler_defines(compiler)
                    if not defines:
                        popen_exceptions[' '.join(compiler)] = 'no pre-processor defines'
                        continue
                    if guess_gcc_or_lcc == 'lcc':
                        version = self.get_lcc_version_from_defines(defines)
                        cls = ElbrusFortranCompiler
                    else:
                        version = self.get_gnu_version_from_defines(defines)
                        cls = GnuFortranCompiler
                    linker = self._guess_nix_linker(
                        compiler, cls, for_machine)
                    return cls(
                        compiler, version, for_machine, is_cross, info,
                        exe_wrap, defines, full_version=full_version,
                        linker=linker)

                if 'G95' in out:
                    linker = self._guess_nix_linker(
                        compiler, cls, for_machine)
                    return G95FortranCompiler(
                        compiler, version, for_machine, is_cross, info,
                        exe_wrap, full_version=full_version, linker=linker)

                if 'Sun Fortran' in err:
                    version = search_version(err)
                    linker = self._guess_nix_linker(
                        compiler, cls, for_machine)
                    return SunFortranCompiler(
                        compiler, version, for_machine, is_cross, info,
                        exe_wrap, full_version=full_version, linker=linker)

                if 'Intel(R) Visual Fortran' in err:
                    version = search_version(err)
                    target = 'x86' if 'IA-32' in err else 'x86_64'
                    cls = IntelClFortranCompiler
                    self.coredata.add_lang_args(cls.language, cls, for_machine, self)
                    linker = XilinkDynamicLinker(for_machine, [], version=version)
                    return cls(
                        compiler, version, for_machine, is_cross, info,
                        target, exe_wrap, linker=linker)

                if 'ifort (IFORT)' in out:
                    linker = self._guess_nix_linker(compiler, IntelFortranCompiler, for_machine)
                    return IntelFortranCompiler(
                        compiler, version, for_machine, is_cross, info,
                        exe_wrap, full_version=full_version, linker=linker)

                if 'PathScale EKOPath(tm)' in err:
                    return PathScaleFortranCompiler(
                        compiler, version, for_machine, is_cross, info,
                        exe_wrap, full_version=full_version)

                if 'PGI Compilers' in out:
                    cls = PGIFortranCompiler
                    self.coredata.add_lang_args(cls.language, cls, for_machine, self)
                    linker = PGIDynamicLinker(compiler, for_machine,
                                              cls.LINKER_PREFIX, [], version=version)
                    return cls(
                        compiler, version, for_machine, is_cross, info, exe_wrap,
                        full_version=full_version, linker=linker)

                if 'NVIDIA Compilers and Tools' in out:
                    cls = NvidiaHPC_FortranCompiler
                    self.coredata.add_lang_args(cls.language, cls, for_machine, self)
                    linker = PGIDynamicLinker(compiler, for_machine,
                                              cls.LINKER_PREFIX, [], version=version)
                    return cls(
                        compiler, version, for_machine, is_cross, info, exe_wrap,
                        full_version=full_version, linker=linker)

                if 'flang' in out or 'clang' in out:
                    linker = self._guess_nix_linker(
                        compiler, FlangFortranCompiler, for_machine)
                    return FlangFortranCompiler(
                        compiler, version, for_machine, is_cross, info,
                        exe_wrap, full_version=full_version, linker=linker)

                if 'Open64 Compiler Suite' in err:
                    linker = self._guess_nix_linker(
                        compiler, Open64FortranCompiler, for_machine)
                    return Open64FortranCompiler(
                        compiler, version, for_machine, is_cross, info,
                        exe_wrap, full_version=full_version, linker=linker)

                if 'NAG Fortran' in err:
                    linker = self._guess_nix_linker(
                        compiler, NAGFortranCompiler, for_machine)
                    return NAGFortranCompiler(
                        compiler, version, for_machine, is_cross, info,
                        exe_wrap, full_version=full_version, linker=linker)

        self._handle_exceptions(popen_exceptions, compilers)

    def get_scratch_dir(self) -> str:
        return self.scratch_dir

    def detect_objc_compiler(self, for_machine: MachineInfo) -> 'Compiler':
        return self._detect_objc_or_objcpp_compiler(for_machine, True)

    def detect_objcpp_compiler(self, for_machine: MachineInfo) -> 'Compiler':
        return self._detect_objc_or_objcpp_compiler(for_machine, False)

    def _detect_objc_or_objcpp_compiler(self, for_machine: MachineChoice, objc: bool) -> 'Compiler':
        popen_exceptions = {}
        compilers, ccache, exe_wrap = self._get_compilers('objc' if objc else 'objcpp', for_machine)
        is_cross = self.is_cross_build(for_machine)
        info = self.machines[for_machine]

        for compiler in compilers:
            if isinstance(compiler, str):
                compiler = [compiler]
            arg = ['--version']
            try:
                p, out, err = Popen_safe(compiler + arg)
            except OSError as e:
                popen_exceptions[' '.join(compiler + arg)] = e
                continue
            version = search_version(out)
            if 'Free Software Foundation' in out:
                defines = self.get_gnu_compiler_defines(compiler)
                if not defines:
                    popen_exceptions[' '.join(compiler)] = 'no pre-processor defines'
                    continue
                version = self.get_gnu_version_from_defines(defines)
                comp = GnuObjCCompiler if objc else GnuObjCPPCompiler
                linker = self._guess_nix_linker(compiler, comp, for_machine)
                return comp(
                    ccache + compiler, version, for_machine, is_cross, info,
                    exe_wrap, defines, linker=linker)
            if 'clang' in out:
                linker = None
                defines = self.get_clang_compiler_defines(compiler)
                if not defines:
                    popen_exceptions[' '.join(compiler)] = 'no pre-processor defines'
                    continue
                if 'Apple' in out:
                    comp = AppleClangObjCCompiler if objc else AppleClangObjCPPCompiler
                else:
                    comp = ClangObjCCompiler if objc else ClangObjCPPCompiler
                if 'windows' in out or self.machines[for_machine].is_windows():
                    # If we're in a MINGW context this actually will use a gnu style ld
                    try:
                        linker = self._guess_win_linker(compiler, comp, for_machine)
                    except MesonException:
                        pass

                if not linker:
                    linker = self._guess_nix_linker(
                        compiler, comp, for_machine)
                return comp(
                    ccache + compiler, version, for_machine,
                    is_cross, info, exe_wrap, linker=linker, defines=defines)
        self._handle_exceptions(popen_exceptions, compilers)

    def detect_java_compiler(self, for_machine):
        exelist = self.lookup_binary_entry(for_machine, 'java')
        info = self.machines[for_machine]
        if exelist is None:
            # TODO support fallback
            exelist = [self.default_java[0]]

        try:
            p, out, err = Popen_safe(exelist + ['-version'])
        except OSError:
            raise EnvironmentException('Could not execute Java compiler "{}"'.format(' '.join(exelist)))
        if 'javac' in out or 'javac' in err:
            version = search_version(err if 'javac' in err else out)
            if not version or version == 'unknown version':
                parts = (err if 'javac' in err else out).split()
                if len(parts) > 1:
                    version = parts[1]
            comp_class = JavaCompiler
            self.coredata.add_lang_args(comp_class.language, comp_class, for_machine, self)
            return comp_class(exelist, version, for_machine, info)
        raise EnvironmentException('Unknown compiler "' + ' '.join(exelist) + '"')

    def detect_cs_compiler(self, for_machine):
        compilers, ccache, exe_wrap = self._get_compilers('cs', for_machine)
        popen_exceptions = {}
        info = self.machines[for_machine]
        for comp in compilers:
            if not isinstance(comp, list):
                comp = [comp]
            try:
                p, out, err = Popen_safe(comp + ['--version'])
            except OSError as e:
                popen_exceptions[' '.join(comp + ['--version'])] = e
                continue

            version = search_version(out)
            if 'Mono' in out:
                cls = MonoCompiler
            elif "Visual C#" in out:
                cls = VisualStudioCsCompiler
            else:
                continue
            self.coredata.add_lang_args(cls.language, cls, for_machine, self)
            return cls(comp, version, for_machine, info)

        self._handle_exceptions(popen_exceptions, compilers)

    def detect_vala_compiler(self, for_machine):
        exelist = self.lookup_binary_entry(for_machine, 'vala')
        is_cross = self.is_cross_build(for_machine)
        info = self.machines[for_machine]
        if exelist is None:
            # TODO support fallback
            exelist = [self.default_vala[0]]

        try:
            p, out = Popen_safe(exelist + ['--version'])[0:2]
        except OSError:
            raise EnvironmentException('Could not execute Vala compiler "{}"'.format(' '.join(exelist)))
        version = search_version(out)
        if 'Vala' in out:
            comp_class = ValaCompiler
            self.coredata.add_lang_args(comp_class.language, comp_class, for_machine, self)
            return comp_class(exelist, version, for_machine, info, is_cross)
        raise EnvironmentException('Unknown compiler "' + ' '.join(exelist) + '"')

    def detect_rust_compiler(self, for_machine: MachineChoice) -> RustCompiler:
        popen_exceptions = {}  # type: T.Dict[str, Exception]
        compilers, _, exe_wrap = self._get_compilers('rust', for_machine)
        is_cross = self.is_cross_build(for_machine)
        info = self.machines[for_machine]

        cc = self.detect_c_compiler(for_machine)
        is_link_exe = isinstance(cc.linker, VisualStudioLikeLinkerMixin)
        override = self.lookup_binary_entry(for_machine, 'rust_ld')

        for compiler in compilers:
            if isinstance(compiler, str):
                compiler = [compiler]
            arg = ['--version']
            try:
                out = Popen_safe(compiler + arg)[1]
            except OSError as e:
                popen_exceptions[' '.join(compiler + arg)] = e
                continue

            version = search_version(out)

            if 'rustc' in out:
                # On Linux and mac rustc will invoke gcc (clang for mac
                # presumably) and it can do this windows, for dynamic linking.
                # this means the easiest way to C compiler for dynamic linking.
                # figure out what linker to use is to just get the value of the
                # C compiler and use that as the basis of the rust linker.
                # However, there are two things we need to change, if CC is not
                # the default use that, and second add the necessary arguments
                # to rust to use -fuse-ld

                if any(a.startswith('linker=') for a in compiler):
                    mlog.warning(
                        'Please do not put -C linker= in your compiler '
                        'command, set rust_ld=command in your cross file '
                        'or use the RUST_LD environment variable, otherwise meson '
                        'will override your selection.')

                if override is None:
                    extra_args = {}
                    always_args = []
                    if is_link_exe:
                        compiler.extend(RustCompiler.use_linker_args(cc.linker.exelist[0]))
                        extra_args['direct'] = True
                        extra_args['machine'] = cc.linker.machine
                    else:
                        exelist = cc.linker.exelist.copy()
                        if 'ccache' in exelist[0]:
                            del exelist[0]
                        c = exelist.pop(0)
                        compiler.extend(RustCompiler.use_linker_args(c))

                        # Also ensure that we pass any extra arguments to the linker
                        for l in exelist:
                            compiler.extend(['-C', f'link-arg={l}'])

                    # This trickery with type() gets us the class of the linker
                    # so we can initialize a new copy for the Rust Compiler
                    if is_link_exe:
                        linker = type(cc.linker)(for_machine, always_args, exelist=cc.linker.exelist,
                                                 version=cc.linker.version, **extra_args)
                    else:
                        linker = type(cc.linker)(compiler, for_machine, cc.LINKER_PREFIX,
                                                 always_args=always_args, version=cc.linker.version,
                                                 **extra_args)
                elif 'link' in override[0]:
                    linker = self._guess_win_linker(
                        override, RustCompiler, for_machine, use_linker_prefix=False)
                    # rustc takes linker arguments without a prefix, and
                    # inserts the correct prefix itself.
                    linker.direct = True
                    compiler.extend(RustCompiler.use_linker_args(linker.exelist[0]))
                else:
                    # On linux and macos rust will invoke the c compiler for
                    # linking, on windows it will use lld-link or link.exe.
                    # we will simply ask for the C compiler that corresponds to
                    # it, and use that.
                    cc = self._detect_c_or_cpp_compiler('c', for_machine, override_compiler=override)
                    linker = cc.linker

                    # Of course, we're not going to use any of that, we just
                    # need it to get the proper arguments to pass to rustc
                    c = linker.exelist[1] if linker.exelist[0].endswith('ccache') else linker.exelist[0]
                    compiler.extend(RustCompiler.use_linker_args(c))

                self.coredata.add_lang_args(RustCompiler.language, RustCompiler, for_machine, self)
                return RustCompiler(
                    compiler, version, for_machine, is_cross, info, exe_wrap,
                    linker=linker)

        self._handle_exceptions(popen_exceptions, compilers)

    def detect_d_compiler(self, for_machine: MachineChoice):
        info = self.machines[for_machine]

        # Detect the target architecture, required for proper architecture handling on Windows.
        # MSVC compiler is required for correct platform detection.
        c_compiler = {'c': self.detect_c_compiler(for_machine)}
        is_msvc = isinstance(c_compiler['c'], VisualStudioCCompiler)
        if not is_msvc:
            c_compiler = {}

        arch = detect_cpu_family(c_compiler)
        if is_msvc and arch == 'x86':
            arch = 'x86_mscoff'

        popen_exceptions = {}
        is_cross = self.is_cross_build(for_machine)
        results, ccache, exe_wrap = self._get_compilers('d', for_machine)
        for exelist in results:
            # Search for a D compiler.
            # We prefer LDC over GDC unless overridden with the DC
            # environment variable because LDC has a much more
            # up to date language version at time (2016).
            if not isinstance(exelist, list):
                exelist = [exelist]
            if os.path.basename(exelist[-1]).startswith(('ldmd', 'gdmd')):
                raise EnvironmentException(
                    'Meson does not support {} as it is only a DMD frontend for another compiler.'
                    'Please provide a valid value for DC or unset it so that Meson can resolve the compiler by itself.'.format(exelist[-1]))
            try:
                p, out = Popen_safe(exelist + ['--version'])[0:2]
            except OSError as e:
                popen_exceptions[' '.join(exelist + ['--version'])] = e
                continue
            version = search_version(out)
            full_version = out.split('\n', 1)[0]

            if 'LLVM D compiler' in out:
                # LDC seems to require a file
                # We cannot use NamedTemproraryFile on windows, its documented
                # to not work for our uses. So, just use mkstemp and only have
                # one path for simplicity.
                o, f = tempfile.mkstemp('.d')
                os.close(o)

                try:
                    if info.is_windows() or info.is_cygwin():
                        objfile = os.path.basename(f)[:-1] + 'obj'
                        linker = self._guess_win_linker(
                            exelist,
                            compilers.LLVMDCompiler, for_machine,
                            use_linker_prefix=True, invoked_directly=False,
                            extra_args=[f])
                    else:
                        # LDC writes an object file to the current working directory.
                        # Clean it up.
                        objfile = os.path.basename(f)[:-1] + 'o'
                        linker = self._guess_nix_linker(
                            exelist, compilers.LLVMDCompiler, for_machine,
                            extra_args=[f])
                finally:
                    mesonlib.windows_proof_rm(f)
                    mesonlib.windows_proof_rm(objfile)

                return compilers.LLVMDCompiler(
                    exelist, version, for_machine, info, arch,
                    full_version=full_version, linker=linker, version_output=out)
            elif 'gdc' in out:
                linker = self._guess_nix_linker(exelist, compilers.GnuDCompiler, for_machine)
                return compilers.GnuDCompiler(
                    exelist, version, for_machine, info, arch,
                    exe_wrapper=exe_wrap, is_cross=is_cross,
                    full_version=full_version, linker=linker)
            elif 'The D Language Foundation' in out or 'Digital Mars' in out:
                # DMD seems to require a file
                # We cannot use NamedTemproraryFile on windows, its documented
                # to not work for our uses. So, just use mkstemp and only have
                # one path for simplicity.
                o, f = tempfile.mkstemp('.d')
                os.close(o)

                # DMD as different detection logic for x86 and x86_64
                arch_arg = '-m64' if arch == 'x86_64' else '-m32'

                try:
                    if info.is_windows() or info.is_cygwin():
                        objfile = os.path.basename(f)[:-1] + 'obj'
                        linker = self._guess_win_linker(
                            exelist, compilers.DmdDCompiler, for_machine,
                            invoked_directly=False, extra_args=[f, arch_arg])
                    else:
                        objfile = os.path.basename(f)[:-1] + 'o'
                        linker = self._guess_nix_linker(
                            exelist, compilers.DmdDCompiler, for_machine,
                            extra_args=[f, arch_arg])
                finally:
                    mesonlib.windows_proof_rm(f)
                    mesonlib.windows_proof_rm(objfile)

                return compilers.DmdDCompiler(
                    exelist, version, for_machine, info, arch,
                    full_version=full_version, linker=linker)
            raise EnvironmentException('Unknown compiler "' + ' '.join(exelist) + '"')

        self._handle_exceptions(popen_exceptions, compilers)

    def detect_swift_compiler(self, for_machine):
        exelist = self.lookup_binary_entry(for_machine, 'swift')
        is_cross = self.is_cross_build(for_machine)
        info = self.machines[for_machine]
        if exelist is None:
            # TODO support fallback
            exelist = [self.default_swift[0]]

        try:
            p, _, err = Popen_safe(exelist + ['-v'])
        except OSError:
            raise EnvironmentException('Could not execute Swift compiler "{}"'.format(' '.join(exelist)))
        version = search_version(err)
        if 'Swift' in err:
            # As for 5.0.1 swiftc *requires* a file to check the linker:
            with tempfile.NamedTemporaryFile(suffix='.swift') as f:
                linker = self._guess_nix_linker(
                    exelist, compilers.SwiftCompiler, for_machine,
                    extra_args=[f.name])
            return compilers.SwiftCompiler(
                exelist, version, for_machine, info, is_cross, linker=linker)

        raise EnvironmentException('Unknown compiler "' + ' '.join(exelist) + '"')

    def detect_zig_compiler(self, for_machine: MachineChoice) -> compilers.ZigCompiler:
        exelist = self.lookup_binary_entry(for_machine, 'zig')
        is_cross = self.is_cross_build(for_machine)
        info = self.machines[for_machine]
        if exelist is None:
            exelist = [self.default_zig[0]]

        try:
            _, ver, _ = Popen_safe(exelist + ['version'])
        except OSError:
            raise EnvironmentException('Could not execute Zig compiler "{}"'.format(' '.join(exelist)))

        version = search_version(ver)
        comp = compilers.ZigCompiler(exelist, version, for_machine, info, self.exe_wrapper, is_cross)
        self.coredata.add_lang_args(comp.language, compilers.ZigCompiler, for_machine, self)

        return comp

    def compiler_from_language(self, lang: str, for_machine: MachineChoice):
        if lang == 'c':
            comp = self.detect_c_compiler(for_machine)
        elif lang == 'cpp':
            comp = self.detect_cpp_compiler(for_machine)
        elif lang == 'objc':
            comp = self.detect_objc_compiler(for_machine)
        elif lang == 'cuda':
            comp = self.detect_cuda_compiler(for_machine)
        elif lang == 'objcpp':
            comp = self.detect_objcpp_compiler(for_machine)
        elif lang == 'java':
            comp = self.detect_java_compiler(for_machine)
        elif lang == 'cs':
            comp = self.detect_cs_compiler(for_machine)
        elif lang == 'vala':
            comp = self.detect_vala_compiler(for_machine)
        elif lang == 'd':
            comp = self.detect_d_compiler(for_machine)
        elif lang == 'rust':
            comp = self.detect_rust_compiler(for_machine)
        elif lang == 'fortran':
            comp = self.detect_fortran_compiler(for_machine)
        elif lang == 'swift':
            comp = self.detect_swift_compiler(for_machine)
        elif lang == 'zig':
            comp = self.detect_zig_compiler(for_machine)
        else:
            comp = None
        return comp

    def detect_compiler_for(self, lang: str, for_machine: MachineChoice):
        comp = self.compiler_from_language(lang, for_machine)
        if comp is not None:
            assert comp.for_machine == for_machine
            self.coredata.process_new_compiler(lang, comp, self)
        return comp

    def detect_static_linker(self, compiler):
        linker = self.lookup_binary_entry(compiler.for_machine, 'ar')
        if linker is not None:
            linkers = [linker]
        else:
            defaults = [[l] for l in self.default_static_linker]
            if isinstance(compiler, compilers.CudaCompiler):
                linkers = [self.cuda_static_linker] + defaults
            elif isinstance(compiler, compilers.VisualStudioLikeCompiler):
                linkers = [self.vs_static_linker, self.clang_cl_static_linker]
            elif isinstance(compiler, compilers.GnuCompiler):
                # Use gcc-ar if available; needed for LTO
                linkers = [self.gcc_static_linker] + defaults
            elif isinstance(compiler, compilers.ClangCompiler):
                # Use llvm-ar if available; needed for LTO
                linkers = [self.clang_static_linker] + defaults
            elif isinstance(compiler, compilers.DCompiler):
                # Prefer static linkers over linkers used by D compilers
                if mesonlib.is_windows():
                    linkers = [self.vs_static_linker, self.clang_cl_static_linker, compiler.get_linker_exelist()]
                else:
                    linkers = defaults
            elif isinstance(compiler, IntelClCCompiler):
                # Intel has it's own linker that acts like microsoft's lib
                linkers = ['xilib']
            elif isinstance(compiler, (PGICCompiler, PGIFortranCompiler)) and mesonlib.is_windows():
                linkers = [['ar']]  # For PGI on Windows, "ar" is just a wrapper calling link/lib.
            else:
                linkers = defaults
        popen_exceptions = {}
        for linker in linkers:
            if not {'lib', 'lib.exe', 'llvm-lib', 'llvm-lib.exe', 'xilib', 'xilib.exe'}.isdisjoint(linker):
                arg = '/?'
            elif not {'ar2000', 'ar2000.exe'}.isdisjoint(linker):
                arg = '?'
            else:
                arg = '--version'
            try:
                p, out, err = Popen_safe(linker + [arg])
            except OSError as e:
                popen_exceptions[' '.join(linker + [arg])] = e
                continue
            if "xilib: executing 'lib'" in err:
                return IntelVisualStudioLinker(linker, getattr(compiler, 'machine', None))
            if '/OUT:' in out.upper() or '/OUT:' in err.upper():
                return VisualStudioLinker(linker, getattr(compiler, 'machine', None))
            if 'ar-Error-Unknown switch: --version' in err:
                return PGIStaticLinker(linker)
            if p.returncode == 0 and ('armar' in linker or 'armar.exe' in linker):
                return ArmarLinker(linker)
            if 'DMD32 D Compiler' in out or 'DMD64 D Compiler' in out:
                return DLinker(linker, compiler.arch)
            if 'LDC - the LLVM D compiler' in out:
                return DLinker(linker, compiler.arch, rsp_syntax=compiler.rsp_file_syntax())
            if 'GDC' in out and ' based on D ' in out:
                return DLinker(linker, compiler.arch)
            if err.startswith('Renesas') and ('rlink' in linker or 'rlink.exe' in linker):
                return CcrxLinker(linker)
            if out.startswith('GNU ar') and ('xc16-ar' in linker or 'xc16-ar.exe' in linker):
                return Xc16Linker(linker)
            if out.startswith('TMS320C2000') and ('ar2000' in linker or 'ar2000.exe' in linker):
                return C2000Linker(linker)
            if out.startswith('The CompCert'):
                return CompCertLinker(linker)
            if p.returncode == 0:
                return ArLinker(linker)
            if p.returncode == 1 and err.startswith('usage'): # OSX
                return ArLinker(linker)
            if p.returncode == 1 and err.startswith('Usage'): # AIX
                return AIXArLinker(linker)
            if p.returncode == 1 and err.startswith('ar: bad option: --'): # Solaris
                return ArLinker(linker)
        self._handle_exceptions(popen_exceptions, linkers, 'linker')
        raise EnvironmentException('Unknown static linker "{}"'.format(' '.join(linkers)))

    def get_source_dir(self) -> str:
        return self.source_dir

    def get_build_dir(self) -> str:
        return self.build_dir

    def get_import_lib_dir(self) -> str:
        "Install dir for the import library (library used for linking)"
        return self.get_libdir()

    def get_shared_module_dir(self) -> str:
        "Install dir for shared modules that are loaded at runtime"
        return self.get_libdir()

    def get_shared_lib_dir(self) -> str:
        "Install dir for the shared library"
        m = self.machines.host
        # Windows has no RPATH or similar, so DLLs must be next to EXEs.
        if m.is_windows() or m.is_cygwin():
            return self.get_bindir()
        return self.get_libdir()

    def get_static_lib_dir(self) -> str:
        "Install dir for the static library"
        return self.get_libdir()

    def get_prefix(self) -> str:
        return self.coredata.get_option(OptionKey('prefix'))

    def get_libdir(self) -> str:
        return self.coredata.get_option(OptionKey('libdir'))

    def get_libexecdir(self) -> str:
        return self.coredata.get_option(OptionKey('libexecdir'))

    def get_bindir(self) -> str:
        return self.coredata.get_option(OptionKey('bindir'))

    def get_includedir(self) -> str:
        return self.coredata.get_option(OptionKey('includedir'))

    def get_mandir(self) -> str:
        return self.coredata.get_option(OptionKey('mandir'))

    def get_datadir(self) -> str:
        return self.coredata.get_option(OptionKey('datadir'))

    def get_compiler_system_dirs(self, for_machine: MachineChoice):
        for comp in self.coredata.compilers[for_machine].values():
            if isinstance(comp, compilers.ClangCompiler):
                index = 1
                break
            elif isinstance(comp, compilers.GnuCompiler):
                index = 2
                break
        else:
            # This option is only supported by gcc and clang. If we don't get a
            # GCC or Clang compiler return and empty list.
            return []

        p, out, _ = Popen_safe(comp.get_exelist() + ['-print-search-dirs'])
        if p.returncode != 0:
            raise mesonlib.MesonException('Could not calculate system search dirs')
        out = out.split('\n')[index].lstrip('libraries: =').split(':')
        return [os.path.normpath(p) for p in out]

    def need_exe_wrapper(self, for_machine: MachineChoice = MachineChoice.HOST):
        value = self.properties[for_machine].get('needs_exe_wrapper', None)
        if value is not None:
            return value
        return not machine_info_can_run(self.machines[for_machine])

    def get_exe_wrapper(self):
        if not self.need_exe_wrapper():
            return EmptyExternalProgram()
        return self.exe_wrapper
