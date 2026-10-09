"""Finding media assets referenced inside columns blocks.

A columns block stores its content as a JSON envelope in the block's
``content`` text column rather than in real columns, so an image placed
in one of its cells is invisible to a query on ``media_asset_id``. The
media usage endpoint is what a creator sees before archiving an image,
and without this it would tell them an image is unused while it sits on
a published step.

The envelope is written by ``frontend/src/lib/columnsBlock.ts`` and
looks like::

    {"layout": {"kind": "columns", "variant": "50-50"},
     "cells": [{"content": "<p>…</p>"},
               {"kind": "image", "content": "",
                "image": {"assetId": "…", "url": "/uploads/…"}}]}

Two deliberate choices here.

*Parsed, not matched.* A substring search for the asset id across
``content`` would also hit a creator who happened to type that id into
a paragraph, and would report an image as in use on a step that merely
mentions it. So the envelope is parsed and only ``cells[*].image.assetId``
is compared.

*Every cell, not only the visible ones.* Narrowing a four-column layout
to two parks the other cells rather than discarding them, and a parked
image returns the moment the creator widens the layout again. It is
therefore still a reference, and archiving the asset would break it
later. The same applies to an image left behind on a cell switched back
to text. Being conservative here is the point of the endpoint: the
failure that matters is telling someone an image is safe to archive
when it is not.
"""

from __future__ import annotations

import json


def columns_image_asset_columns(content: str | None, asset_id: str) -> list[int]:
    """Which columns of this block reference ``asset_id``.

    Returns 1-based column numbers, in order. An empty list means this
    block does not reference the asset — including when ``content`` is
    not a columns envelope at all.
    """
    if not content or not asset_id:
        return []
    try:
        parsed = json.loads(content)
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, dict):
        return []

    layout = parsed.get("layout")
    if not isinstance(layout, dict) or layout.get("kind") != "columns":
        return []

    cells = parsed.get("cells")
    if not isinstance(cells, list):
        return []

    found: list[int] = []
    for index, cell in enumerate(cells):
        if not isinstance(cell, dict):
            continue
        image = cell.get("image")
        if not isinstance(image, dict):
            continue
        if image.get("assetId") == asset_id:
            found.append(index + 1)
    return found
