# SPDX-License-Identifier: Apache-2.0
# Copyright 2016 The Meson development team

from __future__ import annotations

import os
import typing as T
import shutil
import sys
try:
    from __main__ import __file__ as main_file
except ImportError:
    # Happens when running as meson.exe which is native Windows.
    # This is only used for pkexec which is not, so this is fine.
    main_file = None

INSTALL_LOGFILE = 'meson-logs/install-log.txt'

def do_uninstall(log: str) -> None:
    failures = 0
    successes = 0
    for line in open(log, encoding='utf-8'):
        if line.startswith('#'):
            continue
        fname = line.strip()
        try:
            if os.path.isdir(fname) and not os.path.islink(fname):
                os.rmdir(fname)
            else:
                os.unlink(fname)
            print('Deleted:', fname)
            successes += 1
        except Exception as e:
            if e.__class__ == PermissionError  and shutil.which('pkexec') is not None and 'PKEXEC_UID' not in os.environ:
                print('Installation failed due to insufficient permissions.')
                print('Attempting to use polkit to gain elevated privileges...')
                os.execlp('pkexec', 'pkexec', sys.executable, main_file, *sys.argv[1:], os.getcwd())
            else:
                print(f'Could not delete {fname}: {e}.')
                failures += 1
    print('\nUninstall finished.\n')
    print('Deleted:', successes)
    print('Failed:', failures)
    print('\nRemember that files created by custom scripts have not been removed.')

def run(args: T.List[str]) -> int:
    logfile = INSTALL_LOGFILE
    if args:
        if os.path.isdir(args[0]):
            logfile = os.path.join(args[0],logfile)
        else:
            print(f'{args[0]} should be a path')
            return 1
    if not os.path.exists(logfile):
        print('Log file does not exist, no installation has been done.')
        return 0
    do_uninstall(logfile)
    return 0
