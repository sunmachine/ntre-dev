#!/usr/bin/env python3
"""reformat_neo.py: formats every NEO-owned source file in place.

This is the one-time reformat. It covers the same files as the clang-format
check: the NEO directories with their own .clang-format, and the NEO files in
Valve directories with the NEO style. The lists come from format_changed.py.
A second run changes nothing.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from format_changed import NEO_DIRS, NEO_FILES_IN_VALVE_DIRS, NEO_STYLE, ROOT, find_tools  # noqa: E402

EXTENSIONS = ('.c', '.cc', '.cpp', '.cxx', '.h', '.hh', '.hpp', '.hxx', '.inl')


def tracked(patterns):
    out = subprocess.run(['git', 'ls-files', '--', *patterns], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if p.lower().endswith(EXTENSIONS)]


def main():
    _, binary = find_tools()
    in_dirs = tracked(NEO_DIRS)
    in_valve_dirs = tracked(NEO_FILES_IN_VALVE_DIRS)
    if in_dirs:
        subprocess.run([binary, '-i', *in_dirs], cwd=ROOT, check=True)
    if in_valve_dirs:
        subprocess.run([binary, '-i', f'--style=file:{NEO_STYLE}', *in_valve_dirs], cwd=ROOT, check=True)
    print(f'formatted {len(in_dirs) + len(in_valve_dirs)} files')


if __name__ == '__main__':
    main()
