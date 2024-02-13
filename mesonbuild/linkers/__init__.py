# SPDX-License-Identifier: Apache-2.0
# Copyright 2012-2021 The Meson development team

from __future__ import annotations

from .base import ArLikeLinker, RSPFileSyntax
from .detect import defaults, guess_nix_linker, guess_win_linker

__all__ = [
    # base.py
    'ArLikeLinker',
    'RSPFileSyntax',

    # detect.py
    'defaults',
    'guess_win_linker',
    'guess_nix_linker',
]
