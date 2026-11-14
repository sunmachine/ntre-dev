#!/usr/bin/env python3
"""guard_valve_edits.py FILE... [--dry-run]

Guards every unguarded NEO hunk in each FILE, a Valve file given relative to
the repository root. For each hunk the NEO span runs
between the unchanged lines on either side, the Valve span between the
same anchors in Valve's copy at the SDK base. The span becomes
    #ifdef NEO / <NEO span with NEO defined> / #else / <Valve span> / #endif // NEO
or, when NEO removed lines and added none,
    #ifndef NEO / <Valve span> / #endif // NEO
With NEO defined the file compiles exactly as before; without NEO it is
Valve's text. A hunk whose span would split a preprocessor block is
reported and left alone.
"""
import argparse, difflib, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import strip_neo_ifdefs  # noqa: E402
from check_valve_edits import ROOT, ValveBase  # noqa: E402

NEO_SYMBOLS = ['NEO', 'NEO_UNITY', 'NEO_STEAMAUDIO', 'NEO_CI_BUILD']
ap = argparse.ArgumentParser()
ap.add_argument('files', nargs='+')
ap.add_argument('--dry-run', action='store_true')
A = ap.parse_args()
VALVE = ValveBase()

def dec(b):
    try: return b.decode('utf-8')
    except UnicodeDecodeError: return b.decode('latin-1')

def balanced(lines):
    depth = 0
    for l in lines:
        t = dec(l).strip()
        if re.match(r'#\s*if', t): depth += 1
        elif re.match(r'#\s*endif', t):
            depth -= 1
            if depth < 0: return False
        elif re.match(r'#\s*(else|elif)', t) and depth == 0: return False
    return depth == 0

def guard(file):
    path = os.path.join(ROOT, file)
    vraw = VALVE.read(file).split(b'\n')
    nraw = open(path, 'rb').read().split(b'\n')
    a = [(i + 1, dec(l).strip()) for i, l in enumerate(vraw) if dec(l).strip()]
    data = b'\n'.join(nraw)
    if not data.endswith(b'\n'): data += b'\n'
    try:
        stripped, _ = strip_neo_ifdefs.resolve(data, undefined=NEO_SYMBOLS, blank=True)
    except strip_neo_ifdefs.ParseError:
        print('SKIP ' + file + ': unbalanced conditional'); return
    b = [(i + 1, l.strip()) for i, l in enumerate(dec(stripped).splitlines()) if l.strip()]
    ops = difflib.SequenceMatcher(None, [t for _, t in a], [t for _, t in b], autojunk=False).get_opcodes()
    plans = []
    for tag, i1, i2, j1, j2 in ops:
        if tag == 'equal': continue
        added = [t for _, t in b[j1:j2]]
        if added and all('// NEO' in t for t in added): continue  # tagged edits already pass the guard
        v1 = a[i1 - 1][0] + 1 if i1 > 0 else 1
        v2 = a[i2][0] - 1 if i2 < len(a) else len(vraw)
        n1 = b[j1 - 1][0] + 1 if j1 > 0 else 1
        n2 = b[j2][0] - 1 if j2 < len(b) else len(nraw)
        plans.append((n1, n2, v1, v2, tag, j2 - j1, i2 - i1))
    done = skipped = 0
    for n1, n2, v1, v2, tag, na, nr in sorted(plans, reverse=True):
        nspan = nraw[n1 - 1:n2]
        vspan = vraw[v1 - 1:v2]
        while nspan and not dec(nspan[0]).strip() and vspan and not dec(vspan[0]).strip():
            nspan = nspan[1:]; vspan = vspan[1:]; n1 += 1
        while nspan and not dec(nspan[-1]).strip() and vspan and not dec(vspan[-1]).strip():
            nspan = nspan[:-1]; vspan = vspan[:-1]; n2 -= 1
        cont = lambda ls: any(dec(l).rstrip().endswith('\\') for l in ls)
        before = nraw[n1 - 2:n1 - 1] if n1 > 1 else []
        if cont(nspan) or cont(vspan) or cont(before):
            print(f'SKIP {file} neo {n1}-{n2}: span is inside a multi-line macro'); skipped += 1; continue
        if not balanced(nspan) or not balanced(vspan):
            print(f'SKIP {file} neo {n1}-{n2} valve {v1}-{v2}: span splits a preprocessor block'); skipped += 1; continue
        try:
            resolved, _ = strip_neo_ifdefs.resolve(b'\n'.join(nspan) + b'\n', defined={'NEO': 1})
        except strip_neo_ifdefs.ParseError:
            print(f'SKIP {file} neo {n1}-{n2}: unbalanced conditional in the span'); skipped += 1; continue
        neo = re.sub(rb'[ \t]*// NEO(\r?)\n', rb'\1\n', resolved).rstrip(b'\n')
        # Resolving leaves the blank lines that surrounded removed #ifndef NEO blocks; keep at most one
        neo = re.sub(rb'\n(?:[ \t]*\r?\n){2,}', b'\n\n', neo)
        cr = b'\r' if nraw[max(n1 - 2, 0)].endswith(b'\r') else b''
        has_neo = any(dec(l).strip() for l in neo.split(b'\n'))
        if has_neo:
            block = [b'#ifdef NEO' + cr] + neo.split(b'\n') + ([b'#else' + cr] + vspan if any(dec(l).strip() for l in vspan) else []) + [b'#endif // NEO' + cr]
        else:
            block = [b'#ifndef NEO' + cr] + vspan + [b'#endif // NEO' + cr]
        print(f'{file}: neo {n1}-{n2} ({na} unguarded) / valve {v1}-{v2} ({nr} removed) -> {len(block)} lines')
        if n2 < n1:
            nraw[n1 - 1:n1 - 1] = block
        else:
            nraw[n1 - 1:n2] = block
        done += 1
    if not A.dry_run:
        open(path, 'wb').write(b'\n'.join(nraw))
    print(f'{file}: {done} hunks guarded, {skipped} skipped' + (' (dry run)' if A.dry_run else ''))


for f in A.files:
    guard(f)
