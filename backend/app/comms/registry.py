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
    # by ``purchases/routes.py::claim_with_signup``). Preference-locked
    # by CATEGORY_ACCOUNT — the inbox greeting is transactional, not
    # something a first-time user can (or should) have suppressed.
    EventDefinition("account.welcome_after_signup",       TOPIC_ACCOUNT,   PRIORITY_IMMEDIATE),
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
    # record yet). CATEGORY_ACCOUNT is preference-locked-immediate.
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
    # Creator platform-plan activation (Fresh Collective Creator /
    # Creator Portfolio tiers). Registered under TOPIC_ACCOUNT rather
    # than TOPIC_SUBSCRIPTIONS because this is a transactional
    # lifecycle email that must not be preference-gated — CATEGORY_ACCOUNT
    # is default-enabled + locked-immediate, matching invitation and
    # welcome semantics. Emitted from ``creator/plan_activation.py``
    # for genuine inactive→active transitions only (the idempotent
    # no-op path returns ``was_noop=True`` and the emit site skips).
    EventDefinition("creator.plan_activated",             TOPIC_ACCOUNT,            PRIORITY_IMMEDIATE),

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
