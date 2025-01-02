# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Marco Rebhan <me@dblsaiko.net>

from __future__ import annotations

"""
Helper script to merge two plist files.
"""

import plistlib
import typing as T


def run(args: T.List[str]) -> int:
    if len(args) < 1:
        return 1

    [out, *inputs] = args

    data: T.Any = {}

    for path in inputs:
        try:
            fp = open(path, 'rb')
        except OSError as e:
            print(f'merge-plist: cannot open \'{path}\': {e.strerror}')
            return 1

        with fp:
            try:
                new_data = plistlib.load(fp)
            except plistlib.InvalidFileException as e:
                print(f'merge-plist: cannot parse \'{path}\': {e}')
                return 1
            except OSError as e:
                print(f'merge-plist: cannot read \'{path}\': {e}')
                return 1

            data = merge(data, new_data)

    try:
        ofp = open(out, 'wb')
    except OSError as e:
        print(f'merge-plist: cannot create \'{out}\': {e.strerror}')
        return 1

    with ofp:
        try:
            plistlib.dump(data, ofp)
        except OSError as e:
            print(f'merge-plist: cannot write \'{path}\': {e}')
            return 1

    return 0


def merge(prev: T.Any, next: T.Any) -> T.Any:
    if isinstance(prev, dict) and isinstance(next, dict):
        out = prev.copy()

        for k, v in next.items():
            if k in out:
                out[k] = merge(out[k], v)
            else:
                out[k] = v
        return out
    elif isinstance(prev, list) and isinstance(next, list):
        return prev + next
    else:
        return next
