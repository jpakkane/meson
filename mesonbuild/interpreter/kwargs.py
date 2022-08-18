# SPDX-License-Identifier: Apache-2.0
# Copyright © 2021 The Meson Developers
# Copyright © 2021 Intel Corporation

"""Keyword Argument type annotations."""

import typing as T

from typing_extensions import TypedDict, Literal, Protocol

from .. import build
from .. import coredata
from .. import dependencies
from ..compilers import Compiler
from ..mesonlib import MachineChoice, File, FileMode, FileOrString
from ..modules.cmake import CMakeSubprojectOptions
from ..programs import ExternalProgram


class FuncAddProjectArgs(TypedDict):

    """Keyword Arguments for the add_*_arguments family of arguments.

    including `add_global_arguments`, `add_project_arguments`, and their
    link variants

    Because of the use of a convertor function, we get the native keyword as
    a MachineChoice instance already.
    """

    native: MachineChoice
    language: T.List[str]


class BaseTest(TypedDict):

    """Shared base for the Rust module."""

    args: T.List[T.Union[str, File, build.Target]]
    should_fail: bool
    timeout: int
    workdir: T.Optional[str]
    depends: T.List[T.Union[build.CustomTarget, build.BuildTarget]]
    priority: int
    env: build.EnvironmentVariables
    suite: T.List[str]


class FuncBenchmark(BaseTest):

    """Keyword Arguments shared between `test` and `benchmark`."""

    protocol: Literal['exitcode', 'tap', 'gtest', 'rust']


class FuncTest(FuncBenchmark):

    """Keyword Arguments for `test`

    `test` only adds the `is_prallel` argument over benchmark, so inherintance
    is helpful here.
    """

    is_parallel: bool


class ExtractRequired(TypedDict):

    """Keyword Arguments consumed by the `extract_required_kwargs` function.

    Any function that uses the `required` keyword argument which accepts either
    a boolean or a feature option should inherit it's arguments from this class.
    """

    required: T.Union[bool, coredata.UserFeatureOption]


class ExtractSearchDirs(TypedDict):

    """Keyword arguments consumed by the `extract_search_dirs` function.

    See the not in `ExtractRequired`
    """

    dirs: T.List[str]


class FuncGenerator(TypedDict):

    """Keyword rguments for the generator function."""

    arguments: T.List[str]
    output: T.List[str]
    depfile: T.Optional[str]
    capture:  bool
    depends: T.List[T.Union[build.BuildTarget, build.CustomTarget]]


class GeneratorProcess(TypedDict):

    """Keyword Arguments for generator.process."""

    preserve_path_from: T.Optional[str]
    extra_args: T.List[str]

class DependencyMethodPartialDependency(TypedDict):

    """ Keyword Arguments for the dep.partial_dependency methods """

    compile_args: bool
    link_args: bool
    links: bool
    includes: bool
    sources: bool

class BuildTargeMethodExtractAllObjects(TypedDict):
    recursive: bool

class FuncInstallSubdir(TypedDict):

    install_dir: str
    strip_directory: bool
    exclude_files: T.List[str]
    exclude_directories: T.List[str]
    install_mode: FileMode


class FuncInstallData(TypedDict):

    install_dir: str
    sources: T.List[FileOrString]
    rename: T.List[str]
    install_mode: FileMode


class FuncInstallHeaders(TypedDict):

    install_dir: T.Optional[str]
    install_mode: FileMode
    subdir: T.Optional[str]


class FuncInstallMan(TypedDict):

    install_dir: T.Optional[str]
    install_mode: FileMode
    locale: T.Optional[str]


class FuncImportModule(ExtractRequired):

    disabler: bool


class FuncIncludeDirectories(TypedDict):

    is_system: bool

class FuncAddLanguages(ExtractRequired):

    native: T.Optional[bool]

class RunTarget(TypedDict):

    command: T.List[T.Union[str, build.BuildTarget, build.CustomTarget, ExternalProgram, File]]
    depends: T.List[T.Union[build.BuildTarget, build.CustomTarget]]
    env: build.EnvironmentVariables


class CustomTarget(TypedDict):

    build_always: bool
    build_always_stale: T.Optional[bool]
    build_by_default: T.Optional[bool]
    capture: bool
    command: T.List[T.Union[str, build.BuildTarget, build.CustomTarget,
                            build.CustomTargetIndex, ExternalProgram, File]]
    console: bool
    depend_files: T.List[FileOrString]
    depends: T.List[T.Union[build.BuildTarget, build.CustomTarget]]
    depfile: T.Optional[str]
    env: build.EnvironmentVariables
    feed: bool
    input: T.List[T.Union[str, build.BuildTarget, build.CustomTarget, build.CustomTargetIndex,
                          build.ExtractedObjects, build.GeneratedList, ExternalProgram, File]]
    install: bool
    install_dir: T.List[T.Union[str, T.Literal[False]]]
    install_mode: FileMode
    install_tag: T.List[T.Optional[str]]
    output: T.List[str]

class AddTestSetup(TypedDict):

    exe_wrapper: T.List[T.Union[str, ExternalProgram]]
    gdb: bool
    timeout_multiplier: int
    is_default: bool
    exclude_suites: T.List[str]
    env: build.EnvironmentVariables


class Project(TypedDict):

    version: T.Optional[FileOrString]
    meson_version: T.Optional[str]
    default_options: T.List[str]
    license: T.List[str]
    subproject_dir: str


class _FoundProto(Protocol):

    """Protocol for subdir arguments.

    This allows us to define any objec that has a found(self) -> bool method
    """

    def found(self) -> bool: ...


class Subdir(TypedDict):

    if_found: T.List[_FoundProto]


class Summary(TypedDict):

    section: str
    bool_yn: bool
    list_sep: T.Optional[str]


class FindProgram(ExtractRequired, ExtractSearchDirs):

    native: MachineChoice
    version: T.List[str]


class RunCommand(TypedDict):

    check: bool
    capture: T.Optional[bool]
    env: build.EnvironmentVariables


class FeatureOptionRequire(TypedDict):

    error_message: T.Optional[str]


class DependencyPkgConfigVar(TypedDict):

    default: T.Optional[str]
    define_variable: T.List[str]


class DependencyGetVariable(TypedDict):

    cmake: T.Optional[str]
    pkgconfig: T.Optional[str]
    configtool: T.Optional[str]
    internal: T.Optional[str]
    default_value: T.Optional[str]
    pkgconfig_define: T.List[str]


class ConfigurationDataSet(TypedDict):

    description: T.Optional[str]

class VcsTag(TypedDict):

    command: T.List[T.Union[str, build.BuildTarget, build.CustomTarget,
                            build.CustomTargetIndex, ExternalProgram, File]]
    fallback: T.Optional[str]
    input: T.List[T.Union[str, build.BuildTarget, build.CustomTarget, build.CustomTargetIndex,
                          build.ExtractedObjects, build.GeneratedList, ExternalProgram, File]]
    output: T.List[str]
    replace_string: str


class ConfigureFile(TypedDict):

    output: str
    capture: bool
    format: Literal['meson', 'cmake', 'cmake@']
    output_format: Literal['c', 'nasm']
    depfile: T.Optional[str]
    install: T.Optional[bool]
    install_dir: T.Union[str, Literal[False]]
    install_mode: FileMode
    install_tag: T.Optional[str]
    encoding: str
    command: T.Optional[T.List[T.Union[build.Executable, ExternalProgram, Compiler, File, str]]]
    input: T.List[FileOrString]
    configuration: T.Optional[T.Union[T.Dict[str, T.Union[str, int, bool]], build.ConfigurationData]]


class Subproject(ExtractRequired):

    default_options: T.List[str]
    version: T.List[str]


class DoSubproject(ExtractRequired):

    default_options: T.List[str]
    version: T.List[str]
    cmake_options: T.List[str]
    options: T.Optional[CMakeSubprojectOptions]


GNU_SYMBOL_VISIBILITY = Literal['default', 'internal', 'hidden', 'protected', 'inlineshidden']
LINK_LANGUAGE = Literal['c', 'cpp', 'objc', 'objcpp', 'd', 'rust', 'swift', 'cuda', 'fortran', 'vala', 'cs', 'java', 'cython']


class _BuildTargetBase(TypedDict):

    build_by_default: bool
    build_rpath: str
    d_debug: T.List[str]
    d_import_dirs: T.List[T.Union[str, build.IncludeDirs]]
    d_module_versions: T.List[str]
    d_unittest: bool
    dependencies: T.List[dependencies.Dependency]
    extra_files: T.List[T.Union[File, build.CustomTarget, build.CustomTargetIndex]]
    gnu_symbol_visibility: GNU_SYMBOL_VISIBILITY
    implicit_include_directories: bool
    include_directories: T.List[T.Union[build.IncludeDirs, str]]
    install: bool
    install_dir: T.Optional[str]
    install_mode: FileMode
    install_rpath: str
    install_tag: T.Optional[str]
    install_vala_header: T.Union[None, bool, str]
    install_vala_gir: T.Union[None, bool, str]
    install_vala_vapi: T.Union[None, bool, str]
    link_depends: T.List[T.Union[str, File, build.CustomTarget, build.CustomTargetIndex]]
    link_language: LINK_LANGUAGE
    link_whole: T.List[T.Union[build.BothLibraries, build.SharedLibrary, build.StaticLibrary, build.SharedModule, build.CustomTarget, build.CustomTargetIndex]]
    name_prefix: T.Optional[str]
    name_suffix: T.Optional[str]
    native: MachineChoice
    objects: T.List[T.Union[str, File, build.ExtractedObjects]]
    override_options: T.Dict[coredata.OptionKey, str]
    resources: T.List[str]
    sources: T.List[T.Union[FileOrString, build.GeneratedTypes]]
    vala_header: T.Optional[str]
    vala_vapi: T.Optional[str]
    vala_gir: T.Optional[str]
    c_pch: T.List[str]
    cpp_pch: T.List[str]

    c_args: T.List[str]
    cpp_args: T.List[str]
    cs_args: T.List[str]
    cuda_args: T.List[str]
    cython_args: T.List[str]
    d_args: T.List[str]
    fortran_args: T.List[str]
    java_args: T.List[str]
    objc_args: T.List[str]
    objcpp_args: T.List[str]
    rust_args: T.List[str]
    swift_args: T.List[str]
    vala_args: T.List[str]


class _StaticLibraryMixin(TypedDict):

    pic: T.Optional[bool]
    prelink: bool


class StaticLibrary(_BuildTargetBase, _StaticLibraryMixin):

    rust_crate_type: Literal['lib', 'rlib', 'staticlib']
    link_with: T.List[T.Union[build.BothLibraries, build.SharedLibrary, build.StaticLibrary, build.SharedModule, build.CustomTarget, build.CustomTargetIndex]]


class _SharedModuleMixin(TypedDict):

    vs_module_defs: T.Optional[T.Union[str, File, CustomTarget, build.CustomTargetIndex]]


class SharedModule(_BuildTargetBase, _SharedModuleMixin):

    link_with: T.List[T.Union[build.BothLibraries, build.SharedLibrary, build.StaticLibrary, build.SharedModule, build.CustomTarget, build.CustomTargetIndex, build.Executable]]


class _SharedLibraryMixin(TypedDict):

    version: T.Optional[str]
    soversion: T.Optional[str]
    darwin_versions: T.Tuple[T.Optional[str], T.Optional[str]]


class SharedLibrary(_BuildTargetBase, _SharedModuleMixin, _SharedLibraryMixin):

    rust_crate_type: Literal['lib', 'dylib', 'cdylib', 'proc-macro']
    link_with: T.List[T.Union[build.BothLibraries, build.SharedLibrary, build.StaticLibrary, build.SharedModule, build.CustomTarget, build.CustomTargetIndex]]


class _ExecutableMixin(TypedDict):

    export_dynamic: bool
    gui_app: T.Optional[bool]
    implib: T.Optional[T.Union[str, bool]]
    pie: T.Optional[bool]
    win_subsystem: T.Optional[str]


class Executable(_BuildTargetBase, _ExecutableMixin):

    link_with: T.List[T.Union[build.BothLibraries, build.SharedLibrary, build.StaticLibrary, build.SharedModule, build.CustomTarget, build.CustomTargetIndex]]


class BothLibrary(_BuildTargetBase, _ExecutableMixin, _SharedLibraryMixin, _StaticLibraryMixin):

    rust_crate_type: Literal['lib', 'rlib', 'staticlib', 'dylib', 'cdylib', 'proc-macro']
    link_with: T.List[T.Union[build.BothLibraries, build.SharedLibrary, build.StaticLibrary, build.SharedModule, build.CustomTarget, build.CustomTargetIndex]]


class _JarMixin(TypedDict):

    main_class: str
    java_resources: T.Optional[build.StructuredSources]

class Jar(_BuildTargetBase, _ExecutableMixin, _JarMixin):

    link_with: T.List[build.Jar]


class BuildTarget(BothLibrary, _JarMixin):

    target_type: Literal['executable', 'shared_library', 'static_library', 'shared_module',
                         'both_libraries', 'library', 'jar']
