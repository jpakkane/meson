#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2014 Jussi Pakkanen

import typing as T
from pathlib import Path
import sys
import re
import argparse


class Token:
    def __init__(self, tid: str, value: str):
        self.tid = tid
        self.value = value
        self.lineno = 0
        self.colno = 0

class Statement:
    def __init__(self, name: str, args: list):
        self.name = name.lower()
        self.args = args

class Lexer:
    def __init__(self) -> None:
        self.token_specification = [
            # Need to be sorted longest to shortest.
            ('ignore', re.compile(r'[ \t]')),
            ('string', re.compile(r'"([^\\]|(\\.))*?"', re.M | re.S)),
            ('varexp', re.compile(r'\${[-_0-9a-z/A-Z.]+}')),
            ('id', re.compile('''[,-><%${}=+_0-9a-z/A-Z|@.*']+''')),
            ('eol', re.compile(r'\n')),
            ('comment', re.compile(r'#.*')),
            ('lparen', re.compile(r'\(')),
            ('rparen', re.compile(r'\)')),
        ]

    def lex(self, code: str, debuginfo_path: Path) -> T.Iterator[Token]:
        lineno = 1
        line_start = 0
        loc = 0
        col = 0
        while loc < len(code):
            matched = False
            for (tid, reg) in self.token_specification:
                mo = reg.match(code, loc)
                if mo:
                    col = mo.start() - line_start
                    matched = True
                    loc = mo.end()
                    match_text = mo.group()
                    if tid == 'ignore':
                        continue
                    if tid == 'comment':
                        yield(Token('comment', match_text))
                    elif tid == 'lparen':
                        yield(Token('lparen', '('))
                    elif tid == 'rparen':
                        yield(Token('rparen', ')'))
                    elif tid == 'string':
                        yield(Token('string',
                            match_text[1:-1]
                                .replace('\\\n', '')
                                .replace('\'', '\\\'')))
                    elif tid == 'id':
                        yield(Token('id', match_text.replace('\'', '\\\'')))
                    elif tid == 'eol':
                        # yield('eol')
                        lineno += 1
                        col = 1
                        line_start = mo.end()
                    elif tid == 'varexp':
                        yield(Token('varexp', match_text[2:-1]))
                    else:
                        raise ValueError(f'lex: unknown element {tid}')
                    break
            if not matched:
                raise ValueError('Lexer got confused path %s line %d column %d'
                    % (debuginfo_path, lineno, col))

class Parser:
    def __init__(self, code: str, debuginfo_path: Path) -> None:
        self.stream = Lexer().lex(code, debuginfo_path)
        self.getsym()

    def getsym(self) -> None:
        try:
            self.current = next(self.stream)
        except StopIteration:
            self.current = Token('eof', '')

    def accept(self, s: str) -> bool:
        if self.current.tid == s:
            self.getsym()
            return True
        return False

    def expect(self, s: str) -> bool:
        if self.accept(s):
            return True
        raise ValueError(f'Expecting {s} got {self.current.tid}.', self.current.lineno, self.current.colno)

    def statement(self) -> Statement:
        cur = self.current
        if self.accept('comment'):
            return Statement('_', [cur.value])
        self.accept('id')
        self.expect('lparen')
        args = self.arguments()
        self.expect('rparen')
        return Statement(cur.value, args)

    def arguments(self) -> T.List[T.Union[Token, T.Any]]:
        args: T.List[T.Union[Token, T.Any]] = []
        if self.accept('lparen'):
            args.append(self.arguments())
            self.expect('rparen')
        arg = self.current
        if self.accept('comment'):
            rest = self.arguments()
            args += rest
        elif self.accept('string') \
                or self.accept('varexp') \
                or self.accept('id'):
            args.append(arg)
            rest = self.arguments()
            args += rest
        return args

    def parse(self) -> T.Iterator[Statement]:
        while not self.accept('eof'):
            yield(self.statement())

def token_or_group(arg: T.Union[Token, T.List[Token]]) -> str:
    if isinstance(arg, Token):
        return ' ' + arg.value
    elif isinstance(arg, list):
        line = ' ('
        for a in arg:
            line += ' ' + token_or_group(a)
        line += ' )'
        return line
    raise RuntimeError('Conversion error in token_or_group')

class Converter:
    ignored_funcs = {'cmake_minimum_required': True,
                     'enable_testing': True}

    known_programs = ['bison']

    comp_op = {
        'EQUAL': '==',
        'LESS': '<',
        'LESS_EQUAL': '<=',
        'GREATER': '>',
        'GREATER_EQUAL': '>=',
        'STREQUAL': '==',
        'STRLESS': '<',
        'STRLESS_EQUAL': '<=',
        'STRGREATER': '>',
        'STRGREATER_EQUAL': '>=',
        'VERSION_EQUAL': 'todo',
        'VERSION_LESS': 'todo',
        'VERSION_LESS_EQUAL': 'todo',
        'VERSION_GREATER': 'todo',
        'VERSION_GREATER_EQUAL': 'todo',
        'PATH_EQUAL': '=='
    }

    def __init__(self, cmake_root: str):
        self.cmake_root = Path(cmake_root).expanduser()
        self.indent_unit = '  '
        self.indent_level = 0
        self.options: T.List[T.Tuple[str, str, T.Optional[str]]] = []

    def convert_condition_part(self, arg: Token) -> str:
        mapping = {
            'APPLE': '(build_machine.system() == \'darwin\')',
            'WIN32': '(build_machine.system() == \'windows\')',
        }
        if arg.value in mapping:
            return mapping[arg.value]
        elif arg.value in self.comp_op:
            return self.comp_op[arg.value]
        elif arg.value.endswith('_FOUND'):
            # find_package(SomePackage) will set the variable SomePackage_FOUND Source:
            # https://cmake.org/cmake/help/latest/command/find_package.html
            pkgname = arg.value[:-len('_FOUND')]
            return '%s_dep.found()' % pkgname
        elif arg.tid == 'string':
            return "'%s'" % arg.value
        elif arg.value in [el[0] for el in self.options]:
            return "get_option('%s')" % arg.value
        else:
            return arg.value.lower()

    def convert_condition(self, args: T.List[Token]) -> str:
        ar = list(map(self.convert_condition_part, args))

        # return ' '.join(ar) would be simple, but cmake has another operator
        # precedence than meson so we need to fix some brakets.

        # For everyone wondering how cmake's grammar works, here are some examples:
        # (Assume that `set(tv true)` and `set(fv false)` has been run)
        # NOT tv -> false
        # NOT NOT tv -> error
        # NOT (NOT tv) -> true
        # NOT tv AND fv -> (NOT tv) AND fv -> false
        # NOT tv OR tv -> (NOT tv) OR tv -> true
        # tv OR tv AND fv -> (tv OR tv) AND fv -> false
        # fv AND tv OR tv -> (fv AND tv) OR tv -> true
        # NOT 3 EQUAL 3 -> NOT (3 EQUAL 3) -> false

        # In contrast, Meson has the following operator precedence:
        # not
        # comparison operators
        # and
        # or
        # Examples:
        # not a == b -> (not a) == b
        # not true and false -> (not true) and false -> false
        # true or true and false -> true or (true and false) -> true

        def find_braket_end(pos, direction):
            assert direction in [+1, -1]
            if ar[pos] != '(':
                return pos
            else:
                depth = 1
                while depth > 0:
                    pos += direction
                    if ar[pos] == '(':
                        depth += 1
                    elif ar[pos] == ')':
                        depth -= 1
                return pos

        def find_comp_end(pos, direction):
            assert direction in [+1, -1]
            pos = find_braket_end(pos, direction)
            if pos + direction < len(ar) and ar[pos + direction] in self.comp_op.values():
                return find_braket_end(pos + 2 * direction, direction)
            else:
                return pos

        # I'm not sure how correct this while loop is. It's tricky and I'm currently really, really stupid.
        i = 0
        while i < len(ar):
            if ar[i] == 'not':
                ar.insert(i+1, '(')
                i = find_comp_end(i+2, +1)+1
                ar.insert(i, ')')
            elif ar[i] == 'or':
                ar.insert(0, '(')
                i = find_comp_end(i+2, +1)+1
                ar.insert(i, ')')
            else:
                i += 1
        return ' '.join(ar)

    def convert_args(self, args: T.List[Token], as_array: bool = True) -> str:
        res = []
        if as_array:
            start = '['
            end = ']'
        else:
            start = ''
            end = ''
        for i in args:
            if i.tid == 'id':
                res.append("'%s'" % i.value)
            elif i.tid == 'varexp':
                res.append('%s' % i.value.lower())
            elif i.tid == 'string':
                res.append("'%s'" % i.value)
            else:
                raise ValueError(f'Unknown arg type {i.tid}')
        if len(res) > 1:
            return start + ', '.join(res) + end
        if len(res) == 1:
            return res[0]
        return ''

    def write_entry(self, outfile: T.TextIO, t: Statement) -> None:
        if t.name in Converter.ignored_funcs:
            return
        preincrement = 0
        postincrement = 0
        if t.name == '_':
            line = t.args[0]
        elif t.name == 'add_subdirectory':
            line = "subdir('" + t.args[0].value + "')"
        elif t.name == 'include':
            assert(len(t.args) == 1)
            assert(t.args[0].tid == 'id')
            # Design Choice: Maybe the 'include' commands should be done by some sort of preprocessor?
            fp = self.cmake_root / Path('cmake') / Path('Modules') / Path('%s.cmake' % t.args[0].value)
            if fp.exists(): # Otherwise, we assume that it is a build-in-module https://cmake.org/cmake/help/latest/manual/cmake-modules.7.html
                with fp.open(encoding='utf-8') as f:
                    cmakecode = f.read()
                p = Parser(cmakecode, fp)
                for t_inner in p.parse():
                    self.write_entry(outfile, t_inner)
            return
        elif t.name == 'pkg_search_module' or t.name == 'pkg_search_modules':
            varname = t.args[0].value.lower()
            mods = ["dependency('%s')" % i.value for i in t.args[1:]]
            if len(mods) == 1:
                line = '{} = {}'.format(varname, mods[0])
            else:
                line = '{} = [{}]'.format(varname, ', '.join(["'%s'" % i for i in mods]))
        elif t.name == 'find_package':
            value = t.args[0].value
            if value.lower() in self.known_programs:
                line = "{}_dep = find_program('{}')".format(value, value.lower())
            else:
                line = "{}_dep = dependency('{}')".format(value, value)
        elif t.name == 'find_library':
            line = "{} = find_library('{}')".format(t.args[0].value.lower(), t.args[0].value)
        elif t.name == 'add_executable':
            line = '{}_exe = executable({})'.format(t.args[0].value, self.convert_args(t.args, False))
        elif t.name == 'add_library':
            if t.args[1].value == 'SHARED':
                libcmd = 'shared_library'
                args = [t.args[0]] + t.args[2:]
            elif t.args[1].value == 'STATIC':
                libcmd = 'static_library'
                args = [t.args[0]] + t.args[2:]
            else:
                libcmd = 'library'
                args = t.args
            line = '{}_lib = {}({})'.format(t.args[0].value, libcmd, self.convert_args(args, False))
        elif t.name == 'add_test':
            line = 'test(%s)' % self.convert_args(t.args, False)
        elif t.name == 'option':
            optname = t.args[0].value
            description = t.args[1].value
            if len(t.args) > 2:
                default = t.args[2].value
            else:
                default = None
            self.options.append((optname, description, default))
            return
        elif t.name == 'project':
            pname = t.args[0].value
            args = [pname]
            for l in t.args[1:]:
                l = l.value.lower()
                if l == 'cxx':
                    l = 'cpp'
                args.append(l)
            args = ["'%s'" % i for i in args]
            line = 'project(' + ', '.join(args) + ", default_options : ['default_library=static'])"
        elif t.name == 'set':
            varname = t.args[0].value.lower()
            line = '{} = {}\n'.format(varname, self.convert_args(t.args[1:2]))
        elif t.name == 'if':
            postincrement = 1
            line = 'if %s' % self.convert_condition(t.args)
        elif t.name == 'elseif':
            preincrement = -1
            postincrement = 1
            line = 'elif %s' % self.convert_condition(t.args)
        elif t.name == 'else':
            preincrement = -1
            postincrement = 1
            line = 'else'
        elif t.name == 'endif':
            preincrement = -1
            line = 'endif'
        else:
            line = '''# {}({})'''.format(t.name, self.convert_args(t.args))
        self.indent_level += preincrement
        indent = self.indent_level * self.indent_unit
        outfile.write(indent)
        outfile.write(line)
        if not(line.endswith('\n')):
            outfile.write('\n')
        self.indent_level += postincrement

    def convert(self, subdir: Path = None) -> None:
        if not subdir:
            subdir = self.cmake_root
        cfile = Path(subdir).expanduser() / 'CMakeLists.txt'
        try:
            with cfile.open(encoding='utf-8') as f:
                cmakecode = f.read()
        except FileNotFoundError:
            print('\nWarning: No CMakeLists.txt in', subdir, '\n', file=sys.stderr)
            return
        p = Parser(cmakecode, cfile)
        with (subdir / 'meson.build').open('w', encoding='utf-8') as outfile:
            for t in p.parse():
                if t.name == 'add_subdirectory':
                    # print('\nRecursing to subdir',
                    #       self.cmake_root / t.args[0].value,
                    #       '\n')
                    self.convert(subdir / t.args[0].value)
                    # print('\nReturning to', self.cmake_root, '\n')
                self.write_entry(outfile, t)
        if subdir == self.cmake_root and len(self.options) > 0:
            self.write_options()

    def write_options(self) -> None:
        filename = self.cmake_root / 'meson_options.txt'
        with filename.open('w', encoding='utf-8') as optfile:
            for o in self.options:
                (optname, description, default) = o
                if default is None:
                    typestr = ''
                    defaultstr = ''
                else:
                    if default == 'OFF':
                        typestr = ' type : \'boolean\','
                        default = 'false'
                    elif default == 'ON':
                        default = 'true'
                        typestr = ' type : \'boolean\','
                    else:
                        typestr = ' type : \'string\','
                    defaultstr = ' value : %s,' % default
                line = "option({!r},{}{} description : '{}')\n".format(optname,
                                                                 typestr,
                                                                 defaultstr,
                                                                 description)
                optfile.write(line)

if __name__ == '__main__':
    p = argparse.ArgumentParser(description='Convert CMakeLists.txt to meson.build and meson_options.txt')
    p.add_argument('cmake_root', help='CMake project root (where top-level CMakeLists.txt is)')
    P = p.parse_args()

    Converter(P.cmake_root).convert()
