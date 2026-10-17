"""A plain-text opening line for a Conversation that has no title.

``CommunityPost.title`` is optional, and an untitled discussion used
to reach Recent Moments as the literal words "New conversation" — a
row that said nothing about itself, in a list whose whole job is to
say what happened.

Why the body cannot simply be sliced
------------------------------------

``body`` is sanitised HTML (see ``sanitize``): the creator composer
emits ``<p>``, ``<br>``, ``<a>`` and a small set of inline tags. Three
things follow.

* Tags must be removed, not truncated through. ``"<p>Hello"[:4]`` is
  ``"<p>H"``, which renders as nothing at all.
* Entities must be resolved before measuring, or ``&amp;`` spends five
  characters to show one, and a cut can land inside one.
* The result is inserted as text, never as markup. Stripping is for
  legibility; the safety boundary stays where it is, in ``sanitize``.

``nh3`` is already a dependency and already the project's HTML
authority, so it does the stripping here too rather than a regex
learning the same lesson a second time.
"""

from __future__ import annotations

import html
import re

import nh3

#: Roughly one line in the Recent Moments row. Long enough to carry a
#: real opening clause, short enough that the row stays one line at a
#: narrow width.
DEFAULT_LIMIT = 100

#: An ellipsis is appended only when something was actually cut.
_ELLIPSIS = "…"

_WHITESPACE = re.compile(r"\s+")


def plain_text_excerpt(body: str | None, *, limit: int = DEFAULT_LIMIT) -> str | None:
    """A short, safe, plain-text opening of ``body``.

    Returns ``None`` when there is nothing to show — an empty body, or
    one that was only markup — so the caller can fall back rather than
    render an empty string.

    Cuts on a word boundary where one is available in the last quarter
    of the budget; a single long word is cut mid-word rather than
    dropped, because returning nothing would be worse than returning
    something clipped.
    """
    if not body:
        return None

    # Tags out, text kept. ``<br>`` and block tags become nothing, so
    # insert a space first or "one<br>two" would read as "onetwo".
    spaced = re.sub(r"<(br|/p|/div|p|div)\b[^>]*>", " ", body, flags=re.IGNORECASE)
    stripped = nh3.clean(spaced, tags=set(), attributes={})
    text = _WHITESPACE.sub(" ", html.unescape(stripped)).strip()
    if not text:
        return None

    if len(text) <= limit:
        return text

    head = text[:limit]
    cut = head.rfind(" ")
    # Only honour a word boundary that is not absurdly early, or a
    # body beginning with one very long token would return a single
    # letter.
    if cut >= int(limit * 0.75):
        head = head[:cut]
    return head.rstrip() + _ELLIPSIS
