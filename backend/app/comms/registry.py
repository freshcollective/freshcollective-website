"""Event type registry — resolves ``event_type`` to (topic, default priority).

The category is derived from the topic via
``TOPIC_TO_CATEGORY`` in ``categories.py``. Adding a new event type
requires adding it here; a new topic requires an accompanying migration.

Milestone 1 seeds a small, representative slice of the ~60 event types
inventoried in the architecture doc — enough to exercise ``emit()`` and
the admin surface. Later milestones will grow this table as each domain
subsystem cuts over.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.comms.categories import (
    PRIORITY_IMMEDIATE,
    PRIORITY_SCHEDULED,
    PRIORITY_SILENT,
    PriorityType,
    TOPIC_ACCOUNT,
    TOPIC_COLLECTIVE_UPDATES,
    TOPIC_CONVERSATIONS,
    TOPIC_CREATOR_BROADCASTS,
    TOPIC_DIRECT_MESSAGES,
    TOPIC_GATHERINGS,
    TOPIC_MODERATION,
    TOPIC_PATHWAYS,
    TOPIC_PURCHASES,
    TOPIC_SECURITY,
    TOPIC_TO_CATEGORY,
)


@dataclass(frozen=True)
class EventDefinition:
    """Declarative registration for a communication-worthy event.

    * ``event_type``       — the dotted namespace key domain code emits.
    * ``topic``            — the internal topic; must exist in
                             ``communication_topics``.
    * ``default_priority`` — pacing hint applied at emit time. Individual
                             recipients may override in later milestones.
    """

    event_type: str
    topic: str
    default_priority: PriorityType


# Seed slice — sized for Milestone 1. Grows as domain code migrates.
_EVENT_DEFINITIONS: tuple[EventDefinition, ...] = (
    # Account & security
    EventDefinition("account.created",                    TOPIC_ACCOUNT,   PRIORITY_SILENT),
    # Fires once per new signup, after the User row is committed. Only
    # emit site: ``auth/routes.py::signup`` (and the same helper reused
    # by ``purchases/routes.py::claim_with_signup``). Deliberately NOT
    # in TRANSACTIONAL_EVENT_TYPES: a greeting is not a security
    # message, a receipt or an access-state change, so a member who
    # would rather not have one may say so. Default-enabled, so one
    # still arrives unless they do.
    EventDefinition("account.welcome_after_signup",       TOPIC_ACCOUNT,   PRIORITY_IMMEDIATE),
    # SEC-009 — the sole email a new unverified account receives at
    # signup. Warm + welcoming, primary CTA "verify your email".
    # The existing ``account.welcome_after_signup`` above fires
    # AFTER successful verification so a new account gets exactly
    # two account emails across its lifetime: verify → welcome.
    # Event-locked (TRANSACTIONAL_EVENT_TYPES) — an account that
    # cannot confirm itself is an account nobody can use, so no
    # preference reaches this one.
    EventDefinition("account.email_verification_requested", TOPIC_ACCOUNT, PRIORITY_IMMEDIATE),
    EventDefinition("account.password_reset_requested",   TOPIC_SECURITY,  PRIORITY_IMMEDIATE),
    EventDefinition("account.password_reset_completed",   TOPIC_SECURITY,  PRIORITY_IMMEDIATE),

    # Collective membership
    EventDefinition("collective.membership.joined",       TOPIC_COLLECTIVE_UPDATES, PRIORITY_SILENT),
    EventDefinition("collective.membership.left",         TOPIC_COLLECTIVE_UPDATES, PRIORITY_SILENT),
    EventDefinition("collective.membership.role_changed", TOPIC_COLLECTIVE_UPDATES, PRIORITY_SILENT),
    # A creator has sent an invitation email to a prospective member.
    # Fires when the operator clicks "Send" on a draft invitation in
    # Creator Studio (POST /api/creator/spaces/{slug}/invitations/{id}/send).
    # Registered under TOPIC_ACCOUNT (not COLLECTIVE_UPDATES) because
    # this is an entry/account transactional email whose delivery must
    # not be preference-gated by the *inviter's* CATEGORY_COMMUNITY
    # preferences (the invitee is external and typically has no user
    # record yet). Event-locked as well — see the note beside
    # ``collective.invitation.sent`` in TRANSACTIONAL_EVENT_TYPES for
    # why the inviter's preference must not reach it.
    EventDefinition("collective.invitation.sent",         TOPIC_ACCOUNT,            PRIORITY_IMMEDIATE),

    # Community
    EventDefinition("community.post.published",           TOPIC_CONVERSATIONS,      PRIORITY_IMMEDIATE),
    EventDefinition("community.comment.created",          TOPIC_CONVERSATIONS,      PRIORITY_IMMEDIATE),
    EventDefinition("community.mention.created",          TOPIC_CONVERSATIONS,      PRIORITY_IMMEDIATE),

    # Direct messages
    EventDefinition("dm.message.sent",                    TOPIC_DIRECT_MESSAGES,    PRIORITY_IMMEDIATE),

    # Gatherings
    EventDefinition("gathering.booking.confirmed",        TOPIC_GATHERINGS,         PRIORITY_IMMEDIATE),
    EventDefinition("gathering.reminder.24h",             TOPIC_GATHERINGS,         PRIORITY_SCHEDULED),
    EventDefinition("gathering.reminder.1h",              TOPIC_GATHERINGS,         PRIORITY_SCHEDULED),
    EventDefinition("gathering.cancelled",                TOPIC_GATHERINGS,         PRIORITY_IMMEDIATE),
    # One member action (or one creator action) that books SEVERAL
    # gatherings at once — booking a whole Series, or a creator adding a
    # member to a run of recurring sessions. One summary email, never
    # one per occurrence. See ``services/gathering_booking_emit.py``.
    EventDefinition("gathering.multi_booking.confirmed",  TOPIC_GATHERINGS,         PRIORITY_IMMEDIATE),

    # Pathways
    EventDefinition("pathway.published",                  TOPIC_PATHWAYS,           PRIORITY_IMMEDIATE),
    EventDefinition("pathway.step_added",                 TOPIC_PATHWAYS,           PRIORITY_IMMEDIATE),
    EventDefinition("pathway.enrolment.completed",        TOPIC_PATHWAYS,           PRIORITY_IMMEDIATE),

    # Purchases & subscriptions — member-facing money/access lifecycle.
    # ``purchase.completed`` covers both a successful single payment and
    # the successful FIRST payment of a finite Payment Plan; the template
    # branches on ``payment_mode`` in the payload. Later successful
    # instalments do NOT re-fire this event.
    EventDefinition("purchase.completed",                 TOPIC_PURCHASES,          PRIORITY_IMMEDIATE),
    # Fires on the ``active → payment_problem`` transition inside
    # ``finite_plan_lifecycle.handle_invoice_failed_for_plan``. The grace
    # window opens atomically with the failure, so there is intentionally
    # NO separate "grace_started" event — payload carries
    # ``grace_expires_at`` for the copy. Replays and cascading same-grace
    # failures do not re-fire (guarded by the domain transition itself).
    EventDefinition("payment.instalment_failed",          TOPIC_PURCHASES,          PRIORITY_IMMEDIATE),
    # Fires on the ``payment_problem → suspended`` transition inside
    # ``finite_plan_lifecycle._suspend_plan_and_access`` (invoked by the
    # reconciler when grace elapses). One event per genuine suspension.
    EventDefinition("access.suspended",                   TOPIC_PURCHASES,          PRIORITY_IMMEDIATE),
    # Fires on ``{payment_problem, suspended} → active`` inside
    # ``finite_plan_lifecycle.record_later_successful_instalment`` when
    # a non-final instalment lands. Payload carries ``was_suspended`` so
    # the template distinguishes "access remains active" (grace recovery)
    # from "access is active again" (post-suspension recovery). Suppressed
    # when the recovery happens on the final instalment — the completion
    # email covers that member moment instead.
    EventDefinition("payment.recovered",                  TOPIC_PURCHASES,          PRIORITY_IMMEDIATE),
    # Fires when ``installments_paid >= installments_expected`` and the
    # plan transitions to ``completed`` inside
    # ``finite_plan_lifecycle.record_later_successful_instalment``. One
    # event per plan for its whole lifetime.
    EventDefinition("purchase.plan_completed",            TOPIC_PURCHASES,          PRIORITY_IMMEDIATE),
    # A refund Stripe has actually settled. Emitted from
    # ``webhooks/refund_handlers.py`` on ``charge.refunded``, which
    # Stripe fires only AFTER a refund succeeds — never on a refund
    # merely being requested. Fires once per genuine increase in the
    # charge's cumulative refunded amount, so a partial refund followed
    # by a second partial produces two events, and a duplicate webhook
    # delivery produces none.
    EventDefinition("purchase.refunded",                  TOPIC_PURCHASES,          PRIORITY_IMMEDIATE),
    # FIP4A — the very first instalment of a payment plan was declined,
    # so the plan never started. Distinct from
    # ``payment.instalment_failed``, which tells a member with LIVE
    # access that a later payment failed and their access continues
    # during grace. Here the opposite is true: nothing started, no
    # access was granted, nothing was charged, and the provider
    # schedule has been cancelled. Emitted from the shared termination
    # helper so both the synchronous card-decline and the asynchronous
    # ``invoice.payment_failed`` path are covered.
    EventDefinition("purchase.first_payment_failed",      TOPIC_PURCHASES,          PRIORITY_IMMEDIATE),
    # Creator platform-plan activation (Fresh Collective Creator /
    # Creator Portfolio tiers). Registered under TOPIC_ACCOUNT rather
    # than TOPIC_SUBSCRIPTIONS because this is a transactional
    # lifecycle email that must not be preference-gated — it is
    # event-locked in TRANSACTIONAL_EVENT_TYPES, matching the creator
    # subscription emails below. Emitted from ``creator/plan_activation.py``
    # for genuine inactive→active transitions only (the idempotent
    # no-op path returns ``was_noop=True`` and the emit site skips).
    EventDefinition("creator.plan_activated",             TOPIC_ACCOUNT,            PRIORITY_IMMEDIATE),

    # Creator monthly Stripe subscription lifecycle. Same TOPIC_ACCOUNT
    # + immediate priority as plan_activated, and event-locked for the
    # same reason — every one of these is a "your billing state has
    # changed" message that must not be preference-gated, and the
    # Account category no longer locks anything on its behalf.
    # Emitted from the creator-billing
    # webhook handlers (see ``app/webhooks/creator_billing_handlers.py``).
    EventDefinition("creator.subscription.payment_failed",         TOPIC_ACCOUNT, PRIORITY_IMMEDIATE),
    EventDefinition("creator.subscription.recovered",              TOPIC_ACCOUNT, PRIORITY_IMMEDIATE),
    EventDefinition("creator.subscription.cancellation_scheduled", TOPIC_ACCOUNT, PRIORITY_IMMEDIATE),
    EventDefinition("creator.subscription.cancelled",              TOPIC_ACCOUNT, PRIORITY_IMMEDIATE),

    # Creator updates (broadcasts internally, "Updates" to members)
    EventDefinition("creator.update.sent",                TOPIC_CREATOR_BROADCASTS, PRIORITY_IMMEDIATE),

    # Moderation / safety
    EventDefinition("moderation.action.applied",          TOPIC_MODERATION,         PRIORITY_IMMEDIATE),

    # ── Diagnostics ─────────────────────────────────────────────────
    # Provider-path proof event. Emitted only by the dev-only
    # test-send endpoint (see /api/internal/comms/dev-test-send).
    # Reuses TOPIC_ACCOUNT so no new topic migration is needed —
    # the event is scoped by its dotted key, not by topic. Priority
    # is immediate so the diagnostic intent runs through the same
    # code path a real transactional email would.
    EventDefinition("diagnostics.provider_probe",         TOPIC_ACCOUNT,            PRIORITY_IMMEDIATE),
)


_BY_TYPE: dict[str, EventDefinition] = {d.event_type: d for d in _EVENT_DEFINITIONS}


# ---------------------------------------------------------------------------
# Transactional events — the delivery lock
# ---------------------------------------------------------------------------
#
# Membership is decided by one question, asked of the *recipient*:
#
#     Can they opt out of this email without losing a security
#     message, a receipt, a money- or access-state notification, or a
#     material change to something they booked or bought?
#
# When the answer is no, the event is listed here and its delivery
# stops depending on a preference. This is a statement about reach,
# and it is deliberately separate from whether an admin may edit the
# copy: ``gathering.cancelled`` is fully editable and fully locked,
# ``account.welcome_after_signup`` is editable and not locked.
#
# Why the lock lives at the event level rather than the category
# level. ``communication_channel_defaults.is_locked`` locks a whole
# (category, channel) pair. Locking Gatherings that way to protect a
# cancellation notice would drag reminders along with it, and a
# reminder is exactly the kind of message a member should be able to
# quieten. The same reasoning emptied the Account category lock:
# migration 133 removed it precisely because every Account email that
# needed protecting is named below, and the one that did not — the
# welcome note — should not have been swept up. Purchases remains a
# locked category, so its events are belt-and-braces there; that lock
# is a seed row a future migration could reasonably revisit, and the
# guarantee these emails need should not rest on it. Listing them
# makes the promise explicit, survives a category-policy change, and
# is what the World Management inventory reads to tell an admin
# whether a member can switch an email off.
#
# What the lock does NOT do — see ``routing/decision.py``:
#   * it does not bypass hard-bounce or complaint suppression;
#   * it does not bypass the consent gates;
#   * it does not make the category itself locked, so
#     ``set_preference`` still accepts overrides for Gatherings and
#     those overrides still govern every other gathering event.
TRANSACTIONAL_EVENT_TYPES: frozenset[str] = frozenset({
    # ── Security and account entry ───────────────────────────────────
    # The member is mid-flow and waiting. A preference cannot be
    # allowed to strand someone outside their own account.
    "account.email_verification_requested",
    "account.password_reset_requested",
    # The recipient is a prospective member who usually has no account
    # and therefore no preferences at all. The preference the pipeline
    # would consult belongs to the *inviter* (see
    # ``routing/resolvers/collective.py``, which threads the inviter's
    # user_id through because the pipeline needs a real one) — so
    # without this lock a creator quietening their own Account email
    # would silence invitations addressed to other people, and a
    # digest cadence on the inviter would divert an invitation into
    # the inviter's own digest, where the invitee would never see it.
    "collective.invitation.sent",

    # ── Gatherings ───────────────────────────────────────────────────
    # Receipts for something the member just booked, and the one
    # message that tells them a thing they booked is not happening.
    # Reminders stay preference-controlled.
    "gathering.booking.confirmed",
    "gathering.multi_booking.confirmed",
    "gathering.cancelled",

    # ── Member money and access ──────────────────────────────────────
    # Purchase receipts, refund confirmations, and every transition of
    # the payment-plan lifecycle. Each states what was charged or what
    # access the member now has; several state a deadline the member
    # must act on.
    "purchase.completed",
    "purchase.refunded",
    "purchase.first_payment_failed",
    "purchase.plan_completed",
    "payment.instalment_failed",
    "payment.recovered",
    "access.suspended",

    # ── Creator plan billing ─────────────────────────────────────────
    # The creator's own subscription state: activated, failing,
    # recovered, ending, ended. Money and access, addressed to the
    # person whose money and access it is.
    "creator.plan_activated",
    "creator.subscription.payment_failed",
    "creator.subscription.recovered",
    "creator.subscription.cancellation_scheduled",
    "creator.subscription.cancelled",
})


# A typo here would fail silently — the event would simply never match
# and an essential email would stay preference-controlled. Catch it at
# import instead.
_UNREGISTERED_TRANSACTIONAL = TRANSACTIONAL_EVENT_TYPES - set(_BY_TYPE)
if _UNREGISTERED_TRANSACTIONAL:  # pragma: no cover — import-time guard
    raise RuntimeError(
        "TRANSACTIONAL_EVENT_TYPES names unregistered event types: "
        + ", ".join(sorted(_UNREGISTERED_TRANSACTIONAL))
    )


def is_transactional_event(event_type: str) -> bool:
    """True when this event is one the member cannot opt out of through
    ordinary category preferences — a security message, a receipt, a
    money- or access-state notification, or a material change to
    something they booked or bought."""
    return event_type in TRANSACTIONAL_EVENT_TYPES


def get_event_definition(event_type: str) -> EventDefinition | None:
    """Return the registered definition for an event type, or None if
    the type isn't registered. Callers of ``emit()`` receive a clear
    error rather than a None so this function stays quiet and testable.
    """
    return _BY_TYPE.get(event_type)


def registered_event_types() -> tuple[str, ...]:
    """Sorted tuple of every currently-registered event type. Useful
    for admin diagnostics and tests.
    """
    return tuple(sorted(_BY_TYPE.keys()))


def category_for_topic(topic: str) -> str:
    """Look up the member-facing category for an internal topic.

    Raises ``KeyError`` for unknown topics — a mismapping is a
    programming error, not a runtime edge case.
    """
    return TOPIC_TO_CATEGORY[topic]
