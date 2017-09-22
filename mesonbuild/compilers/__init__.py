# Copyright 2017 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Public symbols for compilers sub-package when using 'from . import compilers'
__all__ = [
    'CLANG_OSX',
    'CLANG_STANDARD',
    'CLANG_WIN',
    'GCC_CYGWIN',
    'GCC_MINGW',
    'GCC_OSX',
    'GCC_STANDARD',
    'ICC_OSX',
    'ICC_STANDARD',
    'ICC_WIN',

    'base_options',
    'clike_langs',
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
    'lang_suffixes',
    'sanitizer_compile_args',
    'sort_clike',

    'CCompiler',
    'ClangCCompiler',
    'ClangCompiler',
    'ClangCPPCompiler',
    'ClangObjCCompiler',
    'ClangObjCPPCompiler',
    'CompilerArgs',
    'CPPCompiler',
    'DCompiler',
    'DmdDCompiler',
    'FortranCompiler',
    'G95FortranCompiler',
    'GnuCCompiler',
    'GnuCompiler',
    'GnuCPPCompiler',
    'GnuDCompiler',
    'GnuFortranCompiler',
    'GnuObjCCompiler',
    'GnuObjCPPCompiler',
    'IntelCompiler',
    'IntelCCompiler',
    'IntelCPPCompiler',
    'IntelFortranCompiler',
    'JavaCompiler',
    'LLVMDCompiler',
    'MonoCompiler',
    'NAGFortranCompiler',
    'ObjCCompiler',
    'ObjCPPCompiler',
    'Open64FortranCompiler',
    'PathScaleFortranCompiler',
    'PGIFortranCompiler',
    'RustCompiler',
    'SunFortranCompiler',
    'SwiftCompiler',
    'ValaCompiler',
    'VisualStudioCCompiler',
    'VisualStudioCPPCompiler',
]

from .c import (
    CCompiler,
    ClangCCompiler,
    GnuCCompiler,
    IntelCCompiler,
    VisualStudioCCompiler,
)
# Bring symbols from each module into compilers sub-package namespace
from .compilers import (
    CLANG_OSX,
    CLANG_STANDARD,
    CLANG_WIN,
    GCC_CYGWIN,
    GCC_MINGW,
    GCC_OSX,
    GCC_STANDARD,
    ICC_OSX,
    ICC_STANDARD,
    ICC_WIN,
    ClangCompiler,
    CompilerArgs,
    GnuCompiler,
    IntelCompiler,
    base_options,
    c_suffixes,
    clike_langs,
    cpp_suffixes,
    get_base_compile_args,
    get_base_link_args,
    is_assembly,
    is_header,
    is_library,
    is_llvm_ir,
    is_object,
    is_source,
    lang_suffixes,
    sanitizer_compile_args,
    sort_clike,
)
from .cpp import (
    ClangCPPCompiler,
    CPPCompiler,
    GnuCPPCompiler,
    IntelCPPCompiler,
    VisualStudioCPPCompiler,
)
from .cs import MonoCompiler
from .d import DCompiler, DmdDCompiler, GnuDCompiler, LLVMDCompiler
from .fortran import (
    FortranCompiler,
    G95FortranCompiler,
    GnuFortranCompiler,
    IntelFortranCompiler,
    NAGFortranCompiler,
    Open64FortranCompiler,
    PathScaleFortranCompiler,
    PGIFortranCompiler,
    SunFortranCompiler,
)
from .java import JavaCompiler
from .objc import ClangObjCCompiler, GnuObjCCompiler, ObjCCompiler
from .objcpp import ClangObjCPPCompiler, GnuObjCPPCompiler, ObjCPPCompiler
from .rust import RustCompiler
from .swift import SwiftCompiler
from .vala import ValaCompiler
