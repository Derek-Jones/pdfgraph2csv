"""Opening a PDF file.

pikepdf (the qpdf library) reads the file: it repairs damaged
cross-reference tables and object offsets, and decrypts files protected
with RC4, AES-128 or AES-256 (user or owner password).  Streams whose data
cannot be decoded are emptied, with a warning, so that one corrupt stream
does not lose a page.  The cleaned, decrypted file is written to memory and
parsed by pdfminer.six, whose content-stream interpreter and font handling
the rest of the program uses (see interpreter.py).
"""

import io
import logging
import re
import zlib

import pikepdf
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfinterp import PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser

# pdfminer reports every oddity of a file through logging; the program
# reports what matters itself
logging.getLogger("pdfminer").setLevel(logging.CRITICAL)

# filters that qpdf decodes (image codecs such as DCT are left alone)
_DECODABLE = {"/FlateDecode", "/Fl", "/LZWDecode", "/LZW", "/ASCII85Decode", "/A85",
              "/ASCIIHexDecode", "/AHx", "/RunLengthDecode", "/RL"}


class PasswordError(ValueError):
    pass


def _reason(e):
    """qpdf's message without the name of the in-memory stream."""
    return re.sub(r"^stream <[^>]*>: ", "", str(e).strip())


def _salvage_flate(obj, names):
    """The part of a damaged Flate stream that does decompress, or b""."""
    if names not in (["/FlateDecode"], ["/Fl"]) or "/DecodeParms" in obj:
        return b""                         # (predictors would need undoing too)
    try:
        return zlib.decompressobj().decompress(obj.read_raw_bytes())
    except zlib.error:
        return b""


class Document:
    """A PDF file, ready for interpretation: `pages()` lists its pages
    (pdfminer PDFPage objects), `rsrcmgr` caches fonts across pages and
    `warnings` collects problems worth telling the user about."""

    def __init__(self, data, password=b""):
        if not data.startswith(b"%PDF") and b"%PDF" not in data[:1024]:
            raise ValueError("not a PDF file")
        self.warnings = []
        pdf = self._open(data, password)
        self._empty_corrupt_streams(pdf)
        buf = io.BytesIO()
        try:
            pdf.save(buf, encryption=False)           # decrypted, repaired
        except pikepdf.PdfError as e:
            raise ValueError("the file is damaged beyond repair (%s)" % _reason(e)) from None
        buf.seek(0)
        self.rsrcmgr = PDFResourceManager(caching=True)
        self._pages = list(PDFPage.create_pages(PDFDocument(PDFParser(buf))))
        if not self._pages:
            raise ValueError("no pages found (damaged file?)")

    @staticmethod
    def _open(data, password):
        """Open with pikepdf.  A password that fails is retried as empty
        (it may be the owner password of a file anyone may open)."""
        try:
            return pikepdf.open(io.BytesIO(data), password=password)
        except pikepdf.PasswordError:
            if password:
                try:
                    return pikepdf.open(io.BytesIO(data), password=b"")
                except pikepdf.PasswordError:
                    raise PasswordError("the password is not correct for this file") from None
            raise PasswordError("the file is encrypted and needs a password "
                                "(use --password)") from None
        except pikepdf.PdfError as e:
            raise ValueError("the file is damaged beyond repair (%s)" % _reason(e)) from None

    def _empty_corrupt_streams(self, pdf):
        """Decode every stream once; one that fails is replaced by an empty
        stream and reported."""
        for obj in pdf.objects:
            if not isinstance(obj, pikepdf.Stream):
                continue
            filters = obj.get("/Filter")
            if filters is None:
                continue
            names = [str(f) for f in (filters if isinstance(filters, pikepdf.Array) else [filters])]
            if not all(n in _DECODABLE for n in names):
                continue
            try:
                obj.read_bytes()
            except pikepdf.PdfError as e:
                data = _salvage_flate(obj, names)
                if data:                       # a truncated Flate stream: keep what decodes
                    obj.write(data)
                    continue
                # qpdf's own warning says what is wrong with the data
                why = [w for w in pdf.get_warnings() if "error decoding stream" in w]
                reason = why[-1].rsplit(": ", 1)[-1] if why else _reason(e)
                self.warn("a corrupt %s stream was skipped (%s)" % (
                    "/".join(n.lstrip("/") for n in names), reason))
                obj.write(b"")

    def warn(self, msg):
        """Record a warning (once) for the user."""
        if msg not in self.warnings:
            self.warnings.append(msg)

    def pages(self):
        return self._pages
