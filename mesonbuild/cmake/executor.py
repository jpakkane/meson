# Copyright 2019 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This class contains the basic functionality needed to run any interpreter
# or an interpreter-based tool.

import subprocess as S
from pathlib import Path
from threading import Thread
import typing as T
import re
import os

from .. import mlog
from ..mesonlib import PerMachine, Popen_safe, version_compare, MachineChoice, is_windows, OptionKey
from ..envconfig import get_env_var

if T.TYPE_CHECKING:
    from ..environment import Environment
    from ..dependencies.base import ExternalProgram
    from ..compilers import Compiler

TYPE_result    = T.Tuple[int, T.Optional[str], T.Optional[str]]
TYPE_cache_key = T.Tuple[str, T.Tuple[str, ...], str, T.FrozenSet[T.Tuple[str, str]]]

class CMakeExecutor:
    # The class's copy of the CMake path. Avoids having to search for it
    # multiple times in the same Meson invocation.
    class_cmakebin = PerMachine(None, None)   # type: PerMachine[T.Optional[ExternalProgram]]
    class_cmakevers = PerMachine(None, None)  # type: PerMachine[T.Optional[str]]
    class_cmake_cache = {}  # type: T.Dict[T.Any, TYPE_result]

    def __init__(self, environment: 'Environment', version: str, for_machine: MachineChoice, silent: bool = False):
        self.min_version = version
        self.environment = environment
        self.for_machine = for_machine
        self.cmakebin, self.cmakevers = self.find_cmake_binary(self.environment, silent=silent)
        self.always_capture_stderr = True
        self.print_cmout = False
        self.prefix_paths = []      # type: T.List[str]
        self.extra_cmake_args = []  # type: T.List[str]

        if self.cmakebin is None:
            return

        if not version_compare(self.cmakevers, self.min_version):
            mlog.warning(
                'The version of CMake', mlog.bold(self.cmakebin.get_path()),
                'is', mlog.bold(self.cmakevers), 'but version', mlog.bold(self.min_version),
                'is required')
            self.cmakebin = None
            return

        self.prefix_paths = self.environment.coredata.options[OptionKey('cmake_prefix_path', machine=self.for_machine)].value
        env_pref_path_raw = get_env_var(
            self.for_machine,
            self.environment.is_cross_build(),
            'CMAKE_PREFIX_PATH')
        if env_pref_path_raw is not None:
            env_pref_path = []  # type: T.List[str]
            if is_windows():
                # Cannot split on ':' on Windows because its in the drive letter
                env_pref_path = env_pref_path_raw.split(os.pathsep)
            else:
                # https://github.com/mesonbuild/meson/issues/7294
                env_pref_path = re.split(r':|;', env_pref_path_raw)
            env_pref_path = [x for x in env_pref_path if x]  # Filter out empty strings
            if not self.prefix_paths:
                self.prefix_paths = []
            self.prefix_paths += env_pref_path

        if self.prefix_paths:
            self.extra_cmake_args += ['-DCMAKE_PREFIX_PATH={}'.format(';'.join(self.prefix_paths))]

    def find_cmake_binary(self, environment: 'Environment', silent: bool = False) -> T.Tuple[T.Optional['ExternalProgram'], T.Optional[str]]:
        from ..dependencies.base import find_external_program, NonExistingExternalProgram

        # Only search for CMake the first time and store the result in the class
        # definition
        if isinstance(CMakeExecutor.class_cmakebin[self.for_machine], NonExistingExternalProgram):
            mlog.debug('CMake binary for %s is cached as not found' % self.for_machine)
            return None, None
        elif CMakeExecutor.class_cmakebin[self.for_machine] is not None:
            mlog.debug('CMake binary for %s is cached.' % self.for_machine)
        else:
            assert CMakeExecutor.class_cmakebin[self.for_machine] is None

            mlog.debug('CMake binary for %s is not cached' % self.for_machine)
            for potential_cmakebin in find_external_program(
                    environment, self.for_machine, 'cmake', 'CMake',
                    environment.default_cmake, allow_default_for_cross=False):
                version_if_ok = self.check_cmake(potential_cmakebin)
                if not version_if_ok:
                    continue
                if not silent:
                    mlog.log('Found CMake:', mlog.bold(potential_cmakebin.get_path()),
                             '({})'.format(version_if_ok))
                CMakeExecutor.class_cmakebin[self.for_machine] = potential_cmakebin
                CMakeExecutor.class_cmakevers[self.for_machine] = version_if_ok
                break
            else:
                if not silent:
                    mlog.log('Found CMake:', mlog.red('NO'))
                # Set to False instead of None to signify that we've already
                # searched for it and not found it
                CMakeExecutor.class_cmakebin[self.for_machine] = NonExistingExternalProgram()
                CMakeExecutor.class_cmakevers[self.for_machine] = None
                return None, None

        return CMakeExecutor.class_cmakebin[self.for_machine], CMakeExecutor.class_cmakevers[self.for_machine]

    def check_cmake(self, cmakebin: 'ExternalProgram') -> T.Optional[str]:
        if not cmakebin.found():
            mlog.log('Did not find CMake {!r}'.format(cmakebin.name))
            return None
        try:
            p, out = Popen_safe(cmakebin.get_command() + ['--version'])[0:2]
            if p.returncode != 0:
                mlog.warning('Found CMake {!r} but couldn\'t run it'
                             ''.format(' '.join(cmakebin.get_command())))
                return None
        except FileNotFoundError:
            mlog.warning('We thought we found CMake {!r} but now it\'s not there. How odd!'
                         ''.format(' '.join(cmakebin.get_command())))
            return None
        except PermissionError:
            msg = 'Found CMake {!r} but didn\'t have permissions to run it.'.format(' '.join(cmakebin.get_command()))
            if not is_windows():
                msg += '\n\nOn Unix-like systems this is often caused by scripts that are not executable.'
            mlog.warning(msg)
            return None
        cmvers = re.search(r'(cmake|cmake3)\s*version\s*([\d.]+)', out).group(2)
        return cmvers

    def set_exec_mode(self, print_cmout: T.Optional[bool] = None, always_capture_stderr: T.Optional[bool] = None) -> None:
        if print_cmout is not None:
            self.print_cmout = print_cmout
        if always_capture_stderr is not None:
            self.always_capture_stderr = always_capture_stderr

    def _cache_key(self, args: T.List[str], build_dir: Path, env: T.Optional[T.Dict[str, str]]) -> TYPE_cache_key:
        fenv = frozenset(env.items()) if env is not None else frozenset()
        targs = tuple(args)
        return (self.cmakebin.get_path(), targs, build_dir.as_posix(), fenv)

    def _call_cmout_stderr(self, args: T.List[str], build_dir: Path, env: T.Optional[T.Dict[str, str]]) -> TYPE_result:
        cmd = self.cmakebin.get_command() + args
        proc = S.Popen(cmd, stdout=S.PIPE, stderr=S.PIPE, cwd=str(build_dir), env=env)  # TODO [PYTHON_37]: drop Path conversion

        # stdout and stderr MUST be read at the same time to avoid pipe
        # blocking issues. The easiest way to do this is with a separate
        # thread for one of the pipes.
        def print_stdout() -> None:
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                mlog.log(line.decode(errors='ignore').strip('\n'))
            proc.stdout.close()

        t = Thread(target=print_stdout)
        t.start()

        try:
            # Read stderr line by line and log non trace lines
            raw_trace = ''
            tline_start_reg = re.compile(r'^\s*(.*\.(cmake|txt))\(([0-9]+)\):\s*(\w+)\(.*$')
            inside_multiline_trace = False
            while True:
                line_raw = proc.stderr.readline()
                if not line_raw:
                    break
                line = line_raw.decode(errors='ignore')
                if tline_start_reg.match(line):
                    raw_trace += line
                    inside_multiline_trace = not line.endswith(' )\n')
                elif inside_multiline_trace:
                    raw_trace += line
                else:
                    mlog.warning(line.strip('\n'))

        finally:
            proc.stderr.close()
            t.join()
            proc.wait()

        return proc.returncode, None, raw_trace

    def _call_cmout(self, args: T.List[str], build_dir: Path, env: T.Optional[T.Dict[str, str]]) -> TYPE_result:
        cmd = self.cmakebin.get_command() + args
        proc = S.Popen(cmd, stdout=S.PIPE, stderr=S.STDOUT, cwd=str(build_dir), env=env)  # TODO [PYTHON_37]: drop Path conversion
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            mlog.log(line.decode(errors='ignore').strip('\n'))
        proc.stdout.close()
        proc.wait()
        return proc.returncode, None, None

    def _call_quiet(self, args: T.List[str], build_dir: Path, env: T.Optional[T.Dict[str, str]]) -> TYPE_result:
        build_dir.mkdir(parents=True, exist_ok=True)
        cmd = self.cmakebin.get_command() + args
        ret = S.run(cmd, env=env, cwd=str(build_dir), close_fds=False,
                    stdout=S.PIPE, stderr=S.PIPE, universal_newlines=False)   # TODO [PYTHON_37]: drop Path conversion
        rc = ret.returncode
        out = ret.stdout.decode(errors='ignore')
        err = ret.stderr.decode(errors='ignore')
        return rc, out, err

    def _call_impl(self, args: T.List[str], build_dir: Path, env: T.Optional[T.Dict[str, str]]) -> TYPE_result:
        mlog.debug('Calling CMake ({}) in {} with:'.format(self.cmakebin.get_command(), build_dir))
        for i in args:
            mlog.debug('  - "{}"'.format(i))
        if not self.print_cmout:
            return self._call_quiet(args, build_dir, env)
        else:
            if self.always_capture_stderr:
                return self._call_cmout_stderr(args, build_dir, env)
            else:
                return self._call_cmout(args, build_dir, env)

    def call(self, args: T.List[str], build_dir: Path, env: T.Optional[T.Dict[str, str]] = None, disable_cache: bool = False) -> TYPE_result:
        if env is None:
            env = os.environ.copy()

        args = args + self.extra_cmake_args
        if disable_cache:
            return self._call_impl(args, build_dir, env)

        # First check if cached, if not call the real cmake function
        cache = CMakeExecutor.class_cmake_cache
        key = self._cache_key(args, build_dir, env)
        if key not in cache:
            cache[key] = self._call_impl(args, build_dir, env)
        return cache[key]

    def found(self) -> bool:
        return self.cmakebin is not None

    def version(self) -> str:
        return self.cmakevers

    def executable_path(self) -> str:
        return self.cmakebin.get_path()

    def get_command(self) -> T.List[str]:
        return self.cmakebin.get_command()

    def get_cmake_prefix_paths(self) -> T.List[str]:
        return self.prefix_paths

    def machine_choice(self) -> MachineChoice:
        return self.for_machine
