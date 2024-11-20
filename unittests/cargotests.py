# SPDX-License-Identifier: Apache-2.0
# Copyright © 2022-2023 Intel Corporation

from __future__ import annotations
import unittest
import os
import tempfile
import textwrap
import typing as T

from mesonbuild.cargo import builder, cfg, load_wraps
from mesonbuild.cargo.cfg import TokenType
from mesonbuild.cargo.version import convert


class CargoVersionTest(unittest.TestCase):

    def test_cargo_to_meson(self) -> None:
        cases: T.List[T.Tuple[str, T.List[str]]] = [
            # Basic requirements
            ('>= 1', ['>= 1']),
            ('> 1', ['> 1']),
            ('= 1', ['= 1']),
            ('< 1', ['< 1']),
            ('<= 1', ['<= 1']),

            # tilde tests
            ('~1', ['>= 1', '< 2']),
            ('~1.1', ['>= 1.1', '< 1.2']),
            ('~1.1.2', ['>= 1.1.2', '< 1.2.0']),

            # Wildcards
            ('*', []),
            ('1.*', ['>= 1', '< 2']),
            ('2.3.*', ['>= 2.3', '< 2.4']),

            # Unqualified
            ('2', ['>= 2', '< 3']),
            ('2.4', ['>= 2.4', '< 3']),
            ('2.4.5', ['>= 2.4.5', '< 3']),
            ('0.0.0', ['< 1']),
            ('0.0', ['< 1']),
            ('0', ['< 1']),
            ('0.0.5', ['>= 0.0.5', '< 0.0.6']),
            ('0.5.0', ['>= 0.5.0', '< 0.6']),
            ('0.5', ['>= 0.5', '< 0.6']),
            ('1.0.45', ['>= 1.0.45', '< 2']),

            # Caret (Which is the same as unqualified)
            ('^2', ['>= 2', '< 3']),
            ('^2.4', ['>= 2.4', '< 3']),
            ('^2.4.5', ['>= 2.4.5', '< 3']),
            ('^0.0.0', ['< 1']),
            ('^0.0', ['< 1']),
            ('^0', ['< 1']),
            ('^0.0.5', ['>= 0.0.5', '< 0.0.6']),
            ('^0.5.0', ['>= 0.5.0', '< 0.6']),
            ('^0.5', ['>= 0.5', '< 0.6']),

            # Multiple requirements
            ('>= 1.2.3, < 1.4.7', ['>= 1.2.3', '< 1.4.7']),
        ]

        for (data, expected) in cases:
            with self.subTest():
                self.assertListEqual(convert(data), expected)


class CargoCfgTest(unittest.TestCase):

    def test_lex(self) -> None:
        cases: T.List[T.Tuple[str, T.List[T.Tuple[TokenType, T.Optional[str]]]]] = [
            ('"unix"', [(TokenType.STRING, 'unix')]),
            ('unix', [(TokenType.IDENTIFIER, 'unix')]),
            ('not(unix)', [
                (TokenType.NOT, None),
                (TokenType.LPAREN, None),
                (TokenType.IDENTIFIER, 'unix'),
                (TokenType.RPAREN, None),
            ]),
            ('any(unix, windows)', [
                (TokenType.ANY, None),
                (TokenType.LPAREN, None),
                (TokenType.IDENTIFIER, 'unix'),
                (TokenType.COMMA, None),
                (TokenType.IDENTIFIER, 'windows'),
                (TokenType.RPAREN, None),
            ]),
            ('target_arch = "x86_64"', [
                (TokenType.IDENTIFIER, 'target_arch'),
                (TokenType.EQUAL, None),
                (TokenType.STRING, 'x86_64'),
            ]),
            ('all(target_arch = "x86_64", unix)', [
                (TokenType.ALL, None),
                (TokenType.LPAREN, None),
                (TokenType.IDENTIFIER, 'target_arch'),
                (TokenType.EQUAL, None),
                (TokenType.STRING, 'x86_64'),
                (TokenType.COMMA, None),
                (TokenType.IDENTIFIER, 'unix'),
                (TokenType.RPAREN, None),
            ]),
            ('cfg(windows)', [
                (TokenType.CFG, None),
                (TokenType.LPAREN, None),
                (TokenType.IDENTIFIER, 'windows'),
                (TokenType.RPAREN, None),
            ]),
        ]
        for data, expected in cases:
            with self.subTest():
                self.assertListEqual(list(cfg.lexer(data)), expected)

    def test_parse(self) -> None:
        cases = [
            ('target_os = "windows"', cfg.Equal(cfg.Identifier("target_os"), cfg.String("windows"))),
            ('target_arch = "x86"', cfg.Equal(cfg.Identifier("target_arch"), cfg.String("x86"))),
            ('target_family = "unix"', cfg.Equal(cfg.Identifier("target_family"), cfg.String("unix"))),
            ('any(target_arch = "x86", target_arch = "x86_64")',
                cfg.Any(
                    [
                        cfg.Equal(cfg.Identifier("target_arch"), cfg.String("x86")),
                        cfg.Equal(cfg.Identifier("target_arch"), cfg.String("x86_64")),
                    ])),
            ('all(target_arch = "x86", target_os = "linux")',
                cfg.All(
                    [
                        cfg.Equal(cfg.Identifier("target_arch"), cfg.String("x86")),
                        cfg.Equal(cfg.Identifier("target_os"), cfg.String("linux")),
                    ])),
            ('not(all(target_arch = "x86", target_os = "linux"))',
                cfg.Not(
                    cfg.All(
                        [
                            cfg.Equal(cfg.Identifier("target_arch"), cfg.String("x86")),
                            cfg.Equal(cfg.Identifier("target_os"), cfg.String("linux")),
                        ]))),
            ('cfg(all(any(target_os = "android", target_os = "linux"), any(custom_cfg)))',
                cfg.All([
                    cfg.Any([
                        cfg.Equal(cfg.Identifier("target_os"), cfg.String("android")),
                        cfg.Equal(cfg.Identifier("target_os"), cfg.String("linux")),
                    ]),
                    cfg.Any([
                        cfg.Identifier("custom_cfg"),
                    ]),
                ])),
        ]
        for data, expected in cases:
            with self.subTest():
                self.assertEqual(cfg.parse(iter(cfg.lexer(data))), expected)

    def test_eval_ir(self) -> None:
        d = {
            'target_os': 'unix',
            'unix': '',
        }
        cases = [
            ('target_os = "windows"', False),
            ('target_os = "unix"', True),
            ('doesnotexist = "unix"', False),
            ('not(target_os = "windows")', True),
            ('any(target_os = "windows", target_arch = "x86_64")', False),
            ('any(target_os = "windows", target_os = "unix")', True),
            ('all(target_os = "windows", target_os = "unix")', False),
            ('all(not(target_os = "windows"), target_os = "unix")', True),
            ('any(unix, windows)', True),
            ('all()', True),
            ('any()', False),
            ('cfg(unix)', True),
            ('cfg(windows)', False),
        ]
        for data, expected in cases:
            with self.subTest():
                value = cfg.eval_cfg(data, d)
                self.assertEqual(value, expected)

class CargoLockTest(unittest.TestCase):
    def test_cargo_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, 'Cargo.lock'), 'w', encoding='utf-8') as f:
                f.write(textwrap.dedent('''\
                    version = 3
                    [[package]]
                    name = "foo"
                    version = "0.1"
                    source = "registry+https://github.com/rust-lang/crates.io-index"
                    checksum = "8a30b2e23b9e17a9f90641c7ab1549cd9b44f296d3ccbf309d2863cfe398a0cb"
                    [[package]]
                    name = "bar"
                    version = "0.1"
                    source = "git+https://github.com/gtk-rs/gtk-rs-core?branch=0.19#23c5599424cc75ec66618891c915d9f490f6e4c2"
                    '''))
            wraps = load_wraps(tmpdir, 'subprojects')
            self.assertEqual(len(wraps), 2)
            self.assertEqual(wraps[0].name, 'foo-0.1-rs')
            self.assertEqual(wraps[0].directory, 'foo-0.1')
            self.assertEqual(wraps[0].type, 'file')
            self.assertEqual(wraps[0].get('method'), 'cargo')
            self.assertEqual(wraps[0].get('source_url'), 'https://crates.io/api/v1/crates/foo/0.1/download')
            self.assertEqual(wraps[0].get('source_hash'), '8a30b2e23b9e17a9f90641c7ab1549cd9b44f296d3ccbf309d2863cfe398a0cb')
            self.assertEqual(wraps[1].name, 'bar-0.1-rs')
            self.assertEqual(wraps[1].directory, 'bar')
            self.assertEqual(wraps[1].type, 'git')
            self.assertEqual(wraps[1].get('method'), 'cargo')
            self.assertEqual(wraps[1].get('url'), 'https://github.com/gtk-rs/gtk-rs-core')
            self.assertEqual(wraps[1].get('revision'), '23c5599424cc75ec66618891c915d9f490f6e4c2')
