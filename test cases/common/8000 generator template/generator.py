#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright © 2024 Intel Corporation

"""Generator script for testing the generator module."""

from __future__ import annotations
import argparse

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('output')
    parser.add_argument('inputs', nargs='+')
    args = parser.parse_args()

    with open(args.output, 'w', encoding='utf-8') as of:
        for i in args.inputs:
            with open(i, 'r', encoding='utf-8') as f:
                of.write(f.read().strip())


if __name__ == "__main__":
    main()
