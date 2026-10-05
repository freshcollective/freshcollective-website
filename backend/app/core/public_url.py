"""The one place a member-facing link is built.

Two settings looked interchangeable and were not
----------------------------------------------
``FRONTEND_ORIGIN`` answers *"which browser origin may call this API"* —
it is the CORS allow-list in ``app/main.py``. On Render it is wired to
fc-web's ``RENDER_EXTERNAL_URL``, so its value is, by construction,
``https://fc-web-….onrender.com``. That is correct for CORS: the Render
host is a real origin the browser can present.

``PUBLIC_APP_URL`` answers *"what address do we give a member"*. That is
the custom domain, and it is the only one that belongs in an email.

Every email link was built from the first one. Since ``PUBLIC_APP_URL``
was also never declared in the blueprint, the fallback chain
``public_app_url or frontend_origin`` meant even the callers that reached
for the right setting resolved to the Render host — so the bug was not
confined to the paths that got it wrong.

Why a helper rather than a convention
-------------------------------------
There were fifteen f-strings building links across resolvers, emit
services and templates, each repeating ``.rstrip("/")`` and its own
slash. Fourteen agreed and one did not, which is what shipped a Render
host into a password-reset email. One function, one source of truth,
and a source test that fails if a new f-string appears.
"""

from __future__ import annotations

from app.core.config import settings

#: Hosts that must never appear in a member-facing link in production.
#: The Render host is a working address — this is not about reachability.
#: It is the wrong *identity*: it tells a member the product lives
#: somewhere other than where it lives, and it breaks the moment the
#: service is renamed or moved.
NON_PUBLIC_HOST_MARKERS = ("onrender.com", "localhost", "127.0.0.1", "0.0.0.0")


def public_app_url(path: str = "") -> str:
    """Absolute URL for a path in the member-facing app.

        public_app_url("/spaces/embody/community/123")
        public_app_url("/reset-password?token=abc")
        public_app_url()                 # the bare origin

    Exactly one slash at the join, query and fragment preserved
    verbatim, and no opinion about what the path means.

    Raises on an absolute URL, rather than returning it unchanged or
    concatenating it onto the origin. A caller passing one has either
    already built the link — in which case routing it through here
    again is a mistake worth seeing — or is passing something
    user-supplied, which must never be reflected into an email as if it
    were ours.
    """
    base = settings.resolved_public_app_url.rstrip("/")

    if not path:
        return base

    lowered = path.lower()
    if lowered.startswith(("http://", "https://", "//")):
        raise ValueError(
            f"public_app_url() takes a path, not an absolute URL: {path!r}. "
            f"If the link is already built, use it as it is; if it came "
            f"from input, do not put it in an email."
        )

    return f"{base}/{path.lstrip('/')}"


def is_public_host(url: str) -> bool:
    """False for a URL on an internal or platform host.

    Used by the boot guard and by tests. Deliberately substring-based
    rather than a hostname parse: the question is "could this have come
    from the wrong setting", and a marker anywhere in the authority is
    enough to answer yes.
    """
    lowered = (url or "").lower()
    return bool(lowered) and not any(
        marker in lowered for marker in NON_PUBLIC_HOST_MARKERS
    )


__all__ = ["public_app_url", "is_public_host", "NON_PUBLIC_HOST_MARKERS"]
