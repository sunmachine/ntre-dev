#!/usr/bin/env python3
"""neo_dev.py: one entry point for NEO's developer tools.

    python tools/neo_dev.py <command> [options]

Run it from anywhere in the repository, on Windows or Linux. Each command runs
one script in tools/ with the options given after the command, so
"<command> --help" shows that script's options. CI runs the same commands.

Before pushing
  format                  Format the lines this branch changed in NEO-owned code, as the
                          clang-format check does. --check only reports.
                          Script: format_changed.py.
  check-valve-edits       Check that every edit this branch made to a Valve file is inside
                          #ifdef NEO or tagged // NEO, so Valve SDK updates keep merging.
                          Script: check_valve_edits.py.
  tidy                    Run clang-tidy over the NEO tree and fail on findings the baseline
                          does not allow. Linux only; on Windows, run it in WSL.
                          Script: run_tidy.py.

After fixing a problem a check already allowed
  update-valve-baseline   Lower the counts in tools/valve-edits-baseline.txt.
                          Script: check_valve_edits.py.
  tidy --update-baseline  Lower the counts in tools/clang-tidy-baseline.txt.

Editor setup
  tidy-compile-db         Write a compile database that clangd and clang-tidy accept.
                          Script: make_tidy_compile_db.py.

Taking a newer Valve SDK
  merge-valve-sdk         Start merging a newer Valve SDK and resolve the conflicts NEO always
                          resolves the same way. Needs bash; on Windows, run it from Git Bash.
                          Script: merge_valve_sdk.sh.
  guard-valve-edits       Put the unguarded NEO hunks in the given Valve files under
                          #ifdef NEO, with Valve's lines under #else.
                          Script: guard_valve_edits.py.
"""
import os
import runpy
import shutil
import subprocess
import sys

TOOLS = os.path.dirname(os.path.realpath(__file__))
COMMANDS = {
    'format': ('format_changed.py', []),
    'check-valve-edits': ('check_valve_edits.py', ['--check']),
    'tidy': ('run_tidy.py', []),
    'update-valve-baseline': ('check_valve_edits.py', ['--update-baseline']),
    'tidy-compile-db': ('make_tidy_compile_db.py', []),
    'merge-valve-sdk': ('merge_valve_sdk.sh', []),
    'guard-valve-edits': ('guard_valve_edits.py', []),
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help', 'help'):
        print(__doc__)
        sys.exit(0)
    name, args = sys.argv[1], sys.argv[2:]
    if name not in COMMANDS:
        print(f'neo_dev.py: unknown command {name}. Run python tools/neo_dev.py --help.', file=sys.stderr)
        sys.exit(2)
    script, fixed = COMMANDS[name]
    path = os.path.join(TOOLS, script)
    if script.endswith('.sh'):
        bash = shutil.which('bash')
        if not bash:
            print(f'neo_dev.py: {name} needs bash. On Windows, run it from Git Bash.', file=sys.stderr)
            sys.exit(2)
        sys.exit(subprocess.run([bash, path, *fixed, *args]).returncode)
    sys.argv = [path, *fixed, *args]
    runpy.run_path(path, run_name='__main__')


if __name__ == '__main__':
    main()
