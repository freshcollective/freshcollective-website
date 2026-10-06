"""Error reporting, with a scrubber that fails closed.

What this is for
----------------
Until now a production failure left a traceback on stdout and nothing
else. 65 ``logger.exception`` sites log and continue — a notification
that never sent, a webhook handler that partially failed — and every
one of them was invisible unless somebody happened to be reading Render
logs at the time. This makes those visible.

Deliberately dependency-free
----------------------------
This module imports nothing from ``app``. ``APP_ENV`` is read straight
from the environment rather than through ``settings``, which costs one
duplicated default (asserted equal by a test) and buys two things: a
cron can call ``init_sentry()`` as its very first statement, and no
import order can ever make this participate in a cycle. ``config``
already learned that lesson the hard way — see ``app/core/url_policy.py``.

Scope
-----
Errors only. ``traces_sample_rate=0``, no profiling, no session replay,
no performance instrumentation beyond what error capture needs. The
FastAPI and logging integrations come from the SDK's defaults; nothing
here widens what they capture.

Phase 1 was fc-api. Phase 2 added the seven cron jobs, which need two
things a web process does not: an explicit :func:`flush_sentry` before
a short-lived process exits, and :func:`capture_job_summary` for the
runs that finish *successfully* while leaving something a person has to
act on. Render stays the alarm for "the cron exited non-zero"; these
two cover the failures that exit zero.

On ``data_collection`` (SDK 2.71)
--------------------------------
The SDK now offers a structured ``data_collection`` option that
supersedes ``send_default_pii``. We deliberately do not use it.

Supplying it wins over ``send_default_pii`` outright and fills every
*omitted* field with the permissive spec default — ``user_info=True``,
``stack_frame_variables=True``, ``database_query_data=True``,
``queues=True``, GraphQL and gen-AI capture on. So a partial dict,
written in good faith to express "collect less", silently turns on
member identity and frame locals, and deprecates the one switch that
currently says no to all of it.

``send_default_pii=False`` plus ``include_local_variables=False``
already resolve to exactly the restrictive configuration we want —
``test_cron_observability`` asserts the resolved dict field by field,
so an SDK upgrade that changes the mapping fails a test rather than
quietly starting to collect. Revisit only with a reason better than
the age of the API.

The scrubber fails closed
-------------------------
If ``before_send`` raises, the event is **dropped** rather than sent
unscrubbed. A missing error report costs debugging time; a member's
password-reset token sitting in a third-party service is a different
kind of problem, and not one that can be taken back. The failure is
logged, so a broken scrubber is visible in Render logs rather than
silent.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

#: Mirrors ``Settings.app_env``'s default. Duplicated so this module
#: stays dependency-free; ``test_observability`` asserts the two agree.
DEFAULT_APP_ENV = "development"

#: Substring matched case-insensitively against key, header and field
#: names. A hit means the value is replaced, never the key removed —
#: knowing that an ``Authorization`` header was present is useful;
#: knowing its contents is not.
SENSITIVE_KEY_PARTS: tuple[str, ...] = (
    "token",            # covers access_token, refresh_token, reset_token,
                        # verification_token, claim_token, x-internal-token
    "authorization",
    "cookie",           # covers set-cookie
    "stripe-signature",
    "stripe_signature",
    "password",
    "secret",
    "passwd",
    "api_key",
    "apikey",
    "bearer",
    "session",
    "jwt",
    # The three absolute links that carry a single-use credential in
    # their query string. Named explicitly because "url" on its own is
    # far too broad to redact.
    "reset_url",
    "verify_url",
    "accept_url",
)

#: Query parameters whose value is a credential.
SENSITIVE_QUERY_PARAMS: tuple[str, ...] = (
    "token", "access_token", "refresh_token", "reset_token",
    "verification_token", "claim_token", "code", "secret", "password",
)

REDACTED = "[redacted]"
REDACTED_EMAIL = "[email redacted]"

#: ``key=value`` inside free text — an exception message that
#: interpolated a URL, most often. Stops at whitespace, ``&``, quotes
#: and closing brackets so only the value is taken.
_INLINE_SECRET = re.compile(
    r"(?i)\b(" + "|".join(SENSITIVE_QUERY_PARAMS) + r")=([^\s&'\"<>\)\]]+)"
)

#: ``Bearer <value>`` in free text. An exception that interpolated a
#: header value does not write it as ``key=value``, so the pattern
#: above cannot see it — this is the one credential shape that
#: announces itself by a prefix instead of a name. Deliberately tight:
#: the word, whitespace, then one run of token characters.
_INLINE_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-~+/=]+")

#: Ordinary email shapes only. Kept deliberately plain: a greedier
#: pattern starts eating Stripe ids and exception text, and a redacted
#: stack trace is worth less than a redacted address.
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")

#: Guard against a pathological structure costing more than the event
#: is worth.
_MAX_DEPTH = 8


def _is_sensitive_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def redact_text(value: str) -> str:
    """Redact inline secrets and email addresses in free text.

    Applied to exception messages, log messages and breadcrumb text —
    never to an exception *type*, a module name or a stack frame, which
    is where the debugging value lives.
    """
    value = _INLINE_SECRET.sub(lambda m: f"{m.group(1)}={REDACTED}", value)
    value = _INLINE_BEARER.sub(f"Bearer {REDACTED}", value)
    return _EMAIL.sub(REDACTED_EMAIL, value)


def _scrub(value: Any, depth: int = 0) -> Any:
    """Recursively redact sensitive keys and text."""
    if depth > _MAX_DEPTH:
        return REDACTED
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, inner in value.items():
            if _is_sensitive_key(key):
                out[key] = REDACTED
            else:
                out[key] = _scrub(inner, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        scrubbed = [_scrub(v, depth + 1) for v in value]
        return type(value)(scrubbed) if isinstance(value, tuple) else scrubbed
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_url(url: str) -> str:
    """Strip credential-bearing query parameters from a URL.

    The path is left alone — ``/api/uploads/media/{slug}/…`` is useful
    for knowing *where* something broke. Only the query string loses
    values, and only for the named parameters.
    """
    if "?" not in url:
        return url
    base, _, query = url.partition("?")
    return f"{base}?{_redact_query(query)}" if query else url


def _redact_query(query: str) -> str:
    parts = []
    for pair in query.split("&"):
        if not pair:
            continue
        name, sep, _value = pair.partition("=")
        if sep and name.lower() in SENSITIVE_QUERY_PARAMS:
            parts.append(f"{name}={REDACTED}")
        else:
            parts.append(pair)
    return "&".join(parts)


def _scrub_request(request: dict[str, Any]) -> dict[str, Any]:
    out = dict(request)

    # The body, unconditionally. ``max_request_body_size="never"``
    # already prevents it; this is the belt to that braces, because a
    # Stripe webhook body carries a customer's email and a reset
    # request carries a raw token.
    out.pop("data", None)
    out.pop("cookies", None)

    headers = out.get("headers")
    if isinstance(headers, dict):
        out["headers"] = {
            name: (REDACTED if _is_sensitive_key(name) else value)
            for name, value in headers.items()
        }

    if isinstance(out.get("url"), str):
        out["url"] = redact_url(out["url"])
    if isinstance(out.get("query_string"), str):
        out["query_string"] = _redact_query(out["query_string"])

    if isinstance(out.get("env"), dict):
        # WSGI/ASGI env can carry the raw query string and remote addr.
        out["env"] = {
            k: (REDACTED if _is_sensitive_key(k) else v)
            for k, v in out["env"].items()
            if k not in ("QUERY_STRING",)
        }

    return out


def scrub_event(
    event: dict[str, Any], hint: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """``before_send`` — redact, or drop the event trying.

    Returns ``None`` only on an internal failure, which drops the
    event. That is the deliberate direction: unscrubbed is worse than
    absent.
    """
    try:
        scrubbed = dict(event)

        request = scrubbed.get("request")
        if isinstance(request, dict):
            scrubbed["request"] = _scrub_request(request)

        for key in ("extra", "contexts", "tags"):
            section = scrubbed.get(key)
            if isinstance(section, dict):
                scrubbed[key] = _scrub(section)

        # Exception messages keep their type and stack; only the
        # human-readable value is cleaned.
        exception = scrubbed.get("exception")
        if isinstance(exception, dict) and isinstance(
            exception.get("values"), list
        ):
            values = []
            for entry in exception["values"]:
                if isinstance(entry, dict) and isinstance(
                    entry.get("value"), str
                ):
                    entry = {**entry, "value": redact_text(entry["value"])}
                values.append(entry)
            scrubbed["exception"] = {**exception, "values": values}

        # Logging-integration events carry their text in three places
        # and only one of them is obvious:
        #
        #   message   — the format template, e.g. "failed for %s"
        #   formatted — the *interpolated* result, which is what Sentry
        #               displays and where the secret actually lands
        #   params    — the raw argument values, with no key to identify
        #               them by
        #
        # Scrubbing ``message`` alone passes a naive test and leaks the
        # real thing. ``params`` is dropped outright rather than
        # scrubbed: a bare value carries no name, so no key-based rule
        # can recognise it, and ``formatted`` already holds everything
        # the message needs to be readable.
        logentry = scrubbed.get("logentry")
        if isinstance(logentry, dict):
            cleaned = dict(logentry)
            for field in ("message", "formatted"):
                if isinstance(cleaned.get(field), str):
                    cleaned[field] = redact_text(cleaned[field])
            cleaned.pop("params", None)
            scrubbed["logentry"] = cleaned
        if isinstance(scrubbed.get("message"), str):
            scrubbed["message"] = redact_text(scrubbed["message"])

        breadcrumbs = scrubbed.get("breadcrumbs")
        if isinstance(breadcrumbs, dict) and isinstance(
            breadcrumbs.get("values"), list
        ):
            scrubbed["breadcrumbs"] = {
                **breadcrumbs,
                "values": [_scrub(b) for b in breadcrumbs["values"]],
            }

        # An opaque id answers "which member hit this". An address and a
        # name answer questions nobody asked.
        user = scrubbed.get("user")
        if isinstance(user, dict):
            kept = {k: v for k, v in user.items() if k == "id"}
            scrubbed["user"] = kept or None
            if scrubbed["user"] is None:
                scrubbed.pop("user")

        return scrubbed
    except Exception:
        logger.warning(
            "observability: the Sentry scrubber failed, so the event was "
            "dropped rather than sent unscrubbed",
            exc_info=True,
        )
        return None


def init_sentry(component: str) -> bool:
    """Start error reporting for one process. True if it was enabled.

    A missing or empty ``SENTRY_DSN`` is a clean no-op — local
    development and the test suite run with no DSN and must behave
    exactly as before, including making no network calls.

    Safe to call more than once; the SDK replaces the client.
    """
    dsn = (os.environ.get("SENTRY_DSN") or "").strip()
    if not dsn:
        logger.info(
            "observability: SENTRY_DSN is not set — error reporting is off "
            "for %s", component,
        )
        return False

    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=(os.environ.get("APP_ENV") or DEFAULT_APP_ENV).strip(),
        # Render supplies this. Absent elsewhere, and ``None`` simply
        # means "no release", which is correct rather than a fake one.
        release=(os.environ.get("RENDER_GIT_COMMIT") or "").strip() or None,
        # --- privacy ---------------------------------------------------
        send_default_pii=False,
        max_request_body_size="never",
        # Frame locals in ``auth/`` and ``webhooks/`` hold raw tokens and
        # Stripe objects. Off until there is a specific debugging need
        # that justifies turning them on with a narrower scrubber.
        include_local_variables=False,
        before_send=scrub_event,
        # --- errors only, Phase 1 --------------------------------------
        traces_sample_rate=0,
        profiles_sample_rate=0,
        # Default integrations stay on: the Starlette/FastAPI pair
        # captures unhandled requests, LoggingIntegration turns
        # ERROR-level logs into events. Neither is widened.
        #
        # ``failed_request_status_codes`` keeps its 500-599 default, so
        # a handled 4xx stays out — and the knob that decides this
        # lives on **StarletteIntegration**, not FastApiIntegration.
        # Measured, because it is not obvious: giving
        # ``FastApiIntegration`` a 4xx range changes nothing, while
        # giving it to ``StarletteIntegration`` turns every member
        # mistake into an issue. Tune the right one if you ever need to.
        default_integrations=True,
    )
    # Both the event handler and the breadcrumb handler consult this,
    # which is the whole point — see RENDER_ONLY_LOGGER_SUFFIX.
    from sentry_sdk.integrations.logging import ignore_logger

    for pattern in NEVER_REPORTED_LOGGERS:
        ignore_logger(pattern)

    sentry_sdk.get_global_scope().set_tag("component", component)
    return True


#: A logger whose name ends in this is for Render's logs only. It
#: produces neither an issue nor a breadcrumb on somebody else's issue.
#:
#: The need is specific and was found by a test rather than reasoned
#: about. The Connect sweepers log the ids of the transfers still owed,
#: because acting on them means opening those rows — and a log line at
#: WARNING becomes a *breadcrumb* attached to the next event the
#: process sends. So the counted summary went out clean and the same
#: ids arrived beside it anyway, through a channel nobody had looked
#: at. Scrubbing could not help: an internal id is not email-shaped and
#: carries no key to match on.
#:
#: A suffix rather than a list of names, so this needs no second source
#: of truth to keep in step, and the logger's own name says what it is.
RENDER_ONLY_LOGGER_SUFFIX = ".ids"

#: Patterns excluded from reporting entirely, registered at init.
#: ``fnmatch``, matched against the logger name.
NEVER_REPORTED_LOGGERS: tuple[str, ...] = (f"*{RENDER_ONLY_LOGGER_SUFFIX}",)

#: How long a dying process will wait for the network. Short: a cron
#: must not hang on error reporting, and the business work is already
#: done and committed by the time this runs.
FLUSH_TIMEOUT_SECONDS = 5.0

#: Substituted for a summary value that is not a count. The key is kept
#: so the mistake is visible in Sentry rather than silent.
DROPPED_NOT_A_COUNT = "[dropped: not a count]"

#: Levels a job summary may use. A summary is never ``info`` — a run
#: with nothing to act on must send nothing at all.
JOB_SUMMARY_LEVELS = ("warning", "error")


def flush_sentry(timeout: float = FLUSH_TIMEOUT_SECONDS) -> None:
    """Hand anything queued to the network before the process exits.

    A cron is a few seconds long. The SDK sends from a background
    worker, so a process that exits the moment its work is done can
    drop the event that explains why it failed. The SDK's own atexit
    hook would usually catch that, with a 2-second budget; this makes
    it explicit, bounded, and visible in the script that depends on it.

    Never raises, and never blocks longer than ``timeout``. A Sentry
    outage must not turn a successful reconciliation into a failed
    cron — so every failure here is swallowed, and the caller's exit
    code is the caller's own.
    """
    try:
        import sentry_sdk

        if not sentry_sdk.get_client().is_active():
            return
        sentry_sdk.flush(timeout=timeout)
    except Exception:
        logger.warning(
            "observability: flushing Sentry failed — the job's own outcome "
            "is unaffected",
            exc_info=True,
        )


def capture_job_summary(
    message: str, *, level: str = "warning", **counts: int,
) -> str | None:
    """Report one actionable partial failure for a run that exits zero.

    The gap this closes: a sweep can finish exactly as designed and
    still leave a creator unpaid or a refund unresolved. The process
    exits 0, Render sees a healthy cron, and the only trace is a log
    line nobody is reading.

    One event per run, not one per affected row. Sentry groups on the
    message, so a condition that persists becomes a single issue with a
    rising count rather than a stream of near-duplicates.

    **Counts only.** Every value is required to be an ``int``; anything
    else — a list of transaction ids, a Stripe object, an address — is
    replaced with :data:`DROPPED_NOT_A_COUNT`. That is a structural
    guarantee rather than a convention: the aggregate is what a person
    needs in order to decide to go and look, and the ids are already in
    the Render log, which is where acting on them belongs.

    Returns the event id, or ``None`` when reporting is off — which is
    every local run and the whole test suite.
    """
    if level not in JOB_SUMMARY_LEVELS:
        logger.warning(
            "observability: %r is not a job-summary level, using 'warning'",
            level,
        )
        level = "warning"

    safe: dict[str, Any] = {}
    for key, value in counts.items():
        if isinstance(value, int):
            safe[key] = value
        else:
            logger.warning(
                "observability: job summary field %r was dropped — a "
                "summary carries counts, not values",
                key,
            )
            safe[key] = DROPPED_NOT_A_COUNT

    try:
        import sentry_sdk

        if not sentry_sdk.get_client().is_active():
            return None
        with sentry_sdk.new_scope() as scope:
            for key, value in safe.items():
                scope.set_extra(key, value)
            return sentry_sdk.capture_message(message, level=level)
    except Exception:
        logger.warning(
            "observability: reporting a job summary failed — the job's own "
            "outcome is unaffected",
            exc_info=True,
        )
        return None


__all__ = [
    "init_sentry",
    "flush_sentry",
    "capture_job_summary",
    "scrub_event",
    "redact_text",
    "redact_url",
    "SENSITIVE_KEY_PARTS",
    "SENSITIVE_QUERY_PARAMS",
    "DEFAULT_APP_ENV",
    "REDACTED",
    "DROPPED_NOT_A_COUNT",
    "NEVER_REPORTED_LOGGERS",
    "RENDER_ONLY_LOGGER_SUFFIX",
    "FLUSH_TIMEOUT_SECONDS",
    "JOB_SUMMARY_LEVELS",
]
