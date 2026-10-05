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

Where the rules live
--------------------
The *policy* — what a non-public host is, how to join an origin to a
path — is in ``app.core.url_policy``, which imports nothing. This module
only supplies the configured origin. That split is not tidiness: it is
what lets ``app.core.config`` apply the same policy in its boot
validator without importing this module and deadlocking on a
partially-initialised ``config``.
"""

from __future__ import annotations

from app.core.url_policy import (
    NON_PUBLIC_HOST_MARKERS,
    is_public_host,
    join_public_url,
    offending_markers,
)


def public_app_url(path: str = "") -> str:
    """Absolute URL for a path in the member-facing app.

        public_app_url("/spaces/embody/community/123")
        public_app_url("/reset-password?token=abc")
        public_app_url()                 # the bare origin

    Exactly one slash at the join, query and fragment preserved
    verbatim, and no opinion about what the path means. Raises on an
    absolute URL — see ``url_policy.join_public_url``.

    ``settings`` is read inside the function rather than imported at
    module scope. The joining rules in ``url_policy`` are needed by
    ``config``'s own boot validator, and keeping this module's
    dependency on ``config`` deferred to call time means no import
    order can reintroduce a cycle here.
    """
    from app.core.config import settings

    return join_public_url(settings.resolved_public_app_url, path)


__all__ = [
    "public_app_url",
    "is_public_host",
    "offending_markers",
    "NON_PUBLIC_HOST_MARKERS",
]
