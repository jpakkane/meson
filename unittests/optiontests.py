# SPDX-License-Identifier: Apache-2.0
# Copyright 2024 Meson project contributors

from mesonbuild.options import *

import unittest


class OptionTests(unittest.TestCase):

    def test_basic(self):
        os = OptionStore()
        name = 'someoption'
        default_value = 'somevalue'
        vo = UserStringOption(name, 'An option of some sort', default_value)
        os.add_system_option(name, vo)
        self.assertEqual(os.get_value_for(name), default_value)

    def test_reset(self):
        os = OptionStore()
        name = 'someoption'
        original_value = 'original'
        reset_value = 'reset'
        vo = UserStringOption(name, 'An option set twice', original_value)
        os.add_system_option(name, vo)
        self.assertEqual(os.get_value_for(name), original_value)
        self.assertEqual(os.num_options(), 1)
        vo2 = UserStringOption(name, 'An option set twice', reset_value)
        os.add_system_option(name, vo2)
        self.assertEqual(os.get_value_for(name), original_value)
        self.assertEqual(os.num_options(), 1)

    def test_project_nonyielding(self):
        os = OptionStore()
        name = 'someoption'
        top_value = 'top'
        sub_value = 'sub'
        vo = UserStringOption(name, 'A top level option', top_value)
        os.add_project_option(name, '', False, vo)
        self.assertEqual(os.get_value_for(name, ''), top_value)
        self.assertEqual(os.num_options(), 1)
        vo2 = UserStringOption(name, 'A subproject option', sub_value)
        os.add_project_option(name, 'sub', False, vo2)
        self.assertEqual(os.get_value_for(name), top_value)
        self.assertEqual(os.get_value_for(name, 'sub'), sub_value)
        self.assertEqual(os.num_options(), 2)

    def test_project_yielding(self):
        os = OptionStore()
        name = 'someoption'
        top_value = 'top'
        sub_value = 'sub'
        vo = UserStringOption(name, 'A top level option', top_value)
        os.add_project_option(name, '', False, vo)
        self.assertEqual(os.get_value_for(name, ''), top_value)
        self.assertEqual(os.num_options(), 1)
        vo2 = UserStringOption(name, 'A subproject option', sub_value)
        os.add_project_option(name, 'sub', True, vo2)
        self.assertEqual(os.get_value_for(name), top_value)
        self.assertEqual(os.get_value_for(name, 'sub'), top_value)
        self.assertEqual(os.num_options(), 2)
