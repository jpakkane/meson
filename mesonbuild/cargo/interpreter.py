# SPDX-License-Identifier: Apache-2.0
# Copyright © 2022-2024 Intel Corporation

"""Interpreter for converting Cargo Toml definitions to Meson AST

There are some notable limits here. We don't even try to convert something with
a build.rs: there's so few limits on what Cargo allows a build.rs (basically
none), and no good way for us to convert them. In that case, an actual meson
port will be required.
"""

from __future__ import annotations
import dataclasses
import glob
import importlib
import itertools
import json
import os
import shutil
import collections
import typing as T

from functools import lru_cache
from pathlib import Path

from . import builder
from . import version
from .cfg import cfg_to_meson
from ..mesonlib import MesonException, Popen_safe, OptionKey
from .. import coredata

if T.TYPE_CHECKING:
    from types import ModuleType

    from . import manifest
    from .. import mparser
    from ..environment import Environment
    from ..coredata import KeyedOptionDictType

# tomllib is present in python 3.11, before that it is a pypi module called tomli,
# we try to import tomllib, then tomli,
# TODO: add a fallback to toml2json?
tomllib: T.Optional[ModuleType] = None
toml2json: T.Optional[str] = None
for t in ['tomllib', 'tomli']:
    try:
        tomllib = importlib.import_module(t)
        break
    except ImportError:
        pass
else:
    # TODO: it would be better to use an Executable here, which could be looked
    # up in the cross file or provided by a wrap. However, that will have to be
    # passed in externally, since we don't have (and I don't think we should),
    # have access to the `Environment` for that in this module.
    toml2json = shutil.which('toml2json')


def load_toml(filename: str) -> T.Dict[object, object]:
    if tomllib:
        with open(filename, 'rb') as f:
            raw = tomllib.load(f)
    else:
        if toml2json is None:
            raise MesonException('Could not find an implementation of tomllib, nor toml2json')

        p, out, err = Popen_safe([toml2json, filename])
        if p.returncode != 0:
            raise MesonException('toml2json failed to decode output\n', err)

        raw = json.loads(out)

    if not isinstance(raw, dict):
        raise MesonException("Cargo.toml isn't a dictionary? How did that happen?")

    return raw


def fixup_meson_varname(name: str) -> str:
    """Fixup a meson variable name

    :param name: The name to fix
    :return: the fixed name
    """
    return name.replace('-', '_')


# Pylance can figure out that these do not, in fact, overlap, but mypy can't
@T.overload
def _fixup_raw_mappings(d: manifest.BuildTarget) -> manifest.FixedBuildTarget: ...  # type: ignore

@T.overload
def _fixup_raw_mappings(d: manifest.LibTarget) -> manifest.FixedLibTarget: ...  # type: ignore

@T.overload
def _fixup_raw_mappings(d: manifest.Dependency) -> manifest.FixedDependency: ...

def _fixup_raw_mappings(d: T.Union[manifest.BuildTarget, manifest.LibTarget, manifest.Dependency, str]
                        ) -> T.Union[manifest.FixedBuildTarget, manifest.FixedLibTarget,
                                     manifest.FixedDependency]:
    """Fixup raw cargo mappings to ones more suitable for python to consume.

    This does the following:
    * replaces any `-` with `_`, cargo likes the former, but python dicts make
      keys with `-` in them awkward to work with
    * Convert Dependndency versions from the cargo format to something meson
      understands

    :param d: The mapping to fix
    :return: the fixed string
    """
    if isinstance(d, str):
        raw = {'version': version.convert(d)}
    else:
        raw = {fixup_meson_varname(k): v for k, v in d.items()}
        if 'version' in raw:
            assert isinstance(raw['version'], str), 'for mypy'
            raw['version'] = version.convert(raw['version'])
    return T.cast('T.Union[manifest.FixedBuildTarget, manifest.FixedLibTarget, manifest.FixedDependency]', raw)


@dataclasses.dataclass
class Package:

    """Representation of a Cargo Package entry, with defaults filled in."""

    name: str
    version: str
    description: T.Optional[str] = None
    resolver: T.Optional[str] = None
    authors: T.List[str] = dataclasses.field(default_factory=list)
    edition: manifest.EDITION = '2015'
    rust_version: T.Optional[str] = None
    documentation: T.Optional[str] = None
    readme: T.Optional[str] = None
    homepage: T.Optional[str] = None
    repository: T.Optional[str] = None
    license: T.Optional[str] = None
    license_file: T.Optional[str] = None
    keywords: T.List[str] = dataclasses.field(default_factory=list)
    categories: T.List[str] = dataclasses.field(default_factory=list)
    workspace: T.Optional[str] = None
    build: T.Optional[str] = None
    links: T.Optional[str] = None
    exclude: T.List[str] = dataclasses.field(default_factory=list)
    include: T.List[str] = dataclasses.field(default_factory=list)
    publish: bool = True
    metadata: T.Dict[str, T.Dict[str, str]] = dataclasses.field(default_factory=dict)
    default_run: T.Optional[str] = None
    autobins: bool = True
    autoexamples: bool = True
    autotests: bool = True
    autobenches: bool = True

    @classmethod
    def from_raw(cls, raw: manifest.Package, workspace: T.Optional[manifest.Workspace]) -> Package:
        """Create a dependency from a raw cargo dictionary"""
        fixed = T.cast('manifest.FixedPackage', {fixup_meson_varname(k): v for k, v in raw.items()})
        for k, v in fixed.items():
            if isinstance(v, dict) and v.get('workspace', False):
                fixed[k] = workspace['package'].get(k, None)
        return cls(**fixed)


@dataclasses.dataclass
class SystemDependency:
    name: T.Optional[str]
    version: T.Optional[T.List[str]] = None
    features: T.Dict[str, T.Dict[str, str]] = dataclasses.field(default_factory=dict)

    @classmethod
    def from_raw(cls, k: str, raw: manifest.DependencyV) -> Dependency:
        """Create a dependency from a raw cargo dictionary"""
        fixed = _fixup_raw_mappings(raw)
        fixed = {
            'name': fixed.get('name', k),
            'version': fixed.get('version'),
            'features': {k: v for k, v in fixed.items() if k not in ['name', 'version']}
        }

        return cls(**fixed)

@dataclasses.dataclass
class Dependency:

    """Representation of a Cargo Dependency Entry."""

    name: dataclasses.InitVar[str]
    version: T.List[str] = dataclasses.field(default_factory=list)
    registry: T.Optional[str] = None
    git: T.Optional[str] = None
    branch: T.Optional[str] = None
    rev: T.Optional[str] = None
    path: T.Optional[str] = None
    optional: bool = False
    package: str = ''
    default_features: bool = True
    features: T.List[str] = dataclasses.field(default_factory=list)
    api: str = dataclasses.field(init=False)

    def __post_init__(self, name: str) -> None:
        self.package = self.package or name
        # Extract wanted API version from version constraints.
        api = set()
        for v in self.version:
            if v.startswith(('>=', '==')):
                api.add(_version_to_api(v[2:].strip()))
            elif v.startswith('='):
                api.add(_version_to_api(v[1:].strip()))
        if not api:
            self.api = '0'
        elif len(api) == 1:
            self.api = list(api)[0]
        else:
            raise MesonException(f'Cannot determine minimum API version from {self.version}.')

    @classmethod
    def from_raw(cls, raw: manifest.DependencyV, name: str, workspace: T.Optional[manifest.Workspace]) -> Dependency:
        """Create a dependency from a raw cargo dictionary"""
        fixed = _fixup_raw_mappings(raw)
        if fixed.get('workspace', False):
            wp_fixed = _fixup_raw_mappings(workspace['dependencies'][name])
            for k, v in wp_fixed.items():
                fixed.setdefault(k, v)
            del fixed['workspace']
        return cls(name, **fixed)


@dataclasses.dataclass
class BuildTarget:

    name: str
    crate_type: T.List[manifest.CRATE_TYPE] = dataclasses.field(default_factory=lambda: ['lib'])
    path: dataclasses.InitVar[T.Optional[str]] = None

    # https://doc.rust-lang.org/cargo/reference/cargo-targets.html#the-test-field
    # True for lib, bin, test
    test: bool = True

    # https://doc.rust-lang.org/cargo/reference/cargo-targets.html#the-doctest-field
    # True for lib
    doctest: bool = False

    # https://doc.rust-lang.org/cargo/reference/cargo-targets.html#the-bench-field
    # True for lib, bin, benchmark
    bench: bool = True

    # https://doc.rust-lang.org/cargo/reference/cargo-targets.html#the-doc-field
    # True for libraries and binaries
    doc: bool = False

    harness: bool = True
    edition: manifest.EDITION = '2015'
    required_features: T.List[str] = dataclasses.field(default_factory=list)
    plugin: bool = False


@dataclasses.dataclass
class Library(BuildTarget):

    """Representation of a Cargo Library Entry."""

    doctest: bool = True
    doc: bool = True
    path: str = os.path.join('src', 'lib.rs')
    proc_macro: bool = False
    crate_type: T.List[manifest.CRATE_TYPE] = dataclasses.field(default_factory=lambda: ['lib'])
    doc_scrape_examples: bool = True


@dataclasses.dataclass
class Binary(BuildTarget):

    """Representation of a Cargo Bin Entry."""

    doc: bool = True


@dataclasses.dataclass
class Test(BuildTarget):

    """Representation of a Cargo Test Entry."""

    bench: bool = True


@dataclasses.dataclass
class Benchmark(BuildTarget):

    """Representation of a Cargo Benchmark Entry."""

    test: bool = True


@dataclasses.dataclass
class Example(BuildTarget):

    """Representation of a Cargo Example Entry."""

    crate_type: T.List[manifest.CRATE_TYPE] = dataclasses.field(default_factory=lambda: ['bin'])


@dataclasses.dataclass
class Manifest:

    """Cargo Manifest definition.

    Most of these values map up to the Cargo Manifest, but with default values
    if not provided.

    Cargo subprojects can contain what Meson wants to treat as multiple,
    interdependent, subprojects.

    :param subdir: the subdirectory that this cargo project is in
    :param path: the path within the cargo subproject.
    """

    package: Package
    dependencies: T.Dict[str, Dependency]
    dev_dependencies: T.Dict[str, Dependency]
    build_dependencies: T.Dict[str, Dependency]
    system_dependencies: T.Dict[str, SystemDependency]
    lib: Library
    bin: T.List[Binary]
    test: T.List[Test]
    bench: T.List[Benchmark]
    example: T.List[Example]
    features: T.Dict[str, T.List[str]]
    target: T.Dict[str, T.Dict[str, Dependency]]
    subdir: str
    path: str = ''

    def __post_init__(self) -> None:
        self.features.setdefault('default', [])


def _convert_manifest(raw_manifest: manifest.Manifest, subdir: str, path: str = '', workspace: T.Optional[manifest.Workspace] = None) -> Manifest:
    # This cast is a bit of a hack to deal with proc-macro
    lib = _fixup_raw_mappings(raw_manifest.get('lib', {}))

    # We need to set the name field if it's not set manually,
    # including if other fields are set in the lib section
    lib.setdefault('name', raw_manifest['package']['name'])

    manifest = Manifest(
        Package.from_raw(raw_manifest['package'], workspace),
        {k: Dependency.from_raw(v, k, workspace) for k, v in raw_manifest.get('dependencies', {}).items()},
        {k: Dependency.from_raw(v, k, workspace) for k, v in raw_manifest.get('dev-dependencies', {}).items()},
        {k: Dependency.from_raw(v, k, workspace) for k, v in raw_manifest.get('build-dependencies', {}).items()},
        {k: SystemDependency.from_raw(k, d) for k, d in raw_manifest['package'].get('metadata', {}).get('system-deps', {}).items()},
        Library(**lib),
        [Binary(**_fixup_raw_mappings(b)) for b in raw_manifest.get('bin', {})],
        [Test(**_fixup_raw_mappings(b)) for b in raw_manifest.get('test', {})],
        [Benchmark(**_fixup_raw_mappings(b)) for b in raw_manifest.get('bench', {})],
        [Example(**_fixup_raw_mappings(b)) for b in raw_manifest.get('example', {})],
        raw_manifest.get('features', {}),
        {k: {k2: Dependency.from_raw(v2, k2, workspace) for k2, v2 in v.get('dependencies', {}).items()}
         for k, v in raw_manifest.get('target', {}).items()},
        subdir,
        path,
    )

    # Optional dependencies are implicitly a feature as well
    for _, dep in _all_dependencies(manifest):
        if dep.optional:
            manifest.features.setdefault(dep.package, [])

    return manifest


_MANIFESTS_CACHE: T.Dict[str, Manifest] = {}

def _load_manifests(subdir: str) -> T.List[Manifest]:
    cached = _MANIFESTS_CACHE.get(subdir)
    if cached:
        return [cached]

    filename = os.path.join(subdir, 'Cargo.toml')
    raw = load_toml(filename)

    manifests: T.List[Manifest] = []

    if 'package' in raw:
        raw_manifest = T.cast('manifest.Manifest', raw)
        manifest = _convert_manifest(raw_manifest, subdir)
        manifests.append(manifest)
        _MANIFESTS_CACHE[subdir] = manifest

    if 'workspace' in raw:
        workspace = T.cast('manifest.Workspace', raw['workspace'])

        # XXX: need to verify that python glob and cargo globbing are the
        # same and probably write  a glob implementation. Blarg
        workspace_path = Path(subdir)
        members = itertools.chain.from_iterable(
            workspace_path.glob(m) for m in workspace['members'])
        if 'exclude' in workspace:
            exclude = [Path(workspace_path, x) for x in workspace['exclude']]
            members = [x for x in members if x not in exclude]

        for m in members:
            filename = os.path.join(m, 'Cargo.toml')
            raw = load_toml(filename)

            raw_manifest = T.cast('manifest.Manifest', raw)
            rel_path = m.relative_to(workspace_path)
            manifest = _convert_manifest(raw_manifest, subdir, str(rel_path), workspace)
            manifests.append(manifest)
            _MANIFESTS_CACHE[os.path.join(subdir, rel_path)] = manifest

    return manifests


def _version_to_api(version: str) -> str:
    # x.y.z -> x
    # 0.x.y -> 0.x
    # 0.0.x -> 0
    vers = version.split('.')
    if int(vers[0]) > 0:
        return vers[0]
    elif len(vers) >= 2 and int(vers[1]) > 0:
        return f'0.{vers[1]}'
    return '0'


def _dependency_name(package_name: str, api: str) -> str:
    basename = package_name[:-3] if package_name.endswith('-rs') else package_name
    return f'{basename}-{api}-rs'


def _dependency_varname(package_name: str) -> str:
    return f'{fixup_meson_varname(package_name)}_dep'


def _package_name(cargo: Manifest) -> str:
    return _dependency_name(cargo.package.name, _version_to_api(cargo.package.version))


_OPTION_NAME_PREFIX = 'feature-'


def _option_name(feature: str) -> str:
    # Add a prefix to avoid collision with Meson reserved options (e.g. "debug")
    return _OPTION_NAME_PREFIX + feature


def _options_varname(depname: str) -> str:
    return f'{fixup_meson_varname(depname)}_options'


def _extra_args_varname() -> str:
    return 'extra_args'


def _extra_deps_varname() -> str:
    return 'extra_deps'


def _create_project(cargo: Manifest, build: builder.Builder) -> T.List[mparser.BaseNode]:
    """Create a function call

    :param cargo: The Manifest to generate from
    :param build: The AST builder
    :return: a list nodes
    """
    args: T.List[mparser.BaseNode] = []
    args.extend([
        build.string(cargo.package.name),
        build.string('rust'),
    ])
    kwargs: T.Dict[str, mparser.BaseNode] = {
        'version': build.string(cargo.package.version),
        # Always assume that the generated meson is using the latest features
        # This will warn when when we generate deprecated code, which is helpful
        # for the upkeep of the module
        'meson_version': build.string(f'>= {coredata.stable_version}'),
        'default_options': build.array([build.string(f'rust_std={cargo.package.edition}')]),
    }
    if cargo.package.license:
        kwargs['license'] = build.string(cargo.package.license)
    elif cargo.package.license_file:
        kwargs['license_files'] = build.string(cargo.package.license_file)

    return [build.function('project', args, kwargs)]


def _all_dependencies(cargo: Manifest) -> T.Iterable[T.Tuple[str, Dependency]]:
    yield from cargo.dependencies.items()
    yield from cargo.dev_dependencies.items()
    yield from cargo.build_dependencies.items()
    for deps in cargo.target.values():
        yield from deps.items()


def _process_feature(cargo: Manifest, feature: str) -> T.Tuple[T.Set[str], T.Dict[str, T.Set[str]], T.Set[str]]:
    # Set of features that must also be enabled if this feature is enabled.
    features: T.Set[str] = set()
    # Map dependency name to a set of features that must also be enabled on that
    # dependency if this feature is enabled.
    dep_features: T.Dict[str, T.Set[str]] = collections.defaultdict(set)
    # Set of dependencies that are required if this feature is enabled.
    required_deps: T.Set[str] = set()
    # Set of features that must be processed recursively.
    to_process: T.Set[str] = {feature}
    while to_process:
        f = to_process.pop()
        if '/' in f:
            dep, dep_f = f.split('/', 1)
            if dep[-1] == '?':
                dep = dep[:-1]
            else:
                required_deps.add(dep)
            dep_features[dep].add(dep_f)
        elif f.startswith('dep:'):
            required_deps.add(f[4:])
        elif f not in features:
            features.add(f)
            to_process.update(cargo.features.get(f, []))
            # A feature can also be a dependency
            if f in cargo.dependencies:
                required_deps.add(f)
    return features, dep_features, required_deps


def _create_features(cargo: Manifest, build: builder.Builder) -> T.List[mparser.BaseNode]:
    # https://doc.rust-lang.org/cargo/reference/features.html#the-features-section

    # Declare a dict that map enabled features to true. One for current project
    # and one per dependency.
    ast: T.List[mparser.BaseNode] = []
    ast.append(build.assign(build.dict({}), 'features'))
    for depname, _ in _all_dependencies(cargo):
        ast.append(build.assign(build.dict({}), _options_varname(depname)))

    # Declare a dict that map required dependencies to true
    ast.append(build.assign(build.dict({}), 'required_deps'))

    for feature in cargo.features:
        # if get_option(feature)
        #   required_deps += {'dep': true, ...}
        #   features += {'foo': true, ...}
        #   xxx_options += {'feature-foo': true, ...}
        #   ...
        # endif
        features, dep_features, required_deps = _process_feature(cargo, feature)
        lines: T.List[mparser.BaseNode] = [
            build.plusassign(
                build.dict({build.string(d): build.bool(True) for d in required_deps}),
                'required_deps'),
            build.plusassign(
                build.dict({build.string(f): build.bool(True) for f in features}),
                'features'),
        ]
        for depname, enabled_features in dep_features.items():
            lines.append(build.plusassign(
                build.dict({build.string(_option_name(f)): build.bool(True) for f in enabled_features}),
                _options_varname(depname)))

        ast.append(build.if_(build.function('get_option', [build.string(_option_name(feature))]), build.block(lines)))

    ast.append(build.function('message', [
        build.string('Enabled features:'),
        build.method('keys', build.identifier('features'))],
    ))

    return ast


def _create_cfg(cargo: Manifest, build: builder.Builder) -> T.List[mparser.BaseNode]:
    # Allow Cargo subprojects to add extra Rust args in meson/meson.build file.
    # This is used to replace build.rs logic.
    # cargo_info = {'CARGO_...': 'value', ...}
    # extra_args = []
    # extra_deps = []
    # fs = import('fs')
    # has_meson_build = fs.is_dir('meson')
    # if has_meson_build
    #  subdir('meson')
    # endif
    # cfg = rust.cargo_cfg(features, skip_build_rs: has_meson_build, info: cargo_info)
    version_arr = cargo.package.version.split('.')
    version_arr += ['' * (4 - len(version_arr))]
    has_build_deps_message = None
    if cargo.build_dependencies:
        has_build_deps_message = build.block([
            build.function('warning', [
                build.string('Cannot use build.rs with build-dependencies. It should be ported manually in meson/meson.build'),
            ]),
        ])
    return [
        build.assign(build.dict({
            # https://doc.rust-lang.org/cargo/reference/environment-variables.html
            build.string('CARGO_MANIFEST_DIR'): build.string(os.path.join(cargo.subdir, cargo.path)),
            build.string('CARGO_PKG_VERSION'): build.string(cargo.package.version),
            build.string('CARGO_PKG_VERSION_MAJOR'): build.string(version_arr[0]),
            build.string('CARGO_PKG_VERSION_MINOR'): build.string(version_arr[1]),
            build.string('CARGO_PKG_VERSION_PATCH'): build.string(version_arr[2]),
            build.string('CARGO_PKG_VERSION_PRE'): build.string(version_arr[3]),
            build.string('CARGO_PKG_AUTHORS'): build.string(','.join(cargo.package.authors)),
            build.string('CARGO_PKG_NAME'): build.string(cargo.package.name),
            build.string('CARGO_PKG_DESCRIPTION'): build.string(cargo.package.description or ''),
            build.string('CARGO_PKG_HOMEPAGE'): build.string(cargo.package.homepage or ''),
            build.string('CARGO_PKG_REPOSITORY'): build.string(cargo.package.repository or ''),
            build.string('CARGO_PKG_LICENSE'): build.string(cargo.package.license or ''),
            build.string('CARGO_PKG_LICENSE_FILE'): build.string(cargo.package.license_file or ''),
            build.string('CARGO_PKG_RUST_VERSION'): build.string(cargo.package.rust_version or ''),
            build.string('CARGO_PKG_README'): build.string(cargo.package.readme or ''),
            }),
            'cargo_info'),
        build.assign(build.array([]), _extra_args_varname()),
        build.assign(build.array([]), _extra_deps_varname()),
        build.assign(build.function('import', [build.string('fs')]), 'fs'),
        build.assign(build.method('is_dir', build.identifier('fs'), [build.string('meson')]), 'has_meson_build'),
        build.if_(build.identifier('has_meson_build'),
                  build.block([build.function('subdir', [build.string('meson')])]),
                  has_build_deps_message),
        build.assign(
            build.method(
                'cargo_cfg',
                build.identifier('rust'),
                [build.method('keys', build.identifier('features'))],
                {'skip_build_rs': build.identifier('has_meson_build'),
                 'info': build.identifier('cargo_info')},
            ),
            'cfg'),
    ]


def _create_dependency(name: str, dep: Dependency, build: builder.Builder) -> T.List[mparser.BaseNode]:
    ast: T.List[mparser.BaseNode] = []
    # xxx_options += {'feature-default': true, ...}
    extra_options: T.Dict[mparser.BaseNode, mparser.BaseNode] = {
        build.string(_option_name('default')): build.bool(dep.default_features),
    }
    for f in dep.features:
        extra_options[build.string(_option_name(f))] = build.bool(True)
    ast.append(build.plusassign(build.dict(extra_options), _options_varname(name)))

    kw = {
        'version': build.array([build.string(s) for s in dep.version]),
        'default_options': build.identifier(_options_varname(name)),
    }
    if dep.optional:
        kw['required'] = build.or_(
            build.method('get', build.identifier('required_deps'), [build.string(name), build.bool(False)]),
            build.method('get', build.identifier('features'), [build.string(name), build.bool(False)]),
        )

    # If dependency name does not match the package name, we have to rename the
    # crate name to the dependency name. Yes, that makes 3 different names for
    # the same dependency, good job cargo! For example:
    # - package name: cairo-sys-rs
    # - crate name: cairo-sys
    # - dependency name: ffi
    # rust_dependency_map += {xxx_dep.get_variable('crate-name'): 'name'}
    rust_dependency_map_ast = []
    if name != dep.package:
        rust_dependency_map_ast.append(
            build.plusassign(build.dict({
                build.method('get_variable', build.identifier(_dependency_varname(dep.package)), [build.string('crate-name')]): build.string(name),
            }), 'rust_dependency_map'))

    # Lookup for this dependency with the features we want in default_options kwarg.
    #
    # However, this subproject could have been previously configured with a
    # different set of features. Cargo collects the set of features globally
    # but Meson can only use features enabled by the first call that triggered
    # the configuration of that subproject.
    #
    # Verify all features that we need are actually enabled for that dependency,
    # otherwise abort with an error message. The user has to set the corresponding
    # option manually with -Dxxx-rs:feature-yyy=true, or the main project can do
    # that in its project(..., default_options: ['xxx-rs:feature-yyy=true']).
    ast.extend([
        # xxx_dep = dependency('xxx', version : ..., default_options : xxx_options)
        build.assign(
            build.function(
                'dependency',
                [build.string(_dependency_name(dep.package, dep.api))],
                kw,
            ),
            _dependency_varname(dep.package),
        ),
        # if xxx_dep.found()
        build.if_(build.method('found', build.identifier(_dependency_varname(dep.package))), build.block([
            # actual_features = xxx_dep.get_variable('features', default_value : '').split(',')
            build.assign(
                build.method(
                    'split',
                    build.method(
                        'get_variable',
                        build.identifier(_dependency_varname(dep.package)),
                        [build.string('features')],
                        {'default_value': build.string('')}
                    ),
                    [build.string(',')],
                ),
                'actual_features'
            ),
            # needed_features = []
            # foreach f, _ : xxx_options
            #   needed_features += f.substring(8)
            # endforeach
            build.assign(build.array([]), 'needed_features'),
            build.foreach(['f', 'enabled'], build.identifier(_options_varname(name)), build.block([
                build.if_(build.identifier('enabled'), build.block([
                    build.plusassign(
                        build.method('substring', build.identifier('f'), [build.number(len(_OPTION_NAME_PREFIX))]),
                        'needed_features'),
                ])),
            ])),
            # foreach f : needed_features
            #   if f not in actual_features
            #     error()
            #   endif
            # endforeach
            build.foreach(['f'], build.identifier('needed_features'), build.block([
                build.if_(build.not_in(build.identifier('f'), build.identifier('actual_features')), build.block([
                    build.function('error', [
                        build.string('Dependency'),
                        build.string(_dependency_name(dep.package, dep.api)),
                        build.string('previously configured with features'),
                        build.identifier('actual_features'),
                        build.string('but need'),
                        build.identifier('needed_features'),
                    ])
                ]))
            ])),
            *rust_dependency_map_ast,
        ])),
    ])

    return ast


def _create_dependencies(cargo: Manifest, build: builder.Builder) -> T.List[mparser.BaseNode]:
    ast: T.List[mparser.BaseNode] = [
        build.assign(build.dict({}), 'rust_dependency_map'),
    ]
    for condition, dependencies in cargo.target.items():
        ifblock: T.List[mparser.BaseNode] = []
        elseblock: T.List[mparser.BaseNode] = []
        notfound = build.function('dependency', [build.string('')], {'required': build.bool(False)})
        for name, dep in dependencies.items():
            ifblock += _create_dependency(name, dep, build)
            elseblock.append(build.assign(notfound, _dependency_varname(dep.package)))
        ast.append(build.if_(cfg_to_meson(condition, build), build.block(ifblock), build.block(elseblock)))
    for name, dep in cargo.dependencies.items():
        ast += _create_dependency(name, dep, build)
    for name, dep in cargo.system_dependencies.items():
        kw = {}
        if dep.version is not None:
            kw['version'] = build.array([build.string(s) for s in dep.version])
        ast.extend([
            build.assign(
                build.function(
                    'dependency',
                    [build.string(dep.name)],
                    kw,
                ),
                f'{fixup_meson_varname(name)}_system_dep',
            ),
        ])
    return ast


def _create_lib(cargo: Manifest, build: builder.Builder, crate_type: manifest.CRATE_TYPE) -> T.List[mparser.BaseNode]:
    dependencies: T.List[mparser.BaseNode] = []
    deps_i = [cargo.dependencies.items()]
    deps_i += [deps.items() for deps in cargo.target.values()]
    for name, dep in itertools.chain.from_iterable(deps_i):
        dependencies.append(build.identifier(_dependency_varname(dep.package)))
    for name, dep in cargo.system_dependencies.items():
        dependencies.append(build.identifier(f'{fixup_meson_varname(name)}_system_dep'))

    rust_args: T.List[mparser.BaseNode] = [
        build.identifier('features_args'),
        build.identifier(_extra_args_varname())
    ]

    dependencies.append(build.identifier(_extra_deps_varname()))

    crate_name = cargo.lib.name or cargo.package.name
    posargs: T.List[mparser.BaseNode] = [
        build.string(fixup_meson_varname(crate_name)),
        build.string(cargo.lib.path),
    ]

    kwargs: T.Dict[str, mparser.BaseNode] = {
        'dependencies': build.array(dependencies),
        'rust_dependency_map': build.identifier('rust_dependency_map'),
        'rust_args': build.array(rust_args),
    }

    lib: mparser.BaseNode
    if cargo.lib.proc_macro or crate_type == 'proc-macro':
        lib = build.method('proc_macro', build.identifier('rust'), posargs, kwargs)
    else:
        if crate_type in {'lib', 'rlib', 'staticlib'}:
            target_type = 'static_library'
        elif crate_type in {'dylib', 'cdylib'}:
            target_type = 'shared_library'
        else:
            raise MesonException(f'Unsupported crate type {crate_type}')
        if crate_type in {'staticlib', 'cdylib'}:
            kwargs['rust_abi'] = build.string('c')
        lib = build.function(target_type, posargs, kwargs)

    # features_args = []
    # foreach f, _ : features
    #   features_args += ['--cfg', 'feature="' + f + '"']
    # endforeach
    # lib = xxx_library()
    # dep = declare_dependency()
    # meson.override_dependency()
    return [
        build.assign(build.array([]), 'features_args'),
        build.foreach(['f', '_'], build.identifier('features'), build.block([
            build.plusassign(
                build.array([
                    build.string('--cfg'),
                    build.plus(build.string('feature="'), build.plus(build.identifier('f'), build.string('"'))),
                ]),
                'features_args')
            ])
        ),
        build.assign(lib, 'lib'),
        build.assign(
            build.function(
                'declare_dependency',
                kw={
                    'link_with': build.identifier('lib'),
                    'variables': build.dict({
                        build.string('features'): build.method('join', build.string(','), [build.method('keys', build.identifier('features'))]),
                        build.string('crate-name'): build.string(crate_name),
                    })
                },
            ),
            'dep'
        ),
        build.method(
            'override_dependency',
            build.identifier('meson'),
            [
                build.string(_package_name(cargo)),
                build.identifier('dep'),
            ],
        ),
    ]


def _create_package(cargo: Manifest, subp_name: str, env: Environment) -> T.Tuple[mparser.CodeBlockNode, KeyedOptionDictType]:
    filename = os.path.join(cargo.subdir, cargo.path, 'Cargo.toml')
    build = builder.Builder(filename)

    # Generate project options
    options: T.Dict[OptionKey, coredata.UserOption] = {}
    for feature in cargo.features:
        key = OptionKey(_option_name(feature), subproject=subp_name)
        enabled = feature == 'default'
        options[key] = coredata.UserBooleanOption(f'Cargo {feature} feature', enabled)

    ast = _create_project(cargo, build)
    ast += [build.assign(build.function('import', [build.string('rust')]), 'rust')]
    ast += _create_features(cargo, build)
    ast += _create_cfg(cargo, build)
    ast += _create_dependencies(cargo, build)

    # Libs are always auto-discovered and there's no other way to handle them,
    # which is unfortunate for reproducability
    if os.path.exists(os.path.join(env.source_dir, cargo.subdir, cargo.path, cargo.lib.path)):
        # FIXME: We can only build one library because Meson would otherwise
        # complain that multiple targets have the same name. Ideally a single
        # library() call should be able to build multiple crate types.
        # For now, pick one in our preference order.
        for crate_type in {'rlib', 'lib', 'dylib', 'staticlib', 'cdylib'}:
            if crate_type in cargo.lib.crate_type:
                break
        else:
            crate_type = cargo.lib.crate_type[0]
        ast.extend(_create_lib(cargo, build, crate_type))

    return build.block(ast), options


def _create_workspace(manifests: T.List[Manifest], subp_name: str, subdir: str, env: Environment) -> T.Tuple[mparser.CodeBlockNode, KeyedOptionDictType]:
    filename = os.path.join(subdir, 'Cargo.toml')
    build = builder.Builder(filename)

    options: T.Dict[OptionKey, coredata.UserOption] = {}

    # project('foo')
    # dependency('member', required: get_option('member'))
    # ...
    ast = [build.function('project', [build.string(subp_name)], {})]
    for cargo in manifests:
        depname = _package_name(cargo)
        ast.append(build.function('dependency', [build.string(depname)], {
            'required': build.function('get_option', [build.string(cargo.package.name)]),
            'allow_fallback': build.bool(True),
        }))
        key = OptionKey(cargo.package.name, subproject=subp_name)
        options[key] = coredata.UserFeatureOption(f'Build {depname}', 'auto')

    return build.block(ast), options


def interpret(subp_name: str, subdir: str, env: Environment) -> T.Tuple[mparser.CodeBlockNode, KeyedOptionDictType]:
    manifests = _load_manifests(os.path.join(env.source_dir, subdir))
    if len(manifests) == 1:
        return _create_package(manifests[0], subp_name, env)
    return _create_workspace(manifests, subp_name, subdir, env)


@dataclasses.dataclass
class CargoPackageDefinition:
    """ A cargo package definition used by the wrap system."""

    package: str
    version: T.List[str] = dataclasses.field(default_factory=list)
    git: T.Optional[str] = None
    revision: T.Optional[str] = None
    path: T.Optional[str] = None


def dependencies(source_dir: str) -> T.Dict[str, CargoPackageDefinition]:
    deps: T.Dict[str, Dependency] = {}
    manifests = _load_manifests(source_dir)
    for cargo in manifests:
        for _, dep in _all_dependencies(cargo):
            depname = _dependency_name(dep.package, dep.api)
            deps[depname] = CargoPackageDefinition(
                dep.package,
                dep.version,
                #dep.git, dep.rev or dep.branch,
            )
        deps[_package_name(cargo)] = CargoPackageDefinition(
            cargo.package.name,
            path=os.path.join(cargo.subdir, cargo.path))
    return deps
