#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright © 2024 Intel Corporation

from __future__ import annotations
import argparse
import difflib
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('input')
    parser.add_argument('expected')
    args = parser.parse_args()

    with open(args.input, 'r', encoding='utf-8') as f:
        actual = f.read()

    if actual != args.expected:
        for line in difflib.ndiff(actual, args.expected):
            print(line, end='')
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
