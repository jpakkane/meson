#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright © 2024 Intel Corporation

from __future__ import annotations
import argparse
import typing as T

if T.TYPE_CHECKING:
    class Arguments(T.Protocol):

        input: str
        output: str
        replacements: T.List[T.Tuple[str, str]]


def process(txt: str, replacements: T.List[T.Tuple[str, str]]) -> str:
    for k, v in replacements:
        txt = txt.replace(k, v)
    return txt


def split_arg(arg: str) -> T.Tuple[str, str]:
    args = arg.split('=', maxsplit=1)
    assert len(args) == 2, 'Did not get the right number of args?'
    return T.cast('T.Tuple[str, str]', tuple(args))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('--replace', action='append', required=True, dest='replacements', type=split_arg)
    args = T.cast('Arguments', parser.parse_args())

    with open(args.input, 'r', encoding='utf-8') as f:
        content = f.read()

    content = process(content, args.replacements)

    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == "__main__":
    main()
