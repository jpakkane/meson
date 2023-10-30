# Copyright 2016-2021 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import subprocess
from itertools import zip_longest
import json
import os
from pathlib import Path
import shutil
import unittest

from mesonbuild.ast import IntrospectionInterpreter, AstIDGenerator
from mesonbuild.ast.printer import RawPrinter
from mesonbuild.mesonlib import windows_proof_rmtree
from .baseplatformtests import BasePlatformTests

class RewriterTests(BasePlatformTests):
    def setUp(self):
        super().setUp()
        self.maxDiff = None

    def prime(self, dirname):
        if os.path.exists(self.builddir):
            windows_proof_rmtree(self.builddir)
        shutil.copytree(os.path.join(self.rewrite_test_dir, dirname), self.builddir)

    def rewrite_raw(self, directory, args):
        if isinstance(args, str):
            args = [args]
        command = self.rewrite_command + ['--verbose', '--skip', '--sourcedir', directory] + args
        p = subprocess.run(command, capture_output=True, text=True, timeout=60)
        print('STDOUT:')
        print(p.stdout)
        print('STDERR:')
        print(p.stderr)
        if p.returncode != 0:
            if 'MESON_SKIP_TEST' in p.stdout:
                raise unittest.SkipTest('Project requested skipping.')
            raise subprocess.CalledProcessError(p.returncode, command, output=p.stdout)
        if not p.stderr:
            return {}
        return json.loads(p.stderr)

    def rewrite(self, directory, args):
        if isinstance(args, str):
            args = [args]
        return self.rewrite_raw(directory, ['command'] + args)

    # The rewriter sorts the sources alphabetically, but this is very unstable
    # and buggy, so we do not test it.
    def assertEqualIgnoreOrder(self, a, b):
        def deepsort(x):
            if isinstance(x, list):
                return sorted([deepsort(el) for el in x])
            elif isinstance(x, dict):
                return {k: deepsort(v) for k,v in x.items()}
            else:
                return x
        self.assertDictEqual(deepsort(a), deepsort(b))

    def test_target_source_list(self):
        self.prime('1 basic')
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'info.json'))
        expected = {
            'target': {
                'trivialprog0@exe': {'name': 'trivialprog0', 'sources': ['main.cpp', 'fileA.cpp', 'fileB.cpp', 'fileC.cpp'], 'extra_files': []},
                'trivialprog1@exe': {'name': 'trivialprog1', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog2@exe': {'name': 'trivialprog2', 'sources': ['fileB.cpp', 'fileC.cpp'], 'extra_files': []},
                'trivialprog3@exe': {'name': 'trivialprog3', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog4@exe': {'name': 'trivialprog4', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog5@exe': {'name': 'trivialprog5', 'sources': ['main.cpp', 'fileB.cpp', 'fileC.cpp'], 'extra_files': []},
                'trivialprog6@exe': {'name': 'trivialprog6', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog7@exe': {'name': 'trivialprog7', 'sources': ['fileB.cpp', 'fileC.cpp', 'main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog8@exe': {'name': 'trivialprog8', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog9@exe': {'name': 'trivialprog9', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog10@exe': {'name': 'trivialprog10', 'sources': ['main.cpp', 'fileA.cpp', 'fileB.cpp'], 'extra_files': []},
                'trivialprog11@exe': {'name': 'trivialprog11', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog12@exe': {'name': 'trivialprog12', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'rightName@exe': {'name': 'rightName', 'sources': ['main.cpp'], 'extra_files': []},
            }
        }
        self.assertEqualIgnoreOrder(out, expected)

    def test_target_add_sources(self):
        self.prime('1 basic')
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'addSrc.json'))
        expected = {
            'target': {
                'trivialprog0@exe': {'name': 'trivialprog0', 'sources': ['main.cpp', 'fileA.cpp', 'fileB.cpp', 'fileC.cpp'], 'extra_files': []},
                'trivialprog1@exe': {'name': 'trivialprog1', 'sources': ['main.cpp', 'fileA.cpp', 'a1.cpp', 'a2.cpp'], 'extra_files': []},
                'trivialprog2@exe': {'name': 'trivialprog2', 'sources': ['fileB.cpp', 'fileC.cpp', 'a7.cpp'], 'extra_files': []},
                'trivialprog3@exe': {'name': 'trivialprog3', 'sources': ['a5.cpp', 'fileA.cpp', 'main.cpp'], 'extra_files': []},
                'trivialprog4@exe': {'name': 'trivialprog4', 'sources': ['main.cpp', 'a5.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog5@exe': {'name': 'trivialprog5', 'sources': ['fileB.cpp', 'fileC.cpp', 'a3.cpp', 'main.cpp'], 'extra_files': []},
                'trivialprog6@exe': {'name': 'trivialprog6', 'sources': ['main.cpp', 'fileA.cpp', 'a4.cpp'], 'extra_files': []},
                'trivialprog7@exe': {'name': 'trivialprog7', 'sources': ['fileB.cpp', 'fileC.cpp', 'fileA.cpp', 'main.cpp'], 'extra_files': []},
                'trivialprog8@exe': {'name': 'trivialprog8', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog9@exe': {'name': 'trivialprog9', 'sources': ['main.cpp', 'fileA.cpp', 'a1.cpp', 'a6.cpp' ], 'extra_files': []},
                'trivialprog10@exe': {'name': 'trivialprog10', 'sources': ['main.cpp', 'fileA.cpp', 'fileB.cpp', 'a1.cpp'], 'extra_files': []},
                'trivialprog11@exe': {'name': 'trivialprog11', 'sources': ['a1.cpp', 'fileA.cpp', 'main.cpp'], 'extra_files': []},
                'trivialprog12@exe': {'name': 'trivialprog12', 'sources': ['a1.cpp', 'fileA.cpp', 'fileB.cpp', 'main.cpp'], 'extra_files': []},
                'rightName@exe': {'name': 'rightName', 'sources': ['main.cpp'], 'extra_files': []},
            }
        }
        self.assertEqualIgnoreOrder(out, expected)

        # Check the written file
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'info.json'))
        self.assertEqualIgnoreOrder(out, expected)

    def test_target_add_sources_abs(self):
        self.prime('1 basic')
        abs_src = [os.path.join(self.builddir, x) for x in ['a1.cpp', 'a2.cpp', 'a6.cpp']]
        add = json.dumps([{"type": "target", "target": "trivialprog1", "operation": "src_add", "sources": abs_src}])
        inf = json.dumps([{"type": "target", "target": "trivialprog1", "operation": "info"}])
        self.rewrite(self.builddir, add)
        out = self.rewrite(self.builddir, inf)
        expected = {'target': {'trivialprog1@exe': {'name': 'trivialprog1', 'sources': ['main.cpp', 'fileA.cpp', 'a1.cpp', 'a2.cpp', 'a6.cpp'], 'extra_files': []}}}
        self.assertDictEqual(out, expected)

    def test_target_remove_sources(self):
        self.prime('1 basic')
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'rmSrc.json'))
        expected = {
            'target': {
                'trivialprog0@exe': {'name': 'trivialprog0', 'sources': ['main.cpp', 'fileA.cpp', 'fileB.cpp', 'fileC.cpp'], 'extra_files': []},
                'trivialprog1@exe': {'name': 'trivialprog1', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog2@exe': {'name': 'trivialprog2', 'sources': ['fileB.cpp', 'fileC.cpp'], 'extra_files': []},
                'trivialprog3@exe': {'name': 'trivialprog3', 'sources': ['main.cpp'], 'extra_files': []},
                'trivialprog4@exe': {'name': 'trivialprog4', 'sources': ['main.cpp'], 'extra_files': []},
                'trivialprog5@exe': {'name': 'trivialprog5', 'sources': ['fileB.cpp', 'fileC.cpp'], 'extra_files': []},
                'trivialprog6@exe': {'name': 'trivialprog6', 'sources': ['main.cpp'], 'extra_files': []},
                'trivialprog7@exe': {'name': 'trivialprog7', 'sources': ['fileC.cpp', 'main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog8@exe': {'name': 'trivialprog8', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog9@exe': {'name': 'trivialprog9', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog10@exe': {'name': 'trivialprog10', 'sources': ['main.cpp'], 'extra_files': []},
                'trivialprog11@exe': {'name': 'trivialprog11', 'sources': ['main.cpp'], 'extra_files': []},
                'trivialprog12@exe': {'name': 'trivialprog12', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'rightName@exe': {'name': 'rightName', 'sources': ['main.cpp'], 'extra_files': []},
            }
        }
        self.assertEqualIgnoreOrder(out, expected)

        # Check the written file
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'info.json'))
        self.assertEqualIgnoreOrder(out, expected)

    def test_target_subdir(self):
        self.prime('2 subdirs')
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'addSrc.json'))
        expected = {'name': 'something', 'sources': ['third.c', f'sub2{os.path.sep}first.c', f'sub2{os.path.sep}second.c'], 'extra_files': []}
        self.assertDictEqual(list(out['target'].values())[0], expected)

        # Check the written file
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'info.json'))
        self.assertDictEqual(list(out['target'].values())[0], expected)

    def test_target_remove(self):
        self.prime('1 basic')
        self.rewrite(self.builddir, os.path.join(self.builddir, 'rmTgt.json'))
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'info.json'))

        expected = {
            'target': {
                'trivialprog2@exe': {'name': 'trivialprog2', 'sources': ['fileB.cpp', 'fileC.cpp'], 'extra_files': []},
                'trivialprog3@exe': {'name': 'trivialprog3', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog4@exe': {'name': 'trivialprog4', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog5@exe': {'name': 'trivialprog5', 'sources': ['main.cpp', 'fileB.cpp', 'fileC.cpp'], 'extra_files': []},
                'trivialprog6@exe': {'name': 'trivialprog6', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog7@exe': {'name': 'trivialprog7', 'sources': ['fileB.cpp', 'fileC.cpp', 'main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog8@exe': {'name': 'trivialprog8', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog10@exe': {'name': 'trivialprog10', 'sources': ['main.cpp', 'fileA.cpp', 'fileB.cpp'], 'extra_files': []},
                'trivialprog11@exe': {'name': 'trivialprog11', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog12@exe': {'name': 'trivialprog12', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
            }
        }
        self.assertEqualIgnoreOrder(out, expected)

    def test_target_add(self):
        self.prime('1 basic')
        self.rewrite(self.builddir, os.path.join(self.builddir, 'addTgt.json'))
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'info.json'))

        expected = {
            'target': {
                'trivialprog0@exe': {'name': 'trivialprog0', 'sources': ['main.cpp', 'fileA.cpp', 'fileB.cpp', 'fileC.cpp'], 'extra_files': []},
                'trivialprog1@exe': {'name': 'trivialprog1', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog2@exe': {'name': 'trivialprog2', 'sources': ['fileB.cpp', 'fileC.cpp'], 'extra_files': []},
                'trivialprog3@exe': {'name': 'trivialprog3', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog4@exe': {'name': 'trivialprog4', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog5@exe': {'name': 'trivialprog5', 'sources': ['main.cpp', 'fileB.cpp', 'fileC.cpp'], 'extra_files': []},
                'trivialprog6@exe': {'name': 'trivialprog6', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog7@exe': {'name': 'trivialprog7', 'sources': ['fileB.cpp', 'fileC.cpp', 'main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog8@exe': {'name': 'trivialprog8', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog9@exe': {'name': 'trivialprog9', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog10@exe': {'name': 'trivialprog10', 'sources': ['main.cpp', 'fileA.cpp', 'fileB.cpp'], 'extra_files': []},
                'trivialprog11@exe': {'name': 'trivialprog11', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog12@exe': {'name': 'trivialprog12', 'sources': ['main.cpp', 'fileA.cpp'], 'extra_files': []},
                'trivialprog13@sha': {'name': 'trivialprog13', 'sources': ['new1.cpp', 'new2.cpp'], 'extra_files': []},
                'rightName@exe': {'name': 'rightName', 'sources': ['main.cpp'], 'extra_files': []},
            }
        }
        self.assertEqualIgnoreOrder(out, expected)

    def test_target_remove_subdir(self):
        self.prime('2 subdirs')
        self.rewrite(self.builddir, os.path.join(self.builddir, 'rmTgt.json'))
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'info.json'))
        self.assertDictEqual(out, {})

    def test_target_add_subdir(self):
        self.prime('2 subdirs')
        self.rewrite(self.builddir, os.path.join(self.builddir, 'addTgt.json'))
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'info.json'))
        expected = {'name': 'something', 'sources': [f'sub2{os.path.sep}first.c', f'sub2{os.path.sep}second.c'], 'extra_files': []}
        self.assertDictEqual(out['target']['94b671c@@something@exe'], expected)

    def test_target_source_sorting(self):
        self.prime('5 sorting')
        add_json = json.dumps([{'type': 'target', 'target': 'exe1', 'operation': 'src_add', 'sources': ['a666.c']}])
        inf_json = json.dumps([{'type': 'target', 'target': 'exe1', 'operation': 'info'}])
        out = self.rewrite(self.builddir, add_json)
        out = self.rewrite(self.builddir, inf_json)
        expected = {
            'target': {
                'exe1@exe': {
                    'name': 'exe1',
                    'sources': [
                        'aaa/a/a1.c',
                        'aaa/b/b1.c',
                        'aaa/b/b2.c',
                        'aaa/f1.c',
                        'aaa/f2.c',
                        'aaa/f3.c',
                        'bbb/a/b1.c',
                        'bbb/b/b2.c',
                        'bbb/c1/b5.c',
                        'bbb/c2/b7.c',
                        'bbb/c10/b6.c',
                        'bbb/a4.c',
                        'bbb/b3.c',
                        'bbb/b4.c',
                        'bbb/b5.c',
                        'a1.c',
                        'a2.c',
                        'a3.c',
                        'a10.c',
                        'a20.c',
                        'a30.c',
                        'a100.c',
                        'a101.c',
                        'a110.c',
                        'a210.c',
                        'a666.c',
                        'b1.c',
                        'c2.c'
                    ],
                    'extra_files': []
                }
            }
        }
        for k1, v1 in expected.items():
            for k2, v2 in v1.items():
                for k3, v3 in v2.items():
                    if isinstance(v3, list):
                        for i in range(len(v3)):
                            v3[i] = v3[i].replace('/', os.path.sep)
        self.assertDictEqual(out, expected)

    def test_target_same_name_skip(self):
        self.prime('4 same name targets')
        #out = self.rewrite(self.builddir, os.path.join(self.builddir, 'addSrc.json'))
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'info.json'))
        expected1 = {'name': 'myExe', 'sources': ['main.cpp'], 'extra_files': []}
        expected2 = {'name': 'myExe', 'sources': [f'sub1{os.path.sep}main.cpp'], 'extra_files': []}
        self.assertEqual(len(out['target']), 2)
        self.assertDictEqual(expected1, out['target']['myExe@exe'])
        self.assertDictEqual(expected2, out['target']['9a11041@@myExe@exe'])

    def test_kwargs_info(self):
        self.prime('3 kwargs')
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'info.json'))
        expected = {
            'kwargs': {
                'project#/': {'version': '0.0.1'},
                'target#tgt1': {'build_by_default': True},
                'dependency#dep1': {'required': False}
            }
        }
        self.assertDictEqual(out, expected)

    def test_kwargs_set(self):
        self.prime('3 kwargs')
        self.rewrite(self.builddir, os.path.join(self.builddir, 'set.json'))
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'info.json'))
        expected = {
            'kwargs': {
                'project#/': {'version': '0.0.2', 'meson_version': '0.50.0', 'license': ['GPL', 'MIT']},
                'target#tgt1': {'build_by_default': False, 'build_rpath': '/usr/local', 'dependencies': 'dep1'},
                'dependency#dep1': {'required': True, 'method': 'cmake'}
            }
        }
        self.assertDictEqual(out, expected)

    def test_kwargs_add(self):
        self.prime('3 kwargs')
        self.rewrite(self.builddir, os.path.join(self.builddir, 'add.json'))
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'info.json'))
        expected = {
            'kwargs': {
                'project#/': {'version': '0.0.1', 'license': ['GPL', 'MIT', 'BSD', 'Boost']},
                'target#tgt1': {'build_by_default': True},
                'dependency#dep1': {'required': False}
            }
        }
        self.assertDictEqual(out, expected)

    def test_kwargs_remove(self):
        self.prime('3 kwargs')
        self.rewrite(self.builddir, os.path.join(self.builddir, 'remove.json'))
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'info.json'))
        expected = {
            'kwargs': {
                'project#/': {'version': '0.0.1', 'license': 'GPL'},
                'target#tgt1': {'build_by_default': True},
                'dependency#dep1': {'required': False}
            }
        }
        self.assertDictEqual(out, expected)

    def test_kwargs_remove_regex(self):
        self.prime('3 kwargs')
        self.rewrite(self.builddir, os.path.join(self.builddir, 'remove_regex.json'))
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'info.json'))
        expected = {
            'kwargs': {
                'project#/': {'version': '0.0.1', 'default_options': 'debug=true'},
                'target#tgt1': {'build_by_default': True},
                'dependency#dep1': {'required': False}
            }
        }
        self.assertDictEqual(out, expected)

    def test_kwargs_delete(self):
        self.prime('3 kwargs')
        self.rewrite(self.builddir, os.path.join(self.builddir, 'delete.json'))
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'info.json'))
        expected = {
            'kwargs': {
                'project#/': {},
                'target#tgt1': {},
                'dependency#dep1': {'required': False}
            }
        }
        self.assertDictEqual(out, expected)

    def test_default_options_set(self):
        self.prime('3 kwargs')
        self.rewrite(self.builddir, os.path.join(self.builddir, 'defopts_set.json'))
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'info.json'))
        expected = {
            'kwargs': {
                'project#/': {'version': '0.0.1', 'default_options': ['buildtype=release', 'debug=True', 'cpp_std=c++11']},
                'target#tgt1': {'build_by_default': True},
                'dependency#dep1': {'required': False}
            }
        }
        self.assertDictEqual(out, expected)

    def test_default_options_delete(self):
        self.prime('3 kwargs')
        self.rewrite(self.builddir, os.path.join(self.builddir, 'defopts_delete.json'))
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'info.json'))
        expected = {
            'kwargs': {
                'project#/': {'version': '0.0.1', 'default_options': ['cpp_std=c++14', 'debug=true']},
                'target#tgt1': {'build_by_default': True},
                'dependency#dep1': {'required': False}
            }
        }
        self.assertDictEqual(out, expected)

    def test_target_add_extra_files(self):
        self.prime('6 extra_files')
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'addExtraFiles.json'))
        expected = {
            'target': {
                'trivialprog0@exe': {'name': 'trivialprog0', 'sources': ['main.cpp'], 'extra_files': ['fileA.hpp', 'main.hpp', 'fileB.hpp', 'fileC.hpp']},
                'trivialprog1@exe': {'name': 'trivialprog1', 'sources': ['main.cpp'], 'extra_files': ['a1.hpp', 'a2.hpp', 'fileA.hpp', 'main.hpp']},
                'trivialprog2@exe': {'name': 'trivialprog2', 'sources': ['main.cpp'], 'extra_files': ['a7.hpp', 'fileB.hpp', 'fileC.hpp']},
                'trivialprog3@exe': {'name': 'trivialprog3', 'sources': ['main.cpp'], 'extra_files': ['a5.hpp', 'fileA.hpp', 'main.hpp']},
                'trivialprog4@exe': {'name': 'trivialprog4', 'sources': ['main.cpp'], 'extra_files': ['a5.hpp', 'main.hpp', 'fileA.hpp']},
                'trivialprog5@exe': {'name': 'trivialprog5', 'sources': ['main.cpp'], 'extra_files': ['a3.hpp', 'main.hpp', 'fileB.hpp', 'fileC.hpp']},
                'trivialprog6@exe': {'name': 'trivialprog6', 'sources': ['main.cpp'], 'extra_files': ['fileA.hpp', 'main.hpp']},
                'trivialprog7@exe': {'name': 'trivialprog7', 'sources': ['main.cpp'], 'extra_files': ['a1.hpp', 'a6.hpp', 'fileA.hpp', 'main.hpp']},
                'trivialprog8@exe': {'name': 'trivialprog8', 'sources': ['main.cpp'], 'extra_files': ['a2.hpp', 'a7.hpp']},
                'trivialprog9@exe': {'name': 'trivialprog9', 'sources': ['main.cpp'], 'extra_files': ['a8.hpp', 'a9.hpp']},
                'trivialprog10@exe': {'name': 'trivialprog10', 'sources': ['main.cpp'], 'extra_files': ['a1.hpp', 'a4.hpp']},
            }
        }
        self.assertEqualIgnoreOrder(out, expected)

        # Check the written file
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'info.json'))
        self.assertEqualIgnoreOrder(out, expected)

    def test_target_remove_extra_files(self):
        self.prime('6 extra_files')
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'rmExtraFiles.json'))
        expected = {
            'target': {
                'trivialprog0@exe': {'name': 'trivialprog0', 'sources': ['main.cpp'], 'extra_files': ['main.hpp', 'fileA.hpp', 'fileB.hpp', 'fileC.hpp']},
                'trivialprog1@exe': {'name': 'trivialprog1', 'sources': ['main.cpp'], 'extra_files': ['main.hpp', 'fileA.hpp']},
                'trivialprog2@exe': {'name': 'trivialprog2', 'sources': ['main.cpp'], 'extra_files': ['fileB.hpp', 'fileC.hpp']},
                'trivialprog3@exe': {'name': 'trivialprog3', 'sources': ['main.cpp'], 'extra_files': ['main.hpp']},
                'trivialprog4@exe': {'name': 'trivialprog4', 'sources': ['main.cpp'], 'extra_files': ['main.hpp']},
                'trivialprog5@exe': {'name': 'trivialprog5', 'sources': ['main.cpp'], 'extra_files': ['fileB.hpp', 'fileC.hpp', 'main.hpp']},
                'trivialprog6@exe': {'name': 'trivialprog6', 'sources': ['main.cpp'], 'extra_files': ['main.hpp', 'fileA.hpp']},
                'trivialprog7@exe': {'name': 'trivialprog7', 'sources': ['main.cpp'], 'extra_files': ['main.hpp', 'fileA.hpp']},
                'trivialprog8@exe': {'name': 'trivialprog8', 'sources': ['main.cpp'], 'extra_files': []},
                'trivialprog9@exe': {'name': 'trivialprog9', 'sources': ['main.cpp'], 'extra_files': []},
                'trivialprog10@exe': {'name': 'trivialprog10', 'sources': ['main.cpp'], 'extra_files': []},
            }
        }
        self.assertEqualIgnoreOrder(out, expected)

        # Check the written file
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'info.json'))
        self.assertEqualIgnoreOrder(out, expected)

    def test_tricky_dataflow(self):
        self.prime('7 tricky dataflow')
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'addSrc.json'))
        expected = {
            'target': {
                'tgt1@sha': {'name': 'tgt1', 'sources': ['foo.c', 'new.c'], 'extra_files': []},
                'tgt2@exe': {'name': 'tgt2', 'sources': ['new.c', 'unknown'], 'extra_files': []},
                'tgt3@exe': {'name': 'tgt3', 'sources': ['foo.c', 'new.c'], 'extra_files': []},
                'tgt4@exe': {'name': 'tgt4', 'sources': ['unknown'], 'extra_files': []},
                'tgt5@exe': {'name': 'tgt5', 'sources': ['unknown', 'new.c'], 'extra_files': []},
                'tgt6@exe': {'name': 'tgt6', 'sources': ['unknown', 'new.c'], 'extra_files': []},
            }
        }
        self.assertEqualIgnoreOrder(out, expected)

        # Check the written file
        out = self.rewrite(self.builddir, os.path.join(self.builddir, 'info.json'))
        self.assertEqualIgnoreOrder(out, expected)

    def test_raw_printer_is_idempotent(self):
        test_path = Path(self.unit_test_dir, '120 rewrite')
        meson_build_file = test_path / 'meson.build'
        # original_contents = meson_build_file.read_bytes()
        original_contents = meson_build_file.read_text(encoding='utf-8')

        interpreter = IntrospectionInterpreter(test_path, '', 'ninja', visitors = [AstIDGenerator()])
        interpreter.analyze()

        printer = RawPrinter()
        interpreter.ast.accept(printer)
        # new_contents = printer.result.encode('utf-8')
        new_contents = printer.result

        # Do it line per line because it is easier to debug like that
        for orig_line, new_line in zip_longest(original_contents.splitlines(), new_contents.splitlines()):
            self.assertEqual(orig_line, new_line)
