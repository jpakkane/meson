# SPDX-License-Identifier: Apache-2.0
# Copyright © 2024 Intel Corporation

project(
  'c cpp stds',
  default_options: [
    'c_std=gnu89,c89',
    'cpp_std=gnu++98,vc++11',
  ],
)

if get_option('with-c')
  add_languages('c', 'cpp', native : false)
endif
if get_option('with-objc')
  add_languages('objc', 'objcpp', native : false)
endif
