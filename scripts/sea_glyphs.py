"""The map's Thai and Lao glyphs: vendor/glyphs/sans/3584-3839.pbf, U+0E00-0EFF, the range the page
asks for when a label holds Thai (U+0E00-0E7F) or Lao (U+0E80-0EFF), from Noto Sans Thai and Noto
Sans Lao (SIL Open Font License 1.1, vendor/glyphs/sans/OFL-NotoSans.txt beside it).

    python3 scripts/sea_glyphs.py      data/raw/fonts/NotoSans{Thai,Lao}-Regular.ttf -> vendor/glyphs/sans/3584-3839.pbf
                                       (+ 3584-3839.json, what it was made from; scripts/build.py packs the .pbf)

The glyphs are signed distance fields as the page's other ranges are (Open Sans Semibold, made by
node-fontnik): drawn at 24 px with a 3 px border, distances to 8 px, the outline at 192 of 255; a
glyph's top is its height above the baseline less 26 px, the ascent those ranges are set with, so
that Thai, Lao and Latin stand on one baseline.

MapLibre has no shaping: each character is one glyph, set one after another by its advance. So
the marks above and below a consonant are drawn where the font puts them for an ordinary
consonant, and a tone mark always in its high place, where it clears a vowel above (ที่, ບໍ່);
over a consonant with nothing above it, it stands a little high. Lao marks are drawn at the
origin in the font and moved by its own mark anchors (GPOS mark-to-base) for ກ; Thai marks are
drawn over the consonant before them already. What this cannot do: move a mark aside for a
consonant with a tall stroke (ป ฝ ฟ), or a vowel below aside for one with a tail (ฎ ฏ).
"""
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "data" / "raw" / "fonts"
OUT = ROOT / "vendor" / "glyphs" / "sans"
RANGE = (3584, 3839)
SIZE, BORDER, RADIUS, CUTOFF = 24, 3, 8, 0.25        # as node-fontnik makes the other ranges
ASCENT = 26                                          # px: top = height above the baseline - 26 (0-255.pbf: H 17 px high, top -9)
FINE = 8                                             # the outline is filled at 8 x 8 points a pixel
STEPS = 8                                            # a curve is drawn as so many straight pieces
# Tone marks in their high place, the glyph the font substitutes after a vowel above:
# Thai ่ ้ ๊ ๋ (U+0E48-0E4B), Lao ່ ້ ໊ ໋ (U+0EC8-0ECB).
HIGH = {**{cp: f"uni{cp:04X}.small" for cp in range(0x0E48, 0x0E4C)}, **{cp: f"uni{cp:04X}.small" for cp in range(0x0EC8, 0x0ECC)}}
FACES = [("NotoSansThai-Regular.ttf", (0x0E00, 0x0E7F), None),
         ("NotoSansLao-Regular.ttf", (0x0E80, 0x0EFF), "uni0E81")]      # the consonant ກ that Lao marks are set on


class Outline(BasePen):
    """A glyph's contours as lists of points, curves cut into straight pieces."""

    def __init__(self, glyphset):
        super().__init__(glyphset)
        self.contours, self.now = [], None

    def _moveTo(self, p):
        self.now = [p]
        self.contours.append(self.now)

    def _lineTo(self, p):
        self.now.append(p)

    def _qCurveToOne(self, p1, p2):
        p0 = self.now[-1]
        for k in range(1, STEPS + 1):
            t = k / STEPS
            self.now.append(((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]))

    def _curveToOne(self, p1, p2, p3):
        p0 = self.now[-1]
        for k in range(1, STEPS + 1):
            t = k / STEPS
            a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
            self.now.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))

    def _closePath(self):
        self.now = None

    _endPath = _closePath


def mark_shifts(font, base):
    """For the marks of a font that draws them at the origin: how far each is moved (font units,
    x only) to stand on `base` when it follows it, by the font's mark-to-base anchors."""
    if not base:
        return {}
    advance = font["hmtx"][base][0]
    shifts = {}
    for lookup in font["GPOS"].table.LookupList.Lookup:
        for sub in lookup.SubTable:
            sub = sub.ExtSubTable if lookup.LookupType == 9 else sub
            if getattr(sub, "LookupType", lookup.LookupType) != 4 or base not in sub.BaseCoverage.glyphs:
                continue
            anchors = sub.BaseArray.BaseRecord[sub.BaseCoverage.glyphs.index(base)].BaseAnchor
            for mark, record in zip(sub.MarkCoverage.glyphs, sub.MarkArray.MarkRecord):
                at = anchors[record.Class]
                if at is not None:
                    shifts.setdefault(mark, at.XCoordinate - advance - record.MarkAnchor.XCoordinate)
    return shifts


def field(contours, scale, dx):
    """(width, height, left, top, bitmap) of one glyph's outline at SIZE px."""
    pts = [((x + dx) * scale, y * scale) for c in contours for x, y in c]
    if not pts:
        return 0, 0, 0, -ASCENT, b""
    left, right = math.floor(min(p[0] for p in pts)), math.ceil(max(p[0] for p in pts))
    bottom, top = math.floor(min(p[1] for p in pts)), math.ceil(max(p[1] for p in pts))
    w, h = right - left, top - bottom
    W, H = w + 2 * BORDER, h + 2 * BORDER
    canvas = np.zeros((H * FINE, W * FINE), dtype=bool)
    for c in contours:            # even-odd: a counter (the hole of ອ) is a contour inside another
        if len(c) < 3:
            continue
        img = Image.new("1", (W * FINE, H * FINE), 0)
        ImageDraw.Draw(img).polygon([(((x + dx) * scale - (left - BORDER)) * FINE, ((top + BORDER) - y * scale) * FINE) for x, y in c], fill=1)
        canvas ^= np.array(img, dtype=bool)
    outside = distance_transform_edt(~canvas)
    inside = distance_transform_edt(canvas)
    signed = np.where(canvas, -(inside - 0.5), outside - 0.5) / FINE          # px, + outside the outline
    centres = signed[FINE // 2::FINE, FINE // 2::FINE][:H, :W]
    values = np.clip(np.rint(255 - 255 * (centres / RADIUS + CUTOFF)), 0, 255).astype(np.uint8)
    return w, h, left, top - ASCENT, values.tobytes()


def varint(n):
    out = bytearray()
    while True:
        byte, n = n & 0x7F, n >> 7
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def key(number, wire):
    return varint(number << 3 | wire)


def message(number, body):
    return key(number, 2) + varint(len(body)) + body


def glyph_pbf(g):
    zigzag = lambda v: (v << 1) ^ (v >> 31)
    body = key(1, 0) + varint(g["id"])
    if g["bitmap"]:
        body += message(2, g["bitmap"])
    body += (key(3, 0) + varint(g["width"]) + key(4, 0) + varint(g["height"]) + key(5, 0) + varint(zigzag(g["left"]))
             + key(6, 0) + varint(zigzag(g["top"])) + key(7, 0) + varint(g["advance"]))
    return message(3, body)


def main():
    glyphs, made = [], {"range": f"{RANGE[0]}-{RANGE[1]}", "size_px": SIZE, "border_px": BORDER, "radius_px": RADIUS,
                        "cutoff": CUTOFF, "ascent_px": ASCENT, "fonts": [], "high_tone_marks": {}, "mark_shifts": {}}
    for name, (lo, hi), base in FACES:
        path = FONTS / name
        font = TTFont(path)
        made["fonts"].append({"file": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                              "name": font["name"].getDebugName(4), "version": font["name"].getDebugName(5),
                              "license": font["name"].getDebugName(13)})
        scale = SIZE / font["head"].unitsPerEm
        glyphset, cmap, shifts = font.getGlyphSet(), font.getBestCmap(), mark_shifts(font, base)
        for cp in sorted(c for c in cmap if lo <= c <= hi and RANGE[0] <= c <= RANGE[1]):
            gname = HIGH.get(cp) if HIGH.get(cp) in glyphset else cmap[cp]
            if gname != cmap[cp]:
                made["high_tone_marks"][f"U+{cp:04X}"] = gname
            advance = font["hmtx"][cmap[cp]][0]
            dx = shifts.get(gname, shifts.get(cmap[cp], 0)) if advance == 0 else 0
            if dx:
                made["mark_shifts"][f"U+{cp:04X}"] = dx
            pen = Outline(glyphset)
            glyphset[gname].draw(pen)
            w, h, left, top, bitmap = field(pen.contours, scale, dx)
            glyphs.append({"id": cp, "bitmap": bitmap, "width": w, "height": h, "left": left, "top": top,
                           "advance": round(advance * scale)})
    stack = message(1, "Noto Sans Thai Regular,Noto Sans Lao Regular".encode()) + message(2, made["range"].encode())
    stack += b"".join(glyph_pbf(g) for g in glyphs)
    data = message(1, stack)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{made['range']}.pbf").write_bytes(data)
    made["glyphs"] = len(glyphs)
    made["sha256"] = hashlib.sha256(data).hexdigest()
    (OUT / f"{made['range']}.json").write_text(json.dumps(made, ensure_ascii=False, indent=1) + "\n")
    (OUT / "OFL-NotoSans.txt").write_bytes((FONTS / "OFL.txt").read_bytes())
    print(f"{made['range']}.pbf: {len(glyphs)} glyphs, {len(data)} bytes; high tone marks {len(made['high_tone_marks'])}, "
          f"marks moved by their anchors {len(made['mark_shifts'])}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
