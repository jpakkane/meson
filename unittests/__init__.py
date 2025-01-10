import os

import mesonbuild.compilers
from mesonbuild.mesonlib import setup_vsenv

def unset_envs():
    # For unit tests we must fully control all command lines
    # so that there are no unexpected changes coming from the
    # environment, for example when doing a package build.
    varnames = ['CPPFLAGS', 'LDFLAGS'] + list(mesonbuild.compilers.compilers.CFLAGS_MAPPING.values())
    for v in varnames:
        if v in os.environ:
            del os.environ[v]

def set_envs():
    os.environ.setdefault('MESON_UNIT_TEST_BACKEND', 'ninja')

def init():
    setup_vsenv()
    unset_envs()
    set_envs()

init()
