# Copyright 2021 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import tempfile
import subprocess
from unittest import skipIf

from .baseplatformtests import BasePlatformTests
from .helpers import is_ci
from mesonbuild.mesonlib import is_linux
from mesonbuild.optinterpreter import OptionInterpreter, OptionException

@skipIf(is_ci() and not is_linux(), "Run only on fast platforms")
class PlatformAgnosticTests(BasePlatformTests):
    '''
    Tests that does not need to run on all platforms during CI
    '''

    def test_relative_find_program(self):
        '''
        Tests that find_program() with a relative path does not find the program
        in current workdir.
        '''
        testdir = os.path.join(self.unit_test_dir, '100 relative find program')
        self.init(testdir, workdir=testdir)

    def test_invalid_option_names(self):
        interp = OptionInterpreter('')

        def write_file(code: str):
            with tempfile.NamedTemporaryFile('w', dir=self.builddir, encoding='utf-8', delete=False) as f:
                f.write(code)
                return f.name

        fname = write_file("option('default_library', type: 'string')")
        self.assertRaisesRegex(OptionException, 'Option name default_library is reserved.',
                               interp.process, fname)

        fname = write_file("option('c_anything', type: 'string')")
        self.assertRaisesRegex(OptionException, 'Option name c_anything is reserved.',
                               interp.process, fname)

        fname = write_file("option('b_anything', type: 'string')")
        self.assertRaisesRegex(OptionException, 'Option name b_anything is reserved.',
                               interp.process, fname)

        fname = write_file("option('backend_anything', type: 'string')")
        self.assertRaisesRegex(OptionException, 'Option name backend_anything is reserved.',
                               interp.process, fname)

        fname = write_file("option('foo.bar', type: 'string')")
        self.assertRaisesRegex(OptionException, 'Option names can only contain letters, numbers or dashes.',
                               interp.process, fname)

        # platlib is allowed, only python.platlib is reserved.
        fname = write_file("option('platlib', type: 'string')")
        interp.process(fname)

    def test_python_dependency_without_pkgconfig(self):
        testdir = os.path.join(self.unit_test_dir, '102 python without pkgconfig')
        self.init(testdir, override_envvars={'PKG_CONFIG': 'notfound'})

    def test_debug_function_outputs_to_meson_log(self):
        testdir = os.path.join(self.unit_test_dir, '104 debug function')
        log_msg = 'This is an example debug output, should only end up in debug log'
        output = self.init(testdir)

        # Check if message is not printed to stdout while configuring
        self.assertNotIn(log_msg, output)

        # Check if message is written to the meson log
        mesonlog = os.path.join(self.builddir, 'meson-logs/meson-log.txt')
        with open(mesonlog, mode='r', encoding='utf-8') as file:
            self.assertIn(log_msg, file.read())

    def test_yielding_project_option(self):
        testdir = os.path.join(self.unit_test_dir, '105 set yielding option')

        # Should pass with default values
        self.init(testdir)

        # Changing value on main project is allowed
        self.setconf('-Dopt=uservalue')

        # Changing value on subproject is not allowed
        with self.assertRaises(subprocess.CalledProcessError) as cm:
            self.setconf('-Dsub:opt=uservalue')
        error_msg = 'ERROR: Option sub:opt is yielding, please set value on parent project instead'
        self.assertIn(error_msg, cm.exception.stdout)

        # Should fail when setting option on main project because subproject
        # asserts a different value.
        self.new_builddir()
        out = self.init(testdir, extra_args=['-Dopt=uservalue'], allow_fail=True)
        self.assertIn('ERROR: Assert failed: value is uservalue', out)

        self.new_builddir()
        out = self.init(testdir, extra_args=['-Dsub:opt=uservalue'], allow_fail=True)
        self.assertIn(error_msg, out)
