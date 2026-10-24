"""A preference category of its own for the Collective welcome email.

Revision ID: 165
Revises: 164
Create Date: 2026-10-24

The welcome email shipped silent. Two gates, either of which alone
delivers nothing and says nothing:

1. ``collective.membership.welcome`` sat under topic
   ``collective_updates``, which is absent from ``COMMS_LIVE_TOPICS``.
   ``schedule_routing_if_needed`` returns early for a topic that is not
   live, so the event row was written and no intent was ever created.

2. That topic maps to category ``community``, which migration 097 seeds
   with ``(email_transactional, default_enabled=False)``. Even with the
   first gate open, every member's effective priority is ``silent`` and
   the intent is written straight into ``recorded`` — a row that exists
   and sends nothing.

Why a new category rather than an existing one
----------------------------------------------

Each existing candidate refuses the email for a different reason.
Measured end to end, routing a welcome for a member holding default
settings:

    collective_updates -> community        state=recorded
    creator_broadcasts -> creator_updates  state=suppressed/no_consent
    account            -> account          state=sent

``community`` cannot simply be switched on: ``community.post.published``
and ``community.comment.created`` share that category and their topic is
already live, so raising the default would email every member about
every post. ``creator_updates`` is gated in ``CONSENT_GATES`` on
``creator_broadcast`` consent, and a member who has never touched that
consent has no row — which the gate reads as refusal. Every new member
is in exactly that position, so it would have replaced one silent
failure with an identical one. ``account`` does deliver, but only by
accident of its defaults, and it would tell members that a Collective's
welcome is an account matter.

So: a tenth category, and a topic carrying exactly one event. The
narrow topic is what lets ``COMMS_LIVE_TOPICS`` activate this email
without also activating the three silent membership events that share
``collective_updates``.

What this does NOT do
---------------------

Nothing retrospective. This seeds configuration rows only. Routing is
invoked at emit time and nowhere else — there is no scanner, no cron
and no replay endpoint — so welcome events already written stay inert,
including the one from the failed smoke test.

No existing category, default or consent rule is altered. ``community``
keeps email off, ``creator_updates`` keeps its consent gate, and
``account`` keeps both its defaults and its event-level locks on
password resets and verification.
"""

from alembic import op
import sqlalchemy as sa

revision = "165"
down_revision = "164"
branch_labels = None
depends_on = None


_TOPIC = "collective_welcome"
_CATEGORY = "collective_welcome"

#: Sort order 75 — between Community (70) and Creator Updates (80).
#: Member-facing settings list by this, and a welcome belongs beside
#: the other Collective-shaped preferences rather than appended after
#: platform announcements.
_SORT_ORDER = 75

_CHANNEL_DEFAULTS = [
    # (channel, default_enabled, is_locked)
    #
    # Email is the whole point: enabled, so it arrives without being
    # asked for, and unlocked, so a member can switch it off. That
    # pairing is the one the product asked for and the one no existing
    # category offered.
    ("email_transactional", True, False),
    # In-app is DISABLED until it is supported. No in-app welcome
    # template exists and ``PROVIDER_MAP`` registers email only for
    # this category, so an enabled default would advertise a channel
    # that delivers nothing — a switch in the member's settings
    # promising a notification they would never receive. Flip this to
    # True in the same change that adds the template and the provider
    # entry, not before.
    ("in_app", False, False),
    # Push is off everywhere and stays off here.
    ("push", False, False),
]


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO communication_topics (key, label) "
            "VALUES (:key, :label)"
        ).bindparams(key=_TOPIC, label="Collective Welcome")
    )
    op.execute(
        sa.text(
            "INSERT INTO communication_categories "
            "(key, label, description, sort_order, is_critical) "
            "VALUES (:key, :label, :description, :sort_order, false)"
        ).bindparams(
            key=_CATEGORY,
            label="Collective Welcome",
            description=(
                "The welcome message a Collective sends when you join it."
            ),
            sort_order=_SORT_ORDER,
        )
    )
    for channel, enabled, locked in _CHANNEL_DEFAULTS:
        op.execute(
            sa.text(
                "INSERT INTO communication_channel_defaults "
                "(id, category_key, channel, default_enabled, is_locked) "
                "VALUES (:id, :cat, :chan, :enabled, :locked)"
            ).bindparams(
                # ``ccd_{category}_{channel}`` — the deterministic id
                # scheme migration 097 established for this table.
                id=f"ccd_{_CATEGORY}_{channel}",
                cat=_CATEGORY, chan=channel,
                enabled=enabled, locked=locked,
            )
        )


def downgrade() -> None:
    # Member overrides first: ``communication_preferences`` references
    # the category, and a member who switched their welcome off has a
    # row here. Removing the category without them would either fail
    # the foreign key or orphan the rows.
    op.execute(
        sa.text(
            "DELETE FROM communication_preferences WHERE category_key = :k"
        ).bindparams(k=_CATEGORY)
    )
    op.execute(
        sa.text(
            "DELETE FROM communication_channel_defaults "
            "WHERE category_key = :k"
        ).bindparams(k=_CATEGORY)
    )
    op.execute(
        sa.text("DELETE FROM communication_categories WHERE key = :k")
        .bindparams(k=_CATEGORY)
    )
    # Topics are referenced by communication_events with ON DELETE
    # RESTRICT, so any welcome already emitted pins this row. Deleted
    # only when nothing points at it; left in place otherwise, which is
    # harmless — an unreferenced topic key affects nothing.
    op.execute(
        sa.text(
            "DELETE FROM communication_topics WHERE key = :k "
            "AND NOT EXISTS (SELECT 1 FROM communication_events "
            "WHERE topic_key = :k)"
        ).bindparams(k=_TOPIC)
    )
