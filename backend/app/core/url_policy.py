"""What counts as a public link, and how to build one. No dependencies.

A leaf on purpose
-----------------
This module imports nothing from ``app``. It is the bottom of the
dependency graph so that ``app.core.config`` can use it while being
instantiated, which is the whole reason it exists.

The previous arrangement put these rules in ``app.core.public_url``,
which reads ``settings``. ``config`` then reached back for them inside
its own validator, so importing ``config`` cold in production ran:

    config  →  Settings()  →  _check_public_app_url
            →  app.core.public_url
            →  from app.core.config import settings   # still executing
            →  ImportError: partially initialized module

Policy and configuration are different things, and separating them
removes the cycle rather than papering over it. The dependency
direction is now strictly one-way::

    url_policy          (knows the rules, knows nothing else)
       ↑        ↑
    config    public_url                (public_url → config → url_policy)
"""

from __future__ import annotations

#: Hosts that must never appear in a member-facing link in production.
#:
#: The Render host is a working address — this is not about
#: reachability. It is the wrong *identity*: it tells a member the
#: product lives somewhere other than where it lives, and it breaks the
#: moment the service is renamed or moved.
NON_PUBLIC_HOST_MARKERS: tuple[str, ...] = (
    "onrender.com",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
)


def is_public_host(url: str) -> bool:
    """False for a URL on an internal or platform host.

    Deliberately substring-based rather than a hostname parse: the
    question is "could this have come from the wrong setting", and a
    marker anywhere in the authority is enough to answer yes.
    """
    lowered = (url or "").lower()
    return bool(lowered) and not any(
        marker in lowered for marker in NON_PUBLIC_HOST_MARKERS
    )


def offending_markers(url: str) -> list[str]:
    """Which markers make this URL unsuitable for a member-facing link.

    Returned rather than just a boolean so the boot guard can name the
    specific problem in its error message — "a onrender.com host" is
    far more actionable than "invalid".
    """
    lowered = (url or "").lower()
    return [m for m in NON_PUBLIC_HOST_MARKERS if m in lowered]


def join_public_url(base: str, path: str = "") -> str:
    """Join an origin and a path with exactly one slash.

    Pure, so the joining rules are testable without any configuration
    at all. ``public_app_url`` is the thin wrapper that supplies
    ``base`` from settings.

    Query strings and fragments pass through untouched — in the bug
    this module came from, the reset token was always correct and only
    the origin was wrong.

    Raises on an absolute URL rather than returning it unchanged or
    concatenating it onto the origin. A caller passing one has either
    already built the link — in which case routing it through here
    again is a mistake worth seeing — or is passing something
    user-supplied, which must never be reflected into an email as if it
    were ours.
    """
    origin = (base or "").rstrip("/")

    if not path:
        return origin

    if path.lower().startswith(("http://", "https://", "//")):
        raise ValueError(
            f"public_app_url() takes a path, not an absolute URL: {path!r}. "
            f"If the link is already built, use it as it is; if it came "
            f"from input, do not put it in an email."
        )

    return f"{origin}/{path.lstrip('/')}"


def canonicalise_origin(url: str | None, public_base: str) -> str | None:
    """Move a URL on a non-public host onto the public origin.

    Path, query and fragment are preserved exactly — only the scheme
    and authority change::

        https://fc-web-xxx.onrender.com/reset-password?token=X
        →  https://freshcollective.au/reset-password?token=X

    Left alone, deliberately:

      * relative URLs — in-app navigation is relative by design and
        has no origin to correct;
      * anything whose host carries no non-public marker, which means
        every genuinely external link. A Stripe or Resend URL is not
        ours to rewrite, and silently repointing one at our own domain
        would break it.

    Keyed on the marker list rather than on one known hostname, so this
    keeps working the next time the public address changes. The strict
    single-host form belongs in the one-time script that edits stored
    records — see ``replace_origin``.
    """
    if not url:
        return url
    if not url.lower().startswith(("http://", "https://")):
        return url
    if not offending_markers(url):
        return url

    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    target = urlsplit(public_base.rstrip("/"))
    return urlunsplit((
        target.scheme or parts.scheme,
        target.netloc or parts.netloc,
        parts.path,
        parts.query,
        parts.fragment,
    ))


def replace_origin(
    url: str | None, old_origin: str, new_origin: str,
) -> str | None:
    """Rewrite one exact origin, and nothing else.

    Deliberately narrower than ``canonicalise_origin``: this one edits
    stored records, so it matches a single scheme+host+port and leaves
    everything else untouched — a different ``onrender.com`` subdomain,
    an external host, a relative path. Returns the URL unchanged when
    the origin does not match exactly.
    """
    if not url:
        return url

    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    old = urlsplit(old_origin.rstrip("/"))
    if (parts.scheme.lower(), parts.netloc.lower()) != (
        old.scheme.lower(), old.netloc.lower()
    ):
        return url

    new = urlsplit(new_origin.rstrip("/"))
    return urlunsplit((
        new.scheme, new.netloc, parts.path, parts.query, parts.fragment,
    ))


__all__ = [
    "NON_PUBLIC_HOST_MARKERS",
    "is_public_host",
    "offending_markers",
    "join_public_url",
    "canonicalise_origin",
    "replace_origin",
]
