#!/usr/bin/env python3
"""Generate the digit templates embedded in pdfpoints/outlined_text.py (_DIGIT_TEMPLATES).

Needs Pillow and the fonts below; the pdfpoints package itself does not.  Each digit
is rendered large, cropped to its ink, resampled to GW x GH cells (cell is
ink when more than half covered) and written as a hex bitmap plus the ink
aspect ratio (width / height).  Several fonts are used so that sans-serif,
serif and monospaced tick labels are all recognised.
"""
from PIL import Image, ImageDraw, ImageFont

GW, GH = 12, 16
FONTS = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",   # ~Arial/Helvetica
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",  # ~Times
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",   # ~Courier
]


def template(font, ch):
    img = Image.new("L", (400, 400), 0)
    ImageDraw.Draw(img).text((50, 20), ch, font=font, fill=255)
    box = img.getbbox()
    ink = img.crop(box)
    w, h = ink.size
    small = ink.resize((GW, GH), Image.BOX)
    bits = "".join("1" if small.getpixel((x, y)) > 127 else "0"
                   for y in range(GH) for x in range(GW))
    return "%0*x" % (GW * GH // 4, int(bits, 2)), w / h


def main():
    print("_DIGIT_TEMPLATES = [  # (char, aspect w/h, %dx%d bitmap rows top->bottom as hex)" % (GW, GH))
    for path in FONTS:
        font = ImageFont.truetype(path, 300)
        print("    # " + path.rsplit("/", 1)[-1])
        for ch in "0123456789":
            hx, asp = template(font, ch)
            print('    ("%s", %.3f, "%s"),' % (ch, asp, hx))
    print("]")


if __name__ == "__main__":
    main()
