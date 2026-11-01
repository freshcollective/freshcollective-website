"""World Builders — the creator learning environment, measured.

World Builders is where creators learn to build: Pathways about
establishing a Collective, Gatherings, Conversations, and the guidance
that sits behind Creator Studio. It is classified
``internal_operations`` and stays that way, so it never inflates the
production figures on the other six dashboards. That classification is
the reason it was invisible, not a reason it should be.

Almost nothing here is new
--------------------------
Thirty-two of the registry's metrics already declare ``space_id``, so
membership, participation, Pathway steps, Gathering attendance and
Conversation activity are answered for World Builders by the existing
metrics with a Collective filter. This module adds only the three
questions the registry could not already answer, and each exists
because the obvious substitute would be wrong:

* **Eligibility** is not membership and is not "creator accounts".
* **Participation by a creator** needs the independent / founder-
  operated split, which a space-scoped participation count does not
  carry.
* **Development milestones** need to be readable side by side for
  creators who did and did not take part.

Eligible is not joined, and joined is not a choice
--------------------------------------------------
Membership of World Builders is **granted automatically**. Any user
passing ``is_eligible_creator`` gets a ``source='auto_role'``
membership, reconciled whenever their eligibility changes. So "creators
who joined" is not a funnel stage a creator ever passes through, and
presenting it as one would describe a decision nobody made.

The gap that *is* real runs in both directions, which is why both
figures are reported:

* Eligible but not a member — reconciliation has not run, or the row
  was removed.
* A member but not eligible — the founder's account holds the ``admin``
  role, so it fails the strict predicate while genuinely taking part.

The predicate here is the strict one from
``services.creator_eligibility``, because that is what actually decides
the grant. It is deliberately **not** ``creator_accounts``, which the
Creators dashboard widens to "anybody operating a Collective" so the
founder stays visible. Two different questions, two different
populations, and conflating them would make the eligibility figure a
description of nothing.

What this module will not claim
-------------------------------
There is no completion metric. ``ActivityType.pathway_completed`` is
declared and never emitted, and a step count cannot stand in for it:
the set of steps in a Pathway changes over time, so "finished every
step" is not answerable for a past date. Steps completed and distinct
Pathway participants are both real and both reported; completion is
not.

Nothing here reads a Conversation's text, a reflection, or a message.
Participation is counted from the existence of an act, never from what
it said.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.platform import (
    Space,
    SpaceMembership,
    SpaceMembershipStatus,
)
from app.models.user import User, UserRole
from app.reporting.creators import founder_operated_space_ids
from app.reporting.engagement import participation_events
from app.reporting.population import (
    ALL,
    DIMENSION as POPULATION_DIMENSION,
    Population,
)
from app.reporting.registry import (
    REGISTRY,
    Aggregation,
    Availability,
    DateBasis,
    Grain,
    Metric,
    MetricValue,
    Window,
)
from app.reporting.scope import Access, ReportScope


def learning_space_ids():
    """Collectives whose membership is granted by role, as a select.

    Structural, like every other World Builders lookup in the codebase:
    ``Space.auto_grant_role IS NOT NULL`` rather than a slug. A renamed
    or re-slugged Collective keeps reporting; a second learning
    environment starts reporting without a code change.
    """
    return select(Space.id).where(Space.auto_grant_role.isnot(None))


def _eligible_creator_ids(population: Population):
    """Accounts the auto-grant rule considers eligible, as a select.

    The strict predicate from ``services.creator_eligibility`` —
    ``role == 'creator'`` and neither suspended nor cancelled —
    expressed in SQL because it has to run over the whole table rather
    than per user. If that module's rule changes, this is the line that
    has to change with it; the contract test asserts the three
    conditions are all present.
    """
    q = select(User.id).where(
        User.role == UserRole.creator.value,
        User.creator_suspended_at.is_(None),
        User.creator_cancelled_at.is_(None),
    )
    excluded = population.excluded_account_select()
    if excluded is not None:
        q = q.where(User.id.notin_(excluded))
    return q


def _wb_members_select():
    """Active memberships of a learning Collective, as (user_id)."""
    return (
        select(SpaceMembership.user_id)
        .where(
            SpaceMembership.space_id.in_(learning_space_ids()),
            SpaceMembership.status == SpaceMembershipStatus.active,
        )
    )


def _eligible_creators(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """How many creators the auto-grant rule currently covers.

    A snapshot of a predicate over the ``users`` table, which carries no
    history of role, suspension or cancellation — so this is today's
    answer and cannot be reconstructed for a past date. Declared
    ``observation_only`` for exactly that reason.
    """
    eligible = set(r[0] for r in db.execute(_eligible_creator_ids(population)))
    members = set(r[0] for r in db.execute(_wb_members_select()))
    return MetricValue(
        key="wb_eligible_creators",
        value=len(eligible),
        qualifiers={
            **population.qualifiers(),
            # Both directions, because both happen and each means
            # something different. See the module docstring.
            "members": len(members),
            "eligible_without_membership": len(eligible - members),
            "members_not_eligible": len(members - eligible),
            "grant_note": (
                "Membership is granted automatically to eligible creators, "
                "so joining is not a step a creator chooses to take. A "
                "member who is not eligible holds the membership another "
                "way — the founder's account holds the admin role."
            ),
        },
    )


def _wb_participation(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Distinct people who did something in a learning Collective.

    Distinct people, not acts: somebody who completes four steps and
    posts twice is one participant. Split by whether they operate a
    founder-operated Collective, which is the comparison section 14
    asks for — and the split is descriptive, not a judgement about
    whose participation counts.
    """
    part = participation_events()
    q = select(part.c.user_id).where(
        part.c.space_id.in_(learning_space_ids()),
        part.c.user_id.isnot(None),
    )
    if window.starts_at is not None:
        q = q.where(part.c.occurred_at >= window.starts_at)
    if window.ends_at is not None:
        q = q.where(part.c.occurred_at < window.ends_at)
    excluded = population.excluded_account_select()
    if excluded is not None:
        q = q.where(part.c.user_id.notin_(excluded))

    people = {r[0] for r in db.execute(q)}

    founders = {
        r[0]
        for r in db.execute(
            select(Space.creator_id).where(
                Space.id.in_(founder_operated_space_ids()),
                Space.creator_id.isnot(None),
            )
        )
    }

    # Which kinds of act produced the figure, so a participation count
    # is never a number without a shape — four Conversation reactions
    # and four completed Pathway steps are not the same month.
    by_kind = dict(
        db.execute(
            select(part.c.kind, func.count(func.distinct(part.c.user_id)))
            .where(
                part.c.space_id.in_(learning_space_ids()),
                part.c.user_id.isnot(None),
                *(
                    [part.c.occurred_at >= window.starts_at]
                    if window.starts_at is not None
                    else []
                ),
                *(
                    [part.c.occurred_at < window.ends_at]
                    if window.ends_at is not None
                    else []
                ),
            )
            .group_by(part.c.kind)
        ).all()
    )

    return MetricValue(
        key="wb_creator_participation",
        value=len(people),
        qualifiers={
            **population.qualifiers(),
            "founder_operated": len(people & founders),
            "independent": len(people - founders),
            "distinct_people_by_kind": {k: int(v) for k, v in by_kind.items()},
        },
    )


#: The development milestones that can be read as a current state.
#:
#: Each rests on a record that exists today. Three more were asked for
#: and are **not** here, because the records do not support them:
#: a Pathway has a status and no published date, a Gathering has
#: ``is_published`` and no date, so "published their first Pathway" and
#: "published a Gathering" have no honest answer even for today beyond
#: "has one that is currently published" — which is a different
#: sentence, and is the one used. An Offering does carry
#: ``published_at``.
_MILESTONES = ("has_collective", "has_member", "has_sale")


def _creator_development(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Where creators have got to, beside whether they used World Builders.

    **Descriptive, and only descriptive.** Creators who take part in a
    learning environment are not a random sample of creators — someone
    already building is more likely to come looking for guidance — so a
    difference between the two columns is not evidence that World
    Builders produced it, and nothing in the output says it is.

    A current state rather than a trend. Milestone dates exist for some
    of these and not others, and a funnel that reconstructed three
    stages and froze the rest would read as one coherent history.
    """
    from app.models.payment import PaymentTransaction, PaymentTransactionStatus

    part = participation_events()
    participants = {
        r[0]
        for r in db.execute(
            select(part.c.user_id).where(
                part.c.space_id.in_(learning_space_ids()),
                part.c.user_id.isnot(None),
            )
        )
    }

    creators = {r[0] for r in db.execute(_eligible_creator_ids(population))}
    owners = {
        r[0]: r[1]
        for r in db.execute(
            select(Space.creator_id, Space.id).where(Space.creator_id.isnot(None))
        )
    }
    creators |= set(owners)

    with_collective = set(owners)

    with_member = {
        r[0]
        for r in db.execute(
            select(Space.creator_id)
            .join(SpaceMembership, SpaceMembership.space_id == Space.id)
            .where(
                Space.creator_id.isnot(None),
                SpaceMembership.status == SpaceMembershipStatus.active,
                SpaceMembership.user_id != Space.creator_id,
            )
        )
    }

    with_sale = {
        r[0]
        for r in db.execute(
            select(Space.creator_id)
            .join(PaymentTransaction, PaymentTransaction.space_id == Space.id)
            .where(
                Space.creator_id.isnot(None),
                PaymentTransaction.status.in_(
                    [
                        PaymentTransactionStatus.succeeded.value,
                        PaymentTransactionStatus.partially_refunded.value,
                    ]
                ),
            )
        )
    }

    def side(group: set[str]) -> dict:
        return {
            "creators": len(group),
            "has_collective": len(group & with_collective),
            "has_member": len(group & with_member),
            "has_sale": len(group & with_sale),
        }

    took_part = creators & participants
    did_not = creators - participants

    return MetricValue(
        key="wb_creator_development",
        value=len(took_part),
        qualifiers={
            **population.qualifiers(),
            "participated": side(took_part),
            "did_not_participate": side(did_not),
            "milestones": list(_MILESTONES),
            "comparison_note": (
                "Descriptive only. Creators who take part in World Builders "
                "are not a random sample of creators — somebody already "
                "building is more likely to come looking for guidance — so "
                "a difference between these two groups is not evidence that "
                "World Builders caused it."
            ),
            "unsupported_note": (
                "'Published their first Pathway' and 'published a "
                "Gathering' are not here: a Pathway carries a status and no "
                "publication date, and a Gathering carries is_published and "
                "no date, so neither has an honest answer for any date."
            ),
        },
    )


REGISTRY.add(Metric(
    key="wb_eligible_creators",
    display_name="Creators eligible for World Builders",
    definition=(
        "Creators the automatic-access rule currently covers: an active "
        "creator account, neither suspended nor cancelled. Membership "
        "follows automatically, so this is reach rather than a count of "
        "people who chose to join."
    ),
    source_of_truth="users.role, creator_suspended_at, creator_cancelled_at",
    grain=Grain.snapshot,
    aggregation=Aggregation.snapshot,
    date_basis=DateBasis.none,
    access=Access.platform_only,
    availability=Availability.full,
    limitations=(
        "Today's answer only. The users table keeps no history of role, "
        "suspension or cancellation, so how many creators were eligible "
        "last March cannot be worked out. Narrower than 'Creator "
        "accounts' on the Creators dashboard, which deliberately counts "
        "anybody operating a Collective whatever their role — the "
        "founder is a creator there and is not eligible here."
    ),
    observation_only=True,
    dimensions=(POPULATION_DIMENSION,),
    personal_data=True,
    compute=_eligible_creators,
))

REGISTRY.add(Metric(
    key="wb_creator_participation",
    display_name="Creators taking part in World Builders",
    definition=(
        "People who posted, commented, reacted, attended a Gathering or "
        "completed a Pathway step in World Builders during the period. "
        "Counted once each however much they did."
    ),
    source_of_truth=(
        "community_posts, post_comments, post_reactions, event_bookings, "
        "step_progress — restricted to Collectives with an automatic-"
        "access rule"
    ),
    grain=Grain.period,
    aggregation=Aggregation.distinct_count,
    date_basis=DateBasis.business_event,
    access=Access.platform_only,
    availability=Availability.full,
    limitations=(
        "Taking part is not completing. There is no reliable completion "
        "event for a Pathway, so nothing here says a creator finished "
        "anything. Somebody who stops appearing has not necessarily "
        "disengaged — they may have found what they came for."
    ),
    dimensions=(POPULATION_DIMENSION,),
    personal_data=True,
    compute=_wb_participation,
))

REGISTRY.add(Metric(
    key="wb_creator_development",
    display_name="Creator development, beside World Builders use",
    definition=(
        "Creators who have ever taken part in World Builders, with how "
        "far they and other creators have got: a Collective, a first "
        "member, a first sale. A description of two groups, not a claim "
        "about what moved anyone between stages."
    ),
    source_of_truth="spaces, space_memberships, payment_transactions",
    grain=Grain.snapshot,
    aggregation=Aggregation.snapshot,
    date_basis=DateBasis.none,
    access=Access.platform_only,
    availability=Availability.partial,
    limitations=(
        "Descriptive, never causal: creators who seek out guidance are "
        "not a random sample of creators. A current state rather than a "
        "trend — some milestones carry dates and others do not, and a "
        "funnel mixing the two would read as one history. 'Published a "
        "first Pathway' and 'published a Gathering' are absent because "
        "neither record carries a publication date."
    ),
    observation_only=True,
    dimensions=(POPULATION_DIMENSION,),
    personal_data=True,
    compute=_creator_development,
))
