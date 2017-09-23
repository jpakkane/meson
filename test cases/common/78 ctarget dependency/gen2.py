#!/usr/bin/env python3

import os
import sys
from glob import glob

files = glob(os.path.join(sys.argv[1], '*.tmp'))
assert(len(files) == 1)

with open(files[0], 'r') as ifile, open(sys.argv[2], 'w') as ofile:
    ofile.write(ifile.read())
