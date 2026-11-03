"""Formatted descriptions: safe on the way in, plain on the way out.

A Gathering's and a Gathering Series' ``description`` carries the
creator's own formatting — paragraphs, headings, bold, italic, lists
and links — written in the same TipTap editor the Collective About
page uses, and stored as HTML in the column it has always used.

Two jobs, and they belong together because they are the same
allowlist read in both directions.

Safe on the way in
------------------
:func:`sanitize_rich_text` is the authoritative boundary. The editor
also constrains what a creator can produce, but that is a UX
constraint, not a security control — any direct HTTP call bypasses it.
``nh3`` does the work because it is already this project's HTML
authority (see ``app/community/sanitize``), and reusing it means the
URL-scheme and ``rel`` rules are decided in one place rather than
learned twice.

The allowlist is deliberately *narrower* than "rich text" and matches
exactly what the renderer displays. A tag that survives sanitising but
has no renderer would vanish silently at display time, which reads to
a creator as lost work; a tag the renderer handles but the sanitiser
strips would vanish at save time, which is worse. So the two lists are
kept the same, and ``frontend/src/components/ui/MarkdownBody.tsx`` is
the other half.

Plain on the way out
--------------------
Most surfaces are not HTML. A card, a search result, a calendar entry
and an email body all need text, and an email is the sharpest case:
``render_email_shell`` escapes everything it is given, so handing it
``<strong>Join us</strong>`` puts those angle brackets in front of a
member. :func:`rich_text_to_plain` is the one conversion, so there is
no second stripping implementation to drift.

Legacy descriptions pass through both functions unchanged: plain text
has no tags to strip and no markup to escape, and the renderer treats
anything that does not start with a tag as markdown — which is what
every existing description already was.
"""

from __future__ import annotations

import html as _html
import re

import nh3

#: Exactly what ``MarkdownBody`` renders in HTML mode. Block tags
#: first, then the inline marks.
#:
#: ``ol`` and ``li`` are here because a numbered list is one of the
#: things creators are offered. ``br`` is here because a soft line
#: break inside a paragraph is a real authoring choice.
ALLOWED_TAGS: frozenset[str] = frozenset({
    "p", "br",
    "h2", "h3",
    "ul", "ol", "li",
    "strong", "b", "em", "i",
    "a",
})

#: ``rel`` is deliberately absent — nh3 owns it via ``link_rel``, the
#: same arrangement the community sanitiser documents.
ALLOWED_ATTRIBUTES: dict[str, set[str]] = {"a": {"href", "target"}}

#: Real navigable web URLs only. Everything else — ``javascript:``,
#: ``data:``, ``vbscript:`` — is dropped by default.
URL_SCHEMES: frozenset[str] = frozenset({"http", "https"})

LINK_REL = "noopener noreferrer"

#: Tags whose boundaries are a break in the text. Replaced with a
#: space before stripping, or "one<br>two" would read as "onetwo" and
#: "<p>A</p><p>B</p>" as "AB".
_BREAKS = re.compile(
    r"</?(br|p|div|h[1-6]|li|ul|ol)\b[^>]*>", flags=re.IGNORECASE,
)
_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


#: Anything that looks like a tag. Requires a letter after the ``<``,
#: so "3 < 5" and "<3 you all" are prose rather than markup.
_TAGLIKE = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")


def sanitize_rich_text(value: str | None) -> str | None:
    """A description safe to store and to render.

    Idempotent, so sanitising an already-sanitised value is a no-op and
    a round trip through the editor does not erode content. ``None``
    and the empty string pass through as they are, so "no description"
    stays distinguishable from "an empty one".

    A value containing no markup at all is returned **byte for byte**.
    This is not an optimisation. ``nh3`` escapes text as well as
    stripping tags, so running it over the descriptions that already
    exist would turn "tea & biscuits" into "tea &amp; biscuits" and
    "3 < 5" into "3 &lt; 5" — rewriting a creator's words on the next
    save of an untouched field. Plain text is not HTML, nothing renders
    it as HTML (``MarkdownBody`` builds React nodes and never touches
    ``innerHTML``), so there is nothing to clean.

    A value that *does* contain a tag is cleaned, whether or not it
    looks like editor output — so "Hello <script>…</script>" typed
    straight at the API is handled rather than trusted for not
    beginning with a tag.
    """
    if not value:
        return value
    if not _TAGLIKE.search(value):
        return value
    return nh3.clean(
        value,
        tags=set(ALLOWED_TAGS),
        attributes={k: set(v) for k, v in ALLOWED_ATTRIBUTES.items()},
        url_schemes=set(URL_SCHEMES),
        link_rel=LINK_REL,
    )


def rich_text_to_plain(value: str | None, *, limit: int | None = None) -> str:
    """The description as text, for a surface that cannot show markup.

    Block boundaries become line breaks, so paragraphs and list items
    stay separated — an email that collapsed a description into one
    run-on line would be a different kind of wrong from one showing
    tags. Entities are resolved, because ``&amp;`` should reach a
    member as ``&``.

    ``limit`` truncates on a word boundary with an ellipsis, for a card
    or a meta description. Without it the whole text is returned.

    Returns ``""`` rather than ``None`` so callers can concatenate
    without a guard; there is no caller that needs to tell "empty"
    from "absent" at this point.
    """
    if not value:
        return ""

    spaced = _BREAKS.sub("\n", value)
    stripped = nh3.clean(spaced, tags=set(), attributes={})
    text = _html.unescape(stripped)
    # Collapse runs of spaces but keep the line structure.
    text = "\n".join(_WHITESPACE.sub(" ", line).strip() for line in text.split("\n"))
    text = _BLANK_LINES.sub("\n\n", text).strip()

    if limit is None or len(text) <= limit:
        return text

    head = text[:limit]
    cut = head.rfind(" ")
    # Only honour a word boundary that is not absurdly early, or a
    # description beginning with one very long token returns a letter.
    if cut >= int(limit * 0.75):
        head = head[:cut]
    return head.rstrip() + "…"


def rich_text_first_line(value: str | None, *, limit: int | None = None) -> str:
    """The opening line only — for a one-line card or summary row."""
    text = rich_text_to_plain(value)
    if not text:
        return ""
    first = next((line for line in text.split("\n") if line.strip()), "")
    if limit is not None and len(first) > limit:
        return rich_text_to_plain(first, limit=limit)
    return first


__all__ = [
    "ALLOWED_ATTRIBUTES",
    "ALLOWED_TAGS",
    "LINK_REL",
    "URL_SCHEMES",
    "rich_text_first_line",
    "rich_text_to_plain",
    "sanitize_rich_text",
]
