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
from app.core.public_url import public_app_url
from app.core.database import get_db
from app.models.creator_stripe_account import (
    CreatorStripeAccount,
    OnboardingState,
    SyncSource,
)
from app.models.platform import Space
from app.models.user import User
from app.services import connect_account_sync as sync
from app.services import connect_earnings as earnings
from app.services import creator_bank_payout_sync as payout_sync
from app.services import connect_routing_enablement as enablement
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

    #: The payout bank account, masked. Never an account or routing number:
    #: Stripe collects those through hosted onboarding and Fresh Collective
    #: does not hold them. All three are null when Stripe has told us nothing
    #: — which is a real state, not an error.
    bank_name: str | None = None
    bank_last4: str | None = None
    bank_currency: str | None = None

    #: Whether money actually routes through Connect for this creator.
    #: False for everyone until a deliberate, separate action sets it.
    connect_routing_enabled: bool = False

    #: Whether the creator has acknowledged how the fees fall. A
    #: precondition for routing, and never a trigger for it.
    fee_disclosure_acknowledged: bool = False
    fee_disclosure_acknowledged_at: datetime | None = None
    fee_disclosure_version: str | None = None

    last_synced_at: datetime | None = None
    last_sync_source: str | None = None
    last_error_message: str | None = None


class ConnectEarningOut(BaseModel):
    """One Connect-routed sale. No Stripe ids, no recovery internals."""

    payment_transaction_id: str
    created_at: str
    currency: str
    sale_amount_cents: int
    platform_fee_cents: int
    processing_fee_cents: int | None
    creator_amount_cents: int | None
    status: str
    status_label: str
    amount_is_estimate: bool
    refunded_amount_cents: int
    installment_number: int | None


class ConnectEarningsResponse(BaseModel):
    currency: str
    sale_total_cents: int
    platform_fee_total_cents: int
    processing_fee_total_cents: int
    creator_total_cents: int
    sent_total_cents: int
    #: Everything not yet sent. Equals ``owed_total_cents +
    #: uncollected_total_cents``; retained so an older client keeps working.
    awaiting_total_cents: int
    #: Collected from the customer and owed to the creator — the figure to
    #: show as "owed to you".
    owed_total_cents: int
    #: Collected but never queued for transfer. Expected to be zero; a
    #: non-zero figure is a stuck row, not money awaiting a customer. See
    #: ``ConnectEarningsSummary`` for why uncollected instalments cannot
    #: appear here.
    awaiting_payment_total_cents: int
    row_count: int
    rows: list[ConnectEarningOut]


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

    base = public_app_url()
    parsed = urlparse(base)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or host in _UNUSABLE_URL_HOSTS:
        return None
    if "." not in host or host.endswith(".local"):
        return None
    return f"{base}/spaces/{space.slug}"


def _link_urls() -> tuple[str, str]:
    return (
        public_app_url("/creator-studio/billing/connect/return"),
        public_app_url("/creator-studio/billing/connect/refresh"),
    )


def _sync(
    db: Session,
    row: CreatorStripeAccount,
    *,
    source: SyncSource,
    v2: dict | None = None,
) -> CreatorStripeAccount:
    """Thin alias over the shared sync service.

    Shared with the v2 webhook intake — two callers writing the same row
    from the same two Stripe objects should not be two implementations.
    """
    return sync.sync_from_stripe(db, row, source=source, v2=v2)


def _record_failure(db: Session, row: CreatorStripeAccount, message: str) -> None:
    sync.record_sync_failure(db, row, message)


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
        bank_name=row.bank_name,
        bank_last4=row.bank_last4,
        bank_currency=row.bank_currency,
        payout_delay_days=row.payout_delay_days,
        connect_routing_enabled=row.connect_payouts_enabled_at is not None,
        fee_disclosure_acknowledged=row.fee_disclosure_acknowledged_at is not None,
        fee_disclosure_acknowledged_at=row.fee_disclosure_acknowledged_at,
        fee_disclosure_version=row.fee_disclosure_version,
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
        # ``entity_type`` stays at its ``individual`` default. Fresh
        # Collective records nothing about a creator's legal entity, so
        # there is nothing here to derive it from, and guessing would send
        # a sole trader down a company verification path or vice versa.
        # Supporting companies needs one question asked once — before the
        # account is created, because Stripe fixes the entity at creation
        # and it cannot be changed afterwards. That is a product decision,
        # not a default this code should invent.
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

    # Weekly rather than Stripe's daily default, before the first sync so
    # the projection records the schedule the account will actually use.
    # Non-fatal by design — see ``set_weekly_payout_schedule``.
    connect.set_weekly_payout_schedule(str(account_id))

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


def _has_outstanding_requirements(row: CreatorStripeAccount) -> bool:
    """Whether Stripe still has something to collect from this creator.

    Two quite different reasons it might:

    * They never finished onboarding, so ``details_submitted`` is false.
    * They finished, and Stripe has since asked for more — a new capability,
      an expiring document, a bank account it still wants. Those arrive as
      ``currently_due`` entries on the projection.

    Either way the answer is the same hosted onboarding form, which is what
    makes this one predicate rather than two branches. Deliberately *not*
    keyed on ``onboarding_state``: a restricted account can have nothing
    currently due and still not be payable, and sending that creator to a
    form with nothing in it would imply the problem is theirs to fix.
    """
    if not row.details_submitted:
        return True
    return bool(row.currently_due_json)


@router.post("/onboarding-link", response_model=AccountLinkResponse)
def create_onboarding_link(
    creator: User = Depends(get_creator_user),
    db: Session = Depends(get_db),
) -> AccountLinkResponse:
    """Mint a fresh Stripe-hosted link, every single call.

    The URL is never stored. Account links expire five minutes after
    creation, so a cached one is usually dead by the time a creator clicks
    it, and handing out a dead link is worse than making them ask again.

    Which link depends on what Stripe still has to collect, not on whether
    the creator once finished a form.

    This previously routed on ``details_submitted``: anyone who had submitted
    got an ``account_update`` link. Stripe does not support those for Fresh
    Collective's accounts — they are documented as available "only for
    connected accounts where your platform is responsible for collecting
    requirements" and as impossible to create "for accounts that have access
    to a Stripe-hosted Dashboard", and FC's are ``requirements_collector:
    "stripe"`` *and* ``dashboard: "express"``. So every already-onboarded
    creator who pressed Continue was asking for a link Stripe would refuse.

    The supported routing, per Stripe's own guidance:

    * Anything outstanding — a creator mid-onboarding, or one Stripe has
      since asked more of — gets ``account_onboarding``. Stripe is explicit
      that this type is for first-time onboarding *or* "when an existing
      user has new requirements", and that "the onboarding interface knows
      what information it needs to collect".
    * Nothing outstanding gets an Express Dashboard login link, which is
      where Stripe lets an account holder view and change what they have
      already given, including their payout bank account.

    Neither path lets Fresh Collective see or write identity or bank
    details; Stripe collects both.
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

    # Nothing left to collect: hosted onboarding would present an empty
    # form, and an ``account_update`` link is unsupported here. The Express
    # Dashboard is the surface Stripe provides for this state.
    if not _has_outstanding_requirements(row):
        try:
            url = connect.create_express_dashboard_link(str(row.stripe_account_id))
        except StripeNotConfiguredError as exc:
            raise HTTPException(
                status_code=503, detail="Stripe is not configured on this server.",
            ) from exc
        except connect.ConnectError as exc:
            logger.error(
                "connect: dashboard link failed for %s: %s",
                row.stripe_account_id, exc,
            )
            _record_failure(db, row, str(exc))
            raise _translate(exc) from exc
        return AccountLinkResponse(url=url)

    return_url, refresh_url = _link_urls()

    try:
        url = connect.create_onboarding_link(
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


@router.post("/acknowledge-fees", response_model=ConnectStatusResponse)
def acknowledge_fees(
    creator: User = Depends(get_creator_user),
    db: Session = Depends(get_db),
) -> ConnectStatusResponse:
    """Record that the creator has seen how the fees fall.

    Deliberately does not enable anything. Acknowledging is the one
    precondition the creator controls; whether their sales route through
    Connect stays an administrative decision, so this endpoint cannot be the
    thing that moves a creator's money.
    """
    try:
        row = enablement.acknowledge_fee_disclosure(db, creator_user_id=creator.id)
    except enablement.RoutingEnablementError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_status(row)


@router.post("/dashboard-link", response_model=AccountLinkResponse)
def create_dashboard_link(
    creator: User = Depends(get_creator_user),
    db: Session = Depends(get_db),
) -> AccountLinkResponse:
    """A single-use link into this creator's Stripe Express Dashboard.

    Where a creator changes their bank details. Stripe leaves no alternative
    for accounts shaped like Fresh Collective's — see
    :func:`stripe_connect_accounts.create_express_dashboard_link` for why an
    ``account_update`` link and a direct ``external_account`` write are both
    refused. Fresh Collective never sees an account number either way, which
    is the point.

    Scoped to the authenticated creator's own account row, so the link can
    only ever open their own dashboard.
    """
    row = _find_row(db, creator)
    if row is None or not row.stripe_account_id:
        raise HTTPException(
            status_code=409,
            detail="Set up bank payouts before opening your Stripe dashboard.",
        )
    if row.onboarding_state == OnboardingState.closed.value:
        raise HTTPException(
            status_code=409,
            detail="This account has been closed and cannot be opened.",
        )

    try:
        url = connect.create_express_dashboard_link(str(row.stripe_account_id))
    except StripeNotConfiguredError as exc:
        raise HTTPException(
            status_code=503, detail="Stripe is not configured on this server.",
        ) from exc
    except connect.ConnectError as exc:
        logger.error(
            "connect: dashboard link failed for %s: %s",
            row.stripe_account_id, exc,
        )
        raise _translate(exc) from exc

    return AccountLinkResponse(url=url)


class BankPayoutOut(BaseModel):
    """One bank payout, as the creator sees it.

    No Stripe payout id and no raw failure code: an id is not actionable by a
    creator, and a code like ``account_closed`` reads as jargon. The status
    carries the meaning, and ``paid`` is the only value that means the money
    reached the bank.
    """

    amount_cents: int
    currency: str
    status: str
    arrival_date: datetime | None = None
    initiated_at: datetime | None = None


class BankPayoutsResponse(BaseModel):
    payouts: list[BankPayoutOut]
    #: When Fresh Collective last read these from Stripe. Lets the page say
    #: how current the list is rather than implying it is live.
    synced_at: datetime | None = None
    #: Whether another page of already-imported payouts exists.
    has_more: bool = False
    #: Whether Stripe has confirmed there are no older payouts left to
    #: import. False while the history import is still walking backwards —
    #: the page says so, because a partial history shown as complete is
    #: worse than one shown as partial.
    history_complete: bool = False


@router.get("/payouts", response_model=BankPayoutsResponse)
def list_bank_payouts(
    limit: int = payout_sync.PAGE_SIZE,
    offset: int = 0,
    creator: User = Depends(get_creator_user),
    db: Session = Depends(get_db),
) -> BankPayoutsResponse:
    """This creator's actual bank payouts, newest first.

    Read from Fresh Collective's projection of Stripe's own ``Payout``
    records — never inferred from transfers. A transfer reaching the
    creator's Stripe balance says nothing about whether the bank accepted
    the deposit, so the two are reported separately and only ``paid`` means
    arrived.

    Scoped to the authenticated creator and to this environment's Stripe
    mode by :func:`payout_sync.list_for_creator`.
    """
    rows, has_more = payout_sync.list_for_creator(
        db, creator_user_id=creator.id,
        limit=min(max(limit, 1), 50), offset=max(offset, 0),
    )
    return BankPayoutsResponse(
        payouts=[
            BankPayoutOut(
                amount_cents=r.amount_cents,
                currency=r.currency,
                status=r.status,
                arrival_date=r.arrival_date,
                initiated_at=r.initiated_at,
            )
            for r in rows
        ],
        synced_at=max((r.synced_at for r in rows), default=None),
        has_more=has_more,
        history_complete=payout_sync.history_is_complete(
            db, creator_user_id=creator.id,
        ),
    )


@router.get("/earnings", response_model=ConnectEarningsResponse)
def get_connect_earnings(
    creator: User = Depends(get_creator_user),
    db: Session = Depends(get_db),
) -> ConnectEarningsResponse:
    """Connect-routed sales, with the fee breakdown for each.

    Separate from the manual payout figures on the Billing page, because for
    these sales Fresh Collective owes nothing by hand — Stripe does. Folding
    them together would tell a creator FC is holding money it is not.
    """
    rows = earnings.list_connect_earnings(db, creator_user_id=creator.id)
    currency = rows[0].currency if rows else "AUD"
    summary = earnings.summarise(rows, currency=currency)
    return ConnectEarningsResponse(
        currency=summary.currency,
        sale_total_cents=summary.sale_total_cents,
        platform_fee_total_cents=summary.platform_fee_total_cents,
        processing_fee_total_cents=summary.processing_fee_total_cents,
        creator_total_cents=summary.creator_total_cents,
        sent_total_cents=summary.sent_total_cents,
        awaiting_total_cents=summary.awaiting_total_cents,
        owed_total_cents=summary.owed_total_cents,
        awaiting_payment_total_cents=summary.awaiting_payment_total_cents,
        row_count=summary.row_count,
        rows=[
            ConnectEarningOut(**{
                field: getattr(row, field)
                for field in ConnectEarningOut.model_fields
            })
            for row in rows
        ],
    )
