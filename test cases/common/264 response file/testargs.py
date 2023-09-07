import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--nargs', type=int)
parser.add_argument('argv_file', type=Path)
parser.add_argument('parsed_file', type=Path)
arguments = parser.parse_args()

argv = arguments.argv_file.read_text(encoding='utf-8').splitlines()
parsed = arguments.parsed_file.read_text(encoding='utf-8').splitlines()

assert len(parsed) == arguments.nargs

if argv[0].startswith('@'):
    assert Path(argv[0][1:]).exists()

else:
    assert len(argv) == arguments.nargs
