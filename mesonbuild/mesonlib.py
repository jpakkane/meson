# SPDX-license-identifier: Apache-2.0
# Copyright 2012-2021 The Meson development team
# Copyright © 2021-2023 Intel Corporation
#
# pylint: skip-file

"""Helper functions and classes."""

from __future__ import annotations

import os

from .utils.core import *
from .utils.universal import *
from .utils.vsenv import *

# Here we import either the posix implementations, the windows implementations,
# or a generic no-op implementation
if os.name == 'posix':
    from .utils.posix import *
elif os.name == 'nt':
    from .utils.win32 import *
else:
    from .utils.platform import *
