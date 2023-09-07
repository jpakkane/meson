import argparse
from pathlib import Path
import sys

parser = argparse.ArgumentParser(fromfile_prefix_chars='@')
parser.add_argument('argv_output', type=Path)
parser.add_argument('parsed_output', type=Path)
parser.add_argument('items', nargs='*')
arguments = parser.parse_args()

arguments.argv_output.write_text(
    '\n'.join(sys.argv[3:]),
    encoding='utf-8'
)

arguments.parsed_output.write_text(
    '\n'.join(arguments.items),
    encoding='utf-8'
)
