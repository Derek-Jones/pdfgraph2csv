"""A streaming tokenizer for content streams.

qpdf (pikepdf.parse_content_stream) tokenizes quickly but returns the whole
stream at once as a list of pikepdf objects, which takes about 1 kB per
operator: a plot of 460 000 markers (2.3 million operators) needed 2.5 GB
for the list alone.  `operators()` yields one (operator, operands) pair at a
time instead, with the operands already as the Python values pdfminer.six
produces (int/float, PSLiteral names, bytes strings, lists, dicts), so memory
use does not grow with the size of the stream.

Streams with inline images (BI ... ID <binary> EI) are not handled here: the
caller uses qpdf for those (see `has_inline_image`).
"""

import re

from pdfminer.psparser import LIT

_WS = b" \t\r\n\f\x00"
_DELIM = b"()<>[]{}/%"
_REGULAR = rb"[^ \t\r\n\f\x00()<>\[\]{}/%]"

# one token per match: whitespace, comment, name, << >> [ ] { }, hex string,
# start of a literal string, or a run of regular characters (number/keyword)
_TOKEN = re.compile(
    rb"[ \t\r\n\f\x00]+"
    rb"|%[^\r\n]*"
    rb"|/" + _REGULAR + rb"*"
    rb"|<<|>>|[\[\]{}]"
    rb"|<[0-9A-Fa-f \t\r\n\f\x00]*>"
    rb"|\("
    rb"|" + _REGULAR + rb"+"
    rb"|[)<>]")
# fast path: optional whitespace, numbers (each followed by whitespace) and
# an operator (not true / false / null), ending at a delimiter or the end
_FAST = re.compile(
    rb"[ \t\r\n\f\x00]*((?:[+-]?(?:\d+\.?\d*|\.\d+)[ \t\r\n\f\x00]+)*)"
    rb"(?!(?:true|false|null)(?:[ \t\r\n\f\x00()<>\[\]{}/%]|\Z))"
    rb"([A-Za-z'\"*][A-Za-z0-9'\"*]*)(?=[ \t\r\n\f\x00()<>\[\]{}/%]|\Z)")
_PATH_OPS = {b"m", b"l", b"c", b"v", b"y"}
_INT = re.compile(rb"[+-]?\d+\Z")
_REAL = re.compile(rb"[+-]?(?:\d+\.\d*|\.\d+)\Z")
_NAME_ESC = re.compile(rb"#([0-9A-Fa-f]{2})")
_INLINE_IMAGE = re.compile(rb"(?:^|[ \t\r\n\f\x00\]>)])BI[ \t\r\n\f\x00/]")
_STRING_ESC = {ord("n"): b"\n", ord("r"): b"\r", ord("t"): b"\t", ord("b"): b"\b",
               ord("f"): b"\f", ord("("): b"(", ord(")"): b")", ord("\\"): b"\\"}
_LITERALS = {}                       # name -> PSLiteral (cached: names repeat)


class Floats(list):
    """Operands that are all floats (the coordinates of a path operator)."""
    __slots__ = ()


def has_inline_image(data):
    return _INLINE_IMAGE.search(data) is not None


def _name(tok):
    raw = tok[1:]
    lit = _LITERALS.get(raw)
    if lit is None:
        s = _NAME_ESC.sub(lambda m: bytes([int(m.group(1), 16)]), raw) if b"#" in raw else raw
        lit = _LITERALS[raw] = LIT(s.decode("latin-1"))
    return lit


def _hex(tok):
    digits = bytes(c for c in tok[1:-1] if c not in _WS)
    if len(digits) % 2:
        digits += b"0"
    return bytes.fromhex(digits.decode("ascii"))


def _literal_string(data, pos):
    """The literal string starting after the '(' at pos - 1; returns
    (bytes, position after the closing ')')."""
    out = bytearray()
    depth, n = 1, len(data)
    i = pos
    while i < n:
        c = data[i]
        if c == 0x5C:                                   # backslash
            i += 1
            if i >= n:
                break
            c = data[i]
            if c in _STRING_ESC:
                out += _STRING_ESC[c]
                i += 1
            elif 0x30 <= c <= 0x37:                     # \ddd octal
                j = i
                while j < n and j < i + 3 and 0x30 <= data[j] <= 0x37:
                    j += 1
                out.append(int(data[i:j], 8) & 0xFF)
                i = j
            elif c == 0x0D:                             # line continuation
                i += 2 if i + 1 < n and data[i + 1] == 0x0A else 1
            elif c == 0x0A:
                i += 1
            else:                                       # unknown escape: the character
                out.append(c)
                i += 1
            continue
        if c == 0x28:
            depth += 1
        elif c == 0x29:
            depth -= 1
            if depth == 0:
                return bytes(out), i + 1
        elif c == 0x0D:                                 # end of line -> \n
            out.append(0x0A)
            i += 2 if i + 1 < n and data[i + 1] == 0x0A else 1
            continue
        out.append(c)
        i += 1
    return bytes(out), n


def operators(data):
    """Yield (operator name, operands) for each operator of the content
    stream `data` (bytes)."""
    operands = []
    stack = []                       # open arrays / dictionaries
    match = _TOKEN.match
    fast = _FAST.match
    pos, n = 0, len(data)
    while pos < n:
        if not operands and not stack:
            # the common case, one regex match: numbers and an operator
            m = fast(data, pos)
            if m is not None:
                nums, op = m.group(1, 2)
                pos = m.end()
                if not nums:
                    yield op.decode("latin-1"), []
                elif op in _PATH_OPS:     # coordinates: floats, as pdfminer makes them
                    yield op.decode("latin-1"), Floats(map(float, nums.split()))
                else:
                    yield op.decode("latin-1"), [float(x) if b"." in x else int(x)
                                                 for x in nums.split()]
                continue
        m = match(data, pos)
        if m is None:                # cannot happen (every byte matches); be safe
            pos += 1
            continue
        tok = m.group()
        pos = m.end()
        c = tok[0]
        if c in _WS or c == 0x25:    # whitespace, comment
            continue
        if c == 0x2F:
            val = _name(tok)
        elif c == 0x28:
            val, pos = _literal_string(data, pos)
        elif tok == b"[" or tok == b"<<":
            stack.append((tok, operands))
            operands = []
            continue
        elif tok == b"]" or tok == b">>":
            if not stack:
                continue             # stray closing bracket
            opener, outer = stack.pop()
            if opener == b"[":
                val = operands
            else:
                it = iter(operands)
                val = {}
                for k in it:
                    v = next(it, None)
                    if hasattr(k, "name"):
                        val[k.name] = v
            operands = outer
        elif c == 0x3C and len(tok) > 1:
            val = _hex(tok)
        elif tok in (b"{", b"}", b")", b"<", b">"):
            continue
        elif _INT.match(tok):
            val = int(tok)
        elif _REAL.match(tok):
            val = float(tok)
        elif tok == b"true" or tok == b"false":
            val = tok == b"true"
        elif tok == b"null":
            val = None
        else:                        # an operator
            if stack:                # an operator inside [ ] / << >>: malformed
                operands = stack[0][1]
                stack = []
            yield tok.decode("latin-1"), operands
            operands = []
            continue
        operands.append(val)
