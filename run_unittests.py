#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2016-2021 The Meson development team

# Work around some pathlib bugs...
from mesonbuild import _pathlib
import sys
sys.modules['pathlib'] = _pathlib

import time
import subprocess
import os
import unittest

import mesonbuild.coredata
from mesonbuild.mesonlib import python_command, setup_vsenv


def convert_args(argv):
    # If we got passed a list of tests, pass it on
    pytest_args = ['-v'] if '-v' in argv else []
    test_list = []
    for arg in argv:
        if arg.startswith('-'):
            if arg in ('-f', '--failfast'):
                arg = '--exitfirst'
            pytest_args.append(arg)
            continue
        # ClassName.test_name => 'ClassName and test_name'
        if '.' in arg:
            arg = ' and '.join(arg.split('.'))
        test_list.append(arg)
    if test_list:
        pytest_args += ['-k', ' or '.join(test_list)]
    return pytest_args

def running_single_tests(argv, cases):
    '''
    Check whether we only got arguments for running individual tests, not
    entire testcases, and not all testcases (no test args).
    '''
    got_test_arg = False
    for arg in argv:
        if arg.startswith('-'):
            continue
        for case in cases:
            if not arg.startswith(case):
                continue
            if '.' not in arg:
                # Got a testcase, done
                return False
            got_test_arg = True
    return got_test_arg

def setup_backend():
    filtered = []
    be = 'ninja'
    for a in sys.argv:
        if a.startswith('--backend'):
            be = a.split('=')[1]
        else:
            filtered.append(a)
    # Since we invoke the tests via unittest or xtest test runner
    # we need to pass the backend to use to the spawned process via
    # this side channel. Yes it sucks, but at least is is fully
    # internal to this file.
    os.environ['MESON_UNIT_TEST_BACKEND'] = be
    sys.argv = filtered

def import_test_cases(suite: unittest.TestSuite) -> list:
    '''
    Imports all test classes into the current module and returns their names
    '''
    classes = set()
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            classes.update(import_test_cases(test))
        elif isinstance(test, unittest.TestCase):
            import importlib
            mod = importlib.import_module(test.__module__)
            class_name = test.__class__.__name__
            test_class = getattr(mod, class_name)
            classes.add(class_name)
            setattr(sys.modules[__name__], class_name, test_class)
    return sorted(classes)

def discover_test_cases() -> list:
    current_dir = os.path.dirname(os.path.realpath(__file__))
    loader = unittest.TestLoader()
    suite = loader.discover(os.path.join(current_dir, 'unittests'), '*tests.py', current_dir)
    if loader.errors:
        raise SystemExit(loader.errors)
    return import_test_cases(suite)

def main():
    cases = discover_test_cases()
    setup_backend()

    try:
        import pytest # noqa: F401
        pytest_args = []
        try:
            # Need pytest-xdist for `-n` arg
            import xdist # noqa: F401
            # Don't use pytest-xdist when running single unit tests since it wastes
            # time spawning a lot of processes to distribute tests to in that case.
            if not running_single_tests(sys.argv, cases):
                pytest_args += ['-n', 'auto']
        except ImportError:
            print('pytest-xdist not found, tests will not be distributed across CPU cores')
        # Let there be colors!
        if 'CI' in os.environ:
            pytest_args += ['--color=yes']
        pytest_args += ['unittests']
        pytest_args += convert_args(sys.argv[1:])
        # Always disable pytest-cov because we use a custom setup
        try:
            import pytest_cov # noqa: F401
            print('Disabling pytest-cov')
            pytest_args += ['-p' 'no:cov']
        except ImportError:
            pass
        return subprocess.run(python_command + ['-m', 'pytest'] + pytest_args).returncode
    except ImportError:
        print('pytest not found, using unittest instead')
    # Fallback to plain unittest.
    return unittest.main(defaultTest=cases, buffer=True)

if __name__ == '__main__':
    setup_vsenv()
    print('Meson build system', mesonbuild.coredata.version, 'Unit Tests')
    start = time.monotonic()
    try:
        raise SystemExit(main())
    finally:
        print('Total time: {:.3f} seconds'.format(time.monotonic() - start))
