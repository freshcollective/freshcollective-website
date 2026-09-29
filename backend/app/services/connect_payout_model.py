"""Decide, once, how a purchase's creator share will reach the creator.

Called at transaction creation and nowhere else. The result is snapshotted
onto the row, and no downstream code re-reads the creator's Connect state —
because a creator who finishes onboarding, or loses a capability, while a
buyer is away at Stripe must not change how *that* purchase pays out. Same
discipline as the grants and discount snapshots already on the ledger.

The decision is deliberately conservative. ``manual`` is the answer to
every question this module cannot answer with certainty, because ``manual``
is what FC does today and getting it wrong means a creator is paid the way
they already expect. ``connect`` requires four separate facts to line up,
and the last of them is a human act.

Why four conditions and not one
-------------------------------
``payouts_status == 'active'`` and ``payouts_enabled`` look redundant. They
are not quite: the boolean is a derived convenience and the status is what
Stripe said, and the table's CHECK constraints tie them together precisely
so that reading both is cheap insurance rather than duplication.

``connect_payouts_enabled_at`` is the one that matters most. Stripe saying
an account is ready must never by itself start moving money — that is a
deliberate, separate, operator-made decision. Without this condition,
completing onboarding would silently change where a creator's earnings go.

And it must be ``payouts``, not ``transfers``. A recipient account reaches
``stripe_transfers: active`` before it has a bank account attached, so
routing on transfers alone would move real money into a Stripe balance the
creator cannot empty. Verified against a live test-mode account: the two
capabilities differ by exactly the ``external_account`` requirement.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.creator_stripe_account import CreatorStripeAccount
from app.models.payment import ConnectTransferStatus, PayoutModel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PayoutModelDecision:
    """What to stamp on the transaction.

    ``destination_account_id`` is non-null exactly when ``payout_model`` is
    ``connect`` — the ledger has a CHECK constraint saying so, so the two
    fields cannot be persisted out of step.
    """

    payout_model: str
    destination_account_id: str | None = None
    #: Why, for logs. Never surfaced to a buyer or a creator.
    reason: str = ""

    @property
    def is_connect(self) -> bool:
        return self.payout_model == PayoutModel.connect.value

    @property
    def manual_payout_applies(self) -> bool:
        """Whether FC's manual payout process covers this row.

        False for Connect rows, which is the whole payout-status decision:
        ``payout_status`` keeps meaning "state of FC's manual payout
        bookkeeping", so a Connect row takes ``not_applicable`` rather than
        being forced into ``pending`` (which would show as money FC owes by
        hand) or later ``paid`` (which means a payout batch recorded a
        disbursement, and would also wrongly imply Stripe had reached the
        creator's bank). ``connect_transfer_status`` is the authority for
        Connect instead.
        """
        return self.payout_model == PayoutModel.manual.value

    @property
    def initial_transfer_status(self) -> str:
        """What ``connect_transfer_status`` should be at creation.

        A Connect row starts ``awaiting_payment`` — a transfer applies to
        it, but is not due until the money arrives. Fulfilment is what
        moves it to ``pending``, which is the only state the sweeper acts
        on, so an abandoned checkout never enters that queue. Every other
        model starts ``not_applicable``, because no transfer will ever be
        owed.
        """
        if self.is_connect:
            return ConnectTransferStatus.awaiting_payment.value
        return ConnectTransferStatus.not_applicable.value


_MANUAL = PayoutModel.manual.value
_CONNECT = PayoutModel.connect.value
_NOT_APPLICABLE = PayoutModel.not_applicable.value


def resolve_payout_model(
    db: Session,
    *,
    creator_user_id: str | None,
    is_platform_owned: bool = False,
) -> PayoutModelDecision:
    """The payout model for a purchase against this creator's Collective.

    ``creator_user_id`` is ``None`` (or ``is_platform_owned``) for
    platform-owned Collectives, where Fresh Collective is the seller and no
    creator share exists.
    """
    if is_platform_owned or not creator_user_id:
        return PayoutModelDecision(
            payout_model=_NOT_APPLICABLE,
            reason="platform-owned: no creator share exists",
        )

    # Scoped to this environment's Stripe mode, so a live-mode account is
    # invisible to a test-mode deployment and vice versa. A test ``acct_…``
    # used under live keys is the kind of mistake that is only discovered
    # by a failed transfer, so it is excluded at the query rather than
    # checked afterwards.
    account = (
        db.query(CreatorStripeAccount)
        .filter(
            CreatorStripeAccount.creator_user_id == creator_user_id,
            CreatorStripeAccount.stripe_mode == settings.stripe_mode,
        )
        .first()
    )

    if account is None:
        return PayoutModelDecision(
            payout_model=_MANUAL,
            reason=f"no {settings.stripe_mode}-mode Connect account",
        )
    if not account.stripe_account_id:
        return PayoutModelDecision(
            payout_model=_MANUAL, reason="Connect account not yet created at Stripe",
        )
    if account.payouts_status != "active" or not account.payouts_enabled:
        return PayoutModelDecision(
            payout_model=_MANUAL,
            reason=(
                f"payouts not active (status={account.payouts_status!r}, "
                f"enabled={account.payouts_enabled})"
            ),
        )
    if account.connect_payouts_enabled_at is None:
        # Stripe is ready; Fresh Collective has not switched this creator
        # over. That is the whole point of the field.
        return PayoutModelDecision(
            payout_model=_MANUAL,
            reason="payout-ready but Connect routing not enabled for this creator",
        )

    return PayoutModelDecision(
        payout_model=_CONNECT,
        destination_account_id=account.stripe_account_id,
        reason="routing enabled and payouts active",
    )


def resolve_for_free_purchase(
    *, creator_user_id: str | None, is_platform_owned: bool = False,
) -> PayoutModelDecision:
    """A purchase with nothing to transfer is never Connect-routed.

    A free checkout has a zero gross, so there is no creator share and no
    transfer to send. Marking it ``connect`` would put a permanent
    zero-amount obligation in the sweeper's queue for no reason.
    """
    if is_platform_owned or not creator_user_id:
        return PayoutModelDecision(
            payout_model=_NOT_APPLICABLE, reason="platform-owned free purchase",
        )
    return PayoutModelDecision(
        payout_model=_MANUAL, reason="free purchase: nothing to transfer",
    )
