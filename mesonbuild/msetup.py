# Copyright 2016-2018 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import typing as T
import time
import sys, stat
import datetime
import os.path
import platform
import cProfile as profile
import argparse
import tempfile
import shutil
import glob

from . import environment, interpreter, mesonlib
from . import build
from . import mlog, coredata
from . import mintro
from .mesonlib import MesonException, universal

git_ignore_file = '''# This file is autogenerated by Meson. If you change or delete it, it won't be recreated.
*
'''

hg_ignore_file = '''# This file is autogenerated by Meson. If you change or delete it, it won't be recreated.
syntax: glob
**/*
'''


def add_arguments(parser: argparse.ArgumentParser) -> None:
    coredata.register_builtin_arguments(parser)
    parser.add_argument('--native-file',
                        default=[],
                        action='append',
                        help='File containing overrides for native compilation environment.')
    parser.add_argument('--cross-file',
                        default=[],
                        action='append',
                        help='File describing cross compilation environment.')
    parser.add_argument('--vsenv', action='store_true',
                        help='Setup Visual Studio environment even when other compilers are found, ' +
                             'abort if Visual Studio is not found. This option has no effect on other ' +
                             'platforms than Windows. Defaults to True when using "vs" backend.')
    parser.add_argument('-v', '--version', action='version',
                        version=coredata.version)
    parser.add_argument('--profile-self', action='store_true', dest='profile',
                        help=argparse.SUPPRESS)
    parser.add_argument('--fatal-meson-warnings', action='store_true', dest='fatal_warnings',
                        help='Make all Meson warnings fatal')
    parser.add_argument('--reconfigure', action='store_true',
                        help='Set options and reconfigure the project. Useful when new ' +
                             'options have been added to the project and the default value ' +
                             'is not working.')
    parser.add_argument('--wipe', action='store_true',
                        help='Wipe build directory and reconfigure using previous command line options. ' +
                             'Useful when build directory got corrupted, or when rebuilding with a ' +
                             'newer version of meson.')
    parser.add_argument('builddir', nargs='?', default=None)
    parser.add_argument('sourcedir', nargs='?', default=None)

class MesonApp:
    def __init__(self, options: argparse.Namespace) -> None:
        (self.source_dir, self.build_dir) = self.validate_dirs(options.builddir,
                                                               options.sourcedir,
                                                               options.reconfigure,
                                                               options.wipe)
        if options.wipe:
            # Make a copy of the cmd line file to make sure we can always
            # restore that file if anything bad happens. For example if
            # configuration fails we need to be able to wipe again.
            restore = []
            with tempfile.TemporaryDirectory() as d:
                for filename in [coredata.get_cmd_line_file(self.build_dir)] + glob.glob(os.path.join(self.build_dir, environment.Environment.private_dir, '*.ini')):
                    try:
                        restore.append((shutil.copy(filename, d), filename))
                    except FileNotFoundError:
                        raise MesonException(
                            'Cannot find cmd_line.txt. This is probably because this '
                            'build directory was configured with a meson version < 0.49.0.')

                coredata.read_cmd_line_file(self.build_dir, options)

                try:
                    # Don't delete the whole tree, just all of the files and
                    # folders in the tree. Otherwise calling wipe form the builddir
                    # will cause a crash
                    for l in os.listdir(self.build_dir):
                        l = os.path.join(self.build_dir, l)
                        if os.path.isdir(l) and not os.path.islink(l):
                            mesonlib.windows_proof_rmtree(l)
                        else:
                            mesonlib.windows_proof_rm(l)
                finally:
                    self.add_vcs_ignore_files(self.build_dir)
                    for b, f in restore:
                        os.makedirs(os.path.dirname(f), exist_ok=True)
                        shutil.move(b, f)

        self.options = options

    def has_build_file(self, dirname: str) -> bool:
        fname = os.path.join(dirname, environment.build_filename)
        return os.path.exists(fname)

    def validate_core_dirs(self, dir1: str, dir2: str) -> T.Tuple[str, str]:
        if dir1 is None:
            if dir2 is None:
                if not os.path.exists('meson.build') and os.path.exists('../meson.build'):
                    dir2 = '..'
                else:
                    raise MesonException('Must specify at least one directory name.')
            dir1 = os.getcwd()
        if dir2 is None:
            dir2 = os.getcwd()
        ndir1 = os.path.abspath(os.path.realpath(dir1))
        ndir2 = os.path.abspath(os.path.realpath(dir2))
        if not os.path.exists(ndir1):
            os.makedirs(ndir1)
        if not os.path.exists(ndir2):
            os.makedirs(ndir2)
        if not stat.S_ISDIR(os.stat(ndir1).st_mode):
            raise MesonException(f'{dir1} is not a directory')
        if not stat.S_ISDIR(os.stat(ndir2).st_mode):
            raise MesonException(f'{dir2} is not a directory')
        if os.path.samefile(ndir1, ndir2):
            # Fallback to textual compare if undefined entries found
            has_undefined = any((s.st_ino == 0 and s.st_dev == 0) for s in (os.stat(ndir1), os.stat(ndir2)))
            if not has_undefined or ndir1 == ndir2:
                raise MesonException('Source and build directories must not be the same. Create a pristine build directory.')
        if self.has_build_file(ndir1):
            if self.has_build_file(ndir2):
                raise MesonException(f'Both directories contain a build file {environment.build_filename}.')
            return ndir1, ndir2
        if self.has_build_file(ndir2):
            return ndir2, ndir1
        raise MesonException(f'Neither directory contains a build file {environment.build_filename}.')

    def add_vcs_ignore_files(self, build_dir: str) -> None:
        if os.listdir(build_dir):
            return
        with open(os.path.join(build_dir, '.gitignore'), 'w', encoding='utf-8') as ofile:
            ofile.write(git_ignore_file)
        with open(os.path.join(build_dir, '.hgignore'), 'w', encoding='utf-8') as ofile:
            ofile.write(hg_ignore_file)

    def validate_dirs(self, dir1: str, dir2: str, reconfigure: bool, wipe: bool) -> T.Tuple[str, str]:
        (src_dir, build_dir) = self.validate_core_dirs(dir1, dir2)
        self.add_vcs_ignore_files(build_dir)
        priv_dir = os.path.join(build_dir, 'meson-private/coredata.dat')
        if os.path.exists(priv_dir):
            if not reconfigure and not wipe:
                print('Directory already configured.\n'
                      '\nJust run your build command (e.g. ninja) and Meson will regenerate as necessary.\n'
                      'If ninja fails, run "ninja reconfigure" or "meson --reconfigure"\n'
                      'to force Meson to regenerate.\n'
                      '\nIf build failures persist, run "meson setup --wipe" to rebuild from scratch\n'
                      'using the same options as passed when configuring the build.'
                      '\nTo change option values, run "meson configure" instead.')
                raise SystemExit
        else:
            has_cmd_line_file = os.path.exists(coredata.get_cmd_line_file(build_dir))
            if (wipe and not has_cmd_line_file) or (not wipe and reconfigure):
                raise SystemExit(f'Directory does not contain a valid build tree:\n{build_dir}')
        return src_dir, build_dir

    def generate(self) -> None:
        env = environment.Environment(self.source_dir, self.build_dir, self.options)
        mlog.initialize(env.get_log_dir(), self.options.fatal_warnings)
        if self.options.profile:
            mlog.set_timestamp_start(time.monotonic())
        with mesonlib.BuildDirLock(self.build_dir):
            self._generate(env)

    def _generate(self, env: environment.Environment) -> None:
        # Get all user defined options, including options that have been defined
        # during a previous invocation or using meson configure.
        user_defined_options = argparse.Namespace(**vars(self.options))
        coredata.read_cmd_line_file(self.build_dir, user_defined_options)

        mlog.debug('Build started at', datetime.datetime.now().isoformat())
        mlog.debug('Main binary:', sys.executable)
        mlog.debug('Build Options:', coredata.format_cmd_line_options(user_defined_options))
        mlog.debug('Python system:', platform.system())
        mlog.log(mlog.bold('The Meson build system'))
        mlog.log('Version:', coredata.version)
        mlog.log('Source dir:', mlog.bold(self.source_dir))
        mlog.log('Build dir:', mlog.bold(self.build_dir))
        if env.is_cross_build():
            mlog.log('Build type:', mlog.bold('cross build'))
        else:
            mlog.log('Build type:', mlog.bold('native build'))
        b = build.Build(env)

        intr = interpreter.Interpreter(b, user_defined_options=user_defined_options)
        if env.is_cross_build():
            logger_fun = mlog.log
        else:
            logger_fun = mlog.debug
        build_machine = intr.builtin['build_machine']
        host_machine = intr.builtin['host_machine']
        target_machine = intr.builtin['target_machine']
        assert isinstance(build_machine, interpreter.MachineHolder)
        assert isinstance(host_machine, interpreter.MachineHolder)
        assert isinstance(target_machine, interpreter.MachineHolder)
        logger_fun('Build machine cpu family:', mlog.bold(build_machine.cpu_family_method([], {})))
        logger_fun('Build machine cpu:', mlog.bold(build_machine.cpu_method([], {})))
        mlog.log('Host machine cpu family:', mlog.bold(host_machine.cpu_family_method([], {})))
        mlog.log('Host machine cpu:', mlog.bold(host_machine.cpu_method([], {})))
        logger_fun('Target machine cpu family:', mlog.bold(target_machine.cpu_family_method([], {})))
        logger_fun('Target machine cpu:', mlog.bold(target_machine.cpu_method([], {})))
        try:
            if self.options.profile:
                fname = os.path.join(self.build_dir, 'meson-private', 'profile-interpreter.log')
                profile.runctx('intr.run()', globals(), locals(), filename=fname)
            else:
                intr.run()
        except Exception as e:
            mintro.write_meson_info_file(b, [e])
            raise
        try:
            dumpfile = os.path.join(env.get_scratch_dir(), 'build.dat')
            # We would like to write coredata as late as possible since we use the existence of
            # this file to check if we generated the build file successfully. Since coredata
            # includes settings, the build files must depend on it and appear newer. However, due
            # to various kernel caches, we cannot guarantee that any time in Python is exactly in
            # sync with the time that gets applied to any files. Thus, we dump this file as late as
            # possible, but before build files, and if any error occurs, delete it.
            cdf = env.dump_coredata()
            if self.options.profile:
                fname = f'profile-{intr.backend.name}-backend.log'
                fname = os.path.join(self.build_dir, 'meson-private', fname)
                profile.runctx('intr.backend.generate()', globals(), locals(), filename=fname)
            else:
                intr.backend.generate()
            b.devenv.append(intr.backend.get_devenv())
            build.save(b, dumpfile)
            universal.pickle_save(
                b.environment.binaries.as_plain_dict(), os.path.join(env.get_scratch_dir(), 'binaries.dat')
            )
            if env.first_invocation:
                # Use path resolved by coredata because they could have been
                # read from a pipe and wrote into a private file.
                self.options.cross_file = env.coredata.cross_files
                self.options.native_file = env.coredata.config_files
                coredata.write_cmd_line_file(self.build_dir, self.options)
            else:
                coredata.update_cmd_line_file(self.build_dir, self.options)

            # Generate an IDE introspection file with the same syntax as the already existing API
            if self.options.profile:
                fname = os.path.join(self.build_dir, 'meson-private', 'profile-introspector.log')
                profile.runctx('mintro.generate_introspection_file(b, intr.backend)', globals(), locals(), filename=fname)
            else:
                mintro.generate_introspection_file(b, intr.backend)
            mintro.write_meson_info_file(b, [], True)

            # Post-conf scripts must be run after writing coredata or else introspection fails.
            intr.backend.run_postconf_scripts()

            # collect warnings about unsupported build configurations; must be done after full arg processing
            # by Interpreter() init, but this is most visible at the end
            if env.coredata.options[mesonlib.OptionKey('backend')].value == 'xcode':
                mlog.warning('xcode backend is currently unmaintained, patches welcome')
            if env.coredata.options[mesonlib.OptionKey('layout')].value == 'flat':
                mlog.warning('-Dlayout=flat is unsupported and probably broken. It was a failed experiment at '
                             'making Windows build artifacts runnable while uninstalled, due to PATH considerations, '
                             'but was untested by CI and anyways breaks reasonable use of conflicting targets in different subdirs. '
                             'Please consider using `meson devenv` instead. See https://github.com/mesonbuild/meson/pull/9243 '
                             'for details.')

        except Exception as e:
            mintro.write_meson_info_file(b, [e])
            if 'cdf' in locals():
                old_cdf = cdf + '.prev'
                if os.path.exists(old_cdf):
                    os.replace(old_cdf, cdf)
                else:
                    os.unlink(cdf)
            raise

def run(options: argparse.Namespace) -> int:
    coredata.parse_cmd_line_options(options)
    app = MesonApp(options)
    app.generate()
    return 0
