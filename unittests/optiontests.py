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