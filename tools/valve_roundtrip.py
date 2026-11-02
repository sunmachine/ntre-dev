#!/usr/bin/env python3
"""valve_roundtrip.py BASE_TREE NEO_TREE [--files ...] [--baseline FILE] [--tagged-ok] [--verbose]

For each Valve source file present in both BASE_TREE and NEO_TREE, strip the NEO
conditionals from the NEO copy with unifdef and diff the result against Valve's
original, ignoring blank lines and leading or trailing whitespace. With
--ignore-space, whitespace changes inside a line are ignored too.

Output: one "<residual line count>\t<file>" line per file that does not round-trip.
With --baseline, exit 1 if any file exceeds its baseline count or is missing from it.
"""
import argparse
import difflib
import os
import subprocess
import sys

NEO_DEFS = ['-UNEO', '-UNEO_UNITY', '-UNEO_STEAMAUDIO', '-UNEO_CI_BUILD']
EXTS = {'.cpp', '.h', '.c', '.cc', '.hpp', '.inl'}


def decode(data):
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('latin-1')


def read(path):
    return decode(open(path, 'rb').read())


def lines(text, collapse):
    out = []
    for l in text.splitlines():
        l = l.strip()
        if not l:
            continue
        if collapse:
            l = ''.join(l.split())
        out.append(l)
    return out


def strip_neo(path, unifdef):
    # Feed the file on stdin with a final newline: unifdef 2.10 reports
    # "EOF in comment" for a file whose last line is a comment with no newline.
    data = open(path, 'rb').read()
    if not data.endswith(b'\n'):
        data += b'\n'
    r = subprocess.run([unifdef, *NEO_DEFS], input=data, capture_output=True)
    if r.returncode == 2:
        return None  # unifdef could not parse the file (unbalanced #if)
    return decode(r.stdout)


def residual(base_file, neo_file, unifdef, tagged_ok, collapse):
    a = lines(read(base_file), collapse)
    stripped = strip_neo(neo_file, unifdef)
    if stripped is None:
        return None
    b = lines(stripped, collapse)
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == 'equal':
            continue
        added = b[j1:j2]
        if tagged_ok and added and all('// NEO' in l for l in added):
            continue  # tagged in-place edit: accepted
        out += [('-', l) for l in a[i1:i2]] + [('+', l) for l in added]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('base')
    ap.add_argument('neo')
    ap.add_argument('--files', nargs='*')
    ap.add_argument('--baseline')
    ap.add_argument('--tagged-ok', action='store_true')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--unifdef', default='unifdef')
    ap.add_argument('--ignore-space', action='store_true',
                    help='also ignore whitespace changes inside a line')
    args = ap.parse_args()

    if args.files is not None:
        rels = [f for f in args.files if os.path.splitext(f)[1].lower() in EXTS]
    else:
        rels = [os.path.relpath(os.path.join(r, f), args.base)
                for r, _, fs in os.walk(os.path.join(args.base, 'src'))
                for f in fs if os.path.splitext(f)[1].lower() in EXTS]

    baseline = {}
    if args.baseline and os.path.exists(args.baseline):
        for l in open(args.baseline):
            if l.strip() and not l.startswith('#'):
                n, f = l.rstrip('\n').split('\t')
                baseline[f] = int(n)

    bad = 0
    for rel in sorted(rels):
        bp, np_ = os.path.join(args.base, rel), os.path.join(args.neo, rel)
        if not (os.path.exists(bp) and os.path.exists(np_)):
            continue
        res = residual(bp, np_, args.unifdef, args.tagged_ok, args.ignore_space)
        if res is None:
            print(f'ERR\t{rel}', file=sys.stderr)
            continue
        n = len(res)
        if n == 0:
            continue
        print(f'{n}\t{rel}')
        if args.verbose:
            for sign, l in res:
                print(f'    {sign} {l[:140]}')
        if args.baseline and n > baseline.get(rel, 0):
            print(f'::error file={rel}::unguarded Valve-tree change: residual {n} > baseline {baseline.get(rel, 0)}')
            bad += 1
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
