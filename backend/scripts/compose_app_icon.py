#!/usr/bin/env python3
"""Compose the Fresh Collective app icon from the approved compact mark.

An app icon is a composition, not a resized logo. It needs its own
background, its own margins and its own sizes — but it must not need
its own drawing. This script builds one from parts that already exist:

* the symbol from ``fresh-collective-mark-white-on-transparent.png``,
  itself derived from the approved lockups (see
  ``derive_compact_marks.py``), and
* the teal that the approved ``fresh-collective-logo-white-on-teal.png``
  puts behind that same white dragonfly.

So the icon is the approved white-on-teal pairing, squared up and with
the wordmark gone. Nothing is redrawn and no new colour is introduced.

Why teal and not navy
---------------------
Both are approved backgrounds and both were rendered at 16, 32, 48 and
64px before choosing. White on teal holds its contrast down to 16px;
white on navy turns into a dark blob at the sizes that matter most,
and risks vanishing entirely against a dark browser tab strip.

Why 6% of margin
----------------
Also chosen by looking: at 14% the dragonfly is a wisp by 16px, and at
0% it crowds the edge at the larger sizes. 6% keeps enough of the
symbol to survive a 16px downscale while leaving the wingtips clear of
the corners an iOS mask rounds off.

What cannot be fixed here, and is not
-------------------------------------
The mark's stroke is a hairline. At 16px it resolves to a soft winged
silhouette on Fresh Collective teal rather than a readable dragonfly,
and no amount of composition changes that — only a heavier-stroke
redraw would, which is a design decision and not one to take in a
script. At 32px and above the wings, body and broken circle all read.

Outputs (run from ``backend/``)::

    .venv/bin/python scripts/compose_app_icon.py

* ``frontend/public/brand/fresh-collective-app-icon.png`` — 512px, the
  bundled default for the ``favicon_app_icon`` role, and what World
  Management shows and can override.
* ``frontend/src/app/favicon.ico`` — 16/32/48, Next.js file convention.
* ``frontend/src/app/icon.png`` — 512px, preferred by modern browsers.
* ``frontend/src/app/apple-icon.png`` — 180px, iOS home screen.

The three static files under ``app/`` exist because Next.js resolves
icons from the filesystem at build time and cannot ask a database what
the brand is. They are generated from this one composition rather than
designed separately, and a test regenerates and compares them so they
cannot drift from the role's default or from each other.
"""

from __future__ import annotations

import pathlib

from PIL import Image


REPO = pathlib.Path(__file__).resolve().parent.parent.parent
BRAND_DIR = REPO / "frontend" / "public" / "brand"
APP_DIR = REPO / "frontend" / "src" / "app"

SOURCE_MARK = "fresh-collective-mark-white-on-transparent.png"

# The teal behind the white dragonfly in the approved
# ``…-logo-white-on-teal.png``. Read from that file, not picked.
TEAL = (36, 147, 162)

INSET = 0.06
ROLE_ASSET = "fresh-collective-app-icon.png"
ROLE_ASSET_PX = 512
ICO_SIZES = (16, 32, 48)
APPLE_PX = 180


def _symbol() -> Image.Image:
    """The dragonfly with its transparent margin trimmed, so this
    script controls the margin rather than inheriting two of them."""
    mark = Image.open(BRAND_DIR / SOURCE_MARK).convert("RGBA")
    return mark.crop(mark.getbbox())


def compose(side: int, symbol: Image.Image | None = None) -> Image.Image:
    """One square icon at ``side`` pixels.

    Each size is resampled once, straight from the symbol at its
    native resolution — never by downscaling an already-downscaled
    icon, which is how thin linework turns to mush.
    """
    symbol = symbol if symbol is not None else _symbol()
    canvas = Image.new("RGBA", (side, side), (*TEAL, 255))
    target = round(side * (1 - 2 * INSET))
    scale = target / max(symbol.size)
    width, height = round(symbol.size[0] * scale), round(symbol.size[1] * scale)
    canvas.alpha_composite(
        symbol.resize((width, height), Image.LANCZOS),
        ((side - width) // 2, (side - height) // 2),
    )
    return canvas


def main() -> int:
    symbol = _symbol()

    role_asset = compose(ROLE_ASSET_PX, symbol)
    role_asset.save(BRAND_DIR / ROLE_ASSET, optimize=True)
    print(f"brand role default   {ROLE_ASSET}  {ROLE_ASSET_PX}px")

    # ICO carries every size inside one file. Build each entry from the
    # symbol rather than letting the encoder downscale one bitmap.
    entries = [compose(s, symbol) for s in ICO_SIZES]
    entries[-1].save(
        APP_DIR / "favicon.ico", format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=entries[:-1],
    )
    print(f"favicon.ico          {', '.join(f'{s}x{s}' for s in ICO_SIZES)}")

    compose(ROLE_ASSET_PX, symbol).save(APP_DIR / "icon.png", optimize=True)
    print(f"icon.png             {ROLE_ASSET_PX}px")

    compose(APPLE_PX, symbol).save(APP_DIR / "apple-icon.png", optimize=True)
    print(f"apple-icon.png       {APPLE_PX}px")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
