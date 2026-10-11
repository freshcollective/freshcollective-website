"""The Stripe calls a creator's Connect account needs, and nothing else.

Same discipline as ``discount_stripe_sessions``: every function here is a
network call whose *failure mode* is part of the correctness argument, so
the exception types make the distinction explicit rather than leaving it
to error-message matching. Nothing here writes to the database, and
nothing here decides policy — it reports what Stripe said.

Which API for which question
----------------------------
v2 owns the account: its configuration, its capability statuses and its
requirement entries. v1 is used for exactly two things that have no v2
representation at all — the external-account list and
``settings.payouts`` — verified by retrieving the same account both ways
and finding no ``schedule``, ``delay_days``, ``external_account`` or
``bank`` anywhere in the v2 object.

Mode safety
-----------
An ``acct_…`` created under a test key is invisible to a live key and
vice versa: Stripe answers ``resource_missing``, which maps to
:class:`ConnectAccountNotFound` here. That is a real guard rather than a
convention, but it is the *second* one — callers must still refuse to use
a row whose ``stripe_mode`` differs from the current environment, because
"not found" is a poor way to learn you were about to cross modes.
"""

from __future__ import annotations

import logging
from typing import Any

import stripe

from app.checkout.stripe_client import get_stripe, get_stripe_client
from app.core.config import settings

logger = logging.getLogger(__name__)

#: What to ask v2 for. Without ``include`` the capability statuses and
#: requirement entries are simply absent from the response, and the
#: projection would read an empty configuration as "restricted".
ACCOUNT_INCLUDES = [
    "configuration.recipient",
    "requirements",
    "defaults",
    "identity",
]


class ConnectError(RuntimeError):
    """Base for every failure in this module."""


class ConnectRejected(ConnectError):
    """Stripe understood the request and refused it.

    Terminal: retrying the identical request gets the identical answer.
    Carries Stripe's ``code`` where one was given so callers can branch
    on it without parsing prose. Authentication and permission failures
    land here too — Stripe did refuse, and retrying will not help; what
    needs fixing is the environment, not the timing.
    """

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class ConnectUnavailable(ConnectError):
    """Stripe could not be asked, or gave an answer we cannot act on.

    The caller must treat this as "unknown", never as a negative result.
    Retryable. Nothing already stored should be overwritten on the
    strength of it.
    """


class ConnectAccountUnusable(ConnectError):
    """The account exists in FC's records but cannot be worked with."""


class ConnectAccountNotFound(ConnectAccountUnusable):
    """Stripe does not recognise this account id.

    Most often a genuine deletion — but also exactly what a mode mismatch
    looks like, so this is never evidence that an account never existed.
    """


class ConnectAccountClosed(ConnectAccountUnusable):
    """The account is closed. It cannot onboard and cannot receive money."""


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


_MISSING_CODES = frozenset({"resource_missing", "account_invalid"})
_CLOSED_MARKERS = ("closed", "rejected")


def _translate(exc: stripe.StripeError, *, what: str) -> ConnectError:
    """Map a Stripe exception onto this module's vocabulary.

    Split on "did Stripe answer?" first, because that is the distinction
    callers act on. Everything transport-shaped is retryable; everything
    Stripe decided is not.
    """
    code = getattr(exc, "code", None)

    if isinstance(exc, (stripe.APIConnectionError, stripe.RateLimitError)):
        return ConnectUnavailable(f"{what}: Stripe could not be reached: {exc}")

    if isinstance(exc, stripe.InvalidRequestError):
        if code in _MISSING_CODES:
            return ConnectAccountNotFound(f"{what}: {exc}")
        message = str(exc).lower()
        if any(marker in message for marker in _CLOSED_MARKERS):
            return ConnectAccountClosed(f"{what}: {exc}")
        return ConnectRejected(f"{what}: {exc}", code=code)

    if isinstance(exc, (stripe.PermissionError, stripe.AuthenticationError)):
        return ConnectRejected(f"{what}: {exc}", code=code or "not_permitted")

    if isinstance(exc, stripe.IdempotencyError):
        return ConnectRejected(f"{what}: {exc}", code=code or "idempotency_error")

    if isinstance(exc, stripe.APIError):
        # A 5xx from Stripe. Retryable, and we know nothing about whether
        # the write landed.
        return ConnectUnavailable(f"{what}: Stripe API error: {exc}")

    return ConnectUnavailable(f"{what}: unclassified Stripe error: {exc}")


def _to_dict(value: Any) -> dict[str, Any]:
    """Plain dict, so the projection layer never touches a StripeObject.

    ``dict(value)`` was wrong for a v2 resource. A ``StripeObject`` in
    stripe 15.x is not a mapping — no ``keys()``, no ``__iter__``, only
    ``__getitem__`` — so ``dict()`` falls back to the legacy sequence
    protocol, asks the account for index ``0`` and gets ``KeyError: 0``.
    That is not a ``TypeError`` or a ``ValueError``, so it escaped the
    guard below and surfaced as a 500 the first time a creator clicked
    Connect Stripe against the real SDK.

    ``to_dict()`` is the SDK's own conversion and recurses by default,
    which is the behaviour this function needs rather than merely a
    behaviour it tolerates: the projection reads nested capability
    statuses and requirement entries, and a shallow copy would hand it
    StripeObjects one level down.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        converted = converter()
        if isinstance(converted, dict):
            return converted
    try:
        return dict(value)
    except (TypeError, ValueError, KeyError):  # pragma: no cover - defensive
        raise ConnectUnavailable("Stripe returned an object we cannot read")


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


#: The entity types Stripe accepts for an Australian recipient account,
#: and the only two Fresh Collective will send. Anything else is a caller
#: bug: passing an unrecognised value through to Stripe would fail
#: verification later, after the creator had already entered their details.
SUPPORTED_ENTITY_TYPES: frozenset[str] = frozenset({"individual", "company"})


def create_recipient_account(
    *,
    display_name: str,
    contact_email: str | None,
    country: str,
    business_url: str | None = None,
    entity_type: str = "individual",
) -> dict[str, Any]:
    """Create the account configuration Fresh Collective actually uses.

    ``recipient`` because FC is the merchant of record and the creator
    never processes a charge — Stripe documents this configuration for
    "Separate Charges & Transfers, or Destination Charges without
    ``on_behalf_of`` set", which is precisely FC's money path.

    ``dashboard: "express"`` gives creators a Stripe-hosted view of their
    payouts without FC building one, and it *requires* both
    responsibilities to be ``application`` — Stripe rejects any other
    combination with
    ``account_controller_express_dash_without_application_losses_or_fees``.
    So the three are one decision, not three.

    ``entity_type`` decides which identity Stripe verifies: a sole trader
    is an ``individual``, a Pty Ltd is a ``company``, and Stripe asks each
    for different documents. It defaults to ``individual`` because that is
    what every account created so far has used and what most Fresh
    Collective creators are. Fresh Collective does not currently record a
    creator's legal entity anywhere, so nothing can derive this yet — see
    the note in ``connect_routes`` for what supporting companies needs.
    Validated against :data:`SUPPORTED_ENTITY_TYPES` rather than passed
    through, so a wrong value fails here instead of surfacing as a
    verification dead end after the creator has filled in Stripe's form.

    ``requirements_collector`` is deliberately not passed. Stripe sets it
    to ``"stripe"`` for an express dashboard, which is why FC cannot write
    identity, ToS or bank details and must hand the creator to hosted
    onboarding instead.

    ``business_url`` is included only when the caller has a real one. It
    gates *both* capabilities, so supplying it removes a requirement from
    every creator's flow — but Stripe validates it (``example.com`` is
    refused as ``url_invalid``), so inventing one would turn a helpful
    prefill into a failed create.
    """
    if entity_type not in SUPPORTED_ENTITY_TYPES:
        raise ConnectError(
            f"unsupported entity_type {entity_type!r}; expected one of "
            f"{sorted(SUPPORTED_ENTITY_TYPES)}"
        )

    client = get_stripe_client()

    defaults: dict[str, Any] = {
        "responsibilities": {
            "fees_collector": "application",
            "losses_collector": "application",
        },
    }
    if business_url:
        defaults["profile"] = {"business_url": business_url}

    params: dict[str, Any] = {
        "display_name": display_name,
        "identity": {"country": country.lower(), "entity_type": entity_type},
        "configuration": {
            "recipient": {
                "capabilities": {
                    "stripe_balance": {"stripe_transfers": {"requested": True}},
                },
            },
        },
        "defaults": defaults,
        "dashboard": "express",
        "include": ACCOUNT_INCLUDES,
    }
    if contact_email:
        params["contact_email"] = contact_email

    try:
        account = client.v2.core.accounts.create(params)
    except stripe.StripeError as exc:
        logger.error("connect: account create failed: %s", exc)
        raise _translate(exc, what="creating a recipient account") from exc

    return _to_dict(account)


def retrieve_account(account_id: str) -> dict[str, Any]:
    """The v2 account, with everything the projection needs included."""
    client = get_stripe_client()
    try:
        account = client.v2.core.accounts.retrieve(
            account_id, {"include": ACCOUNT_INCLUDES},
        )
    except stripe.StripeError as exc:
        raise _translate(exc, what=f"retrieving account {account_id}") from exc
    return _to_dict(account)


def retrieve_legacy_account(account_id: str) -> dict[str, Any]:
    """The v1 account, for the two things v2 does not express.

    ``details_submitted`` separates "has not finished onboarding" from
    "finished, and Stripe has since asked for more".
    ``settings.payouts`` and ``external_accounts`` are the whole
    bank-payout picture, and neither appears in the v2 object.
    """
    api = get_stripe()
    try:
        account = api.Account.retrieve(account_id)
    except stripe.StripeError as exc:
        raise _translate(exc, what=f"retrieving legacy account {account_id}") from exc
    return _to_dict(account)


#: Weekly rather than Stripe's daily default. Every payout costs Fresh
#: Collective a fixed fee plus a percentage, and FC pays those fees, so a
#: creator selling most days generates roughly 22 payouts a month on daily
#: and about 4.3 on weekly. The money lands a few days later and costs
#: materially less to send. Monday keeps it predictable for creators and
#: lines up with Fresh Collective's own payout day.
WEEKLY_PAYOUT_SCHEDULE: dict[str, Any] = {
    "interval": "weekly",
    "weekly_anchor": "monday",
}


WEEKLY_INTERVAL = "weekly"


def _schedule_from(account: Any) -> dict[str, Any] | None:
    """``settings.payouts.schedule`` off an account, or None if absent."""
    data = _to_dict(account)
    settings_block = data.get("settings")
    if not isinstance(settings_block, dict):
        return None
    payouts = settings_block.get("payouts")
    if not isinstance(payouts, dict):
        return None
    schedule = payouts.get("schedule")
    return schedule if isinstance(schedule, dict) else None


def read_payout_schedule(account_id: str) -> dict[str, Any] | None:
    """What Stripe says this account's payout schedule actually is.

    A plain read, used to confirm a write rather than trust it. Returns
    ``None`` when Stripe could not be asked or did not say.
    """
    api = get_stripe()
    try:
        account = api.Account.retrieve(account_id)
    except Exception as exc:  # noqa: BLE001 — confirmation must not raise
        logger.warning(
            "connect: could not read the payout schedule for %s: %s",
            account_id, exc,
        )
        return None
    return _schedule_from(account)


def set_weekly_payout_schedule(account_id: str) -> dict[str, Any] | None:
    """Put an account on weekly payouts, then check that it took.

    Payout settings live only on the v1 account object — they are absent
    from v2 entirely — so this is a v1 ``Account.modify``.

    **Verified, not assumed.** The write is followed by a read of what
    Stripe now reports. If the result is anything other than weekly the
    mismatch is logged at ERROR with the interval the account is actually
    on, because the failure mode this guards against is the quiet one: an
    account left on Stripe's daily default, costing Fresh Collective a
    payout fee every day a creator sells, with nothing in the logs saying
    so. ``payout_interval`` on the account row is refreshed from Stripe by
    every sync, so :func:`accounts_not_on_weekly_payouts` can list the
    stragglers afterwards without asking Stripe again.

    **Deliberately does not raise.** An account that was created
    successfully must not be lost because its payout interval could not be
    set — the creator would be left with no way to be paid at all, which is
    far worse than a suboptimal payout cadence. The interval is re-appliable
    at any time; a half-created account is not.

    Returns the schedule Stripe reports, or ``None`` when it refused or
    would not say — in both cases having logged why.

    Not yet confirmed against Stripe for a ``recipient`` account whose
    ``requirements_collector`` is ``"stripe"``. That setting is why Fresh
    Collective cannot write identity, ToS or bank details on these
    accounts; the payout schedule is a different field and is expected to
    be writable, but "expected" is the honest word. The ERROR log and the
    straggler report are what turn a wrong expectation into something
    somebody notices on the first account created after this shipped.
    """
    api = get_stripe()
    try:
        account = api.Account.modify(
            account_id,
            settings={"payouts": {"schedule": dict(WEEKLY_PAYOUT_SCHEDULE)}},
        )
    except Exception as exc:  # noqa: BLE001 — see "does not raise" above
        logger.error(
            "connect: Stripe refused weekly payouts for %s (%s). The account "
            "stays on its existing schedule — Stripe's default is daily, "
            "which costs a payout fee per selling day. Re-appliable: this "
            "does not affect transfers or the creator's earnings.",
            account_id, exc,
        )
        return None

    # Confirm against what Stripe reports rather than trusting the write.
    # The modify response already carries the post-write state; a read is
    # only needed when it did not include the schedule.
    schedule = _schedule_from(account) or read_payout_schedule(account_id)
    interval = (schedule or {}).get("interval")

    if interval == WEEKLY_INTERVAL:
        logger.info(
            "connect: payout schedule for %s confirmed as %s", account_id, schedule,
        )
        return schedule

    logger.error(
        "connect: weekly payouts did not take for %s — Stripe reports "
        "interval=%r (schedule=%r). The account is not on weekly payouts. "
        "Transfers and creator earnings are unaffected; this is a cost and "
        "cadence problem, and it is re-appliable.",
        account_id, interval, schedule,
    )
    return schedule


def accounts_not_on_weekly_payouts(db: Any) -> list[tuple[str, str, str | None]]:
    """Connected accounts Stripe is not paying out weekly.

    Reads the ``payout_interval`` already projected onto the account row by
    every sync, so it costs no Stripe calls and reflects Stripe's own answer
    rather than what Fresh Collective asked for.

    ``None`` is included: an account that has never synced far enough to
    learn its interval is exactly as unverified as one known to be daily,
    and saying so is more useful than assuming it is fine.

    Returns ``(creator_user_id, stripe_account_id, payout_interval)`` for
    each, so an administrator can act on it without a second query.
    """
    from sqlalchemy import or_

    from app.models.creator_stripe_account import CreatorStripeAccount

    # The NULL branch is explicit because SQL's ``<> 'weekly'`` is false for
    # NULL, so an account with no known interval would otherwise be reported
    # as fine — the opposite of the truth.
    rows = (
        db.query(
            CreatorStripeAccount.creator_user_id,
            CreatorStripeAccount.stripe_account_id,
            CreatorStripeAccount.payout_interval,
        )
        .filter(
            CreatorStripeAccount.stripe_account_id.isnot(None),
            or_(
                CreatorStripeAccount.payout_interval.is_(None),
                CreatorStripeAccount.payout_interval != WEEKLY_INTERVAL,
            ),
        )
        .order_by(CreatorStripeAccount.creator_user_id)
        .all()
    )
    return [(c, a, i) for c, a, i in rows]


def create_express_dashboard_link(account_id: str) -> str:
    """A single-use URL into this account's Stripe Express Dashboard.

    **This is how a creator changes their bank details.** Not a choice of
    convenience — Stripe leaves no alternative for accounts shaped like Fresh
    Collective's:

    * ``account_update`` account links, which would let Fresh Collective host
      an edit form, are documented as available "only for connected accounts
      where your platform is responsible for collecting requirements" and
      explicitly "can't be created for accounts that have access to a
      Stripe-hosted Dashboard". FC's accounts are ``dashboard: "express"``
      *and* ``requirements_collector: "stripe"``, so they fail both halves.
    * Writing ``external_account`` directly is refused for the same reason —
      ``requirements_collector: "stripe"`` means Stripe, not FC, collects
      bank details.
    * Connect embedded components would work but need an AccountSession and a
      client-side integration Fresh Collective does not have.

    The Express Dashboard is the sanctioned surface: Stripe documents that in
    it a connected account "can change their bank account" and can "view and
    edit … the bank accounts used for payouts". FC already creates every
    account with ``dashboard: "express"`` precisely so creators get that view
    — it was simply never linked to.

    Raises :class:`ConnectError` rather than returning None: unlike the payout
    schedule, this is a button a creator just pressed, so a failure has to be
    something the page can tell them about.
    """
    api = get_stripe()
    try:
        link = api.Account.create_login_link(account_id)
    except stripe.StripeError as exc:
        raise _translate(
            exc, what=f"creating an Express Dashboard link for {account_id}",
        ) from exc

    url = getattr(link, "url", None) or _to_dict(link).get("url")
    if not url:
        raise ConnectUnavailable(
            f"Stripe returned a login link with no URL for {account_id}"
        )
    return str(url)


def is_closed(account: dict[str, Any]) -> bool:
    return bool(account.get("closed"))


# ---------------------------------------------------------------------------
# Hosted onboarding
# ---------------------------------------------------------------------------


def _account_link(
    *,
    account_id: str,
    use_case_type: str,
    return_url: str,
    refresh_url: str,
) -> str:
    client = get_stripe_client()
    options: dict[str, Any] = {
        "configurations": ["recipient"],
        # Ask for the minimum that unblocks the creator now, and let
        # Stripe come back for the rest when it actually needs it. A
        # creator who abandons onboarding because it asked for their whole
        # history is the common failure here.
        "collection_options": {"fields": "currently_due"},
        "refresh_url": refresh_url,
        "return_url": return_url,
    }
    try:
        link = client.v2.core.account_links.create({
            "account": account_id,
            "use_case": {"type": use_case_type, use_case_type: options},
        })
    except stripe.StripeError as exc:
        raise _translate(
            exc, what=f"creating a {use_case_type} link for {account_id}",
        ) from exc

    url = _to_dict(link).get("url")
    if not url:
        # A link without a URL is not something to hand a creator.
        raise ConnectUnavailable(
            f"Stripe returned an account link with no URL for {account_id}"
        )
    return str(url)


def create_onboarding_link(
    *, account_id: str, return_url: str, refresh_url: str,
) -> str:
    """A fresh Stripe-hosted onboarding URL.

    Returns the URL alone, deliberately: account links expire **five
    minutes** after creation (measured, not assumed), so there is nothing
    here worth storing and a stored one would usually be dead. Callers
    mint a new link per click, which is also why ``refresh_url`` is
    load-bearing rather than defensive — a creator who opens the page and
    hesitates will land on it.
    """
    return _account_link(
        account_id=account_id,
        use_case_type="account_onboarding",
        return_url=return_url,
        refresh_url=refresh_url,
    )


#: ``account_update`` account links are deliberately absent.
#:
#: They are the obvious way to let a creator edit what they have already
#: given, and Stripe does not support them for accounts shaped like Fresh
#: Collective's: documented as available "only for connected accounts where
#: your platform is responsible for collecting requirements" and as
#: impossible to create "for accounts that have access to a Stripe-hosted
#: Dashboard". FC's accounts are ``requirements_collector: "stripe"`` *and*
#: ``dashboard: "express"``, so they fail both halves.
#:
#: A ``create_update_link`` helper did exist here and was called for every
#: creator who had finished onboarding, which meant every one of them was
#: asking Stripe for a link it would refuse. It is gone rather than left
#: unused, so it cannot be reached again by accident.
#:
#: Use :func:`create_onboarding_link` when Stripe has anything outstanding —
#: Stripe states that type is for first-time onboarding *or* "when an
#: existing user has new requirements" — and
#: :func:`create_express_dashboard_link` when it does not.


# ---------------------------------------------------------------------------
# Mode
# ---------------------------------------------------------------------------


def current_mode() -> str:
    """``'test'`` or ``'live'``, from the key this environment holds."""
    return settings.stripe_mode
