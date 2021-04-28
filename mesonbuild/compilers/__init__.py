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
    'Compiler',

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
    'sort_clink',

    'AppleClangCCompiler',
    'AppleClangCPPCompiler',
    'AppleClangObjCCompiler',
    'AppleClangObjCPPCompiler',
    'ArmCCompiler',
    'ArmCPPCompiler',
    'ArmclangCCompiler',
    'ArmclangCPPCompiler',
    'CCompiler',
    'ClangCCompiler',
    'ClangCompiler',
    'ClangCPPCompiler',
    'ClangObjCCompiler',
    'ClangObjCPPCompiler',
    'ClangClCCompiler',
    'ClangClCPPCompiler',
    'CPPCompiler',
    'DCompiler',
    'DmdDCompiler',
    'FortranCompiler',
    'G95FortranCompiler',
    'GnuCCompiler',
    'ElbrusCCompiler',
    'EmscriptenCCompiler',
    'GnuCompiler',
    'GnuLikeCompiler',
    'GnuCPPCompiler',
    'ElbrusCPPCompiler',
    'EmscriptenCPPCompiler',
    'GnuDCompiler',
    'GnuFortranCompiler',
    'ElbrusFortranCompiler',
    'FlangFortranCompiler',
    'GnuObjCCompiler',
    'GnuObjCPPCompiler',
    'IntelGnuLikeCompiler',
    'IntelVisualStudioLikeCompiler',
    'IntelCCompiler',
    'IntelCPPCompiler',
    'IntelClCCompiler',
    'IntelClCPPCompiler',
    'IntelFortranCompiler',
    'IntelClFortranCompiler',
    'JavaCompiler',
    'LLVMDCompiler',
    'MonoCompiler',
    'CudaCompiler',
    'VisualStudioCsCompiler',
    'NAGFortranCompiler',
    'ObjCCompiler',
    'ObjCPPCompiler',
    'Open64FortranCompiler',
    'PathScaleFortranCompiler',
    'NvidiaHPC_CCompiler',
    'NvidiaHPC_CPPCompiler',
    'NvidiaHPC_FortranCompiler',
    'PGICCompiler',
    'PGICPPCompiler',
    'PGIFortranCompiler',
    'RustCompiler',
    'CcrxCCompiler',
    'CcrxCPPCompiler',
    'Xc16CCompiler',
    'CompCertCCompiler',
    'C2000CCompiler',
    'C2000CPPCompiler',
    'SunFortranCompiler',
    'SwiftCompiler',
    'ValaCompiler',
    'VisualStudioLikeCompiler',
    'VisualStudioCCompiler',
    'VisualStudioCPPCompiler',
    'ZigCompiler'
]

# Bring symbols from each module into compilers sub-package namespace
from .compilers import (
    Compiler,
    all_languages,
    base_options,
    clib_langs,
    clink_langs,
    c_suffixes,
    cpp_suffixes,
    get_base_compile_args,
    get_base_link_args,
    is_header,
    is_source,
    is_assembly,
    is_llvm_ir,
    is_object,
    is_library,
    is_known_suffix,
    lang_suffixes,
    LANGUAGES_USING_LDFLAGS,
    sort_clink,
)
from .c import (
    CCompiler,
    AppleClangCCompiler,
    ArmCCompiler,
    ArmclangCCompiler,
    ClangCCompiler,
    ClangClCCompiler,
    GnuCCompiler,
    ElbrusCCompiler,
    EmscriptenCCompiler,
    IntelCCompiler,
    IntelClCCompiler,
    NvidiaHPC_CCompiler,
    PGICCompiler,
    CcrxCCompiler,
    Xc16CCompiler,
    CompCertCCompiler,
    C2000CCompiler,
    VisualStudioCCompiler,
)
from .cpp import (
    CPPCompiler,
    AppleClangCPPCompiler,
    ArmCPPCompiler,
    ArmclangCPPCompiler,
    ClangCPPCompiler,
    ClangClCPPCompiler,
    GnuCPPCompiler,
    ElbrusCPPCompiler,
    EmscriptenCPPCompiler,
    IntelCPPCompiler,
    IntelClCPPCompiler,
    NvidiaHPC_CPPCompiler,
    PGICPPCompiler,
    CcrxCPPCompiler,
    C2000CPPCompiler,
    VisualStudioCPPCompiler,
)
from .cs import MonoCompiler, VisualStudioCsCompiler
from .d import (
    DCompiler,
    DmdDCompiler,
    GnuDCompiler,
    LLVMDCompiler,
)
from .cuda import CudaCompiler
from .fortran import (
    FortranCompiler,
    G95FortranCompiler,
    GnuFortranCompiler,
    ElbrusFortranCompiler,
    FlangFortranCompiler,
    IntelFortranCompiler,
    IntelClFortranCompiler,
    NAGFortranCompiler,
    Open64FortranCompiler,
    PathScaleFortranCompiler,
    NvidiaHPC_FortranCompiler,
    PGIFortranCompiler,
    SunFortranCompiler,
)
from .java import JavaCompiler
from .objc import (
    ObjCCompiler,
    AppleClangObjCCompiler,
    ClangObjCCompiler,
    GnuObjCCompiler,
)
from .objcpp import (
    ObjCPPCompiler,
    AppleClangObjCPPCompiler,
    ClangObjCPPCompiler,
    GnuObjCPPCompiler,
)
from .rust import RustCompiler
from .swift import SwiftCompiler
from .vala import ValaCompiler
from .zig import ZigCompiler
from .mixins.visualstudio import VisualStudioLikeCompiler
from .mixins.gnu import GnuCompiler, GnuLikeCompiler
from .mixins.intel import IntelGnuLikeCompiler, IntelVisualStudioLikeCompiler
from .mixins.clang import ClangCompiler
