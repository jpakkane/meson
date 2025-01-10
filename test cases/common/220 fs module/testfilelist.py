#!/usr/bin/env python3

import sys
from pathlib import Path

input_file = Path(sys.argv[-1])
if not input_file.exists():
    sys.exit('Input file not found')

with input_file.open('r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not Path(line).exists():
            sys.exit(f'File {line} not found')

sys.exit(0)
