from __future__ import annotations

import os
import subprocess
import json
import pathlib
import shutil

from .. import mlog
from .core import MesonException
from .universal import is_windows, windows_detect_native_arch


__all__ = [
    'setup_vsenv',
]


# If on Windows and VS is installed but not set up in the environment,
# set it to be runnable. In this way Meson can be directly invoked
# from any shell, VS Code etc.
def _setup_vsenv(force: bool) -> bool:
    if not is_windows():
        return False
    if os.environ.get('OSTYPE') == 'cygwin':
        return False
    if 'MESON_FORCE_VSENV_FOR_UNITTEST' not in os.environ:
        # VSINSTALL is set when running setvars from a Visual Studio installation
        # Tested with Visual Studio 2012 and 2017
        if 'VSINSTALLDIR' in os.environ:
            return False
        # Check explicitly for cl when on Windows
        if shutil.which('cl.exe'):
            return False
    if not force:
        if shutil.which('cc'):
            return False
        if shutil.which('gcc'):
            return False
        if shutil.which('clang'):
            return False
        if shutil.which('clang-cl'):
            return False

    root = os.environ.get("ProgramFiles(x86)") or os.environ.get("ProgramFiles")
    bat_locator_bin = pathlib.Path(root, 'Microsoft Visual Studio/Installer/vswhere.exe')
    if not bat_locator_bin.exists():
        raise MesonException(f'Could not find {bat_locator_bin}')
    bat_json = subprocess.check_output(
        [
            str(bat_locator_bin),
            '-latest',
            '-prerelease',
            '-requiresAny',
            '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
            '-requires', 'Microsoft.VisualStudio.Workload.WDExpress',
            '-products', '*',
            '-utf8',
            '-format',
            'json'
        ]
    )
    bat_info = json.loads(bat_json)
    if not bat_info:
        # VS installer installed but not VS itself maybe?
        raise MesonException('Could not parse vswhere.exe output')
    bat_root = pathlib.Path(bat_info[0]['installationPath'])
    if windows_detect_native_arch() == 'arm64':
        bat_path = bat_root / 'VC/Auxiliary/Build/vcvarsarm64.bat'
        if not bat_path.exists():
            bat_path = bat_root / 'VC/Auxiliary/Build/vcvarsx86_arm64.bat'
    else:
        bat_path = bat_root / 'VC/Auxiliary/Build/vcvars64.bat'
        # if VS is not found try VS Express
        if not bat_path.exists():
            bat_path = bat_root / 'VC/Auxiliary/Build/vcvarsx86_amd64.bat'
    if not bat_path.exists():
        raise MesonException(f'Could not find {bat_path}')

    mlog.log('Activating VS', bat_info[0]['catalog']['productDisplayVersion'])

    before_separator = '---BEFORE---'
    after_separator = '---AFTER---'
    # This will print to stdout the env variables set before the VS
    # activation and after VS activation so that we can process only
    # newly created environment variables. This is required to correctly parse
    # environment variables taking into account that some variables
    # can have multiple lines. (https://github.com/mesonbuild/meson/pull/13682)
    cmd = f'set&& echo {before_separator}&&"{bat_path.absolute()}" && echo {after_separator}&& set'
    process = subprocess.Popen(
        f'cmd.exe /c "{cmd}"',
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True,
    )
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"Script failed with error: {stderr.decode()}")
    lines = stdout.decode().splitlines()

    # Remove the output from the vcvars script
    try:
        lines_before = lines[:lines.index(before_separator)]
        lines_after = lines[lines.index(after_separator) + 1:]
    except ValueError:
        raise MesonException('Could not find separators in environment variables output')

    # Filter out duplicated lines to remove env variables that haven't changed
    new_lines = set(lines_before) - set(lines_after)
    for line in new_lines:
        k, v = line.split('=', 1)
        os.environ[k] = v
    return True


def setup_vsenv(force: bool = False) -> bool:
    try:
        return _setup_vsenv(force)
    except MesonException as e:
        if force:
            raise
        mlog.warning('Failed to activate VS environment:', str(e))
        return False
