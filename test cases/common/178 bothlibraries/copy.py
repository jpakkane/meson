#!/usr/bin/env python3

import argparse
import shutil

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('dest')
    args = parser.parse_args()

    shutil.copyfile(args.source, args.dest)
