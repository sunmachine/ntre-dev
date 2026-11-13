#!/usr/bin/env python3
"""tag_valve_edits.py [--files-from BASELINE] [--max-hunk N] [--plan OUT.tsv] [--apply] [--revert-noise]

For each Valve file listed in the baseline, find the unguarded lines NEO
added or changed (the same round-trip as valve_roundtrip.py), map them back
to their line numbers in the NEO file, and plan a trailing "// NEO" tag for
each line of every hunk with at most N added lines. Larger hunks are NEO
logic, left for an #ifdef NEO guard or a hook refactor.

Every hunk gets one plan row:
  file  first_line  added  removed  kind  action  sample
kind:   space-only  (added and removed lines equal once whitespace is removed)
        encoding    (the only difference is a non-ASCII byte, e.g. a copyright sign)
        insert      (lines added, nothing removed)
        delete      (Valve lines removed, nothing added; cannot be tagged)
        edit        (anything else)
action: tag | revert | skip-large | skip-delete | skip-continuation | skip-tagged

With --revert-noise, space-only and encoding hunks get Valve's exact text
back instead of a tag, when the span holds no NEO-guarded lines.
"""
import argparse
import difflib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import strip_neo_ifdefs  # noqa: E402
from check_valve_edits import BASELINE, ROOT, ValveBase  # noqa: E402

NEO_SYMBOLS = ['NEO', 'NEO_UNITY', 'NEO_STEAMAUDIO', 'NEO_CI_BUILD']
TAG = '// NEO'


def decode(data):
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('latin-1')


def numbered(text):
    """(1-based line number, stripped text) for each non-blank line."""
    return [(i + 1, l.strip()) for i, l in enumerate(text.splitlines()) if l.strip()]


def strip_neo(path):
    data = open(path, 'rb').read()
    if not data.endswith(b'\n'):
        data += b'\n'
    try:
        out, _ = strip_neo_ifdefs.resolve(data, undefined=NEO_SYMBOLS, blank=True)
    except strip_neo_ifdefs.ParseError:
        return None
    return decode(out)


def kind_of(added, removed):
    if not added:
        return 'delete'
    if not removed:
        return 'insert'
    a = ''.join(''.join(l.split()) for l in added)
    r = ''.join(''.join(l.split()) for l in removed)
    if a == r:
        return 'space-only'
    if a.encode('ascii', 'replace') == r.encode('ascii', 'replace') or \
       ''.join(c for c in a if ord(c) < 128) == ''.join(c for c in r if ord(c) < 128):
        return 'encoding'
    return 'edit'


def plan_file(valve, rel, max_hunk, revert_noise):
    base_raw = valve.read(rel).split(b'\n')
    neo_raw = open(os.path.join(ROOT, rel), 'rb').read().split(b'\n')
    a = numbered(decode(b'\n'.join(base_raw)))
    s = strip_neo(os.path.join(ROOT, rel))
    if s is None:
        return None
    stripped = s.splitlines()
    b = numbered(s)
    rows = []
    sm = difflib.SequenceMatcher(None, [t for _, t in a], [t for _, t in b], autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            continue
        removed = [t for _, t in a[i1:i2]]
        added = b[j1:j2]
        k = kind_of([t for _, t in added], removed)
        first = added[0][0] if added else (b[j1 - 1][0] if j1 > 0 else 0)
        revert = None
        if revert_noise and k in ('space-only', 'encoding') and added and removed:
            n1, n2 = added[0][0], added[-1][0]
            # Only when every line of the NEO span survived the stripping unchanged,
            # i.e. the span holds no NEO-guarded lines.
            clean = all(decode(neo_raw[n - 1]).strip() == stripped[n - 1].strip() for n in range(n1, n2 + 1))
            if clean:
                v1, v2 = a[i1][0], a[i2 - 1][0]
                revert = (n1, n2, base_raw[v1 - 1:v2])
        if revert:
            action = 'revert'
        elif not added:
            action = 'skip-delete'
        elif all(TAG in t for _, t in added):
            action = 'skip-tagged'
        elif len(added) > max_hunk:
            action = 'skip-large'
        elif any(t.endswith('\\') for _, t in added):
            action = 'skip-continuation'
        else:
            action = 'tag'
        sample = (added[0][1] if added else removed[0])[:100]
        rows.append((rel, first, len(added), len(removed), k, action, sample, [n for n, _ in added], revert))
    return rows


def apply_changes(rel, tag_lines, reverts):
    path = os.path.join(ROOT, rel)
    lines = open(path, 'rb').read().split(b'\n')
    for n in tag_lines:
        line = lines[n - 1]
        if TAG.encode() in line:
            continue  # already marked, e.g. a // NEO TODO comment
        cr = line.endswith(b'\r')
        body = line[:-1] if cr else line
        lines[n - 1] = body.rstrip(b' \t') + b' ' + TAG.encode() + (b'\r' if cr else b'')
    for n1, n2, valve in sorted(reverts, reverse=True):
        cr = lines[n1 - 1].endswith(b'\r')
        repl = [v.rstrip(b'\r') + (b'\r' if cr else b'') for v in valve]
        lines[n1 - 1:n2] = repl
    open(path, 'wb').write(b'\n'.join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--files-from', default=BASELINE)
    ap.add_argument('--max-hunk', type=int, default=3)
    ap.add_argument('--plan')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--only-kinds', default='')
    ap.add_argument('--revert-noise', action='store_true')
    args = ap.parse_args()

    valve = ValveBase()
    rels = []
    for l in open(args.files_from):
        if l.strip() and not l.startswith('#'):
            rels.append(l.rstrip('\n').split('\t')[1])
    only = set(k for k in args.only_kinds.split(',') if k)
    out = open(args.plan, 'w') if args.plan else None
    if out:
        out.write('file\tline\tadded\tremoved\tkind\taction\tsample\n')
    to_apply = {}
    for rel in sorted(rels):
        rows = plan_file(valve, rel, args.max_hunk, args.revert_noise)
        if rows is None:
            print(f'ERR\t{rel}', file=sys.stderr)
            continue
        for rel_, first, na, nr, k, action, sample, nums, revert in rows:
            if action == 'tag' and only and k not in only:
                action = 'skip-kind'
            if out:
                out.write(f'{rel_}\t{first}\t{na}\t{nr}\t{k}\t{action}\t{sample}\n')
            if action == 'tag':
                to_apply.setdefault(rel_, ([], []))[0].extend(nums)
            elif action == 'revert':
                to_apply.setdefault(rel_, ([], []))[1].append(revert)
    if args.apply:
        for rel, (nums, reverts) in to_apply.items():
            apply_changes(rel, sorted(set(nums)), reverts)
        print(f'tagged {sum(len(set(v[0])) for v in to_apply.values())} lines, '
              f'reverted {sum(len(v[1]) for v in to_apply.values())} hunks, in {len(to_apply)} files')


if __name__ == '__main__':
    main()
