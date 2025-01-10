# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

"""Helper script to delete files

On Windows we cannot expect coreutils to be available in PATH,
and cmd.exe has lots of shortcomings.
"""

from pathlib import Path
import typing as T


def run(args: T.List[str]) -> int:
    try:
        # We do not pass missing_ok = True to unlink() for compat with Python 3.7
        Path(args[0]).unlink()
    except FileNotFoundError:
        return 0
    except Exception:
        return 1
    return 0
