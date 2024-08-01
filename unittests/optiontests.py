# SPDX-License-Identifier: Apache-2.0
# Copyright 2024 Meson project contributors

from mesonbuild.options import *

import unittest


class OptionTests(unittest.TestCase):

    def test_basic(self):
        optstore = OptionStore(False)
        name = 'someoption'
        default_value = 'somevalue'
        new_value = 'new_value'
        vo = UserStringOption(name, 'An option of some sort', default_value)
        optstore.add_system_option(name, vo)
        self.assertEqual(optstore.get_value_for(name), default_value)
        optstore.set_option(name, None, new_value)
        self.assertEqual(optstore.get_value_for(name), new_value)

    def test_toplevel_project(self):
        optstore = OptionStore(False)
        name = 'someoption'
        default_value = 'somevalue'
        new_value = 'new_value'
        k = OptionKey(name)
        vo = UserStringOption(k.name, 'An option of some sort', default_value)
        optstore.add_system_option(k.name, vo)
        self.assertEqual(optstore.get_value_for(k), default_value)
        optstore.set_from_top_level_project_call([f'someoption={new_value}'], {}, {})
        self.assertEqual(optstore.get_value_for(k), new_value)

    def test_parsing(self):
        s1 = OptionKey.from_string('sub:optname')
        s1_expected = OptionKey('optname', 'sub', MachineChoice.HOST)
        self.assertEqual(s1, s1_expected)
        self.assertEqual(str(s1), 'sub:optname')

        s2 = OptionKey.from_string('optname')
        s2_expected = OptionKey('optname', None, MachineChoice.HOST)
        self.assertEqual(s2, s2_expected)

        self.assertEqual(str(s2), 'optname')

        s3 = OptionKey.from_string(':optname')
        s3_expected = OptionKey('optname', '', MachineChoice.HOST)
        self.assertEqual(s3, s3_expected)
        self.assertEqual(str(s3), ':optname')

    def test_subproject_for_system(self):
        optstore = OptionStore(False)
        name = 'someoption'
        default_value = 'somevalue'
        vo = UserStringOption(name, 'An option of some sort', default_value)
        optstore.add_system_option(name, vo)
        self.assertEqual(optstore.get_value_for(name, 'somesubproject'), default_value)

    def test_reset(self):
        optstore = OptionStore(False)
        name = 'someoption'
        original_value = 'original'
        reset_value = 'reset'
        vo = UserStringOption(name, 'An option set twice', original_value)
        optstore.add_system_option(name, vo)
        self.assertEqual(optstore.get_value_for(name), original_value)
        self.assertEqual(optstore.num_options(), 1)
        vo2 = UserStringOption(name, 'An option set twice', reset_value)
        optstore.add_system_option(name, vo2)
        self.assertEqual(optstore.get_value_for(name), original_value)
        self.assertEqual(optstore.num_options(), 1)

    def test_project_nonyielding(self):
        optstore = OptionStore(False)
        name = 'someoption'
        top_value = 'top'
        sub_value = 'sub'
        vo = UserStringOption(name, 'A top level option', top_value, False)
        optstore.add_project_option(OptionKey(name, ''), vo)
        self.assertEqual(optstore.get_value_for(name, ''), top_value, False)
        self.assertEqual(optstore.num_options(), 1)
        vo2 = UserStringOption(name, 'A subproject option', sub_value)
        optstore.add_project_option(OptionKey(name, 'sub'), vo2)
        self.assertEqual(optstore.get_value_for(name, ''), top_value)
        self.assertEqual(optstore.get_value_for(name, 'sub'), sub_value)
        self.assertEqual(optstore.num_options(), 2)

    def test_project_yielding(self):
        optstore = OptionStore(False)
        name = 'someoption'
        top_value = 'top'
        sub_value = 'sub'
        vo = UserStringOption(name, 'A top level option', top_value)
        optstore.add_project_option(OptionKey(name, ''), vo)
        self.assertEqual(optstore.get_value_for(name, ''), top_value)
        self.assertEqual(optstore.num_options(), 1)
        vo2 = UserStringOption(name, 'A subproject option', sub_value, True)
        optstore.add_project_option(OptionKey(name, 'sub'), vo2)
        self.assertEqual(optstore.get_value_for(name, ''), top_value)
        self.assertEqual(optstore.get_value_for(name, 'sub'), top_value)
        self.assertEqual(optstore.num_options(), 2)

    def test_augments(self):
        optstore = OptionStore(False)
        name = 'cpp_std'
        sub_name = 'sub'
        sub2_name = 'sub2'
        top_value = 'c++11'
        aug_value = 'c++23'

        co = UserComboOption(name,
                             'C++ language standard to use',
                             ['c++98', 'c++11', 'c++14', 'c++17', 'c++20', 'c++23'],
                             top_value)
        optstore.add_system_option(name, co)
        self.assertEqual(optstore.get_value_for(name), top_value)
        self.assertEqual(optstore.get_value_for(name, sub_name), top_value)
        self.assertEqual(optstore.get_value_for(name, sub2_name), top_value)

        # First augment a subproject
        optstore.set_from_configure_command([], [f'{sub_name}:{name}={aug_value}'], [])
        self.assertEqual(optstore.get_value_for(name), top_value)
        self.assertEqual(optstore.get_value_for(name, sub_name), aug_value)
        self.assertEqual(optstore.get_value_for(name, sub2_name), top_value)
        optstore.set_from_configure_command([], [], [f'{sub_name}:{name}'])
        self.assertEqual(optstore.get_value_for(name), top_value)
        self.assertEqual(optstore.get_value_for(name, sub_name), top_value)
        self.assertEqual(optstore.get_value_for(name, sub2_name), top_value)

        # And now augment the top level option
        optstore.set_from_configure_command([], [f':{name}={aug_value}'], [])
        self.assertEqual(optstore.get_value_for(name, None), top_value)
        self.assertEqual(optstore.get_value_for(name, ''), aug_value)
        self.assertEqual(optstore.get_value_for(name, sub_name), top_value)
        self.assertEqual(optstore.get_value_for(name, sub2_name), top_value)
        optstore.set_from_configure_command([], [], [f':{name}'])
        self.assertEqual(optstore.get_value_for(name), top_value)
        self.assertEqual(optstore.get_value_for(name, sub_name), top_value)
        self.assertEqual(optstore.get_value_for(name, sub2_name), top_value)

    def test_augment_set_sub(self):
        optstore = OptionStore(False)
        name = 'cpp_std'
        sub_name = 'sub'
        sub2_name = 'sub2'
        top_value = 'c++11'
        aug_value = 'c++23'
        set_value = 'c++20'

        co = UserComboOption(name,
                             'C++ language standard to use',
                             ['c++98', 'c++11', 'c++14', 'c++17', 'c++20', 'c++23'],
                             top_value)
        optstore.add_system_option(name, co)
        optstore.set_from_configure_command([], [f'{sub_name}:{name}={aug_value}'], [])
        optstore.set_from_configure_command([f'{sub_name}:{name}={set_value}'], [], [])
        self.assertEqual(optstore.get_value_for(name), top_value)
        self.assertEqual(optstore.get_value_for(name, sub_name), set_value)

    def test_subproject_call_options(self):
        optstore = OptionStore(False)
        name = 'cpp_std'
        default_value = 'c++11'
        override_value = 'c++14'
        unused_value = 'c++20'
        subproject = 'sub'

        co = UserComboOption(name,
                             'C++ language standard to use',
                             ['c++98', 'c++11', 'c++14', 'c++17', 'c++20', 'c++23'],
                             default_value)
        optstore.add_system_option(name, co)
        optstore.set_subproject_options(subproject, [f'cpp_std={override_value}'], [f'cpp_std={unused_value}'])
        self.assertEqual(optstore.get_value_for(name), default_value)
        self.assertEqual(optstore.get_value_for(name, subproject), override_value)

        # Trying again should change nothing
        optstore.set_subproject_options(subproject, [f'cpp_std={unused_value}'], [f'cpp_std={unused_value}'])
        self.assertEqual(optstore.get_value_for(name), default_value)
        self.assertEqual(optstore.get_value_for(name, subproject), override_value)
