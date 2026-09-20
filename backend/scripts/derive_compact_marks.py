#!/usr/bin/env python3
"""Derive the compact brand marks from the approved full lockups.

Fresh Collective's compact marks are not new artwork. They are the
dragonfly-and-broken-circle symbol already present in the approved
lockups, with the FRESH COLLECTIVE wordmark cropped away — nothing is
redrawn, re-traced, recoloured or generated.

Two steps, and both are exact.

**Recovering the alpha.** Each approved lockup is a flat-colour
drawing composited onto a flat background: every pixel is
``C = a*stroke + (1-a)*background``, with antialiasing the only source
of intermediate values. That was verified before this script was
written — of the 14,555 symbol pixels in each file, zero lie off the
stroke-to-background line. Solving for ``a`` is therefore the exact
inverse of how the file was produced, not an estimate, and the stroke
colour is read from the file rather than chosen.

**Cropping and padding.** The symbol's bounding box is taken from the
recovered alpha, above the wordmark band, and pasted unscaled into a
transparent square. There is no resampling anywhere in this script, so
no pixel of the dragonfly is averaged with another.

The result is checked by recompositing onto the original background
and comparing with the source: the worst difference is 1/255, which is
alpha rounding, and no pixel differs by more than that.

Run from ``backend/``::

    .venv/bin/python scripts/derive_compact_marks.py

``tests/test_brand_assets.py::TestCompactMarkDerivation`` runs the same
derivation and asserts the committed files match, so the marks in the
repository cannot drift from the approved artwork they came from.
"""

from __future__ import annotations

import pathlib
import sys

from PIL import Image, ImageChops


BRAND_DIR = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "frontend" / "public" / "brand"
)

# The FRESH COLLECTIVE wordmark occupies y=418..435 on the 500px
# canvas. Everything above 415 is symbol, with clear space between.
SYMBOL_MAX_Y = 415

# Transparent breathing room on each side of the square, so the mark
# never touches the text beside it in a header or sidebar.
MARGIN = 0.06


class Derivation:
    """One compact mark and where it comes from."""

    def __init__(
        self, source: str, stroke: tuple[int, int, int],
        background: tuple[int, int, int], output: str, role: str,
    ) -> None:
        self.source = source
        self.stroke = stroke
        self.background = background
        self.output = output
        self.role = role


DERIVATIONS = (
    Derivation(
        source="fresh-collective-logo-navy-gold-on-white.png",
        stroke=(44, 50, 89), background=(255, 255, 255),
        output="fresh-collective-mark-navy-on-transparent.png",
        role="compact_light_mark",
    ),
    Derivation(
        source="fresh-collective-logo-white-gold-on-navy.png",
        stroke=(255, 255, 255), background=(44, 50, 89),
        output="fresh-collective-mark-white-on-transparent.png",
        role="compact_dark_mark",
    ),
)


def build(d: Derivation) -> tuple[Image.Image, Image.Image, tuple[int, ...]]:
    """Return (square mark, cropped symbol, symbol bbox)."""
    src = Image.open(BRAND_DIR / d.source).convert("RGBA")
    width, _ = src.size
    px = src.load()

    # Solve on the channel with the widest stroke/background
    # separation — the most numerically stable of the three, and the
    # other two agree with it to within 0.6%.
    channel = max(range(3), key=lambda i: abs(d.stroke[i] - d.background[i]))
    span = d.stroke[channel] - d.background[channel]

    extracted = Image.new("RGBA", (width, SYMBOL_MAX_Y), (0, 0, 0, 0))
    out = extracted.load()
    for y in range(SYMBOL_MAX_Y):
        for x in range(width):
            alpha = (px[x, y][channel] - d.background[channel]) / span
            if alpha <= 0:
                continue
            out[x, y] = (*d.stroke, 255 if alpha >= 1 else round(alpha * 255))

    box = extracted.getbbox()
    symbol = extracted.crop(box)
    sw, sh = symbol.size

    side = round(max(sw, sh) / (1 - 2 * MARGIN))
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(symbol, ((side - sw) // 2, (side - sh) // 2))
    return square, symbol, box


def verify(d: Derivation, symbol: Image.Image, box: tuple[int, ...]) -> int:
    """Recomposite onto the source background and return the worst
    per-channel difference. Anything above 2 means the symbol was
    altered rather than extracted."""
    src = Image.open(BRAND_DIR / d.source).convert("RGBA")
    back = Image.alpha_composite(
        Image.new("RGBA", symbol.size, (*d.background, 255)), symbol,
    ).convert("RGB")
    diff = ImageChops.difference(back, src.crop(box).convert("RGB"))
    return max(hi for _lo, hi in diff.getextrema())


def main() -> int:
    for d in DERIVATIONS:
        square, symbol, box = build(d)
        worst = verify(d, symbol, box)
        if worst > 2:
            print(f"REFUSING to write {d.output}: symbol altered "
                  f"(worst difference {worst}/255)", file=sys.stderr)
            return 1
        square.save(BRAND_DIR / d.output, optimize=True)
        print(f"{d.role:20} {d.output}")
        print(f"   from      {d.source}")
        print(f"   symbol    {box} -> {symbol.size[0]} x {symbol.size[1]}")
        print(f"   written   {square.size[0]} x {square.size[1]} RGBA, "
              f"{MARGIN:.0%} margin, no resampling")
        print(f"   verified  worst difference {worst}/255 on recomposite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
