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

# Work around some pathlib bugs...

from . import _pathlib
import sys
sys.modules['pathlib'] = _pathlib

# This file is an entry point for all commands, including scripts. Include the
# strict minimum python modules for performance reasons.
import os.path
import platform
import importlib
import argparse

from .utils.core import MesonException, MesonBugException
from . import mlog

def errorhandler(e, command):
    import traceback
    if isinstance(e, MesonException):
        mlog.exception(e)
        logfile = mlog.shutdown()
        if logfile is not None:
            mlog.log("\nA full log can be found at", mlog.bold(logfile))
        if os.environ.get('MESON_FORCE_BACKTRACE'):
            raise e
        return 1
    else:
        # We assume many types of traceback are Meson logic bugs, but most
        # particularly anything coming from the interpreter during `setup`.
        # Some things definitely aren't:
        # - PermissionError is always a problem in the user environment
        # - runpython doesn't run Meson's own code, even though it is
        #   dispatched by our run()
        if os.environ.get('MESON_FORCE_BACKTRACE'):
            raise e
        traceback.print_exc()

        if command == 'runpython':
            return 2
        elif isinstance(e, OSError):
            mlog.exception("Unhandled python OSError. This is probably not a Meson bug, "
                           "but an issue with your build environment.")
            return e.errno
        else: # Exception
            msg = 'Unhandled python exception'
            if all(getattr(e, a, None) is not None for a in ['file', 'lineno', 'colno']):
                e = MesonBugException(msg, e.file, e.lineno, e.colno) # type: ignore
            else:
                e = MesonBugException(msg)
            mlog.exception(e)
        return 2

# Note: when adding arguments, please also add them to the completion
# scripts in $MESONSRC/data/shell-completions/
class CommandLineParser:
    def __init__(self):
        # only import these once we do full argparse processing
        from . import mconf, mdist, minit, minstall, mintro, msetup, mtest, rewriter, msubprojects, munstable_coredata, mcompile, mdevenv
        from .scripts import env2mfile
        from .wrap import wraptool
        import shutil

        self.term_width = shutil.get_terminal_size().columns
        self.formatter = lambda prog: argparse.HelpFormatter(prog, max_help_position=int(self.term_width / 2), width=self.term_width)

        self.commands = {}
        self.hidden_commands = []
        self.parser = argparse.ArgumentParser(prog='meson', formatter_class=self.formatter)
        self.subparsers = self.parser.add_subparsers(title='Commands', dest='command',
                                                     description='If no command is specified it defaults to setup command.')
        self.add_command('setup', msetup.add_arguments, msetup.run,
                         help_msg='Configure the project')
        self.add_command('configure', mconf.add_arguments, mconf.run,
                         help_msg='Change project options',)
        self.add_command('dist', mdist.add_arguments, mdist.run,
                         help_msg='Generate release archive',)
        self.add_command('install', minstall.add_arguments, minstall.run,
                         help_msg='Install the project')
        self.add_command('introspect', mintro.add_arguments, mintro.run,
                         help_msg='Introspect project')
        self.add_command('init', minit.add_arguments, minit.run,
                         help_msg='Create a new project')
        self.add_command('test', mtest.add_arguments, mtest.run,
                         help_msg='Run tests')
        self.add_command('wrap', wraptool.add_arguments, wraptool.run,
                         help_msg='Wrap tools')
        self.add_command('subprojects', msubprojects.add_arguments, msubprojects.run,
                         help_msg='Manage subprojects')
        self.add_command('rewrite', lambda parser: rewriter.add_arguments(parser, self.formatter), rewriter.run,
                         help_msg='Modify the project definition')
        self.add_command('compile', mcompile.add_arguments, mcompile.run,
                         help_msg='Build the project')
        self.add_command('devenv', mdevenv.add_arguments, mdevenv.run,
                         help_msg='Run commands in developer environment')
        self.add_command('env2mfile', env2mfile.add_arguments, env2mfile.run,
                         help_msg='Convert current environment to a cross or native file')
        # Add new commands above this line to list them in help command
        self.add_command('help', self.add_help_arguments, self.run_help_command,
                         help_msg='Print help of a subcommand')

        # Hidden commands
        self.add_command('runpython', self.add_runpython_arguments, self.run_runpython_command,
                         help_msg=argparse.SUPPRESS)
        self.add_command('unstable-coredata', munstable_coredata.add_arguments, munstable_coredata.run,
                         help_msg=argparse.SUPPRESS)

    def add_command(self, name, add_arguments_func, run_func, help_msg, aliases=None):
        aliases = aliases or []
        # FIXME: Cannot have hidden subparser:
        # https://bugs.python.org/issue22848
        if help_msg == argparse.SUPPRESS:
            p = argparse.ArgumentParser(prog='meson ' + name, formatter_class=self.formatter)
            self.hidden_commands.append(name)
        else:
            p = self.subparsers.add_parser(name, help=help_msg, aliases=aliases, formatter_class=self.formatter)
        add_arguments_func(p)
        p.set_defaults(run_func=run_func)
        for i in [name] + aliases:
            self.commands[i] = p

    def add_runpython_arguments(self, parser: argparse.ArgumentParser):
        parser.add_argument('-c', action='store_true', dest='eval_arg', default=False)
        parser.add_argument('--version', action='version', version=platform.python_version())
        parser.add_argument('script_file')
        parser.add_argument('script_args', nargs=argparse.REMAINDER)

    def run_runpython_command(self, options):
        import runpy
        if options.eval_arg:
            exec(options.script_file)
        else:
            sys.argv[1:] = options.script_args
            sys.path.insert(0, os.path.dirname(options.script_file))
            runpy.run_path(options.script_file, run_name='__main__')
        return 0

    def add_help_arguments(self, parser):
        parser.add_argument('command', nargs='?', choices=list(self.commands.keys()))

    def run_help_command(self, options):
        if options.command:
            self.commands[options.command].print_help()
        else:
            self.parser.print_help()
        return 0

    def run(self, args):
        implicit_setup_command_notice = False
        pending_python_deprecation_notice = False
        # If first arg is not a known command, assume user wants to run the setup
        # command.
        known_commands = list(self.commands.keys()) + ['-h', '--help']
        if not args or args[0] not in known_commands:
            implicit_setup_command_notice = True
            args = ['setup'] + args

        # Hidden commands have their own parser instead of using the global one
        if args[0] in self.hidden_commands:
            command = args[0]
            parser = self.commands[command]
            args = args[1:]
        else:
            parser = self.parser
            command = None

        from . import mesonlib
        args = mesonlib.expand_arguments(args)
        options = parser.parse_args(args)

        if command is None:
            command = options.command

        # Bump the version here in order to add a pre-exit warning that we are phasing out
        # support for old python. If this is already the oldest supported version, then
        # this can never be true and does nothing.
        if command in ('setup', 'compile', 'test', 'install') and sys.version_info < (3, 7):
            pending_python_deprecation_notice = True

        try:
            return options.run_func(options)
        except Exception as e:
            return errorhandler(e, command)
        finally:
            if implicit_setup_command_notice:
                mlog.warning('Running the setup command as `meson [options]` instead of '
                             '`meson setup [options]` is ambiguous and deprecated.', fatal=False)
            if pending_python_deprecation_notice:
                mlog.notice('You are using Python 3.6 which is EOL. Starting with v0.62.0, '
                            'Meson will require Python 3.7 or newer', fatal=False)
            mlog.shutdown()

def run_script_command(script_name, script_args):
    # Map script name to module name for those that doesn't match
    script_map = {'exe': 'meson_exe',
                  'install': 'meson_install',
                  'delsuffix': 'delwithsuffix',
                  'gtkdoc': 'gtkdochelper',
                  'hotdoc': 'hotdochelper',
                  'regencheck': 'regen_checker'}
    module_name = script_map.get(script_name, script_name)

    try:
        module = importlib.import_module('mesonbuild.scripts.' + module_name)
    except ModuleNotFoundError as e:
        mlog.exception(e)
        return 1

    try:
        return module.run(script_args)
    except MesonException as e:
        mlog.error(f'Error in {script_name} helper script:')
        mlog.exception(e)
        return 1

def ensure_stdout_accepts_unicode():
    if sys.stdout.encoding and not sys.stdout.encoding.upper().startswith('UTF-'):
        sys.stdout.reconfigure(errors='surrogateescape')

def set_meson_command(mainfile):
    # Set the meson command that will be used to run scripts and so on
    from . import mesonlib
    mesonlib.set_meson_command(mainfile)

def run(original_args, mainfile):
    if sys.version_info >= (3, 10) and os.environ.get('MESON_RUNNING_IN_PROJECT_TESTS'):
        # workaround for https://bugs.python.org/issue34624
        import warnings
        warnings.filterwarnings('error', category=EncodingWarning, module='mesonbuild')

    # Meson gets confused if stdout can't output Unicode, if the
    # locale isn't Unicode, just force stdout to accept it. This tries
    # to emulate enough of PEP 540 to work elsewhere.
    ensure_stdout_accepts_unicode()

    # https://github.com/mesonbuild/meson/issues/3653
    if sys.platform == 'cygwin' and os.environ.get('MSYSTEM', '') not in ['MSYS', '']:
        mlog.error('This python3 seems to be msys/python on MSYS2 Windows, but you are in a MinGW environment')
        mlog.error('Please install and use mingw-w64-x86_64-python3 and/or mingw-w64-x86_64-meson with Pacman')
        return 2

    args = original_args[:]

    # Special handling of internal commands called from backends, they don't
    # need to go through argparse.
    if len(args) >= 2 and args[0] == '--internal':
        if args[1] == 'regenerate':
            set_meson_command(mainfile)
            from . import msetup
            try:
                return msetup.run(['--reconfigure'] + args[2:])
            except Exception as e:
                return errorhandler(e, 'setup')
        else:
            return run_script_command(args[1], args[2:])

    set_meson_command(mainfile)
    return CommandLineParser().run(args)

def main():
    # Always resolve the command path so Ninja can find it for regen, tests, etc.
    if 'meson.exe' in sys.executable:
        assert os.path.isabs(sys.executable)
        launcher = sys.executable
    else:
        launcher = os.path.realpath(sys.argv[0])
    return run(sys.argv[1:], launcher)

if __name__ == '__main__':
    sys.exit(main())
