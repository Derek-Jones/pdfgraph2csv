"""A streaming tokenizer for content streams.

qpdf (pikepdf.parse_content_stream) tokenizes quickly but returns the whole
stream at once as a list of pikepdf objects, which takes about 1 kB per
operator: a plot of 460 000 markers (2.3 million operators) needed 2.5 GB
for the list alone.  `operators()` yields one (operator, operands) pair at a
time instead, with the operands already as the Python values pdfminer.six
produces (int/float, PSLiteral names, bytes strings, lists, dicts), so memory
use does not grow with the size of the stream.

Inline images (BI <dict> ID <binary> EI) are yielded as ("BI", (dict,
data)): the data's end is found from its length when that is known (no
filter: width x height x components x bits; Flate: where the compressed
data ends), else at the first "EI" between white space.  A stream whose
image end cannot be found raises InlineImageError, and the caller reads
it with qpdf (see `has_inline_image`).
"""

import zlib

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


_DECIMALS = re.compile(rb"[0-9]\.([0-9]+)|[^0-9]\.([0-9]+)")


_DECIMALS_SAMPLE = 2000000  # the decimals of numbers counted in the first 2 MB
_DECIMALS_SHARE = 0.95      # the 95th percentile of their decimals
_DECIMALS_MAX = 12          # at most 12 decimals


def coordinate_decimals(data, sample=_DECIMALS_SAMPLE):
    """How many decimals the stream's numbers are written with: the 95th
    percentile of the decimals of the numbers in (the start of) the stream,
    so that one odd number does not count.  0 for whole numbers only."""
    counts = {}
    for m in _DECIMALS.finditer(data, 0, min(len(data), sample)):
        n = len(m.group(1) or m.group(2))
        counts[n] = counts.get(n, 0) + 1
    total = sum(counts.values())
    if not total:
        return 0
    seen = 0
    for n in sorted(counts):
        seen += counts[n]
        if seen >= _DECIMALS_SHARE * total:
            return min(n, _DECIMALS_MAX)
    return min(max(counts), _DECIMALS_MAX)


def has_inline_image(data):
    return _INLINE_IMAGE.search(data) is not None


class InlineImageError(ValueError):
    """An inline image whose data's end was not found."""


_II_KEYS = {"W": "Width", "H": "Height", "BPC": "BitsPerComponent", "CS": "ColorSpace",
            "F": "Filter", "DP": "DecodeParms", "IM": "ImageMask", "D": "Decode", "I": "Interpolate"}
_II_FILTERS = {"AHx": "ASCIIHexDecode", "A85": "ASCII85Decode", "LZW": "LZWDecode",
               "Fl": "FlateDecode", "RL": "RunLengthDecode", "CCF": "CCITTFaxDecode",
               "DCT": "DCTDecode"}
_II_COMPONENTS = {"G": 1, "DeviceGray": 1, "RGB": 3, "DeviceRGB": 3, "CMYK": 4,
                  "DeviceCMYK": 4, "I": 1, "Indexed": 1}
_EI = re.compile(rb"[ \t\r\n\f\x00]EI(?=[ \t\r\n\f\x00()<>\[\]{}/%]|\Z)")
_ID = re.compile(rb"(?<=[ \t\r\n\f\x00\]>)])ID(?=[ \t\r\n\f\x00])")
_EI_AFTER = re.compile(rb"[ \t\r\n\f\x00]*EI(?=[ \t\r\n\f\x00()<>\[\]{}/%]|\Z)")


_FLATE_FIRST = 512  # Flate data fed in pieces from 512 bytes
_FLATE_GROWTH = 4   # each piece 4 times the last


def _inline_image(data, pos):
    """The inline image whose dictionary starts at `pos` (just after BI):
    (dict with full key and filter names, raw data, position after EI)."""
    ops = operators_until_id(data, pos)
    if ops is None:
        raise InlineImageError("no ID")
    d, pos = ops
    start = pos + 1                   # (one white-space byte after ID)
    filters = d.get("Filter")
    filters = [] if filters is None else (filters if isinstance(filters, list) else [filters])
    filters = [_II_FILTERS.get(f.name, f.name) if hasattr(f, "name") else f for f in filters]
    d["Filter"] = filters
    end = None
    try:
        if not filters:
            w, h, bpc = int(d["Width"]), int(d["Height"]), int(d.get("BitsPerComponent", 1))
            cs = d.get("ColorSpace")
            if d.get("ImageMask"):
                comps, bpc = 1, 1
            else:
                comps = _II_COMPONENTS.get(getattr(cs, "name", None)) if cs is not None else None
                if isinstance(cs, list) and cs and getattr(cs[0], "name", None) in ("I", "Indexed"):
                    comps = 1
            if comps:
                end = start + (w * comps * bpc + 7) // 8 * h
        elif filters == ["FlateDecode"]:
            # (fed in growing pieces: handing over the rest of a long stream
            # for each of thousands of small images copies it each time)
            z = zlib.decompressobj()
            fed, step = start, _FLATE_FIRST
            while not z.eof and fed < len(data):
                z.decompress(data[fed:fed + step])
                fed = min(fed + step, len(data))
                step *= _FLATE_GROWTH
            if z.eof:
                end = fed - len(z.unused_data)
    except (KeyError, TypeError, ValueError, zlib.error):
        end = None
    if end is not None:
        m = _EI_AFTER.match(data, end)
        if m is not None:              # (the data up to EI, as qpdf gives it)
            return d, data[start:m.end() - 2], m.end()
    m = _EI.search(data, start)
    if m is None:
        raise InlineImageError("no EI")
    return d, data[start:m.end() - 2], m.end()


def inline_images_found(data):
    """Can the end of every inline image of `data` be found?  (Each "BI"
    keyword, found by pattern, read as an image, the search going on after
    its EI.)"""
    pos = 0
    while True:
        m = _INLINE_IMAGE.search(data, pos)
        if m is None:
            return True
        try:
            _, _, pos = _inline_image(data, m.end() - 1)
        except InlineImageError:
            return False


def operators_until_id(data, pos):
    """The inline image dictionary from `pos` to its ID keyword: ({full key:
    value}, position of the end of ID), or None."""
    items = []
    for name, operands in operators(data[pos:pos + 4096], images=False):
        if name == "ID":
            items += operands
            break
        return None                   # (any other operator: no image dictionary)
    else:
        return None
    m = _ID.search(data, pos)
    if m is None:
        return None
    d = {}
    it = iter(items)
    for k in it:
        v = next(it, None)
        if hasattr(k, "name"):
            d[_II_KEYS.get(k.name, k.name)] = v
    return d, m.end()


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


def operators(data, images=True):
    """Yield (operator name, operands) for each operator of the content
    stream `data` (bytes); an inline image as ("BI", (dict, raw data))."""
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
                    if op == b"BI" and images:
                        d, raw, pos = _inline_image(data, pos)
                        yield "BI", (d, raw)
                        continue
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
            if tok == b"BI" and images:
                d, raw, pos = _inline_image(data, pos)
                yield "BI", (d, raw)
                operands = []
                continue
            yield tok.decode("latin-1"), operands
            operands = []
            continue
        operands.append(val)
