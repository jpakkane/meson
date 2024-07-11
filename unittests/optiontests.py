# SPDX-License-Identifier: Apache-2.0
# Copyright 2024 Meson project contributors

from mesonbuild.options import *

import unittest


class OptionTests(unittest.TestCase):

    def test_basic(self):
        optstore = OptionStore()
        name = 'someoption'
        default_value = 'somevalue'
        new_value = 'new_value'
        k = OptionParts(name)
        vo = UserStringOption(k, 'An option of some sort', default_value)
        optstore.add_system_option(k.name, vo)
        self.assertEqual(optstore.get_value_for(k), default_value)
        optstore.set_option(k, new_value)
        self.assertEqual(optstore.get_value_for(k), new_value)

    def test_toplevel_project(self):
        optstore = OptionStore()
        name = 'someoption'
        default_value = 'somevalue'
        new_value = 'new_value'
        k = OptionParts(name)
        vo = UserStringOption(k, 'An option of some sort', default_value)
        optstore.add_system_option(k.name, vo)
        self.assertEqual(optstore.get_value_for(k), default_value)
        optstore.set_from_top_level_project_call([f'someoption={new_value}'], {}, {})
        self.assertEqual(optstore.get_value_for(k), new_value)

    def test_parsing(self):
        optstore = OptionStore()
        s1 = optstore.split_keystring('sub:optname')
        s1_expected = OptionParts('optname', 'sub', False)
        self.assertEqual(s1, s1_expected)
        self.assertEqual(optstore.form_canonical_keystring(s1), 'sub:optname')

        s2 = optstore.split_keystring('optname')
        s2_expected = OptionParts('optname', None, False)
        self.assertEqual(s2, s2_expected)

        self.assertEqual(optstore.form_canonical_keystring(s2), 'optname')

        s3 = optstore.split_keystring(':optname')
        s3_expected = OptionParts('optname', '', False)
        self.assertEqual(s3, s3_expected)
        self.assertEqual(optstore.form_canonical_keystring(s3), ':optname')

    def test_subproject_for_system(self):
        optstore = OptionStore()
        name = 'someoption'
        key = OptionParts(name)
        subkey = key.copy_with(subproject='somesubproject')
        default_value = 'somevalue'
        vo = UserStringOption(name, 'An option of some sort', default_value)
        optstore.add_system_option(name, vo)
        self.assertEqual(optstore.get_value_for(subkey), default_value)

    def test_reset(self):
        optstore = OptionStore()
        name = 'someoption'
        original_value = 'original'
        reset_value = 'reset'
        k = OptionParts(name)
        vo = UserStringOption(name, 'An option set twice', original_value)
        optstore.add_system_option(name, vo)
        self.assertEqual(optstore.get_value_for(k), original_value)
        self.assertEqual(optstore.num_options(), 1)
        vo2 = UserStringOption(name, 'An option set twice', reset_value)
        optstore.add_system_option(name, vo2)
        self.assertEqual(optstore.get_value_for(k), original_value)
        self.assertEqual(optstore.num_options(), 1)

    def test_project_nonyielding(self):
        optstore = OptionStore()
        name = 'someoption'
        top_value = 'top'
        sub_value = 'sub'
        top_key = OptionParts(name, '')
        sub_key = top_key.copy_with(subproject='sub')
        vo = UserStringOption(name, 'A top level option', top_value, False)
        optstore.add_project_option(name, '', vo)
        self.assertEqual(optstore.get_value_for(top_key), top_value, False)
        self.assertEqual(optstore.num_options(), 1)
        vo2 = UserStringOption(name, 'A subproject option', sub_value)
        optstore.add_project_option(name, 'sub', vo2)
        self.assertEqual(optstore.get_value_for(top_key), top_value)
        self.assertEqual(optstore.get_value_for(sub_key), sub_value)
        self.assertEqual(optstore.num_options(), 2)

    def test_project_yielding(self):
        optstore = OptionStore()
        name = 'someoption'
        top_value = 'top'
        sub_value = 'sub'
        vo = UserStringOption(name, 'A top level option', top_value)
        top_key = OptionParts(name, '')
        sub_key = top_key.copy_with(subproject='sub')
        optstore.add_project_option(name, '', vo)
        self.assertEqual(optstore.get_value_for(top_key), top_value)
        self.assertEqual(optstore.num_options(), 1)
        vo2 = UserStringOption(name, 'A subproject option', sub_value, True)
        optstore.add_project_option(name, 'sub', vo2)
        self.assertEqual(optstore.get_value_for(top_key), top_value)
        self.assertEqual(optstore.get_value_for(sub_key), top_value)
        self.assertEqual(optstore.num_options(), 2)

    def test_augments(self):
        optstore = OptionStore()
        name = 'cpp_std'
        sub_name = 'sub'
        sub2_name = 'sub2'
        top_value = 'c++11'
        aug_value = 'c++23'
        top_key = OptionParts(name)
        topsub_key = top_key.copy_with(subproject='')
        sub_key = top_key.copy_with(subproject=sub_name)
        sub2_key = top_key.copy_with(subproject=sub2_name)

        co = UserComboOption(name,
                             'C++ language standard to use',
                             ['c++98', 'c++11', 'c++14', 'c++17', 'c++20', 'c++23'],
                             top_value)
        optstore.add_system_option(name, co)
        self.assertEqual(optstore.get_value_for(top_key), top_value)
        self.assertEqual(optstore.get_value_for(sub_key), top_value)
        self.assertEqual(optstore.get_value_for(sub2_key), top_value)

        # First augment a subproject
        optstore.set_from_configure_command([], [f'{sub_name}:{name}={aug_value}'], [])
        self.assertEqual(optstore.get_value_for(top_key), top_value)
        self.assertEqual(optstore.get_value_for(sub_key), aug_value)
        self.assertEqual(optstore.get_value_for(sub2_key), top_value)
        optstore.set_from_configure_command([], [], [f'{sub_name}:{name}'])
        self.assertEqual(optstore.get_value_for(top_key), top_value)
        self.assertEqual(optstore.get_value_for(sub_key), top_value)
        self.assertEqual(optstore.get_value_for(sub2_key), top_value)

        # And now augment the top level option
        optstore.set_from_configure_command([], [f':{name}={aug_value}'], [])
        self.assertEqual(optstore.get_value_for(top_key), top_value)
        self.assertEqual(optstore.get_value_for(topsub_key), aug_value)
        self.assertEqual(optstore.get_value_for(sub_key), top_value)
        self.assertEqual(optstore.get_value_for(sub2_key), top_value)
        optstore.set_from_configure_command([], [], [f':{name}'])
        self.assertEqual(optstore.get_value_for(top_key), top_value)
        self.assertEqual(optstore.get_value_for(sub_key), top_value)
        self.assertEqual(optstore.get_value_for(sub2_key), top_value)

    def test_augment_set_sub(self):
        optstore = OptionStore()
        name = 'cpp_std'
        sub_name = 'sub'
        top_value = 'c++11'
        aug_value = 'c++23'
        set_value = 'c++20'
        top_key = OptionParts(name=name)
        sub_key = top_key.copy_with(subproject=sub_name)

        co = UserComboOption(name,
                             'C++ language standard to use',
                             ['c++98', 'c++11', 'c++14', 'c++17', 'c++20', 'c++23'],
                             top_value)
        optstore.add_system_option(name, co)
        optstore.set_from_configure_command([], [f'{sub_name}:{name}={aug_value}'], [])
        optstore.set_from_configure_command([f'{sub_name}:{name}={set_value}'], [], [])
        self.assertEqual(optstore.get_value_for(top_key), top_value)
        self.assertEqual(optstore.get_value_for(sub_key), set_value)

    def test_subproject_call_options(self):
        optstore = OptionStore()
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
        optstore.set_from_subproject_call(subproject, [f'cpp_std={override_value}'], [f'cpp_std={unused_value}'])
        k = OptionParts(name)
        sub_k = k.copy_with(subproject=subproject)
        self.assertEqual(optstore.get_value_for(k), default_value)
        self.assertEqual(optstore.get_value_for(sub_k), override_value)

        # Trying again should change nothing
        optstore.set_from_subproject_call(subproject, [f'cpp_std={unused_value}'], [f'cpp_std={unused_value}'])
        self.assertEqual(optstore.get_value_for(k), default_value)
        self.assertEqual(optstore.get_value_for(sub_k), override_value)
