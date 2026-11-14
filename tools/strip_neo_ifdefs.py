#!/usr/bin/env python3
"""strip_neo_ifdefs.py [-D SYM[=VAL]]... [-U SYM]... [-l] < in > out

Resolves the preprocessor conditionals that depend on a few known symbols and
leaves every other line byte for byte. With -U NEO it gives back Valve's text
of a Valve file NEO edited under #ifdef NEO, which is what the Valve edits
check compares.

A condition is resolved when its value follows from the known symbols and its
constants. One that depends on an unknown symbol, or that holds no symbol at
all, such as #if 0, stays as written. A resolved branch loses its directive lines; a false branch loses
its body too. When an earlier branch stays, a true #elif becomes #else, and
when every earlier branch is gone, a kept #elif becomes #if. With -l, removed
lines become empty lines, so line numbers stay put.

Exit status: 0 when nothing changed, 1 when the output differs, 2 on an
unbalanced conditional.
"""
import re
import sys

DIRECTIVE = re.compile(rb'^([ \t]*#[ \t]*)(if|ifdef|ifndef|elif|else|endif)\b')
TOKEN = re.compile(r'\s*(?:(defined)\b|([A-Za-z_]\w*)|(0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
                   r'|(&&|\|\||==|!=|<=|>=|<<|>>|[!~+\-*/%<>&^|()?:,]))')
UNKNOWN = None


class ParseError(Exception):
    pass


def logical_lines(lines):
    """Groups physical lines into logical lines and marks the directives.

    Yields (first, last, is_directive) as physical line indices. A directive
    runs on over backslash continuations and over a block comment it opens.
    Lines inside a block comment or a string are never directives.
    """
    in_comment = False
    i = 0
    while i < len(lines):
        start = i
        directive = not in_comment and DIRECTIVE.match(lines[i]) is not None
        while True:
            in_comment = scan(lines[i], in_comment)
            continued = lines[i].rstrip(b'\r').endswith(b'\\')
            if i + 1 < len(lines) and (continued or (directive and in_comment)):
                i += 1
                continue
            break
        yield start, i, directive
        i += 1


def scan(line, in_comment):
    """Returns whether a block comment is still open at the end of the line."""
    j, n = 0, len(line)
    while j < n:
        if in_comment:
            k = line.find(b'*/', j)
            if k < 0:
                return True
            in_comment, j = False, k + 2
            continue
        c = line[j:j + 1]
        if c == b'/' and line[j + 1:j + 2] == b'*':
            in_comment, j = True, j + 2
        elif c == b'/' and line[j + 1:j + 2] == b'/':
            return False
        elif c in (b'"', b"'"):
            j += 1
            while j < n and line[j:j + 1] != c:
                j += 2 if line[j:j + 1] == b'\\' else 1
            j += 1
        else:
            j += 1
    return in_comment


def strip_comments(text):
    return re.sub(r'/\*.*?\*/|//.*', ' ', text, flags=re.S)


class Expr:
    """Three-valued evaluation: an int, or UNKNOWN."""

    def __init__(self, text, defined, undefined):
        text = strip_comments(text.replace('\\\n', ' ').replace('\\\r\n', ' '))
        self.toks, pos = [], 0
        while pos < len(text) and text[pos:].strip():
            m = TOKEN.match(text, pos)
            if not m:
                raise ValueError(text)
            self.toks.append(m.group(m.lastindex) if m.lastindex != 1 else 'defined')
            pos = m.end()
        self.i = 0
        self.defined, self.undefined = defined, undefined
        self.symbolic = False

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self, want=None):
        t = self.peek()
        if want is not None and t != want:
            raise ValueError(want)
        self.i += 1
        return t

    def value(self):
        v = self.ternary()
        if self.peek() is not None:
            raise ValueError(self.peek())
        return v

    def ternary(self):
        c = self.binary(0)
        if self.peek() != '?':
            return c
        self.take()
        a = self.ternary()
        self.take(':')
        b = self.ternary()
        if c is UNKNOWN:
            return a if a == b and a is not UNKNOWN else UNKNOWN
        return a if c else b

    LEVELS = [['||'], ['&&'], ['|'], ['^'], ['&'], ['==', '!='], ['<', '>', '<=', '>='], ['<<', '>>'],
              ['+', '-'], ['*', '/', '%']]

    def binary(self, level):
        if level == len(self.LEVELS):
            return self.unary()
        left = self.binary(level + 1)
        while self.peek() in self.LEVELS[level]:
            op = self.take()
            right = self.binary(level + 1)
            left = self.apply(op, left, right)
        return left

    @staticmethod
    def apply(op, a, b):
        if op == '&&':
            if a == 0 or b == 0:
                return 0
            return UNKNOWN if UNKNOWN in (a, b) else 1
        if op == '||':
            if (a is not UNKNOWN and a != 0) or (b is not UNKNOWN and b != 0):
                return 1
            return UNKNOWN if UNKNOWN in (a, b) else 0
        if UNKNOWN in (a, b):
            return UNKNOWN
        if op in ('/', '%') and b == 0:
            return UNKNOWN
        return int({
            '|': lambda: a | b, '^': lambda: a ^ b, '&': lambda: a & b, '==': lambda: a == b,
            '!=': lambda: a != b, '<': lambda: a < b, '>': lambda: a > b, '<=': lambda: a <= b,
            '>=': lambda: a >= b, '<<': lambda: a << b, '>>': lambda: a >> b, '+': lambda: a + b,
            '-': lambda: a - b, '*': lambda: a * b, '/': lambda: int(a / b), '%': lambda: a % b,
        }[op]())

    def unary(self):
        t = self.take()
        if t in ('!', '~', '-', '+'):
            v = self.unary()
            if v is UNKNOWN:
                return UNKNOWN
            return {'!': int(not v), '~': ~v, '-': -v, '+': v}[t]
        if t == '(':
            v = self.ternary()
            self.take(')')
            return v
        if t == 'defined':
            paren = self.peek() == '('
            if paren:
                self.take()
            name = self.take()
            if paren:
                self.take(')')
            return self.lookup(name, True)
        if t is not None and t[0].isdigit():
            return int(t.rstrip('uUlL'), 0)
        if t is not None and (t[0].isalpha() or t[0] == '_'):
            if self.peek() == '(':
                # A call: a defined symbol keeps its value and its arguments are
                # skipped. A call of an undefined symbol cannot be evaluated, so
                # the whole condition stays as written.
                if t in self.undefined:
                    raise ValueError(t)
                depth = 0
                while True:
                    u = self.take()
                    if u is None:
                        raise ValueError('(')
                    depth += (u == '(') - (u == ')')
                    if depth == 0:
                        break
            return self.lookup(t, False)
        raise ValueError(t)

    def lookup(self, name, is_defined):
        self.symbolic = True
        if name in self.defined:
            return 1 if is_defined else self.defined[name]
        if name in self.undefined:
            return 0
        return UNKNOWN


def condition(kind, text, defined, undefined):
    """Value of a directive's condition: True, False or UNKNOWN."""
    if kind in ('ifdef', 'ifndef'):
        name = strip_comments(text).split()
        if not name:
            return UNKNOWN
        name = name[0]
        if name in defined or name in undefined:
            return (name in defined) == (kind == 'ifdef')
        return UNKNOWN
    try:
        e = Expr(text, defined, undefined)
        v = e.value()
    except (ValueError, ZeroDivisionError):
        return UNKNOWN
    if v is UNKNOWN or not e.symbolic:
        return UNKNOWN
    return bool(v)


def resolve(data, defined=None, undefined=(), blank=False):
    """Returns (output bytes, changed). Raises ParseError when unbalanced."""
    defined = {k: int(v) for k, v in (defined or {}).items()}
    undefined = set(undefined)
    original = data
    if data and not data.endswith(b'\n'):
        data += b'\n'  # every line written ends with a newline
    lines = data.split(b'\n')
    out = []
    # Each open group: [emitting_parent, kept_directive, resolved_true, live]
    # live: whether the current branch's body is output.
    stack = []

    def live():
        return not stack or stack[-1][3]

    def drop(first, last):
        if blank:
            out.extend(b'' for _ in range(first, last + 1))

    for first, last, is_dir in logical_lines(lines):
        if not is_dir:
            if live():
                out.extend(lines[first:last + 1])
            else:
                drop(first, last)
            continue
        m = DIRECTIVE.match(lines[first])
        kind = m.group(2).decode()
        text = b'\n'.join(lines[first:last + 1])[m.end():].decode('latin-1')
        if kind in ('if', 'ifdef', 'ifndef'):
            parent = live()
            v = condition(kind, text, defined, undefined) if parent else False
            if not parent:
                stack.append([False, False, True, False])
                drop(first, last)
            elif v is UNKNOWN:
                stack.append([True, True, False, True])
                out.extend(lines[first:last + 1])
            else:
                stack.append([True, False, v, v])
                drop(first, last)
            continue
        if not stack:
            raise ParseError(f'line {first + 1}: #{kind} without #if')
        g = stack[-1]
        parent, kept, done = g[0], g[1], g[2]
        if kind == 'endif':
            stack.pop()
            if parent and kept:
                out.extend(lines[first:last + 1])
            else:
                drop(first, last)
            continue
        v = True if kind == 'else' else (condition('if', text, defined, undefined) if parent and not done else False)
        if not parent or done or v is False:
            g[3] = False
            drop(first, last)
        elif v is True:
            g[2], g[3] = True, True
            if kept:
                if kind == 'elif':
                    out.append(m.group(1) + b'else' + (b'\r' if lines[last].endswith(b'\r') else b''))
                    drop(first + 1, last)
                else:
                    out.extend(lines[first:last + 1])
            else:
                drop(first, last)
        else:
            g[3] = True
            if kept:
                out.extend(lines[first:last + 1])
            else:
                g[1] = True
                head = m.group(1) + b'if  ' + lines[first][m.end():]
                out.append(head)
                out.extend(lines[first + 1:last + 1])
    if stack:
        raise ParseError('end of file inside a conditional')
    result = b'\n'.join(out)
    return result, result != data and result != original


def main():
    defined, undefined, blank = {}, set(), False
    args = sys.argv[1:]
    while args:
        a = args.pop(0)
        if a == '-l':
            blank = True
        elif a.startswith('-D'):
            sym = a[2:] or args.pop(0)
            name, _, val = sym.partition('=')
            defined[name] = val or '1'
        elif a.startswith('-U'):
            undefined.add(a[2:] or args.pop(0))
        else:
            sys.exit(f'strip_neo_ifdefs.py: unknown option {a}')
    data = sys.stdin.buffer.read()
    try:
        result, changed = resolve(data, defined, undefined, blank)
    except ParseError as e:
        print(f'strip_neo_ifdefs.py: {e}', file=sys.stderr)
        sys.exit(2)
    sys.stdout.buffer.write(result)
    sys.exit(1 if changed else 0)


if __name__ == '__main__':
    main()
