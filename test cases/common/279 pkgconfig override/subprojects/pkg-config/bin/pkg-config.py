#!/usr/bin/env python3

import sys

if len(sys.argv) > 1:
    if sys.argv[1] == "--modversion":
        if sys.argv[2] == "test-package-0.0":
            print("0.0.0")
        else:
            exit(-1)
    elif sys.argv[1] == "--version":
        print("0.0.0")
        exit(0)
