"""Every metric that declares a classification filter must apply it.

The failure this exists for is the one a reader cannot catch. A metric
that declares ``reporting_class`` and then ignores it returns the
whole-platform figure under a heading that says "Production" — the
number looks reasonable, the label looks right, and nothing on the page
is wrong enough to notice.

It happened. Ten engagement metrics were given the dimension in one
pass; three of them built their own queries rather than going through
the shared scoping helper, so ``gathering_attendance``,
``pathway_steps_completed`` and ``overlap_vs_engagement`` counted test
Collectives in a production view.

Declaring is cheap and applying is not, so the declaration is checked
against behaviour here rather than trusted. Every metric is exercised
by the same fixture: all activity belongs to a Collective classified
``test``, performed by an account classified ``test``. A production
view of that world is empty. Any metric that reports otherwise is
ignoring the filter it declares.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

import app.models.community_care  # noqa: F401
from app.models.payment import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from app.models.platform import (
    CommunityPost,
    ConversationChannel,
    EventBooking,
    Pathway,
    PathwayStep,
    PostComment,
    PostReaction,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
    StepProgress,
)
from app.reporting.classification import TEST
from app.reporting.population import DIMENSION, Population, PopulationView
from app.reporting.registry import REGISTRY, Window
from app.reporting.scope import platform_scope

WINDOW = Window(datetime(2026, 10, 1), datetime(2026, 11, 1), "oct")
WHEN = datetime(2026, 10, 10)


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def test_only_world(db, make_user, make_space, make_event):
    """A platform whose every record is classified ``test``.

    One Collective, one member, and one of every kind of activity the
    registry recognises. Under ``production`` nothing here counts.
    """
    # The creator is classified too. An *unclassified* account is
    # deliberately counted as production — that is the rule — so a
    # fixture that left the Collective's owner unclassified would make
    # the account-counting metrics look as though they ignored the
    # filter when they were obeying it.
    creator = make_user(role="creator", reporting_class=TEST)
    space = make_space(name="Fixture", creator=creator, reporting_class=TEST)
    member = make_user(reporting_class=TEST)

    db.add(SpaceMembership(
        id=_uid("sm"), user_id=member.id, space_id=space.id,
        role=SpaceRole.learner, status=SpaceMembershipStatus.active,
        joined_at=datetime(2026, 1, 1),
    ))

    channel = ConversationChannel(
        id=_uid("ch"), space_id=space.id, name="General",
        slug=f"general-{uuid.uuid4().hex[:6]}", channel_type="standard",
    )
    db.add(channel)
    db.flush()
    post = CommunityPost(
        id=_uid("cp"), space_id=space.id, channel_id=channel.id,
        author_id=member.id, body="hello", created_at=WHEN,
    )
    db.add(post)
    db.flush()
    db.add(PostComment(
        id=_uid("pc"), post_id=post.id, author_id=member.id,
        body="reply", created_at=WHEN,
    ))
    db.add(PostReaction(
        id=_uid("pr"), post_id=post.id, user_id=member.id,
        emoji="\u2764\ufe0f", created_at=WHEN,
    ))

    event = make_event(space=space, starts_at=WHEN,
                       ends_at=WHEN + timedelta(hours=1))
    db.add(EventBooking(
        id=_uid("bk"), event_id=event.id, user_id=member.id,
        status="confirmed", booked_at=WHEN, attendance_status="attended",
    ))

    pathway = Pathway(
        id=_uid("pw"), space_id=space.id, title="A Pathway",
        slug=f"pw-{uuid.uuid4().hex[:6]}",
    )
    db.add(pathway)
    db.flush()
    step = PathwayStep(
        id=_uid("st"), pathway_id=pathway.id, title="Step",
        slug=f"step-{uuid.uuid4().hex[:6]}", position=1,
    )
    db.add(step)
    db.flush()
    db.add(StepProgress(
        id=_uid("sp"), user_id=member.id, step_id=step.id, completed_at=WHEN,
    ))

    db.add(PaymentTransaction(
        id=_uid("txn"),
        transaction_type=PaymentTransactionType.member_pathway_purchase,
        status=PaymentTransactionStatus.succeeded,
        payer_user_id=member.id, creator_user_id=creator.id,
        space_id=space.id, currency="AUD", gross_amount_cents=5000,
        platform_fee_basis_points=1000, platform_fee_cents=500,
        net_creator_amount_cents=4500, processing_fee_cents=150,
        stripe_mode="test", created_at=WHEN, settled_at=WHEN,
    ))
    db.flush()
    return space, member


DECLARING = sorted(m.key for m in REGISTRY.all() if DIMENSION in m.dimensions)


class TestDeclaringTheFilterMeansApplyingIt:
    def test_the_registry_declares_it_everywhere(self):
        assert len(DECLARING) == len(REGISTRY), (
            "every metric should be narrowable; see the engagement family"
        )

    @pytest.mark.parametrize("key", DECLARING)
    def test_a_production_view_excludes_a_test_world(self, db, test_only_world, key):
        """All the activity is test-classified, so production sees none."""
        metric = REGISTRY.get(key)
        everything = metric.evaluate(
            db, platform_scope(), WINDOW, Population(PopulationView.all),
        )
        production = metric.evaluate(
            db, platform_scope(), WINDOW, Population(PopulationView.production),
        )

        if everything.value in (None, 0):
            pytest.skip(f"{key} reports nothing even unfiltered here")

        assert production.value in (None, 0), (
            f"{key} reports {production.value} under Production while every "
            f"record in the database is classified test — it declares the "
            f"filter and does not apply it"
        )

    @pytest.mark.parametrize("key", DECLARING)
    def test_the_filter_is_not_simply_breaking_the_metric(
        self, db, test_only_world, key,
    ):
        """A metric that returns nothing for *every* population would
        pass the test above by being broken rather than by filtering."""
        metric = REGISTRY.get(key)
        under_test = metric.evaluate(
            db, platform_scope(), WINDOW, Population.parse(TEST),
        )
        everything = metric.evaluate(
            db, platform_scope(), WINDOW, Population(PopulationView.all),
        )
        if everything.value in (None, 0):
            pytest.skip(f"{key} reports nothing even unfiltered here")
        assert under_test.value == everything.value, (
            f"{key} under the 'test' population should match the unfiltered "
            f"figure, because every record here is test-classified"
        )
