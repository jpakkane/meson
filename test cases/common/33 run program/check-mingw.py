#!/usr/bin/env python3

import os, sys, re

if 'MSYSTEM' in os.environ and os.environ['MSYSTEM'] != '':
    print(os.environ['MSYSTEM'])
else:
    match = re.search(r'[\\/](mingw32|mingw64|clang32|clang64|clangarm64|ucrt64)[\\/]', sys.executable, flags=re.IGNORECASE)
    if match:
        print(match.group(1).upper())
