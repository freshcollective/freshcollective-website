"""Creator-facing endpoints for connecting a Stripe account.

    POST /api/creator/stripe-connect/account          create or return
    POST /api/creator/stripe-connect/onboarding-link   mint a fresh link
    GET  /api/creator/stripe-connect/status            stored projection
    POST /api/creator/stripe-connect/refresh           re-read Stripe

None of these move money or decide that a creator's money should route
through Connect. ``connect_payouts_enabled_at`` is never written here —
it is the only field that changes payment behaviour, and turning it on is
a separate, deliberate act.

Two rules shape the whole module.

**A status read must not depend on Stripe.** ``GET /status`` answers from
FC's own row and makes no network call. A creator loading their billing
page when Stripe is slow should see their state, not a spinner, and a page
view should not be able to rewrite stored state as a side effect.
``POST /refresh`` is the explicit way to ask Stripe again.

**Never conclude anything from an unanswered question.** A retryable
Stripe failure leaves the stored projection exactly as it was and records
why; it never degrades a good state into a worse one. ``resource_missing``
is treated the same way, because that is also what a mode mismatch looks
like — see ``stripe_connect_accounts.ConnectAccountNotFound``.

Mode separation is enforced at the query: every lookup is keyed on
``(creator_user_id, current Stripe mode)``, so a live-mode row is simply
invisible to a test-mode environment. Stripe's own ``resource_missing``
is the second line of defence, not the first.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_creator_user
from app.checkout.stripe_client import StripeNotConfiguredError
from app.core.config import settings
from app.core.database import get_db
from app.models.creator_stripe_account import (
    CreatorStripeAccount,
    OnboardingState,
    SyncSource,
)
from app.models.platform import Space
from app.models.user import User
from app.services import connect_account_state as projection
from app.services import stripe_connect_accounts as connect

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/creator/stripe-connect", tags=["creator-stripe-connect"])

#: Hosts Stripe will not accept as a business URL, and localhost variants
#: that are meaningless to it. ``example.com`` is refused outright with
#: ``url_invalid``, which is why this list exists rather than a bare
#: "is it a URL?" check.
_UNUSABLE_URL_HOSTS = frozenset({
    "localhost", "127.0.0.1", "0.0.0.0", "example.com", "www.example.com",
})


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------


class ConnectStatusResponse(BaseModel):
    """FC's stored picture. Never a live read — see the module docstring."""

    connected: bool
    state: str
    stripe_mode: str
    stripe_account_id: str | None = None

    transfers_status: str | None = None
    transfers_status_codes: list[str] = []
    payouts_status: str | None = None
    payouts_status_codes: list[str] = []
    transfers_enabled: bool = False
    payouts_enabled: bool = False

    details_submitted: bool = False
    requirements: list[dict] = []
    requirements_deadline: datetime | None = None
    action_required: bool = False

    external_account_count: int = 0
    payout_interval: str | None = None
    payout_delay_days: int | None = None

    #: Whether money actually routes through Connect for this creator.
    #: False for everyone until a deliberate, separate action sets it.
    connect_routing_enabled: bool = False

    last_synced_at: datetime | None = None
    last_sync_source: str | None = None
    last_error_message: str | None = None


class AccountLinkResponse(BaseModel):
    url: str
    #: Measured, not assumed. Surfaced so the frontend can refuse to cache.
    expires_in_seconds: int = 300


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mode() -> str:
    return connect.current_mode()


def _find_row(db: Session, creator: User) -> CreatorStripeAccount | None:
    """The creator's row **for this environment's Stripe mode only**."""
    return (
        db.query(CreatorStripeAccount)
        .filter(
            CreatorStripeAccount.creator_user_id == creator.id,
            CreatorStripeAccount.stripe_mode == _mode(),
        )
        .first()
    )


def _get_or_create_row(db: Session, creator: User) -> CreatorStripeAccount:
    """One row per (creator, mode), even under concurrent requests.

    The unique constraint is the arbiter rather than a pre-check: two
    simultaneous first-time calls both see no row, and only one insert can
    win. The loser re-reads instead of failing, so the endpoint stays
    idempotent from the caller's point of view.
    """
    row = _find_row(db, creator)
    if row is not None:
        return row

    row = CreatorStripeAccount(
        id=f"csa_{uuid.uuid4()}",
        creator_user_id=creator.id,
        stripe_mode=_mode(),
        onboarding_state=OnboardingState.not_started.value,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _find_row(db, creator)
        if existing is None:  # pragma: no cover - only if the constraint changed
            raise
        return existing
    return row


def _business_url(db: Session, creator: User) -> str | None:
    """A real public URL for the creator's collective, or nothing.

    Worth supplying because ``business_url`` gates *both* capabilities, so
    filling it removes one requirement from the creator's hosted flow. But
    Stripe validates it — a placeholder is refused as ``url_invalid`` and
    would turn a helpful prefill into a failed account create — so this
    returns ``None`` rather than inventing anything when the environment
    has no public host (local development) or the creator has no
    collective yet.
    """
    space = (
        db.query(Space)
        .filter(Space.creator_id == creator.id)
        .order_by(Space.created_at.asc())
        .first()
    )
    if space is None or not space.slug:
        return None

    base = settings.resolved_public_app_url
    parsed = urlparse(base)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or host in _UNUSABLE_URL_HOSTS:
        return None
    if "." not in host or host.endswith(".local"):
        return None
    return f"{base}/spaces/{space.slug}"


def _link_urls() -> tuple[str, str]:
    base = settings.resolved_public_app_url
    return (
        f"{base}/creator-studio/billing/connect/return",
        f"{base}/creator-studio/billing/connect/refresh",
    )


def _sync(
    db: Session,
    row: CreatorStripeAccount,
    *,
    source: SyncSource,
    v2: dict | None = None,
) -> CreatorStripeAccount:
    """Re-read Stripe, project, persist, and stamp the diagnostics.

    ``v2`` may be supplied when the caller already has a fresh account
    object — the create response is one — to avoid an immediate second
    read of something just returned.

    Both objects are fetched before anything is written, so a failure
    halfway through cannot leave the row describing a mixture of two
    moments.
    """
    account = v2 if v2 is not None else connect.retrieve_account(row.stripe_account_id)
    legacy = connect.retrieve_legacy_account(row.stripe_account_id)

    projection.project(
        stripe_account_id=row.stripe_account_id, v2=account, v1=legacy,
    ).apply_to(row)

    row.last_synced_at = datetime.utcnow()
    row.last_sync_source = source.value
    row.last_error_message = None
    db.commit()
    return row


def _record_failure(db: Session, row: CreatorStripeAccount, message: str) -> None:
    """Record why a sync failed without touching the projection.

    Deliberately leaves every projected field alone: an unanswered
    question is not evidence, and a creator who was ``ready`` a minute ago
    must not be demoted because Stripe timed out.
    """
    row.last_error_message = message[:1000]
    db.commit()


def _to_status(row: CreatorStripeAccount | None) -> ConnectStatusResponse:
    if row is None:
        return ConnectStatusResponse(
            connected=False,
            state=OnboardingState.not_started.value,
            stripe_mode=_mode(),
        )
    requirements = row.currently_due_json or []
    return ConnectStatusResponse(
        connected=bool(row.stripe_account_id),
        state=row.onboarding_state,
        stripe_mode=row.stripe_mode,
        stripe_account_id=row.stripe_account_id,
        transfers_status=row.transfers_status,
        transfers_status_codes=list(row.transfers_status_codes or []),
        payouts_status=row.payouts_status,
        payouts_status_codes=list(row.payouts_status_codes or []),
        transfers_enabled=row.transfers_enabled,
        payouts_enabled=row.payouts_enabled,
        details_submitted=row.details_submitted,
        requirements=requirements,
        requirements_deadline=row.requirements_deadline,
        action_required=any(
            e.get("awaiting_action_from") == "user" for e in requirements
        ),
        external_account_count=row.external_account_count,
        payout_interval=row.payout_interval,
        payout_delay_days=row.payout_delay_days,
        connect_routing_enabled=row.connect_payouts_enabled_at is not None,
        last_synced_at=row.last_synced_at,
        last_sync_source=row.last_sync_source,
        last_error_message=row.last_error_message,
    )


def _translate(exc: connect.ConnectError) -> HTTPException:
    """Domain failure → HTTP, keeping the retryable/terminal split intact."""
    if isinstance(exc, connect.ConnectUnavailable):
        return HTTPException(
            status_code=503,
            detail=(
                "Stripe could not be reached just now. Nothing has changed — "
                "please try again in a moment."
            ),
        )
    if isinstance(exc, connect.ConnectAccountClosed):
        return HTTPException(
            status_code=409,
            detail="This Stripe account has been closed and cannot be set up again.",
        )
    if isinstance(exc, connect.ConnectAccountNotFound):
        return HTTPException(
            status_code=409,
            detail=(
                "Stripe does not recognise this account. Fresh Collective has "
                "kept what it already knew; please contact support."
            ),
        )
    return HTTPException(
        status_code=502,
        detail="Stripe refused this request. Please contact support.",
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/account", response_model=ConnectStatusResponse)
def create_or_get_account(
    creator: User = Depends(get_creator_user),
    db: Session = Depends(get_db),
) -> ConnectStatusResponse:
    """Create the creator's Stripe account, or return the existing one.

    Idempotent at FC's level: a second call returns the stored account and
    makes no Stripe call at all. That matters more than it sounds —
    creating a duplicate connected account is not something FC could
    cleanly undo, and a creator double-clicking is the normal case.

    The account id is committed immediately after Stripe returns it, before
    any projection work. If the projection read then fails, FC still owns
    the account rather than having created one it cannot name.
    """
    row = _get_or_create_row(db, creator)

    if row.stripe_account_id:
        return _to_status(row)

    try:
        account = connect.create_recipient_account(
            display_name=creator.name or creator.email,
            contact_email=creator.email,
            country=settings.stripe_connect_account_country,
            business_url=_business_url(db, creator),
        )
    except StripeNotConfiguredError as exc:
        raise HTTPException(
            status_code=503,
            detail="Stripe is not configured on this server.",
        ) from exc
    except connect.ConnectError as exc:
        logger.error("connect: create failed for creator=%s: %s", creator.id, exc)
        _record_failure(db, row, str(exc))
        raise _translate(exc) from exc

    account_id = account.get("id")
    if not account_id:
        _record_failure(db, row, "Stripe returned an account with no id")
        raise HTTPException(
            status_code=502, detail="Stripe returned an account we cannot identify.",
        )

    # Commit the id on its own, first. Everything after this is recoverable;
    # losing the id is not.
    row.stripe_account_id = str(account_id)
    db.commit()

    try:
        _sync(db, row, source=SyncSource.manual, v2=account)
    except connect.ConnectError as exc:
        # The account exists and is ours. A failed first read is a stale
        # projection, not a failed creation.
        logger.warning(
            "connect: created %s for creator=%s but could not project it: %s",
            account_id, creator.id, exc,
        )
        _record_failure(db, row, str(exc))

    return _to_status(row)


@router.post("/onboarding-link", response_model=AccountLinkResponse)
def create_onboarding_link(
    creator: User = Depends(get_creator_user),
    db: Session = Depends(get_db),
) -> AccountLinkResponse:
    """Mint a fresh Stripe-hosted link, every single call.

    The URL is never stored. Account links expire five minutes after
    creation, so a cached one is usually dead by the time a creator clicks
    it, and handing out a dead link is worse than making them ask again.

    Which link depends on where they are: a creator who has already
    submitted needs ``account_update`` for re-collection, not
    ``account_onboarding``.
    """
    row = _find_row(db, creator)
    if row is None or not row.stripe_account_id:
        raise HTTPException(
            status_code=409,
            detail="Connect a Stripe account before starting setup.",
        )
    if row.onboarding_state == OnboardingState.closed.value:
        raise HTTPException(
            status_code=409,
            detail="This Stripe account has been closed and cannot be set up again.",
        )

    return_url, refresh_url = _link_urls()
    mint = (
        connect.create_update_link if row.details_submitted
        else connect.create_onboarding_link
    )

    try:
        url = mint(
            account_id=row.stripe_account_id,
            return_url=return_url,
            refresh_url=refresh_url,
        )
    except StripeNotConfiguredError as exc:
        raise HTTPException(
            status_code=503, detail="Stripe is not configured on this server.",
        ) from exc
    except connect.ConnectError as exc:
        logger.error(
            "connect: link creation failed for %s: %s", row.stripe_account_id, exc,
        )
        _record_failure(db, row, str(exc))
        raise _translate(exc) from exc

    # Counted, not stored. "Did they ever actually start?" is answerable
    # without keeping a URL that will not work.
    row.account_link_count = (row.account_link_count or 0) + 1
    row.last_account_link_created_at = datetime.utcnow()
    db.commit()

    return AccountLinkResponse(url=url)


@router.get("/status", response_model=ConnectStatusResponse)
def get_status(
    creator: User = Depends(get_creator_user),
    db: Session = Depends(get_db),
) -> ConnectStatusResponse:
    """FC's stored projection. No Stripe call, ever.

    A page view must not be able to fail because Stripe is slow, and must
    not rewrite stored state as a side effect. ``POST /refresh`` is how a
    caller asks for a live read.
    """
    return _to_status(_find_row(db, creator))


@router.post("/refresh", response_model=ConnectStatusResponse)
def refresh_status(
    creator: User = Depends(get_creator_user),
    db: Session = Depends(get_db),
) -> ConnectStatusResponse:
    """Re-read Stripe and persist the projection.

    The explicit "recheck Stripe" action, in the shape agreed for stuck
    discount reservations: it asks again and records the answer. There is
    no variant that forces a state FC has not observed.
    """
    row = _find_row(db, creator)
    if row is None or not row.stripe_account_id:
        raise HTTPException(
            status_code=409,
            detail="There is no Stripe account to refresh yet.",
        )

    try:
        _sync(db, row, source=SyncSource.manual)
    except StripeNotConfiguredError as exc:
        raise HTTPException(
            status_code=503, detail="Stripe is not configured on this server.",
        ) from exc
    except connect.ConnectError as exc:
        logger.warning(
            "connect: refresh failed for %s: %s", row.stripe_account_id, exc,
        )
        # No rollback: ``_sync`` fetches both objects before it writes
        # anything, so a failed read has mutated nothing to undo. Rolling
        # back here would discard the row's own existence in a caller's
        # open transaction.
        _record_failure(db, row, str(exc))
        raise _translate(exc) from exc

    return _to_status(row)
