# Copyright 2013-2019 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations

import functools
import typing as T

from .base import DependencyMethods, SystemDependency, detect_compiler
from .cmake import CMakeDependency
from .factory import factory_methods
from .pkgconfig import PkgConfigDependency

if T.TYPE_CHECKING:
    from ..environment import Environment, MachineChoice
    from .factory import DependencyGenerator


@factory_methods({DependencyMethods.PKGCONFIG, DependencyMethods.CMAKE, DependencyMethods.SYSTEM})
def coarray_factory(env: 'Environment',
                    for_machine: 'MachineChoice',
                    kwargs: T.Dict[str, T.Any],
                    methods: T.List[DependencyMethods]) -> T.List['DependencyGenerator']:
    fcid = detect_compiler('coarray', env, for_machine, 'fortran').get_id()
    candidates: T.List['DependencyGenerator'] = []

    if fcid == 'gcc':
        # OpenCoarrays is the most commonly used method for Fortran Coarray with GCC
        if DependencyMethods.PKGCONFIG in methods:
            for pkg in ['caf-openmpi', 'caf']:
                candidates.append(functools.partial(
                    PkgConfigDependency, pkg, env, kwargs, language='fortran'))

        if DependencyMethods.CMAKE in methods:
            if 'modules' not in kwargs:
                kwargs['modules'] = 'OpenCoarrays::caf_mpi'
            candidates.append(functools.partial(
                CMakeDependency, 'OpenCoarrays', env, kwargs, language='fortran'))

    if DependencyMethods.SYSTEM in methods:
        candidates.append(functools.partial(CoarrayDependency, env, kwargs))

    return candidates


class CoarrayDependency(SystemDependency):
    """
    Coarrays are a Fortran 2008 feature.

    Coarrays are sometimes implemented via external library (GCC+OpenCoarrays),
    while other compilers just build in support (Cray, IBM, Intel, NAG).
    Coarrays may be thought of as a high-level language abstraction of
    low-level MPI calls.
    """
    def __init__(self, environment: 'Environment', kwargs: T.Dict[str, T.Any]) -> None:
        super().__init__('coarray', environment, kwargs, language='fortran')
        kwargs['required'] = False
        kwargs['silent'] = True

        cid = self.get_compiler().get_id()
        if cid == 'gcc':
            # Fallback to single image
            self.compile_args = ['-fcoarray=single']
            self.version = 'single image (fallback)'
            self.is_found = True
        elif cid == 'intel':
            # Coarrays are built into Intel compilers, no external library needed
            self.is_found = True
            self.link_args = ['-coarray=shared']
            self.compile_args = self.link_args
        elif cid == 'intel-cl':
            # Coarrays are built into Intel compilers, no external library needed
            self.is_found = True
            self.compile_args = ['/Qcoarray:shared']
        elif cid == 'nagfor':
            # NAG doesn't require any special arguments for Coarray
            self.is_found = True
