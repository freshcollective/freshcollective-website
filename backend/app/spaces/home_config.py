"""Creator configuration for the member Collective Home.

One nullable JSON column on ``spaces`` rather than a table or a column
per control. The precedent is ``OfferPage.sections_config``, documented
in the model as *"a JSON blob… so shapes can evolve without a
migration"*, and the same reasoning applies: five optional settings
across five optional tiles is twenty columns that are almost always
null, and a ``CollectiveHome`` table would hold at most one row per
Collective forever.

The rule that shapes every function here: **absence is a valid,
complete configuration.** A Collective that has never opened the editor
has ``home_config = None`` and gets exactly the Phase 1 Home. A
Collective configured before a later tile type exists gets that tile
automatically, at the end, without anyone reopening the editor — which
is how Offerings arrived without a migration. So
``resolve`` always starts from the canonical defaults and lays whatever
the creator said on top — it never treats stored config as the whole
truth.

What a creator may not do is expose something the platform has turned
off. ``show_member_directory`` wins over any stored visibility for the
Members tile: the directory is a privacy setting, and a Home
configuration must not become a way around it. ``reachable_areas``
does the same job for the rest — a tile whose area this viewer cannot
reach is not offered, which is what keeps the Offerings tile out of
Collectives outside the Offerings pilot without this module knowing
anything about pilots.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


# The canonical tile vocabulary, in default display order. Adding a
# tile here is all it takes for every existing Collective to gain it.
TILE_KEYS: tuple[str, ...] = (
    "gatherings",
    "pathways",
    # Sits with the other two "things to do here" doorways rather than
    # at the end, because that is what it is. Every Collective that has
    # never opened the editor gets it here; one that HAS configured
    # gets it appended, keeping the order it chose — see ``resolve``.
    "offerings",
    "conversations",
    "messages",
    "members",
    "about",
)

# Longest a custom description may be. Two lines on a card; the client
# clamps at two as well, so anything longer would be authored and never
# seen.
MAX_DESCRIPTION_LENGTH = 160


class HomeConfigError(ValueError):
    """Raised for a configuration the server refuses to store."""


def _clean_description(value: Any) -> str | None:
    """Blank means "use the Fresh Collective default", so empty strings
    normalise to ``None`` rather than being stored as a description
    that renders as nothing."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise HomeConfigError("A tile description must be text.")
    trimmed = value.strip()
    if not trimmed:
        return None
    if len(trimmed) > MAX_DESCRIPTION_LENGTH:
        raise HomeConfigError(
            f"A tile description must be {MAX_DESCRIPTION_LENGTH} characters "
            f"or fewer; that one is {len(trimmed)}."
        )
    return trimmed


def _clean_image_url(value: Any) -> str | None:
    """Accept only what the existing media handling produces.

    ``ImagePickerField`` yields one of three things: an uploaded asset
    under ``/api/uploads/…``, an existing library asset in the same
    shape, or an external ``https://`` URL the creator pasted. Anything
    else — a ``javascript:`` URI, a bare filesystem path, a protocol
    the browser would treat as same-origin — is refused rather than
    stored and rendered later.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise HomeConfigError("A tile image must be a URL.")
    trimmed = value.strip()
    if not trimmed:
        return None
    if trimmed.startswith("/api/uploads/") or trimmed.startswith("https://"):
        return trimmed
    raise HomeConfigError(
        "A tile image must be an uploaded asset or an https:// URL."
    )


def validate(raw: Any) -> dict[str, Any] | None:
    """Normalise a creator-supplied configuration for storage.

    Returns ``None`` for an empty configuration so the column stays
    null and the Collective keeps the plain default path.

    Unknown tile keys are **ignored rather than rejected**: a client
    from a future release that knows about a sixth tile should not be
    able to make an older server reject the whole payload, and a tile
    that was removed from the platform should not strand a creator
    unable to save anything else.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise HomeConfigError("Home configuration must be an object.")

    tiles = raw.get("tiles")
    if tiles is None:
        return None
    if not isinstance(tiles, list):
        raise HomeConfigError("Home configuration tiles must be a list.")
    if len(tiles) > len(TILE_KEYS) * 2:
        raise HomeConfigError("Too many tiles in the Home configuration.")

    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in tiles:
        if not isinstance(entry, dict):
            raise HomeConfigError("Each Home tile must be an object.")
        key = entry.get("key")
        if not isinstance(key, str) or key not in TILE_KEYS:
            continue  # unknown or malformed key — ignore, do not reject
        if key in seen:
            continue  # a duplicate would make ordering ambiguous
        seen.add(key)

        visible = entry.get("visible", True)
        if not isinstance(visible, bool):
            raise HomeConfigError("A tile's visibility must be true or false.")

        cleaned.append({
            "key": key,
            "visible": visible,
            "image_url": _clean_image_url(entry.get("image_url")),
            "description": _clean_description(entry.get("description")),
        })

    if not cleaned:
        return None

    # Order is the array order. An explicit ``position`` is honoured if
    # the caller sent one — older clients may — but it is not stored,
    # because two sources of truth for order is one too many.
    if all(isinstance(t.get("position"), int) for t in tiles if isinstance(t, dict)):
        by_key = {t["key"]: t.get("position") for t in tiles if isinstance(t, dict) and t.get("key") in seen}
        cleaned.sort(key=lambda t: by_key.get(t["key"], 0))

    return {"tiles": cleaned}


def _carry_forward_entry(entry: Any) -> dict[str, Any] | None:
    """Re-normalise a stored tile before storing it again, or ``None``.

    The row was validated when it was first saved, but it is being
    written back, and a hand-edited or hand-migrated column should not
    get a free pass on the way through. So it goes through the same two
    cleaners the write path uses.

    Returns ``None`` rather than raising when a row cannot be cleaned:
    the creator is saving a *different* tile, and failing their save on
    a tile the editor never showed them would be unfixable from the UI.
    """
    if not isinstance(entry, dict):
        return None
    key = entry.get("key")
    if not isinstance(key, str) or key not in TILE_KEYS:
        return None
    visible = entry.get("visible", True)
    if not isinstance(visible, bool):
        visible = True
    try:
        return {
            "key": key,
            "visible": visible,
            "image_url": _clean_image_url(entry.get("image_url")),
            "description": _clean_description(entry.get("description")),
        }
    except HomeConfigError:
        return None


def merge_unavailable(
    stored: Any,
    cleaned: dict[str, Any] | None,
    *,
    available_keys: Iterable[str],
) -> dict[str, Any] | None:
    """Carry forward the configuration of tiles the editor could not show.

    The problem this solves
    ----------------------
    ``available_keys`` narrows the vocabulary by two platform switches
    the creator does not own: ``show_member_directory`` for Members,
    and the Offerings feature flag plus pilot scope for Offerings. The
    editor is handed the narrowed list and does not render a row for
    anything outside it — correctly, since a control that cannot take
    effect is worse than no control.

    But the save is a whole-document PUT. So a creator who had
    configured a tile, lost access to the feature behind it, and then
    changed something unrelated used to have that tile's description,
    image, visibility and position quietly deleted — and getting the
    feature back gave them a default tile at the end of the list rather
    than the one they had set up.

    So the stored entry is reattached here, after validation and before
    the write.

    Why it is safe
    --------------
    Nothing from the **request** is trusted by this function. It only
    re-stores what was already in the column, re-cleaned on the way
    through by :func:`_carry_forward_entry`. A creator still cannot
    configure a tile they are not permitted to configure — the request
    cannot reach a key the editor did not offer, and ``resolve`` drops
    an unavailable tile from the member Home regardless of what is
    stored. A carried-forward entry is invisible until the platform
    switch says otherwise.

    Relative position
    -----------------
    Preserved against the tile it used to sit **before**, not against
    an index. "Offerings came just before Conversations" survives the
    creator reordering everything else; a remembered index would not.
    A tile stored last is appended last.
    """
    available = set(available_keys)
    stored_tiles = (
        stored.get("tiles")
        if isinstance(stored, dict) and isinstance(stored.get("tiles"), list)
        else None
    )
    if not stored_tiles:
        return cleaned

    result: list[dict[str, Any]] = list(
        (cleaned or {}).get("tiles") or []
    )
    present = {t["key"] for t in result}
    stored_keys = [
        e.get("key") if isinstance(e, dict) else None for e in stored_tiles
    ]

    for index, entry in enumerate(stored_tiles):
        key = stored_keys[index]
        if key in available:
            continue  # the editor could show it; the request is authoritative
        carried = _carry_forward_entry(entry)
        if carried is None or carried["key"] in present:
            continue
        # The first tile that followed it and is still in the document
        # becomes its anchor.
        anchor = next(
            (k for k in stored_keys[index + 1:] if k in present), None,
        )
        if anchor is None:
            result.append(carried)
        else:
            at = next(i for i, t in enumerate(result) if t["key"] == anchor)
            result.insert(at, carried)
        present.add(carried["key"])

    # A configuration that is nothing but carried-forward tiles is still
    # a configuration worth keeping — clearing the column would lose
    # exactly what this function exists to protect.
    return {"tiles": result} if result else None


def resolve(
    stored: Any, *, show_member_directory: bool,
    reachable_areas: set[str] | frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """The tile list the member Home should render.

    Always built from :data:`TILE_KEYS` outwards, so a tile the stored
    config has never heard of still appears — at the end, with
    defaults. Configured tiles keep their configured order; the rest
    follow in canonical order.
    """
    configured: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    if isinstance(stored, dict) and isinstance(stored.get("tiles"), list):
        for entry in stored["tiles"]:
            if not isinstance(entry, dict):
                continue
            key = entry.get("key")
            if key in TILE_KEYS and key not in configured:
                configured[key] = entry
                order.append(key)

    # Configured tiles first in their chosen order, then anything the
    # configuration predates, in canonical order.
    ordered = order + [k for k in TILE_KEYS if k not in configured]

    out: list[dict[str, Any]] = []
    for key in ordered:
        entry = configured.get(key, {})
        visible = bool(entry.get("visible", True))
        # The platform's own switch is not overridable by configuration.
        # Area policy decides which doorways exist for this viewer.
        # The Home must not offer a tile whose route and API will
        # refuse — the nav and the tiles read the same resolved set so
        # they cannot disagree. ``None`` means "not supplied", which
        # keeps every existing caller behaving as before.
        if reachable_areas is not None and key not in reachable_areas:
            continue
        if key == "members" and not show_member_directory:
            continue
        if not visible:
            continue
        out.append({
            "key": key,
            "image_url": entry.get("image_url") or None,
            "description": entry.get("description") or None,
        })
    return out
