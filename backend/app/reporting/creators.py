"""The creator journey, as metrics rather than as a bespoke query.

Four stages, each a snapshot that can be reconstructed for a past date
because every one of them rests on a record that carries its own date:
an account's ``created_at``, a Collective's ``created_at``, a
membership's ``joined_at``, a payment's settlement date. So the funnel
has a history, and it is a real history rather than today's figures
drawn backwards.

The one stage that is *not* here
-------------------------------
"Creators who have published a Collective" is the obvious fifth stage
and it cannot be reconstructed. ``spaces.status`` holds one value with
no history behind it, so there is no honest answer for a past date —
the same reason the Collective counts are observation-only. Rather than
publish a funnel with one silently-unreliable step, publishing is left
to the observed Collective counts, where its limitation is already
stated.

Each stage counts distinct **people**, so the stages narrow rather than
sum, and a creator with three Collectives is one creator throughout.

Founder-operated
----------------
Derived from the data — a Collective whose creator holds the ``admin``
role — rather than from a list of names, so it stays true as the
platform grows. It was defined inside the outstanding-payouts
breakdown; it is defined here now and imported there, because two
definitions of "founder-operated" is how the member transaction-type
set drifted.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.payment import PaymentTransaction
from app.models.platform import Space, SpaceMembership, SpaceMembershipStatus
from app.models.user import User, UserRole
from app.reporting.dates import settlement_date
from app.reporting.eligibility import member_purchase_filters
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


def founder_operated_space_ids():
    """Collectives whose creator is a platform administrator.

    Data-derived rather than a list of names: it stays correct as the
    platform grows, and it cannot quietly go stale when somebody's role
    changes.
    """
    return (
        select(Space.id)
        .join(User, User.id == Space.creator_id)
        .where(User.role == UserRole.admin.value)
    )


def _as_at(window: Window):
    return window.ends_at


def _creator_accounts(population: Population):
    """Creator accounts this population counts."""
    q = select(User.id).where(User.role == UserRole.creator.value)
    excluded = population.excluded_account_select()
    if excluded is not None:
        q = q.where(User.id.notin_(excluded))
    return q


def _spaces_in(population: Population, scope: ReportScope, as_at=None):
    """Collectives this population and scope may count."""
    q = select(Space.id, Space.creator_id)
    if as_at is not None:
        q = q.where(Space.created_at <= as_at)
    allowed = scope.space_filter
    if allowed is not None:
        if not allowed:
            return q.where(False)
        q = q.where(Space.id.in_(allowed))
    spaces = population.space_id_select()
    if spaces is not None:
        q = q.where(Space.id.in_(spaces))
    return q


def _count_distinct(db: Session, q) -> int:
    inner = q.subquery()
    return int(
        db.execute(
            select(func.count(func.distinct(inner.c[0]))).select_from(inner)
        ).scalar()
        or 0
    )


# ---------------------------------------------------------------------------
# The stages
# ---------------------------------------------------------------------------

def _creators_registered(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Creator accounts that came into being during the period.

    The flow beside ``registered_creators``, which is the snapshot.
    Counts accounts rather than Collectives: somebody who signs up and
    builds nothing is still a creator who arrived, and losing them from
    the figure would make the funnel look healthier than it is.
    """
    q = db.query(func.count(User.id)).filter(User.role == UserRole.creator.value)
    if window.starts_at is not None:
        q = q.filter(User.created_at >= window.starts_at)
    if window.ends_at is not None:
        q = q.filter(User.created_at < window.ends_at)
    excluded = population.excluded_account_select()
    if excluded is not None:
        q = q.filter(User.id.notin_(excluded))
    return MetricValue(
        key="creators_registered",
        value=int(q.scalar() or 0),
        qualifiers=population.qualifiers(),
    )


def _creators_with_a_collective(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Creators who had built at least one Collective, as at the date."""
    as_at = _as_at(window)
    spaces = _spaces_in(population, scope, as_at).subquery()
    q = (
        select(spaces.c.creator_id)
        .where(spaces.c.creator_id.in_(_creator_accounts(population)))
    )
    return MetricValue(
        key="creators_with_a_collective",
        value=_count_distinct(db, q),
        qualifiers={**population.qualifiers(), "as_at": _label(window)},
    )


def _creators_with_a_member(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Creators whose Collectives held at least one member, as at the date.

    Membership is reconstructed from ``joined_at`` / ``removed_at``, the
    same basis ``unique_members`` uses, so this is a real past figure
    rather than today's drawn backwards.
    """
    as_at = _as_at(window)
    spaces = _spaces_in(population, scope, as_at).subquery()

    members = select(SpaceMembership.space_id).where(
        SpaceMembership.joined_at <= as_at if as_at is not None else True,
    )
    if as_at is not None:
        members = members.where(
            (SpaceMembership.removed_at.is_(None))
            | (SpaceMembership.removed_at > as_at)
        )
    else:
        members = members.where(
            SpaceMembership.status == SpaceMembershipStatus.active
        )
    excluded = population.excluded_account_select()
    if excluded is not None:
        # A Collective whose only member is a test account has not
        # attracted anybody, and counting its creator as having done so
        # is the inflation this whole classification exists to prevent.
        members = members.where(SpaceMembership.user_id.notin_(excluded))

    q = (
        select(spaces.c.creator_id)
        .where(
            spaces.c.creator_id.in_(_creator_accounts(population)),
            spaces.c.id.in_(members),
        )
    )
    return MetricValue(
        key="creators_with_a_member",
        value=_count_distinct(db, q),
        qualifiers={**population.qualifiers(), "as_at": _label(window)},
    )


def _creators_earning(
    db: Session, scope: ReportScope, window: Window,
    population: Population = ALL,
) -> MetricValue:
    """Creators whose Collectives had taken money, as at the date.

    Counted on the settlement date, the same basis every money metric
    uses, so a creator joins this stage the period their first payment
    arrived rather than the period a checkout was created.
    """
    from app.core.config import settings

    as_at = _as_at(window)
    spaces = _spaces_in(population, scope, as_at).subquery()

    paid = select(PaymentTransaction.space_id).where(
        *member_purchase_filters(settings.stripe_mode),
    )
    if as_at is not None:
        paid = paid.where(settlement_date() < as_at)

    q = (
        select(spaces.c.creator_id)
        .where(
            spaces.c.creator_id.in_(_creator_accounts(population)),
            spaces.c.id.in_(paid),
        )
    )
    return MetricValue(
        key="creators_earning",
        value=_count_distinct(db, q),
        qualifiers={**population.qualifiers(), "as_at": _label(window)},
    )


def _label(window: Window) -> str:
    return window.ends_at.isoformat() if window.ends_at else "now"


_STAGES = (
    (
        "creators_with_a_collective",
        "Creators with a Collective",
        "Creators who have built at least one Collective, whatever its stage.",
        "spaces.created_at, counted as-at",
        _creators_with_a_collective,
    ),
    (
        "creators_with_a_member",
        "Creators with a member",
        (
            "Creators whose Collectives hold at least one membership. "
            "Somebody has arrived."
        ),
        "space_memberships.joined_at / removed_at, reconstructed as-at",
        _creators_with_a_member,
    ),
    (
        "creators_earning",
        "Creators earning",
        "Creators whose Collectives have taken at least one settled payment.",
        "payment_transactions, counted on the settlement date",
        _creators_earning,
    ),
)

for _key, _name, _definition, _source, _compute in _STAGES:
    REGISTRY.add(Metric(
        key=_key,
        display_name=_name,
        definition=_definition,
        source_of_truth=_source,
        grain=Grain.snapshot,
        # A snapshot of people, so a week is the state at its end and
        # never the sum of its days — a creator who had a member on
        # Monday still has one on Tuesday.
        aggregation=Aggregation.snapshot,
        date_basis=DateBasis.none,
        access=Access.platform_only,
        availability=Availability.full,
        limitations=(
            "Counts people, so the stages narrow rather than add up and a "
            "creator with three Collectives is one creator throughout. A "
            "snapshot — take the latest, never sum across periods."
        ),
        # **No ``space_id``.** Per Collective these degenerate to a
        # boolean — "does this Collective's creator have a member" is 0
        # or 1 — which is not a figure anybody would read, and
        # declaring the dimension made the loader write twenty-one such
        # rows a day beside the four that mean something. A request to
        # break one of these down by Collective is refused with a
        # reason instead, which is the honest answer: the creator
        # journey is a platform-level question.
        dimensions=(POPULATION_DIMENSION,),
        personal_data=True,
        compute=_compute,
    ))

REGISTRY.add(Metric(
    key="creators_registered",
    display_name="Creators registered",
    definition=(
        "Creator accounts created during the period. The flow beside the "
        "'Registered creators' snapshot."
    ),
    source_of_truth="users.created_at where role = creator",
    grain=Grain.period,
    aggregation=Aggregation.additive,
    date_basis=DateBasis.created,
    access=Access.platform_only,
    availability=Availability.full,
    limitations=(
        "An account, not a Collective. Somebody who signs up and builds "
        "nothing still counts here, which is the point — the gap between "
        "this and 'Creators with a Collective' is the first step of the "
        "journey."
    ),
    dimensions=(POPULATION_DIMENSION,),
    personal_data=True,
    compute=_creators_registered,
))
