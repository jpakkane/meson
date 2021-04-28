#!/usr/bin/env python3

# Copyright 2012-2019 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from concurrent.futures import ProcessPoolExecutor, CancelledError
from enum import Enum
from io import StringIO
from pathlib import Path, PurePath
import argparse
import functools
import itertools
import json
import multiprocessing
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import typing as T
import xml.etree.ElementTree as ET
import collections

from mesonbuild import build
from mesonbuild import environment
from mesonbuild import compilers
from mesonbuild import mesonlib
from mesonbuild import mlog
from mesonbuild import mtest
from mesonbuild.build import ConfigurationData
from mesonbuild.mesonlib import MachineChoice, Popen_safe, TemporaryDirectoryWinProof
from mesonbuild.mlog import bold, green, red, yellow
from mesonbuild.coredata import backendlist, version as meson_version

from run_tests import get_fake_options, run_configure, get_meson_script
from run_tests import get_backend_commands, get_backend_args_for_dir, Backend
from run_tests import ensure_backend_detects_changes
from run_tests import guess_backend

ALL_TESTS = ['cmake', 'common', 'native', 'warning-meson', 'failing-meson', 'failing-build', 'failing-test',
             'keyval', 'platform-osx', 'platform-windows', 'platform-linux',
             'java', 'C#', 'vala',  'rust', 'd', 'objective c', 'objective c++',
             'fortran', 'swift', 'cuda', 'python3', 'python', 'fpga', 'frameworks', 'nasm', 'wasm', 'zig'
             ]


class BuildStep(Enum):
    configure = 1
    build = 2
    test = 3
    install = 4
    clean = 5
    validate = 6


class TestResult(BaseException):
    def __init__(self, cicmds):
        self.msg = ''  # empty msg indicates test success
        self.stdo = ''
        self.stde = ''
        self.mlog = ''
        self.cicmds = cicmds
        self.conftime = 0
        self.buildtime = 0
        self.testtime = 0

    def add_step(self, step, stdo, stde, mlog='', time=0):
        self.step = step
        self.stdo += stdo
        self.stde += stde
        self.mlog += mlog
        if step == BuildStep.configure:
            self.conftime = time
        elif step == BuildStep.build:
            self.buildtime = time
        elif step == BuildStep.test:
            self.testtime = time

    def fail(self, msg):
        self.msg = msg

class InstalledFile:
    def __init__(self, raw: T.Dict[str, str]):
        self.path = raw['file']
        self.typ = raw['type']
        self.platform = raw.get('platform', None)
        self.language = raw.get('language', 'c')  # type: str

        version = raw.get('version', '')  # type: str
        if version:
            self.version = version.split('.')  # type: T.List[str]
        else:
            # split on '' will return [''], we want an empty list though
            self.version = []

    def get_path(self, compiler: str, env: environment.Environment) -> T.Optional[Path]:
        p = Path(self.path)
        canonical_compiler = compiler
        if ((compiler in ['clang-cl', 'intel-cl']) or
                (env.machines.host.is_windows() and compiler in {'pgi', 'dmd', 'ldc'})):
            canonical_compiler = 'msvc'

        has_pdb = False
        if self.language in {'c', 'cpp'}:
            has_pdb = canonical_compiler == 'msvc'
        elif self.language == 'd':
            # dmd's optlink does not genearte pdb iles
            has_pdb = env.coredata.compilers.host['d'].linker.id in {'link', 'lld-link'}

        # Abort if the platform does not match
        matches = {
            'msvc': canonical_compiler == 'msvc',
            'gcc': canonical_compiler != 'msvc',
            'cygwin': env.machines.host.is_cygwin(),
            '!cygwin': not env.machines.host.is_cygwin(),
        }.get(self.platform or '', True)
        if not matches:
            return None

        # Handle the different types
        if self.typ in ['file', 'dir']:
            return p
        elif self.typ == 'shared_lib':
            if env.machines.host.is_windows() or env.machines.host.is_cygwin():
                # Windows only has foo.dll and foo-X.dll
                if len(self.version) > 1:
                    return None
                if self.version:
                    p = p.with_name('{}-{}'.format(p.name, self.version[0]))
                return p.with_suffix('.dll')

            p = p.with_name(f'lib{p.name}')
            if env.machines.host.is_darwin():
                # MacOS only has libfoo.dylib and libfoo.X.dylib
                if len(self.version) > 1:
                    return None

                # pathlib.Path.with_suffix replaces, not appends
                suffix = '.dylib'
                if self.version:
                    suffix = '.{}{}'.format(self.version[0], suffix)
            else:
                # pathlib.Path.with_suffix replaces, not appends
                suffix = '.so'
                if self.version:
                    suffix = '{}.{}'.format(suffix, '.'.join(self.version))
            return p.with_suffix(suffix)
        elif self.typ == 'exe':
            if env.machines.host.is_windows() or env.machines.host.is_cygwin():
                return p.with_suffix('.exe')
        elif self.typ == 'pdb':
            if self.version:
                p = p.with_name('{}-{}'.format(p.name, self.version[0]))
            return p.with_suffix('.pdb') if has_pdb else None
        elif self.typ == 'implib' or self.typ == 'implibempty':
            if env.machines.host.is_windows() and canonical_compiler == 'msvc':
                # only MSVC doesn't generate empty implibs
                if self.typ == 'implibempty' and compiler == 'msvc':
                    return None
                return p.parent / (re.sub(r'^lib', '', p.name) + '.lib')
            elif env.machines.host.is_windows() or env.machines.host.is_cygwin():
                return p.with_suffix('.dll.a')
            else:
                return None
        elif self.typ == 'expr':
            return Path(platform_fix_name(p.as_posix(), canonical_compiler, env))
        else:
            raise RuntimeError(f'Invalid installed file type {self.typ}')

        return p

    def get_paths(self, compiler: str, env: environment.Environment, installdir: Path) -> T.List[Path]:
        p = self.get_path(compiler, env)
        if not p:
            return []
        if self.typ == 'dir':
            abs_p = installdir / p
            if not abs_p.exists():
                raise RuntimeError(f'{p} does not exist')
            if not abs_p.is_dir():
                raise RuntimeError(f'{p} is not a directory')
            return [x.relative_to(installdir) for x in abs_p.rglob('*') if x.is_file() or x.is_symlink()]
        else:
            return [p]

@functools.total_ordering
class TestDef:
    def __init__(self, path: Path, name: T.Optional[str], args: T.List[str], skip: bool = False):
        self.path = path
        self.name = name
        self.args = args
        self.skip = skip
        self.env = os.environ.copy()
        self.installed_files = []  # type: T.List[InstalledFile]
        self.do_not_set_opts = []  # type: T.List[str]
        self.stdout = [] # type: T.List[T.Dict[str, str]]

    def __repr__(self) -> str:
        return '<{}: {:<48} [{}: {}] -- {}>'.format(type(self).__name__, str(self.path), self.name, self.args, self.skip)

    def display_name(self) -> str:
        if self.name:
            return f'{self.path.as_posix()}   ({self.name})'
        return self.path.as_posix()

    def __lt__(self, other: object) -> bool:
        if isinstance(other, TestDef):
            # None is not sortable, so replace it with an empty string
            s_id = int(self.path.name.split(' ')[0])
            o_id = int(other.path.name.split(' ')[0])
            return (s_id, self.path, self.name or '') < (o_id, other.path, other.name or '')
        return NotImplemented

failing_logs = []
print_debug = 'MESON_PRINT_TEST_OUTPUT' in os.environ
under_ci = 'CI' in os.environ
skip_scientific = under_ci and ('SKIP_SCIENTIFIC' in os.environ)
do_debug = under_ci or print_debug
no_meson_log_msg = 'No meson-log.txt found.'

host_c_compiler = None
compiler_id_map = {}  # type: T.Dict[str, str]
tool_vers_map = {}    # type: T.Dict[str, str]

class StopException(Exception):
    def __init__(self):
        super().__init__('Stopped by user')

stop = False
def stop_handler(signal, frame):
    global stop
    stop = True
signal.signal(signal.SIGINT, stop_handler)
signal.signal(signal.SIGTERM, stop_handler)

def setup_commands(optbackend):
    global do_debug, backend, backend_flags
    global compile_commands, clean_commands, test_commands, install_commands, uninstall_commands
    backend, backend_flags = guess_backend(optbackend, shutil.which('msbuild'))
    compile_commands, clean_commands, test_commands, install_commands, \
        uninstall_commands = get_backend_commands(backend, do_debug)

# TODO try to eliminate or at least reduce this function
def platform_fix_name(fname: str, canonical_compiler: str, env: environment.Environment) -> str:
    if '?lib' in fname:
        if env.machines.host.is_windows() and canonical_compiler == 'msvc':
            fname = re.sub(r'lib/\?lib(.*)\.', r'bin/\1.', fname)
            fname = re.sub(r'/\?lib/', r'/bin/', fname)
        elif env.machines.host.is_windows():
            fname = re.sub(r'lib/\?lib(.*)\.', r'bin/lib\1.', fname)
            fname = re.sub(r'\?lib(.*)\.dll$', r'lib\1.dll', fname)
            fname = re.sub(r'/\?lib/', r'/bin/', fname)
        elif env.machines.host.is_cygwin():
            fname = re.sub(r'lib/\?lib(.*)\.so$', r'bin/cyg\1.dll', fname)
            fname = re.sub(r'lib/\?lib(.*)\.', r'bin/cyg\1.', fname)
            fname = re.sub(r'\?lib(.*)\.dll$', r'cyg\1.dll', fname)
            fname = re.sub(r'/\?lib/', r'/bin/', fname)
        else:
            fname = re.sub(r'\?lib', 'lib', fname)

    if fname.endswith('?so'):
        if env.machines.host.is_windows() and canonical_compiler == 'msvc':
            fname = re.sub(r'lib/([^/]*)\?so$', r'bin/\1.dll', fname)
            fname = re.sub(r'/(?:lib|)([^/]*?)\?so$', r'/\1.dll', fname)
            return fname
        elif env.machines.host.is_windows():
            fname = re.sub(r'lib/([^/]*)\?so$', r'bin/\1.dll', fname)
            fname = re.sub(r'/([^/]*?)\?so$', r'/\1.dll', fname)
            return fname
        elif env.machines.host.is_cygwin():
            fname = re.sub(r'lib/([^/]*)\?so$', r'bin/\1.dll', fname)
            fname = re.sub(r'/lib([^/]*?)\?so$', r'/cyg\1.dll', fname)
            fname = re.sub(r'/([^/]*?)\?so$', r'/\1.dll', fname)
            return fname
        elif env.machines.host.is_darwin():
            return fname[:-3] + '.dylib'
        else:
            return fname[:-3] + '.so'

    return fname

def validate_install(test: TestDef, installdir: Path, compiler: str, env: environment.Environment) -> str:
    ret_msg = ''
    expected_raw = []  # type: T.List[Path]
    for i in test.installed_files:
        try:
            expected_raw += i.get_paths(compiler, env, installdir)
        except RuntimeError as err:
            ret_msg += f'Expected path error: {err}\n'
    expected = {x: False for x in expected_raw}
    found = [x.relative_to(installdir) for x in installdir.rglob('*') if x.is_file() or x.is_symlink()]
    # Mark all found files as found and detect unexpected files
    for fname in found:
        if fname not in expected:
            ret_msg += f'Extra file {fname} found.\n'
            continue
        expected[fname] = True
    # Check if expected files were found
    for p, f in expected.items():
        if not f:
            ret_msg += f'Expected file {p} missing.\n'
    # List dir content on error
    if ret_msg != '':
        ret_msg += '\nInstall dir contents:\n'
        for i in found:
            ret_msg += f'  - {i}\n'
    return ret_msg

def log_text_file(logfile, testdir, stdo, stde):
    global stop, executor, futures
    logfile.write('%s\nstdout\n\n---\n' % testdir.as_posix())
    logfile.write(stdo)
    logfile.write('\n\n---\n\nstderr\n\n---\n')
    logfile.write(stde)
    logfile.write('\n\n---\n\n')
    if print_debug:
        try:
            print(stdo)
        except UnicodeError:
            sanitized_out = stdo.encode('ascii', errors='replace').decode()
            print(sanitized_out)
        try:
            print(stde, file=sys.stderr)
        except UnicodeError:
            sanitized_err = stde.encode('ascii', errors='replace').decode()
            print(sanitized_err, file=sys.stderr)
    if stop:
        print("Aborting..")
        for f in futures:
            f[2].cancel()
        executor.shutdown()
        raise StopException()


def _run_ci_include(args: T.List[str]) -> str:
    if not args:
        return 'At least one parameter required'
    try:
        data = Path(args[0]).read_text(errors='ignore', encoding='utf-8')
        return 'Included file {}:\n{}\n'.format(args[0], data)
    except Exception:
        return 'Failed to open {}'.format(args[0])

ci_commands = {
    'ci_include': _run_ci_include
}

def run_ci_commands(raw_log: str) -> T.List[str]:
    res = []
    for l in raw_log.splitlines():
        if not l.startswith('!meson_ci!/'):
            continue
        cmd = shlex.split(l[11:])
        if not cmd or cmd[0] not in ci_commands:
            continue
        res += ['CI COMMAND {}:\n{}\n'.format(cmd[0], ci_commands[cmd[0]](cmd[1:]))]
    return res

class OutputMatch:
    def __init__(self, how: str, expected: str, count: int) -> None:
        self.how = how
        self.expected = expected
        self.count = count

    def match(self, actual: str) -> bool:
        if self.how == "re":
            return bool(re.match(self.expected, actual))
        return self.expected == actual

def _compare_output(expected: T.List[T.Dict[str, str]], output: str, desc: str) -> str:
    if expected:
        matches = []
        nomatches = []
        for item in expected:
            how = item.get('match', 'literal')
            expected = item.get('line')
            count = int(item.get('count', -1))

            # Simple heuristic to automatically convert path separators for
            # Windows:
            #
            # Any '/' appearing before 'WARNING' or 'ERROR' (i.e. a path in a
            # filename part of a location) is replaced with '\' (in a re: '\\'
            # which matches a literal '\')
            #
            # (There should probably be a way to turn this off for more complex
            # cases which don't fit this)
            if mesonlib.is_windows():
                if how != "re":
                    sub = r'\\'
                else:
                    sub = r'\\\\'
                expected = re.sub(r'/(?=.*(WARNING|ERROR))', sub, expected)

            m = OutputMatch(how, expected, count)
            if count == 0:
                nomatches.append(m)
            else:
                matches.append(m)


        i = 0
        for actual in output.splitlines():
            # Verify this line does not match any unexpected lines (item.count == 0)
            for item in nomatches:
                if item.match(actual):
                    return f'unexpected "{item.expected}" found in {desc}'
            # If we matched all expected lines, continue to verify there are
            # no unexpected line. If nomatches is empty then we are done already.
            if i >= len(matches):
                if not nomatches:
                    break
                continue
            # Check if this line match current expected line
            item = matches[i]
            if item.match(actual):
                if item.count < 0:
                    # count was not specified, continue with next expected line,
                    # it does not matter if this line will be matched again or
                    # not.
                    i += 1
                else:
                    # count was specified (must be >0), continue expecting this
                    # same line. If count reached 0 we continue with next
                    # expected line but remember that this one must not match
                    # anymore.
                    item.count -= 1
                    if item.count == 0:
                        nomatches.append(item)
                        i += 1

        if i < len(matches):
            # reached the end of output without finding expected
            return f'expected "{matches[i].expected}" not found in {desc}'

    return ''

def validate_output(test: TestDef, stdo: str, stde: str) -> str:
    return _compare_output(test.stdout, stdo, 'stdout')

# There are some class variables and such that cahce
# information. Clear all of these. The better solution
# would be to change the code so that no state is persisted
# but that would be a lot of work given that Meson was originally
# coded to run as a batch process.
def clear_internal_caches():
    import mesonbuild.interpreterbase
    from mesonbuild.dependencies import CMakeDependency
    from mesonbuild.mesonlib import PerMachine
    mesonbuild.interpreterbase.FeatureNew.feature_registry = {}
    CMakeDependency.class_cmakeinfo = PerMachine(None, None)

def run_test_inprocess(testdir):
    old_stdout = sys.stdout
    sys.stdout = mystdout = StringIO()
    old_stderr = sys.stderr
    sys.stderr = mystderr = StringIO()
    old_cwd = os.getcwd()
    os.chdir(testdir)
    test_log_fname = Path('meson-logs', 'testlog.txt')
    try:
        returncode_test = mtest.run_with_args(['--no-rebuild'])
        if test_log_fname.exists():
            test_log = test_log_fname.open(errors='ignore').read()
        else:
            test_log = ''
        returncode_benchmark = mtest.run_with_args(['--no-rebuild', '--benchmark', '--logbase', 'benchmarklog'])
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        os.chdir(old_cwd)
    return max(returncode_test, returncode_benchmark), mystdout.getvalue(), mystderr.getvalue(), test_log

# Build directory name must be the same so Ccache works over
# consecutive invocations.
def create_deterministic_builddir(test: TestDef, use_tmpdir: bool) -> str:
    import hashlib
    src_dir = test.path.as_posix()
    if test.name:
        src_dir += test.name
    rel_dirname = 'b ' + hashlib.sha256(src_dir.encode(errors='ignore')).hexdigest()[0:10]
    abs_pathname = os.path.join(tempfile.gettempdir() if use_tmpdir else os.getcwd(), rel_dirname)
    if os.path.exists(abs_pathname):
        mesonlib.windows_proof_rmtree(abs_pathname)
    os.mkdir(abs_pathname)
    return abs_pathname

def format_parameter_file(file_basename: str, test: TestDef, test_build_dir: str) -> Path:
    confdata = ConfigurationData()
    confdata.values = {'MESON_TEST_ROOT': (str(test.path.absolute()), 'base directory of current test')}

    template = test.path / (file_basename + '.in')
    destination = Path(test_build_dir) / file_basename
    mesonlib.do_conf_file(str(template), str(destination), confdata, 'meson')

    return destination

def detect_parameter_files(test: TestDef, test_build_dir: str) -> T.Tuple[Path, Path]:
    nativefile = test.path / 'nativefile.ini'
    crossfile = test.path / 'crossfile.ini'

    if os.path.exists(str(test.path / 'nativefile.ini.in')):
        nativefile = format_parameter_file('nativefile.ini', test, test_build_dir)

    if os.path.exists(str(test.path / 'crossfile.ini.in')):
        crossfile = format_parameter_file('crossfile.ini', test, test_build_dir)

    return nativefile, crossfile

def run_test(test: TestDef, extra_args: T.List[str], compiler: str, backend: Backend,
            flags: T.List[str], commands: T.Tuple[T.List[str], T.List[str], T.List[str], T.List[str]],
            should_fail: bool, use_tmp: bool) -> T.Optional[TestResult]:
    if test.skip:
        return None
    build_dir = create_deterministic_builddir(test, use_tmp)
    try:
        with TemporaryDirectoryWinProof(prefix='i ', dir=None if use_tmp else os.getcwd()) as install_dir:
            try:
                return _run_test(test, build_dir, install_dir, extra_args, compiler, backend, flags, commands, should_fail)
            except TestResult as r:
                return r
            finally:
                mlog.shutdown() # Close the log file because otherwise Windows wets itself.
    finally:
        mesonlib.windows_proof_rmtree(build_dir)

def _run_test(test: TestDef, test_build_dir: str, install_dir: str,
              extra_args: T.List[str], compiler: str, backend: Backend,
              flags: T.List[str], commands: T.Tuple[T.List[str], T.List[str], T.List[str], T.List[str]],
              should_fail: bool) -> TestResult:
    compile_commands, clean_commands, install_commands, uninstall_commands = commands
    gen_start = time.time()
    # Configure in-process
    gen_args = []  # type: T.List[str]
    if 'prefix' not in test.do_not_set_opts:
        gen_args += ['--prefix', 'x:/usr'] if mesonlib.is_windows() else ['--prefix', '/usr']
    if 'libdir' not in test.do_not_set_opts:
        gen_args += ['--libdir', 'lib']
    gen_args += [test.path.as_posix(), test_build_dir] + flags + extra_args

    nativefile, crossfile = detect_parameter_files(test, test_build_dir)

    if nativefile.exists():
        gen_args.extend(['--native-file', nativefile.as_posix()])
    if crossfile.exists():
        gen_args.extend(['--cross-file', crossfile.as_posix()])
    (returncode, stdo, stde) = run_configure(gen_args, env=test.env)
    try:
        logfile = Path(test_build_dir, 'meson-logs', 'meson-log.txt')
        mesonlog = logfile.open(errors='ignore', encoding='utf-8').read()
    except Exception:
        mesonlog = no_meson_log_msg
    cicmds = run_ci_commands(mesonlog)
    testresult = TestResult(cicmds)
    testresult.add_step(BuildStep.configure, stdo, stde, mesonlog, time.time() - gen_start)
    output_msg = validate_output(test, stdo, stde)
    testresult.mlog += output_msg
    if output_msg:
        testresult.fail('Unexpected output while configuring.')
        return testresult
    if should_fail == 'meson':
        if returncode == 1:
            return testresult
        elif returncode != 0:
            testresult.fail(f'Test exited with unexpected status {returncode}.')
            return testresult
        else:
            testresult.fail('Test that should have failed succeeded.')
            return testresult
    if returncode != 0:
        testresult.fail('Generating the build system failed.')
        return testresult
    builddata = build.load(test_build_dir)
    dir_args = get_backend_args_for_dir(backend, test_build_dir)

    # Build with subprocess
    def build_step():
        build_start = time.time()
        pc, o, e = Popen_safe(compile_commands + dir_args, cwd=test_build_dir)
        testresult.add_step(BuildStep.build, o, e, '', time.time() - build_start)
        if should_fail == 'build':
            if pc.returncode != 0:
                raise testresult
            testresult.fail('Test that should have failed to build succeeded.')
            raise testresult
        if pc.returncode != 0:
            testresult.fail('Compiling source code failed.')
            raise testresult

    # Touch the meson.build file to force a regenerate
    def force_regenerate():
        ensure_backend_detects_changes(backend)
        os.utime(str(test.path / 'meson.build'))

    # just test building
    build_step()

    # test that regeneration works for build step
    force_regenerate()
    build_step()  # TBD: assert nothing gets built after the regenerate?

    # test that regeneration works for test step
    force_regenerate()

    # Test in-process
    clear_internal_caches()
    test_start = time.time()
    (returncode, tstdo, tstde, test_log) = run_test_inprocess(test_build_dir)
    testresult.add_step(BuildStep.test, tstdo, tstde, test_log, time.time() - test_start)
    if should_fail == 'test':
        if returncode != 0:
            return testresult
        testresult.fail('Test that should have failed to run unit tests succeeded.')
        return testresult
    if returncode != 0:
        testresult.fail('Running unit tests failed.')
        return testresult

    # Do installation, if the backend supports it
    if install_commands:
        env = test.env.copy()
        env['DESTDIR'] = install_dir
        # Install with subprocess
        pi, o, e = Popen_safe(install_commands, cwd=test_build_dir, env=env)
        testresult.add_step(BuildStep.install, o, e)
        if pi.returncode != 0:
            testresult.fail('Running install failed.')
            return testresult

    # Clean with subprocess
    env = test.env.copy()
    pi, o, e = Popen_safe(clean_commands + dir_args, cwd=test_build_dir, env=env)
    testresult.add_step(BuildStep.clean, o, e)
    if pi.returncode != 0:
        testresult.fail('Running clean failed.')
        return testresult

    # Validate installed files
    testresult.add_step(BuildStep.install, '', '')
    if not install_commands:
        return testresult
    install_msg = validate_install(test, Path(install_dir), compiler, builddata.environment)
    if install_msg:
        testresult.fail('\n' + install_msg)
        return testresult

    return testresult


def load_test_json(t: TestDef, stdout_mandatory: bool) -> T.List[TestDef]:
    all_tests: T.List[TestDef] = []
    test_def = {}
    test_def_file = t.path / 'test.json'
    if test_def_file.is_file():
        test_def = json.loads(test_def_file.read_text())

    # Handle additional environment variables
    env = {}  # type: T.Dict[str, str]
    if 'env' in test_def:
        assert isinstance(test_def['env'], dict)
        env = test_def['env']
        for key, val in env.items():
            val = val.replace('@ROOT@', t.path.resolve().as_posix())
            val = val.replace('@PATH@', t.env.get('PATH', ''))
            env[key] = val

    # Handle installed files
    installed = []  # type: T.List[InstalledFile]
    if 'installed' in test_def:
        installed = [InstalledFile(x) for x in test_def['installed']]

    # Handle expected output
    stdout = test_def.get('stdout', [])
    if stdout_mandatory and not stdout:
        raise RuntimeError(f"{test_def_file} must contain a non-empty stdout key")

    # Handle the do_not_set_opts list
    do_not_set_opts = test_def.get('do_not_set_opts', [])  # type: T.List[str]

    # Skip tests if the tool requirements are not met
    if 'tools' in test_def:
        assert isinstance(test_def['tools'], dict)
        for tool, vers_req in test_def['tools'].items():
            if tool not in tool_vers_map:
                t.skip = True
            elif not mesonlib.version_compare(tool_vers_map[tool], vers_req):
                t.skip = True

    # Skip the matrix code and just update the existing test
    if 'matrix' not in test_def:
        t.env.update(env)
        t.installed_files = installed
        t.do_not_set_opts = do_not_set_opts
        t.stdout = stdout
        return [t]

    new_opt_list: T.List[T.List[T.Tuple[str, bool]]]

    # 'matrix; entry is present, so build multiple tests from matrix definition
    opt_list = []  # type: T.List[T.List[T.Tuple[str, bool]]]
    matrix = test_def['matrix']
    assert "options" in matrix
    for key, val in matrix["options"].items():
        assert isinstance(val, list)
        tmp_opts = []  # type: T.List[T.Tuple[str, bool]]
        for i in val:
            assert isinstance(i, dict)
            assert "val" in i
            skip = False

            # Skip the matrix entry if environment variable is present
            if 'skip_on_env' in i:
                for skip_env_var in i['skip_on_env']:
                    if skip_env_var in os.environ:
                        skip = True

            # Only run the test if all compiler ID's match
            if 'compilers' in i:
                for lang, id_list in i['compilers'].items():
                    if lang not in compiler_id_map or compiler_id_map[lang] not in id_list:
                        skip = True
                        break

            # Add an empty matrix entry
            if i['val'] is None:
                tmp_opts += [(None, skip)]
                continue

            tmp_opts += [('{}={}'.format(key, i['val']), skip)]

        if opt_list:
            new_opt_list = []
            for i in opt_list:
                for j in tmp_opts:
                    new_opt_list += [[*i, j]]
            opt_list = new_opt_list
        else:
            opt_list = [[x] for x in tmp_opts]

    # Exclude specific configurations
    if 'exclude' in matrix:
        assert isinstance(matrix['exclude'], list)
        new_opt_list = []
        for i in opt_list:
            exclude = False
            opt_names = [x[0] for x in i]
            for j in matrix['exclude']:
                ex_list = [f'{k}={v}' for k, v in j.items()]
                if all([x in opt_names for x in ex_list]):
                    exclude = True
                    break

            if not exclude:
                new_opt_list += [i]

        opt_list = new_opt_list

    for i in opt_list:
        name = ' '.join([x[0] for x in i if x[0] is not None])
        opts = ['-D' + x[0] for x in i if x[0] is not None]
        skip = any([x[1] for x in i])
        test = TestDef(t.path, name, opts, skip or t.skip)
        test.env.update(env)
        test.installed_files = installed
        test.do_not_set_opts = do_not_set_opts
        test.stdout = stdout
        all_tests.append(test)

    return all_tests


def gather_tests(testdir: Path, stdout_mandatory: bool, only: T.List[str]) -> T.List[TestDef]:
    all_tests: T.List[TestDef] = []
    for t in testdir.iterdir():
        # Filter non-tests files (dot files, etc)
        if not t.is_dir() or t.name.startswith('.'):
            continue
        if only and not any(t.name.startswith(prefix) for prefix in only):
            continue
        test_def = TestDef(t, None, [])
        all_tests.extend(load_test_json(test_def, stdout_mandatory))
    return sorted(all_tests)


def have_d_compiler():
    if shutil.which("ldc2"):
        return True
    elif shutil.which("ldc"):
        return True
    elif shutil.which("gdc"):
        return True
    elif shutil.which("dmd"):
        # The Windows installer sometimes produces a DMD install
        # that exists but segfaults every time the compiler is run.
        # Don't know why. Don't know how to fix. Skip in this case.
        cp = subprocess.run(['dmd', '--version'],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
        if cp.stdout == b'':
            return False
        return True
    return False

def have_objc_compiler(use_tmp: bool) -> bool:
    with TemporaryDirectoryWinProof(prefix='b ', dir=None if use_tmp else '.') as build_dir:
        env = environment.Environment(None, build_dir, get_fake_options('/'))
        try:
            objc_comp = env.detect_objc_compiler(MachineChoice.HOST)
        except mesonlib.MesonException:
            return False
        if not objc_comp:
            return False
        env.coredata.process_new_compiler('objc', objc_comp, env)
        try:
            objc_comp.sanity_check(env.get_scratch_dir(), env)
        except mesonlib.MesonException:
            return False
    return True

def have_objcpp_compiler(use_tmp: bool) -> bool:
    with TemporaryDirectoryWinProof(prefix='b ', dir=None if use_tmp else '.') as build_dir:
        env = environment.Environment(None, build_dir, get_fake_options('/'))
        try:
            objcpp_comp = env.detect_objcpp_compiler(MachineChoice.HOST)
        except mesonlib.MesonException:
            return False
        if not objcpp_comp:
            return False
        env.coredata.process_new_compiler('objcpp', objcpp_comp, env)
        try:
            objcpp_comp.sanity_check(env.get_scratch_dir(), env)
        except mesonlib.MesonException:
            return False
    return True

def have_java():
    if shutil.which('javac') and shutil.which('java'):
        return True
    return False

def skippable(suite: str, test: str) -> bool:
    # Everything is optional when not running on CI
    if not under_ci:
        return True

    if not suite.endswith('frameworks'):
        return True

    # this test assumptions aren't valid for Windows paths
    if test.endswith('38 libdir must be inside prefix'):
        return True

    # gtk-doc test may be skipped, pending upstream fixes for spaces in
    # filenames landing in the distro used for CI
    if test.endswith('10 gtk-doc'):
        return True

    # NetCDF is not in the CI Docker image
    if test.endswith('netcdf'):
        return True

    # MSVC doesn't link with GFortran
    if test.endswith('14 fortran links c'):
        return True

    # Blocks are not supported on all compilers
    if test.endswith('29 blocks'):
        return True

    # Scientific libraries are skippable on certain systems
    # See the discussion here: https://github.com/mesonbuild/meson/pull/6562
    if any([x in test for x in ['17 mpi', '25 hdf5', '30 scalapack']]) and skip_scientific:
        return True

    # These create OS specific tests, and need to be skippable
    if any([x in test for x in ['16 sdl', '17 mpi']]):
        return True

    # We test cmake, and llvm-config. Some linux spins don't provide cmake or
    # don't provide either the static or shared llvm libraries (fedora and
    # opensuse only have the dynamic ones, for example).
    if test.endswith('15 llvm'):
        return True

    # This test breaks with gobject-introspection <= 1.58.1
    if test.endswith('34 gir static lib'):
        return True

    # Boost test should only be skipped for windows CI build matrix entries
    # which don't define BOOST_ROOT
    if test.endswith('1 boost'):
        if mesonlib.is_windows():
            return 'BOOST_ROOT' not in os.environ
        return False

    # Not all OSes have all of the methods for qt (qmake and pkg-config), don't
    # fail if that happens.
    #
    # On macOS we should have all of the requirements at all times.
    if test.endswith('4 qt'):
        return not mesonlib.is_osx()

    # Bindgen isn't available in all distros
    if test.endswith('12 bindgen'):
        return False

    # No frameworks test should be skipped on linux CI, as we expect all
    # prerequisites to be installed
    if mesonlib.is_linux():
        return False

    # Other framework tests are allowed to be skipped on other platforms
    return True

def skip_csharp(backend) -> bool:
    if backend is not Backend.ninja:
        return True
    if not shutil.which('resgen'):
        return True
    if shutil.which('mcs'):
        return False
    if shutil.which('csc'):
        # Only support VS2017 for now. Earlier versions fail
        # under CI in mysterious ways.
        try:
            stdo = subprocess.check_output(['csc', '/version'])
        except subprocess.CalledProcessError:
            return True
        # Having incrementing version numbers would be too easy.
        # Microsoft reset the versioning back to 1.0 (from 4.x)
        # when they got the Roslyn based compiler. Thus there
        # is NO WAY to reliably do version number comparisons.
        # Only support the version that ships with VS2017.
        return not stdo.startswith(b'2.')
    return True

# In Azure some setups have a broken rustc that will error out
# on all compilation attempts.

def has_broken_rustc() -> bool:
    dirname = 'brokenrusttest'
    if os.path.exists(dirname):
        mesonlib.windows_proof_rmtree(dirname)
    os.mkdir(dirname)
    open(dirname + '/sanity.rs', 'w').write('''fn main() {
}
''')
    pc = subprocess.run(['rustc', '-o', 'sanity.exe', 'sanity.rs'],
                        cwd=dirname,
                        stdout = subprocess.DEVNULL,
                        stderr = subprocess.DEVNULL)
    mesonlib.windows_proof_rmtree(dirname)
    return pc.returncode != 0

def should_skip_rust(backend: Backend) -> bool:
    if not shutil.which('rustc'):
        return True
    if backend is not Backend.ninja:
        return True
    if mesonlib.is_windows() and has_broken_rustc():
        return True
    return False

def detect_tests_to_run(only: T.Dict[str, T.List[str]], use_tmp: bool) -> T.List[T.Tuple[str, T.List[TestDef], bool]]:
    """
    Parameters
    ----------
    only: dict of categories and list of test cases, optional
        specify names of tests to run

    Returns
    -------
    gathered_tests: list of tuple of str, list of TestDef, bool
        tests to run
    """

    skip_fortran = not(shutil.which('gfortran') or
                       shutil.which('flang') or
                       shutil.which('pgfortran') or
                       shutil.which('ifort'))

    class TestCategory:
        def __init__(self, category: str, subdir: str, skip: bool = False, stdout_mandatory: bool = False):
            self.category = category                  # category name
            self.subdir = subdir                      # subdirectory
            self.skip = skip                          # skip condition
            self.stdout_mandatory = stdout_mandatory  # expected stdout is mandatory for tests in this categroy

    all_tests = [
        TestCategory('cmake', 'cmake', not shutil.which('cmake') or (os.environ.get('compiler') == 'msvc2015' and under_ci)),
        TestCategory('common', 'common'),
        TestCategory('native', 'native'),
        TestCategory('warning-meson', 'warning', stdout_mandatory=True),
        TestCategory('failing-meson', 'failing', stdout_mandatory=True),
        TestCategory('failing-build', 'failing build'),
        TestCategory('failing-test',  'failing test'),
        TestCategory('keyval', 'keyval'),
        TestCategory('platform-osx', 'osx', not mesonlib.is_osx()),
        TestCategory('platform-windows', 'windows', not mesonlib.is_windows() and not mesonlib.is_cygwin()),
        TestCategory('platform-linux', 'linuxlike', mesonlib.is_osx() or mesonlib.is_windows()),
        TestCategory('java', 'java', backend is not Backend.ninja or mesonlib.is_osx() or not have_java()),
        TestCategory('C#', 'csharp', skip_csharp(backend)),
        TestCategory('vala', 'vala', backend is not Backend.ninja or not shutil.which(os.environ.get('VALAC', 'valac'))),
        TestCategory('rust', 'rust', should_skip_rust(backend)),
        TestCategory('d', 'd', backend is not Backend.ninja or not have_d_compiler()),
        TestCategory('objective c', 'objc', backend not in (Backend.ninja, Backend.xcode) or not have_objc_compiler(options.use_tmpdir)),
        TestCategory('objective c++', 'objcpp', backend not in (Backend.ninja, Backend.xcode) or not have_objcpp_compiler(options.use_tmpdir)),
        TestCategory('fortran', 'fortran', skip_fortran or backend != Backend.ninja),
        TestCategory('swift', 'swift', backend not in (Backend.ninja, Backend.xcode) or not shutil.which('swiftc')),
        # CUDA tests on Windows: use Ninja backend:  python run_project_tests.py --only cuda --backend ninja
        TestCategory('cuda', 'cuda', backend not in (Backend.ninja, Backend.xcode) or not shutil.which('nvcc')),
        TestCategory('python3', 'python3', backend is not Backend.ninja),
        TestCategory('python', 'python'),
        TestCategory('fpga', 'fpga', shutil.which('yosys') is None),
        TestCategory('frameworks', 'frameworks'),
        TestCategory('nasm', 'nasm'),
        TestCategory('wasm', 'wasm', shutil.which('emcc') is None or backend is not Backend.ninja),
        TestCategory('zig', 'zig', shutil.which('zig') is None or backend is not Backend.ninja),
    ]

    categories = [t.category for t in all_tests]
    assert categories == ALL_TESTS, 'argparse("--only", choices=ALL_TESTS) need to be updated to match all_tests categories'

    if only:
        all_tests = [t for t in all_tests if t.category in only.keys()]

    gathered_tests = [(t.category, gather_tests(Path('test cases', t.subdir), t.stdout_mandatory, only[t.category]), t.skip) for t in all_tests]
    return gathered_tests

def run_tests(all_tests: T.List[T.Tuple[str, T.List[TestDef], bool]],
              log_name_base: str, failfast: bool,
              extra_args: T.List[str], use_tmp: bool) -> T.Tuple[int, int, int]:
    global logfile
    txtname = log_name_base + '.txt'
    with open(txtname, 'w', encoding='utf-8', errors='ignore') as lf:
        logfile = lf
        return _run_tests(all_tests, log_name_base, failfast, extra_args, use_tmp)

def _run_tests(all_tests: T.List[T.Tuple[str, T.List[TestDef], bool]],
               log_name_base: str, failfast: bool,
               extra_args: T.List[str], use_tmp: bool) -> T.Tuple[int, int, int]:
    global stop, executor, futures, host_c_compiler
    xmlname = log_name_base + '.xml'
    junit_root = ET.Element('testsuites')
    conf_time = 0
    build_time = 0
    test_time = 0
    passing_tests = 0
    failing_tests = 0
    skipped_tests = 0
    commands = (compile_commands, clean_commands, install_commands, uninstall_commands)

    try:
        # This fails in some CI environments for unknown reasons.
        num_workers = multiprocessing.cpu_count()
    except Exception as e:
        print('Could not determine number of CPUs due to the following reason:' + str(e))
        print('Defaulting to using only one process')
        num_workers = 1
    # Due to Ninja deficiency, almost 50% of build time
    # is spent waiting. Do something useful instead.
    #
    # Remove this once the following issue has been resolved:
    # https://github.com/mesonbuild/meson/pull/2082
    if not mesonlib.is_windows():  # twice as fast on Windows by *not* multiplying by 2.
        num_workers *= 2
    executor = ProcessPoolExecutor(max_workers=num_workers)

    for name, test_cases, skipped in all_tests:
        current_suite = ET.SubElement(junit_root, 'testsuite', {'name': name, 'tests': str(len(test_cases))})
        print()
        if skipped:
            print(bold('Not running %s tests.' % name))
        else:
            print(bold('Running %s tests.' % name))
        print()
        futures = []
        for t in test_cases:
            # Jenkins screws us over by automatically sorting test cases by name
            # and getting it wrong by not doing logical number sorting.
            (testnum, testbase) = t.path.name.split(' ', 1)
            testname = '%.3d %s' % (int(testnum), testbase)
            if t.name:
                testname += f' ({t.name})'
            should_fail = False
            suite_args = []
            if name.startswith('failing'):
                should_fail = name.split('failing-')[1]
            if name.startswith('warning'):
                suite_args = ['--fatal-meson-warnings']
                should_fail = name.split('warning-')[1]

            t.skip = skipped or t.skip
            result = executor.submit(run_test, t, extra_args + suite_args + t.args,
                                     host_c_compiler, backend, backend_flags, commands, should_fail, use_tmp)
            futures.append((testname, t, result))
        for (testname, t, result) in futures:
            sys.stdout.flush()
            try:
                result = result.result()
            except CancelledError:
                continue
            if (result is None) or (('MESON_SKIP_TEST' in result.stdo) and (skippable(name, t.path.as_posix()))):
                print(yellow('Skipping:'), t.display_name())
                current_test = ET.SubElement(current_suite, 'testcase', {'name': testname,
                                                                         'classname': name})
                ET.SubElement(current_test, 'skipped', {})
                skipped_tests += 1
            else:
                without_install = "" if len(install_commands) > 0 else " (without install)"
                if result.msg != '':
                    print(red(f'Failed test{without_install} during {result.step.name}: {t.display_name()!r}'))
                    print('Reason:', result.msg)
                    failing_tests += 1
                    if result.step == BuildStep.configure and result.mlog != no_meson_log_msg:
                        # For configure failures, instead of printing stdout,
                        # print the meson log if available since it's a superset
                        # of stdout and often has very useful information.
                        failing_logs.append(result.mlog)
                    elif under_ci:
                        # Always print the complete meson log when running in
                        # a CI. This helps debugging issues that only occur in
                        # a hard to reproduce environment
                        failing_logs.append(result.mlog)
                        failing_logs.append(result.stdo)
                    else:
                        failing_logs.append(result.stdo)
                    for cmd_res in result.cicmds:
                        failing_logs.append(cmd_res)
                    failing_logs.append(result.stde)
                    if failfast:
                        print("Cancelling the rest of the tests")
                        for (_, _, res) in futures:
                            res.cancel()
                else:
                    print(f'Succeeded test{without_install}: {t.display_name()}')
                    passing_tests += 1
                conf_time += result.conftime
                build_time += result.buildtime
                test_time += result.testtime
                total_time = conf_time + build_time + test_time
                log_text_file(logfile, t.path, result.stdo, result.stde)
                current_test = ET.SubElement(current_suite, 'testcase', {'name': testname,
                                                                         'classname': name,
                                                                         'time': '%.3f' % total_time})
                if result.msg != '':
                    ET.SubElement(current_test, 'failure', {'message': result.msg})
                stdoel = ET.SubElement(current_test, 'system-out')
                stdoel.text = result.stdo
                stdeel = ET.SubElement(current_test, 'system-err')
                stdeel.text = result.stde

            if failfast and failing_tests > 0:
                break

    print("\nTotal configuration time: %.2fs" % conf_time)
    print("Total build time: %.2fs" % build_time)
    print("Total test time: %.2fs" % test_time)
    ET.ElementTree(element=junit_root).write(xmlname, xml_declaration=True, encoding='UTF-8')
    return passing_tests, failing_tests, skipped_tests

def check_file(file: Path):
    lines = file.read_bytes().split(b'\n')
    tabdetector = re.compile(br' *\t')
    for i, line in enumerate(lines):
        if re.match(tabdetector, line):
            raise SystemExit("File {} contains a tab indent on line {:d}. Only spaces are permitted.".format(file, i + 1))
        if line.endswith(b'\r'):
            raise SystemExit("File {} contains DOS line ending on line {:d}. Only unix-style line endings are permitted.".format(file, i + 1))

def check_format():
    check_suffixes = {'.c',
                      '.cpp',
                      '.cxx',
                      '.cc',
                      '.rs',
                      '.f90',
                      '.vala',
                      '.d',
                      '.s',
                      '.m',
                      '.mm',
                      '.asm',
                      '.java',
                      '.txt',
                      '.py',
                      '.swift',
                      '.build',
                      '.md',
                      }
    skip_dirs = {
        '.dub',                         # external deps are here
        '.pytest_cache',
        'meson-logs', 'meson-private',
        'work area',
        '.eggs', '_cache',              # e.g. .mypy_cache
        'venv',                         # virtualenvs have DOS line endings
    }
    for (root, _, filenames) in os.walk('.'):
        if any([x in root for x in skip_dirs]):
            continue
        for fname in filenames:
            file = Path(fname)
            if file.suffix.lower() in check_suffixes:
                if file.name in ('sitemap.txt', 'meson-test-run.txt'):
                    continue
                check_file(root / file)

def check_meson_commands_work(options):
    global backend, compile_commands, test_commands, install_commands
    testdir = PurePath('test cases', 'common', '1 trivial').as_posix()
    meson_commands = mesonlib.python_command + [get_meson_script()]
    with TemporaryDirectoryWinProof(prefix='b ', dir=None if options.use_tmpdir else '.') as build_dir:
        print('Checking that configuring works...')
        gen_cmd = meson_commands + [testdir, build_dir] + backend_flags + options.extra_args
        pc, o, e = Popen_safe(gen_cmd)
        if pc.returncode != 0:
            raise RuntimeError(f'Failed to configure {testdir!r}:\n{e}\n{o}')
        print('Checking that introspect works...')
        pc, o, e = Popen_safe(meson_commands + ['introspect', '--targets'], cwd=build_dir)
        json.loads(o)
        if pc.returncode != 0:
            raise RuntimeError(f'Failed to introspect --targets {testdir!r}:\n{e}\n{o}')
        print('Checking that building works...')
        dir_args = get_backend_args_for_dir(backend, build_dir)
        pc, o, e = Popen_safe(compile_commands + dir_args, cwd=build_dir)
        if pc.returncode != 0:
            raise RuntimeError(f'Failed to build {testdir!r}:\n{e}\n{o}')
        print('Checking that testing works...')
        pc, o, e = Popen_safe(test_commands, cwd=build_dir)
        if pc.returncode != 0:
            raise RuntimeError(f'Failed to test {testdir!r}:\n{e}\n{o}')
        if install_commands:
            print('Checking that installing works...')
            pc, o, e = Popen_safe(install_commands, cwd=build_dir)
            if pc.returncode != 0:
                raise RuntimeError(f'Failed to install {testdir!r}:\n{e}\n{o}')


def detect_system_compiler(options):
    global host_c_compiler, compiler_id_map

    with TemporaryDirectoryWinProof(prefix='b ', dir=None if options.use_tmpdir else '.') as build_dir:
        fake_opts = get_fake_options('/')
        if options.cross_file:
            fake_opts.cross_file = [options.cross_file]
        if options.native_file:
            fake_opts.native_file = [options.native_file]

        env = environment.Environment(None, build_dir, fake_opts)

        print_compilers(env, MachineChoice.HOST)
        if options.cross_file:
            print_compilers(env, MachineChoice.BUILD)

        for lang in sorted(compilers.all_languages):
            try:
                comp = env.compiler_from_language(lang, MachineChoice.HOST)
                # note compiler id for later use with test.json matrix
                compiler_id_map[lang] = comp.get_id()
            except mesonlib.MesonException:
                comp = None

            # note C compiler for later use by platform_fix_name()
            if lang == 'c':
                if comp:
                    host_c_compiler = comp.get_id()
                else:
                    raise RuntimeError("Could not find C compiler.")


def print_compilers(env, machine):
    print()
    print(f'{machine.get_lower_case_name()} machine compilers')
    print()
    for lang in sorted(compilers.all_languages):
        try:
            comp = env.compiler_from_language(lang, machine)
            details = '{:<10} {} {}'.format('[' + comp.get_id() + ']', ' '.join(comp.get_exelist()), comp.get_version_string())
        except mesonlib.MesonException:
            details = '[not found]'
        print(f'{lang:<7}: {details}')


def print_tool_versions():
    tools = [
        {
            'tool': 'ninja',
            'args': ['--version'],
            'regex': re.compile(r'^([0-9]+(\.[0-9]+)*(-[a-z0-9]+)?)$'),
            'match_group': 1,
        },
        {
            'tool': 'cmake',
            'args': ['--version'],
            'regex': re.compile(r'^cmake version ([0-9]+(\.[0-9]+)*(-[a-z0-9]+)?)$'),
            'match_group': 1,
        },
        {
            'tool': 'hotdoc',
            'args': ['--version'],
            'regex': re.compile(r'^([0-9]+(\.[0-9]+)*(-[a-z0-9]+)?)$'),
            'match_group': 1,
        },
    ]

    def get_version(t: dict) -> str:
        exe = shutil.which(t['tool'])
        if not exe:
            return 'not found'

        args = [t['tool']] + t['args']
        pc, o, e = Popen_safe(args)
        if pc.returncode != 0:
            return '{} (invalid {} executable)'.format(exe, t['tool'])
        for i in o.split('\n'):
            i = i.strip('\n\r\t ')
            m = t['regex'].match(i)
            if m is not None:
                tool_vers_map[t['tool']] = m.group(t['match_group'])
                return '{} ({})'.format(exe, m.group(t['match_group']))

        return f'{exe} (unknown)'

    print()
    print('tools')
    print()

    max_width = max([len(x['tool']) for x in tools] + [7])
    for tool in tools:
        print('{0:<{2}}: {1}'.format(tool['tool'], get_version(tool), max_width))
    print()

def clear_transitive_files():
    a = Path('test cases/common')
    for d in a.glob('*subproject subdir/subprojects/subsubsub*'):
        if d.is_dir():
            mesonlib.windows_proof_rmtree(d)
        else:
            mesonlib.windows_proof_rm(str(d))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run the test suite of Meson.")
    parser.add_argument('extra_args', nargs='*',
                        help='arguments that are passed directly to Meson (remember to have -- before these).')
    parser.add_argument('--backend', dest='backend', choices=backendlist)
    parser.add_argument('--failfast', action='store_true',
                        help='Stop running if test case fails')
    parser.add_argument('--no-unittests', action='store_true',
                        help='Not used, only here to simplify run_tests.py')
    parser.add_argument('--only', default=[],
                        help='name of test(s) to run, in format "category[/name]" where category is one of: ' + ', '.join(ALL_TESTS), nargs='+')
    parser.add_argument('--cross-file', action='store', help='File describing cross compilation environment.')
    parser.add_argument('--native-file', action='store', help='File describing native compilation environment.')
    parser.add_argument('--use-tmpdir', action='store_true', help='Use tmp directory for temporary files.')
    options = parser.parse_args()

    if options.cross_file:
        options.extra_args += ['--cross-file', options.cross_file]
    if options.native_file:
        options.extra_args += ['--native-file', options.native_file]

    clear_transitive_files()

    print('Meson build system', meson_version, 'Project Tests')
    print('Using python', sys.version.split('\n')[0])
    if 'VSCMD_VER' in os.environ:
        print('VSCMD version', os.environ['VSCMD_VER'])
    setup_commands(options.backend)
    detect_system_compiler(options)
    print_tool_versions()
    script_dir = os.path.split(__file__)[0]
    if script_dir != '':
        os.chdir(script_dir)
    check_format()
    check_meson_commands_work(options)
    only = collections.defaultdict(list)
    for i in options.only:
        try:
            cat, case = i.split('/')
            only[cat].append(case)
        except ValueError:
            only[i].append('')
    try:
        all_tests = detect_tests_to_run(only, options.use_tmpdir)
        (passing_tests, failing_tests, skipped_tests) = run_tests(all_tests, 'meson-test-run', options.failfast, options.extra_args, options.use_tmpdir)
    except StopException:
        pass
    print('\nTotal passed tests:', green(str(passing_tests)))
    print('Total failed tests:', red(str(failing_tests)))
    print('Total skipped tests:', yellow(str(skipped_tests)))
    if failing_tests > 0:
        print('\nMesonlogs of failing tests\n')
        for l in failing_logs:
            try:
                print(l, '\n')
            except UnicodeError:
                print(l.encode('ascii', errors='replace').decode(), '\n')
    for name, dirs, _ in all_tests:
        dir_names = list({x.path.name for x in dirs})
        for k, g in itertools.groupby(dir_names, key=lambda x: x.split()[0]):
            tests = list(g)
            if len(tests) != 1:
                print('WARNING: The {} suite contains duplicate "{}" tests: "{}"'.format(name, k, '", "'.join(tests)))
    clear_transitive_files()
    raise SystemExit(failing_tests)
