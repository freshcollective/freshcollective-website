"""Read each creator's bank payouts from Stripe into a projection.

A Connect transfer and a bank payout are different events, and Fresh
Collective only ever observed the first. This closes that by asking Stripe
directly: ``Payout.list`` on the connected account. Nothing is inferred from
transfer records, because a transfer succeeding says nothing about whether
the bank accepted the deposit days later.

Why polling rather than webhooks
--------------------------------
``payout.*`` events on a connected account are v1 events delivered with a
``Stripe-Account`` header. Fresh Collective's v1 intake handles platform
events only, and its v2 intake handles v2 account events — so receiving them
would need a new endpoint, a new signing secret, and a Dashboard change.
Payouts are weekly; a fifteen-minute lag is immaterial. Polling from the
cron that already runs reuses the schedule, the credentials and the
observability, and changes no blueprint.

The approach does not foreclose webhooks: the natural key below makes an
event-driven writer idempotent against this same table, so one can be added
later without migrating anything.

Idempotency
-----------
Every write is an upsert on ``(provider_payout_id, stripe_mode)``, which is
unique in the schema. Running this twice, or running it while a webhook
writes the same payout, converges on the same row. A payout's status changes
over its life — ``pending`` → ``in_transit`` → ``paid`` — so the row is
updated in place rather than treated as immutable.

Scope
-----
Each payout is written against the ``creator_user_id`` of the account it was
read from, so a creator's list can only ever contain their own payouts.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.creator_bank_payout import PAYOUT_STATUSES, CreatorBankPayout
from app.models.creator_stripe_account import CreatorStripeAccount

logger = logging.getLogger(__name__)

#: Recent payouts read per account per pass, newest first. Ten covers well
#: over two months of weekly payouts, so a run missed for weeks still
#: catches up on current activity.
#:
#: This pass exists to keep *statuses* current: a payout moves ``pending`` →
#: ``in_transit`` → ``paid`` over days, and only a re-read sees that.
DEFAULT_PAYOUT_LIMIT = 10

#: Older payouts read per account per pass while the history import runs.
#:
#: One page, once, per account, per pass — never a loop. At the cron's
#: fifteen-minute cadence that is ninety-six pages a day per account, so
#: even a long history completes within hours while costing at most two
#: Stripe requests per account per pass.
BACKFILL_PAGE_SIZE = 25


@dataclass
class PayoutSyncReport:
    accounts: int = 0
    payouts_seen: int = 0
    created: int = 0
    updated: int = 0
    #: Accounts Stripe would not answer for. Logged and retried next pass.
    unreadable: list[str] = field(default_factory=list)
    #: Accounts whose history import advanced a page this pass.
    backfilled: int = 0
    #: Accounts whose history import finished this pass.
    backfill_completed: int = 0

    def as_log_fields(self) -> dict[str, object]:
        return {
            "accounts": self.accounts,
            "payouts_seen": self.payouts_seen,
            "created": self.created,
            "updated": self.updated,
            "unreadable": len(self.unreadable),
            "backfilled": self.backfilled,
            "backfill_completed": self.backfill_completed,
        }


def _field(entry: object, name: str) -> object | None:
    """One field off a Stripe object or a plain mapping, never raising.

    ``StripeObject`` supports attribute access but not ``.get()``; a dict is
    the other way round. Reading both shapes rather than assuming is the
    difference between this working against the real SDK and only against
    test fixtures.
    """
    if isinstance(entry, dict):
        return entry.get(name)
    return getattr(entry, name, None)


def _timestamp(value: object) -> datetime | None:
    """A Stripe epoch second as a naive UTC datetime, or None."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return datetime.utcfromtimestamp(int(value))
    except (OverflowError, OSError, ValueError):
        return None


def _upsert(
    db: Session,
    *,
    account: CreatorStripeAccount,
    payout: object,
    report: PayoutSyncReport,
) -> None:
    """Record one payout, creating or updating by Stripe's own id."""
    payout_id = _field(payout, "id")
    status = _field(payout, "status")
    amount = _field(payout, "amount")
    currency = _field(payout, "currency")

    if not payout_id or not isinstance(amount, int) or not currency:
        # Nothing to key on, or no figure to show. Better absent than wrong.
        logger.warning(
            "payout sync: account=%s skipping an unreadable payout entry",
            account.stripe_account_id,
        )
        return
    if status not in PAYOUT_STATUSES:
        # A status Stripe has added since this was written. Recording it
        # would violate the check constraint, and guessing the nearest known
        # value would misreport a creator's money.
        logger.warning(
            "payout sync: account=%s payout=%s has unrecognised status %r; "
            "skipped rather than mapped to a guess",
            account.stripe_account_id, payout_id, status,
        )
        return

    existing = (
        db.query(CreatorBankPayout)
        .filter(
            CreatorBankPayout.provider_payout_id == str(payout_id),
            CreatorBankPayout.stripe_mode == account.stripe_mode,
        )
        .one_or_none()
    )

    arrival = _timestamp(_field(payout, "arrival_date"))
    initiated = _timestamp(_field(payout, "created"))
    failure = _field(payout, "failure_code")
    failure_code = str(failure)[:80] if failure else None

    if existing is None:
        db.add(CreatorBankPayout(
            id=f"cbp_{uuid.uuid4()}",
            creator_user_id=account.creator_user_id,
            stripe_account_id=str(account.stripe_account_id),
            stripe_mode=account.stripe_mode,
            provider_payout_id=str(payout_id),
            amount_cents=int(amount),
            currency=str(currency).upper()[:3],
            status=str(status),
            arrival_date=arrival,
            initiated_at=initiated,
            failure_code=failure_code,
            synced_at=datetime.utcnow(),
        ))
        report.created += 1
        return

    # A payout's status moves over its life, so the row is refreshed rather
    # than left at whatever it was first seen as. ``creator_user_id`` is
    # never rewritten: a payout belongs to the account it was read from, and
    # reassigning one would be the only way this could leak across creators.
    existing.status = str(status)
    existing.amount_cents = int(amount)
    existing.currency = str(currency).upper()[:3]
    existing.arrival_date = arrival
    existing.initiated_at = initiated
    existing.failure_code = failure_code
    existing.synced_at = datetime.utcnow()
    report.updated += 1


def _read_page(
    api: object,
    *,
    account_id: str,
    limit: int,
    starting_after: str | None = None,
) -> tuple[list[object], bool]:
    """One page of payouts, and whether Stripe says there are older ones."""
    params: dict[str, object] = {"limit": limit, "stripe_account": account_id}
    if starting_after:
        params["starting_after"] = starting_after
    listing = api.Payout.list(**params)      # type: ignore[attr-defined]
    entries = list(_field(listing, "data") or [])
    return entries, bool(_field(listing, "has_more"))


def sync_creator_bank_payouts(
    db: Session,
    *,
    limit: int = DEFAULT_PAYOUT_LIMIT,
    page_size: int = BACKFILL_PAGE_SIZE,
) -> PayoutSyncReport:
    """One bounded pass over every connected account in this Stripe mode.

    Two phases per account, and at most two Stripe requests:

    * **Recent** — the newest ``limit`` payouts, every pass. This is what
      keeps statuses current as a payout moves towards ``paid``.
    * **History** — one page of older payouts, only while the import is
      unfinished. Resumed from the stored cursor, so the work spreads across
      runs instead of being attempted in one.

    Commits per account so a Stripe failure on one creator cannot discard
    another's payouts, or lose their import progress. Safe to run again at
    any time: every write is an upsert on Stripe's own payout id.
    """
    from app.checkout.stripe_client import get_stripe
    from app.core.config import settings

    report = PayoutSyncReport()
    # An account with no bank account attached has never had a payout, so
    # asking Stripe about it spends a request to learn nothing. Skipping
    # those keeps the request count proportional to accounts that can
    # actually have paid out, rather than to every account ever created —
    # three of Fresh Collective's four are in exactly that state.
    #
    # Scoped to this environment's Stripe mode, so a live pass never reads
    # test-mode accounts or vice versa.
    accounts = (
        db.query(CreatorStripeAccount)
        .filter(
            CreatorStripeAccount.stripe_account_id.isnot(None),
            CreatorStripeAccount.stripe_mode == settings.stripe_mode,
            CreatorStripeAccount.external_account_count > 0,
        )
        .order_by(CreatorStripeAccount.created_at)
        .all()
    )

    for account in accounts:
        report.accounts += 1

        # Read from Stripe first, write afterwards. The isolation this
        # requirement asks for then falls out of the ordering rather than
        # out of transaction gymnastics: if a creator's read fails, nothing
        # has been written for them, so there is nothing to discard and no
        # possibility of half-written work reaching another creator's
        # commit — in particular no cursor advanced past payouts that were
        # never recorded.
        try:
            api = get_stripe()
            recent, _ = _read_page(
                api, account_id=str(account.stripe_account_id), limit=limit,
            )
            oldest_recent: str | None = None
            if recent:
                seen = _field(recent[-1], "id")
                oldest_recent = str(seen) if seen else None

            history: tuple[list[object], bool] | None = None
            if not account.payout_history_complete:
                history = _read_page(
                    api,
                    account_id=str(account.stripe_account_id),
                    limit=page_size,
                    starting_after=account.payout_history_cursor or oldest_recent,
                )
        except Exception as exc:  # noqa: BLE001 — logged, retried next pass
            report.unreadable.append(str(account.stripe_account_id))
            logger.warning(
                "payout sync: could not read payouts for %s: %s",
                account.stripe_account_id, exc,
            )
            continue

        # Phase one: keep recent statuses current.
        for payout in recent:
            report.payouts_seen += 1
            _upsert(db, account=account, payout=payout, report=report)

        # Phase two: one page further back, if there was further back.
        if history is not None:
            entries, has_more = history
            for payout in entries:
                report.payouts_seen += 1
                _upsert(db, account=account, payout=payout, report=report)
            if entries:
                oldest = _field(entries[-1], "id")
                if oldest:
                    account.payout_history_cursor = str(oldest)
                report.backfilled += 1
            if not has_more:
                # Stripe has said there are no older payouts. Only now may
                # the page describe this creator's history as complete.
                account.payout_history_complete = True
                report.backfill_completed += 1

        db.commit()

    if report.unreadable:
        logger.warning(
            "payout sync: %s account(s) unreadable this pass: %s",
            len(report.unreadable), ", ".join(report.unreadable),
        )
    logger.info("payout sync complete: %s", report.as_log_fields())
    return report


#: Payouts per page in Creator Studio. Enough that most creators never page
#: at all, small enough that a long history loads incrementally.
PAGE_SIZE = 12


def list_for_creator(
    db: Session,
    *,
    creator_user_id: str,
    limit: int = PAGE_SIZE,
    offset: int = 0,
) -> tuple[list[CreatorBankPayout], bool]:
    """A page of this creator's payouts, newest first, and whether more exist.

    Scoped on ``creator_user_id`` *and* mode: a creator sees only their own
    payouts, and test-mode payouts never appear in a live list.

    One row is read beyond the page to answer "is there more?" without a
    second count query.
    """
    from app.core.config import settings

    rows = (
        db.query(CreatorBankPayout)
        .filter(
            CreatorBankPayout.creator_user_id == creator_user_id,
            CreatorBankPayout.stripe_mode == settings.stripe_mode,
        )
        .order_by(
            CreatorBankPayout.arrival_date.desc().nullslast(),
            CreatorBankPayout.created_at.desc(),
        )
        .offset(max(0, offset))
        .limit(max(1, limit) + 1)
        .all()
    )
    return rows[:limit], len(rows) > limit


def history_is_complete(db: Session, *, creator_user_id: str) -> bool:
    """Whether Stripe has confirmed there are no older payouts to import.

    False while the import is still walking backwards, and false when there
    is no connected account to import from. The page must not describe a
    partial history as complete, so this is reported rather than assumed.
    """
    from app.core.config import settings
    from app.models.creator_stripe_account import CreatorStripeAccount

    row = (
        db.query(CreatorStripeAccount.payout_history_complete)
        .filter(
            CreatorStripeAccount.creator_user_id == creator_user_id,
            CreatorStripeAccount.stripe_mode == settings.stripe_mode,
        )
        .one_or_none()
    )
    return bool(row and row[0])
