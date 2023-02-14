# SPDX-License-Identifer: Apache-2.0
# Copyright © 2021 Intel Corporation

"""Helper script to copy files at build time.

This is easier than trying to detect whether to use copy, cp, or something else.
"""

from __future__ import annotations
import shutil
import typing as T


def run(args: T.List[str]) -> int:
    try:
        shutil.copy2(args[0], args[1])
    except Exception:
        return 1
    return 0
