#!/usr/bin/env python3
"""tidy_compile_db.py BUILD_DIR OUT_DIR

Copies BUILD_DIR/compile_commands.json to OUT_DIR with the GCC-only flags
removed, so clang-tidy can read a database that CMake generated for GCC.
Run clang-tidy with -p OUT_DIR afterwards.
"""
import json
import os
import shlex
import sys

GCC_ONLY = {
    '-fno-ipa-cp-clone',
    '-fno-devirtualize-speculatively',
    '-Wno-template-id-cdtor',
    '-Wno-nonnull-compare',
    '-Wno-class-memaccess',
}
GCC_ONLY_PREFIX = ('-fabi-compat-version=',)


def keep(arg):
    if arg in GCC_ONLY:
        return False
    return not arg.startswith(GCC_ONLY_PREFIX)


build_dir, out_dir = sys.argv[1:3]
entries = json.load(open(os.path.join(build_dir, 'compile_commands.json')))
for e in entries:
    if 'command' in e:
        args = shlex.split(e['command'])
    else:
        args = e['arguments']
    args = [a for a in args if keep(a)]
    args.append('-Wno-ignored-gch')
    e.pop('command', None)
    e['arguments'] = args
os.makedirs(out_dir, exist_ok=True)
json.dump(entries, open(os.path.join(out_dir, 'compile_commands.json'), 'w'), indent=1)
print(f'{len(entries)} entries written to {out_dir}/compile_commands.json')
