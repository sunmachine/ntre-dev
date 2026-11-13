#!/usr/bin/env python3
"""Wrap each SDK table block in // clang-format off / on.

clang-format cannot parse the SDK's brace-less table macros. Usage:
fence_sdk_tables.py [FILE...] ; rewrites the files in place, prints counts.
Without FILE it covers every NEO-owned file the clang-format check covers.
"""
import os, re, sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from format_changed import NEO_DIRS, NEO_FILES_IN_VALVE_DIRS, ROOT  # noqa: E402
from reformat_neo import tracked  # noqa: E402

BEGIN = re.compile(r'^(\s*)(BEGIN_(DATADESC|SIMPLE_DATADESC|NETWORK_TABLE|NETWORK_TABLE_NOBASE|PREDICTION_DATA'
                   r'|SEND_TABLE|RECV_TABLE|ENT_SCRIPTDESC|SHADER_PARAMS)'
                   r'|IMPLEMENT_(SERVERCLASS_ST|CLIENTCLASS_DT|CLIENTCLASS_EVENT_DT))\b')
END = re.compile(r'^\s*END_(DATADESC|NETWORK_TABLE|PREDICTION_DATA|SEND_TABLE|RECV_TABLE|SCRIPTDESC|SHADER_PARAMS)\b')
OFF, ON = '// clang-format off', '// clang-format on'

total = 0
for path in sys.argv[1:] or [os.path.join(ROOT, p) for p in tracked(NEO_DIRS) + tracked(NEO_FILES_IN_VALVE_DIRS)]:
    raw = open(path, 'rb').read()
    eol = b'\r\n' if b'\r\n' in raw else b'\n'
    lines = raw.decode('utf-8').split(eol.decode())
    out, i, n = [], 0, 0
    while i < len(lines):
        m = BEGIN.match(lines[i])
        if not m:
            out.append(lines[i]); i += 1; continue
        j = i
        while j < len(lines) and not END.match(lines[j]):
            j += 1
        if j == len(lines):
            sys.exit(f'{path}:{i+1}: no END_ for {m.group(2)}')
        block = lines[i:j+1]
        if any(l.rstrip().endswith('\\') for l in block) or (i and lines[i-1].rstrip().endswith('\\')):
            sys.exit(f'{path}:{i+1}: table inside a macro continuation')
        if any('clang-format' in l for l in block):
            sys.exit(f'{path}:{i+1}: already fenced')
        ind = m.group(1)
        out += [ind + OFF] + block + [ind + ON]
        i = j + 1; n += 1
    if n:
        open(path, 'wb').write(eol.join(l.encode() for l in out))
        print(f'{n}\t{path}')
    total += n
print(f'{total}\ttotal', file=sys.stderr)
