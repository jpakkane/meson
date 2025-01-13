# SPDX-License-Identifier: Apache-2.0
# Copyright © 2023-2024 Intel Corporation

project('sanitizer', 'c', meson_version : '>= 1.6')

assert(get_option('b_sanitize') == 'address,undefined', 'order of address + undefined is not correct')

array = get_option('b_sanitize', format : 2)
assert(',' not in array)
assert(array == ['address', 'undefined'] or array == ['undefined', 'address'])
