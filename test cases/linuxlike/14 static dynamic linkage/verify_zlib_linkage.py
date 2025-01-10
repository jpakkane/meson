#!/usr/bin/env python3
"""Test script that checks if zlib was statically or dynamically linked to executable"""
import subprocess
import sys
import argparse

def check_zlib_symbol_common(path, is_static):
    """Tests if the binary contains zlibVersion symbol (non-Cygwin version)."""
    try:
        sym_opt = '--defined-only' if is_static else '--undefined-only'
        output = subprocess.check_output(['nm', sym_opt, '-P', '-A', path]).decode('utf-8')
    except subprocess.CalledProcessError:
        # some NMs only support -U. Older binutils only supports --defined-only.
        opts = '-UPA' if is_static else '-uPA'
        output = subprocess.check_output(['nm', opts, path]).decode('utf-8')
    # POSIX format. Prints all *defined* symbols, looks like this:
    # builddir/main_static: zlibVersion T 1190 39
    # or
    # builddir/main_static: zlibVersion D 1fde0 30
    if ': zlibVersion ' in output:
        return 0
    return 1

def check_zlib_symbol_cygwin(path, is_static):
    """Tests if the binary contains zlibVersion symbol (Cygwin case)."""
    output = subprocess.check_output(['nm', path]).decode('utf-8')
    # No matter static or dynamic, the name must exist in nm output
    if ' zlibVersion' not in output:
        return 2
    is_dynamic = ('I __imp_zlibVersion' in output) or ('D __imp_zlibVersion' in output)
    if is_dynamic == is_static: # expected/got mismatch?
        return 3
    return 0

def main():
    """Main function"""
    parser = argparse.ArgumentParser()
    parser.add_argument('path', help='executable path')
    parser.add_argument('-p', '--platform')
    parser.add_argument('-s', '--static', action='store_true', default=False)
    args = parser.parse_args()
    if args.platform == 'cygwin':
        return check_zlib_symbol_cygwin(args.path, args.static)
    else:
        return check_zlib_symbol_common(args.path, args.static)


if __name__ == '__main__':
    sys.exit(main())
