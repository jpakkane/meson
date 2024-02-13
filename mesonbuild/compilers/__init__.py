# SPDX-License-Identifier: Apache-2.0
# Copyright 2017 The Meson development team

"""Public symbols for compilers sub-package when using 'from . import compilers'"""


from __future__ import annotations

from .compilers import (
    LANGUAGES_USING_LDFLAGS, SUFFIX_TO_LANG, Compiler, RunResult, all_languages, base_options,
    c_suffixes, clib_langs, clink_langs, cpp_suffixes, get_base_compile_args, get_base_link_args,
    is_assembly, is_header, is_known_suffix, is_library, is_llvm_ir, is_object, is_source,
    lang_suffixes, sort_clink
)
from .detect import (
    compiler_from_language, detect_c_compiler, detect_compiler_for, detect_cpp_compiler,
    detect_cs_compiler, detect_cuda_compiler, detect_d_compiler, detect_fortran_compiler,
    detect_java_compiler, detect_objc_compiler, detect_objcpp_compiler, detect_rust_compiler,
    detect_static_linker, detect_swift_compiler, detect_vala_compiler
)

__all__ = [
    'Compiler',
    'RunResult',

    'all_languages',
    'base_options',
    'clib_langs',
    'clink_langs',
    'c_suffixes',
    'cpp_suffixes',
    'get_base_compile_args',
    'get_base_link_args',
    'is_assembly',
    'is_header',
    'is_library',
    'is_llvm_ir',
    'is_object',
    'is_source',
    'is_known_suffix',
    'lang_suffixes',
    'LANGUAGES_USING_LDFLAGS',
    'sort_clink',
    'SUFFIX_TO_LANG',

    'compiler_from_language',
    'detect_compiler_for',
    'detect_static_linker',
    'detect_c_compiler',
    'detect_cpp_compiler',
    'detect_cuda_compiler',
    'detect_fortran_compiler',
    'detect_objc_compiler',
    'detect_objcpp_compiler',
    'detect_java_compiler',
    'detect_cs_compiler',
    'detect_vala_compiler',
    'detect_rust_compiler',
    'detect_d_compiler',
    'detect_swift_compiler',
]
