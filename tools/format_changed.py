#!/usr/bin/env python3
"""format_changed.py [--check] [--base REF]

Formats the lines the current branch changed in NEO-owned code, using the same
commands as the clang-format CI job, which runs this script. It works on Windows
and Linux. With --check it prints a diff and changes nothing.

Install the formatter with: python -m pip install clang-format==19.1.7

Exit status: 0 when the changed lines are formatted, 1 when --check found a
difference, 2 on an error.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

MAJOR_VERSION = '19'
INSTALL_HINT = 'python -m pip install clang-format==19.1.7'
DEFAULT_BASES = ('origin/master', 'master')

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

# These directories carry their own .clang-format.
NEO_DIRS = [
    'src/game/client/neo',
    'src/game/server/neo',
    'src/game/shared/neo',
    'src/common/neo',
    'src/tests',
]

# NEO files inside Valve directories are not reached by a directory
# .clang-format, because the root one disables formatting there. They are listed
# here and formatted with the NEO style. Git expands the patterns, so they behave
# the same in every shell.
NEO_STYLE = 'src/game/shared/neo/.clang-format'
NEO_FILES_IN_VALVE_DIRS = [
    'src/materialsystem/stdshaders/[Nn]eo_*.cpp',
    'src/materialsystem/stdshaders/[Nn]eo_*.h',
    'src/launcher_main/neo_case_heal.h',
]


def fail(message):
    print(f'format_changed.py: {message}', file=sys.stderr)
    sys.exit(2)


def find_tools():
    # A versioned name wins, since a distribution's plain clang-format can be any
    # version. Another major version lays code out differently from CI.
    for suffix in (f'-{MAJOR_VERSION}', ''):
        git_format = shutil.which(f'git-clang-format{suffix}')
        binary = shutil.which(f'clang-format{suffix}')
        if not (git_format and binary):
            continue
        output = subprocess.run([binary, '--version'], capture_output=True, text=True).stdout
        found = re.search(r'version (\d+)\.', output)
        if found and found.group(1) == MAJOR_VERSION:
            return git_format, binary
        fail(f'{binary} is not version {MAJOR_VERSION}. Run: {INSTALL_HINT}')
    fail(f'git-clang-format and clang-format were not found. Run: {INSTALL_HINT}')


def merge_base(requested):
    for ref in [requested] if requested else DEFAULT_BASES:
        result = subprocess.run(['git', 'merge-base', ref, 'HEAD'], cwd=ROOT, capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    fail(f'could not find a merge base with {requested or " or ".join(DEFAULT_BASES)}. Pass one with --base.')


def main():
    parser = argparse.ArgumentParser(description='Format the lines the current branch changed in NEO-owned code.')
    parser.add_argument('--check', action='store_true', help='print a diff and change nothing')
    parser.add_argument('--base', help='branch to compare with, default origin/master, then master')
    args = parser.parse_args()

    git_format, binary = find_tools()
    base = merge_base(args.base)
    command = [git_format, '--binary', binary]
    # --force lets a contributor format edits they have not staged yet. It loses
    # nothing, since the result is computed from the working tree.
    command.append('--diff' if args.check else '--force')

    status = 0
    for style, paths in ((None, NEO_DIRS), (f'file:{NEO_STYLE}', NEO_FILES_IN_VALVE_DIRS)):
        options = [f'--style={style}'] if style else []
        result = subprocess.run(command + options + [base, '--'] + paths, cwd=ROOT)
        status = max(status, result.returncode)

    if args.check and status == 1:
        message = 'Formatting differs on changed lines. Run: python tools/format_changed.py'
        print(f'::error::{message}' if os.environ.get('GITHUB_ACTIONS') else message)
    # git-clang-format also exits 1 when it has just formatted files, which is
    # success for a contributor applying the format.
    sys.exit(0 if not args.check and status == 1 else status)


if __name__ == '__main__':
    main()
