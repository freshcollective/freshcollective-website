"""Audit and removal of the three disposable production test accounts.

This is the most destructive code in the repository: it deletes user
rows, and around forty foreign keys cascade from one. So the tests are
mostly about what it *refuses* to do.

The properties that matter: the scope is exactly three emails, Tom is
untouchable, anything attached to somebody outside the set is a refusal
rather than a warning, and the dry run writes nothing.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_test_account_cleanup.py
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import text

import app.models.community_care  # noqa: F401
from app.models.connections import MemberHello
from app.models.peer_messages import PeerMessage, PeerThread, canonical_pair
from app.models.platform import (
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User
from app.services import test_account_cleanup as cleanup
from app.services.test_account_cleanup import (
    PROTECTED_EMAILS,
    TARGET_EMAILS,
    apply_cleanup,
    audit,
    protected_snapshot,
    recheck_unchanged,
    user_fk_columns,
    verify_deletion_outcome,
    verify_protected_intact,
)

JENSON = "jenson@hilliard.net.au"
CREATOR = "hello@freshcollective.au"
LINDSEY_TEST = "lindsey.wd@gmail.com"
TOM = "tom@hilliard.net.au"


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _exists(db, user_id: str) -> bool:
    """Whether the row is still there, asked of the database.

    ``db.get`` would answer from the identity map, and ``apply_cleanup``
    deletes with Core statements that do not pass through it — so a
    deleted user still comes back as an object.
    """
    return bool(db.scalar(
        text("SELECT 1 FROM users WHERE id = :u"), {"u": user_id},
    ))


@pytest.fixture
def mk_channel(db):
    """``community_posts.channel_id`` is NOT NULL and ``make_space``
    creates no default channel, so a post needs one made for it."""
    def _make(space):
        channel_id = _uid("ch")
        db.execute(text(
            "INSERT INTO conversation_channels "
            "(id, space_id, name, slug, channel_type, is_default, "
            " is_archived, show_in_navigation, position, "
            " member_posting_allowed) "
            "VALUES (:i, :s, 'Common Room', 'common-room', 'general', "
            "        true, false, true, 0, true)"
        ), {"i": channel_id, "s": space.id})
        db.flush()
        return channel_id
    return _make


@pytest.fixture
def mk(db):
    """A user at a given email, so the fixtures read like the real
    accounts rather than like ``user_1``."""
    def _make(email: str, *, role: str = "user", name: str = "Test") -> User:
        u = User(
            id=_uid("u"), email=email, name=name, role=role,
            password_hash="$2b$12$" + "0" * 53,
            email_verified_at=datetime.utcnow(),
        )
        db.add(u)
        db.flush()
        return u
    return _make


class TestTheScopeIsFixed:
    def test_exactly_the_three_approved_emails(self):
        assert TARGET_EMAILS == (JENSON, CREATOR, LINDSEY_TEST)

    def test_tom_is_protected(self):
        assert TOM in PROTECTED_EMAILS

    def test_tom_is_not_a_target(self):
        assert TOM not in TARGET_EMAILS

    def test_no_protected_email_is_also_a_target(self):
        assert not set(PROTECTED_EMAILS) & set(TARGET_EMAILS)

    def test_the_scope_is_not_a_cli_argument(self):
        """A cleanup that takes an arbitrary email from whoever runs it
        is a different and much worse tool."""
        src = (
            cleanup.__file__.replace("test_account_cleanup.py", "")
            and __import__("pathlib").Path(
                __import__("pathlib").Path(cleanup.__file__).parent.parent.parent
                / "scripts" / "cleanup_production_test_accounts.py"
            ).read_text()
        )
        assert "add_argument" in src
        for smell in ("--email", "--user", "--target", "--all"):
            assert smell not in src, f"scope must not be caller-supplied: {smell}"

    def test_a_protected_email_is_refused_even_if_someone_lists_it(
        self, db, mk, monkeypatch,
    ):
        """The runtime belt for the disjointness assertion above.

        If somebody edits ``TARGET_EMAILS`` to include Tom, the test
        above fails in CI — but a failing test can be ignored, and the
        script would then be pointed at him. So the refusal also exists
        at run time, and this exercises it by forcing exactly that
        misconfiguration.
        """
        monkeypatch.setattr(
            cleanup, "TARGET_EMAILS", TARGET_EMAILS + (TOM,),
        )
        mk(TOM, name="Tom Test")

        plan = audit(db)
        finding = next(f for f in plan.findings if f.email == TOM)
        assert not finding.safe
        assert any(b.kind == "protected_account" for b in finding.blockers)
        with pytest.raises(RuntimeError, match="refusing to apply"):
            apply_cleanup(db, plan)

    def test_an_admin_is_refused_even_if_listed(self, db, mk):
        """Protects the real Lindsey Hilliard admin account from ever
        being caught by a typo in the target list."""
        mk(LINDSEY_TEST, role="admin", name="Oops An Admin")
        plan = audit(db)
        finding = next(f for f in plan.findings if f.email == LINDSEY_TEST)
        assert not finding.safe
        assert any(b.kind == "admin_account" for b in finding.blockers)


class TestTheAuditWritesNothing:
    def test_auditing_changes_no_row(self, db, mk):
        jenson = mk(JENSON)
        lindsey = mk(LINDSEY_TEST)
        before = db.scalar(text("SELECT count(*) FROM users"))

        audit(db)

        assert db.scalar(text("SELECT count(*) FROM users")) == before
        for u in (jenson, lindsey):
            assert db.get(User, u.id) is not None

    def test_the_dependency_map_comes_from_the_schema(self, db):
        """Not a hand-written list, which would be wrong the moment
        somebody adds a table."""
        columns = user_fk_columns(db)
        refs = {f"{t}.{c}" for t, c, _ in columns}
        # A sample across the three delete rules.
        assert "space_memberships.user_id" in refs
        assert "creator_subscriptions.user_id" in refs
        assert "payment_transactions.payer_user_id" in refs
        rules = {r for _, _, r in columns}
        assert {"CASCADE", "RESTRICT", "SET NULL"} <= rules

    def test_a_missing_table_does_not_crash_the_audit(self, db, mk):
        """A database behind on migrations is a real situation — the
        local copy of production was missing ``peer_threads`` — and the
        audit has to stay readable there."""
        mk(LINDSEY_TEST)
        assert cleanup.table_exists(db, "users") is True
        assert cleanup.table_exists(db, "no_such_table_at_all") is False
        audit(db)  # must not raise


class TestAbsentTargetsAreSafe:
    def test_none_present_is_not_an_error(self, db):
        plan = audit(db)
        assert all(not f.present for f in plan.findings)
        assert plan.safe is False, "nothing to do is not 'safe to apply'"

    def test_apply_refuses_when_there_is_nothing_to_do(self, db):
        plan = audit(db)
        with pytest.raises(RuntimeError):
            apply_cleanup(db, plan)

    def test_a_partially_present_set_reports_per_account(self, db, mk):
        mk(JENSON)
        plan = audit(db)
        present = {f.email: f.present for f in plan.findings}
        assert present[JENSON] is True
        assert present[CREATOR] is False
        assert present[LINDSEY_TEST] is False


class TestSharedDataBlocksDeletion:
    def test_a_peer_thread_with_an_outsider_blocks(self, db, mk):
        """Deleting a participant cascades the thread and *both* sides'
        messages. The other person's words are not ours to delete."""
        jenson = mk(JENSON)
        real = mk("kelly@example.com", name="Kelly Hamilton")
        low, high = canonical_pair(jenson.id, real.id)
        thread = PeerThread(
            id=_uid("pt"), participant_a_user_id=low, participant_b_user_id=high,
        )
        db.add(thread)
        db.flush()
        db.add(PeerMessage(
            id=_uid("pm"), thread_id=thread.id,
            sender_user_id=real.id, body="Mine, not yours to delete",
        ))
        db.flush()

        finding = next(f for f in audit(db).findings if f.email == JENSON)
        assert not finding.safe
        assert any(b.kind == "shared_peer_thread" for b in finding.blockers)

    def test_a_peer_thread_between_two_targets_does_not_block(self, db, mk):
        """Both ends are being removed, so nothing survives to be
        orphaned and nobody else loses anything."""
        jenson = mk(JENSON)
        creator = mk(CREATOR)
        low, high = canonical_pair(jenson.id, creator.id)
        db.add(PeerThread(
            id=_uid("pt"), participant_a_user_id=low, participant_b_user_id=high,
        ))
        db.flush()

        plan = audit(db)
        for email in (JENSON, CREATOR):
            finding = next(f for f in plan.findings if f.email == email)
            assert not any(
                b.kind == "shared_peer_thread" for b in finding.blockers
            ), email

    def test_a_thread_with_tom_blocks(self, db, mk):
        """Tom counts as an outsider. His conversation is his."""
        jenson = mk(JENSON)
        tom = mk(TOM, name="Tom Test")
        low, high = canonical_pair(jenson.id, tom.id)
        db.add(PeerThread(
            id=_uid("pt"), participant_a_user_id=low, participant_b_user_id=high,
        ))
        db.flush()

        finding = next(f for f in audit(db).findings if f.email == JENSON)
        assert any(b.kind == "shared_peer_thread" for b in finding.blockers)

    def test_a_creator_member_thread_with_an_outsider_blocks(
        self, db, mk, make_space,
    ):
        """``message_threads.creator_id``/``member_id`` cascade, and
        ``direct_messages.thread_id`` cascades from the thread — so the
        creator's side of the conversation goes too."""
        jenson = mk(JENSON)
        real = mk("kelly@example.com", name="Kelly Hamilton")
        space = make_space(creator=real)
        thread_id = _uid("mt")
        db.execute(text(
            "INSERT INTO message_threads "
            "(id, space_id, member_id, creator_id, created_at, updated_at) "
            "VALUES (:i, :s, :m, :c, now(), now())"
        ), {"i": thread_id, "s": space.id, "m": jenson.id, "c": real.id})
        db.flush()
        db.execute(text(
            "INSERT INTO direct_messages "
            "(id, thread_id, sender_id, body, created_at) "
            "VALUES (:i, :t, :u, 'The creator replied', now())"
        ), {"i": _uid("dm"), "t": thread_id, "u": real.id})
        db.flush()

        finding = next(f for f in audit(db).findings if f.email == JENSON)
        assert not finding.safe
        assert any(
            b.kind == "shared_message_thread" for b in finding.blockers
        ), [b.kind for b in finding.blockers]

    def test_a_conversation_other_people_engaged_with_blocks(
        self, db, mk, make_space, mk_channel,
    ):
        """``community_posts.author_id`` cascades, and comments and
        reactions cascade from the post — so a real member's comment
        goes with it."""
        from app.models.platform import CommunityPost, PostComment

        jenson = mk(JENSON)
        real = mk("kelly@example.com")
        space = make_space()
        channel_id = mk_channel(space)
        post = CommunityPost(
            id=_uid("cp"), space_id=space.id, author_id=jenson.id,
            channel_id=channel_id, body="Jenson's post", is_visible=True,
        )
        db.add(post)
        db.flush()
        db.add(PostComment(
            id=_uid("pc"), post_id=post.id, author_id=real.id,
            body="A real member's comment",
        ))
        db.flush()

        finding = next(f for f in audit(db).findings if f.email == JENSON)
        assert any(b.kind == "engaged_conversation" for b in finding.blockers)

    def test_a_collective_with_an_outside_member_blocks(
        self, db, mk, make_space,
    ):
        jenson = mk(JENSON, role="creator")
        real = mk("kelly@example.com")
        space = make_space(creator=jenson, slug="jensons-test-community",
                           name="Jenson's Test Community")
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=real.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.flush()

        finding = next(f for f in audit(db).findings if f.email == JENSON)
        assert not finding.safe
        assert any(
            b.kind == "collective_has_outside_members" for b in finding.blockers
        )
        assert "kelly@example.com" in finding.blockers[0].detail

    def test_tom_as_a_member_of_a_target_collective_blocks(
        self, db, mk, make_space,
    ):
        """The specific instruction: if any of the three have data
        linked to Tom, stop. Deleting the Collective would cascade his
        membership away as a side effect of cleaning up somebody else.
        """
        jenson = mk(JENSON, role="creator")
        tom = mk(TOM, name="Tom Test")
        space = make_space(creator=jenson, slug="jensons-test-community",
                           name="Jenson's Test Community")
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=tom.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.flush()

        finding = next(f for f in audit(db).findings if f.email == JENSON)
        assert not finding.safe
        blocker = next(
            b for b in finding.blockers
            if b.kind == "collective_has_outside_members"
        )
        assert TOM in blocker.detail

    def test_a_collective_with_money_attached_blocks(
        self, db, mk, make_space,
    ):
        """A Collective with a purchase plan or a payment transaction is
        not disposable, whoever owns it. ``purchase_plans.space_id``
        also RESTRICTs, so the delete would fail anyway — but it should
        be refused with an explanation rather than a foreign-key
        error."""
        jenson = mk(JENSON, role="creator")
        space = make_space(creator=jenson, slug="jensons-test-community")
        db.execute(text(
            "INSERT INTO payment_transactions "
            "(id, space_id, payer_user_id, transaction_type, "
            " gross_amount_cents, stripe_mode) "
            "VALUES (:i, :s, :u, 'member_pathway_purchase', 4900, 'test')"
        ), {"i": _uid("ptx"), "s": space.id, "u": jenson.id})
        db.flush()

        finding = next(f for f in audit(db).findings if f.email == JENSON)
        assert not finding.safe
        assert any(b.kind == "collective_has_money" for b in finding.blockers)

    def test_a_subscription_history_is_not_disposable(self, db, mk):
        """``member_subscriptions.user_id`` RESTRICTs and is not on the
        resolvable list: an account that has paid for something is not a
        test account, whatever its email says."""
        from app.services.test_account_cleanup import RESOLVABLE_RESTRICTS

        assert "member_subscriptions.user_id" not in RESOLVABLE_RESTRICTS
        assert "purchase_plans.member_user_id" not in RESOLVABLE_RESTRICTS
        assert "creator_payout_batches.creator_user_id" not in RESOLVABLE_RESTRICTS

        jenson = mk(JENSON)
        plan_id = db.scalar(text("SELECT id FROM creator_plans LIMIT 1"))
        if plan_id is None:
            plan_id = _uid("cpl")
            db.execute(text(
                "INSERT INTO creator_plans "
                "(id, slug, name, monthly_price_cents, "
                " transaction_fee_basis_points, collective_limit) "
                "VALUES (:i, :s, 'Test Plan', 1900, 500, 1)"
            ), {"i": plan_id, "s": f"test-plan-{uuid.uuid4().hex[:6]}"})
            db.flush()
        # A row in a RESTRICT table that this cleanup will not resolve.
        db.execute(text(
            "INSERT INTO creator_payout_batches "
            "(id, creator_user_id, created_by_user_id, currency, "
            " total_amount_cents, transaction_count, reference, "
            " status, paid_at) "
            "VALUES (:i, :u, :u, 'AUD', 4900, 1, :ref, 'paid', now())"
        ), {"i": _uid("cpb"), "u": jenson.id, "ref": _uid("ref")})
        db.flush()

        finding = next(f for f in audit(db).findings if f.email == JENSON)
        assert not finding.safe
        assert any(
            b.kind == "unresolvable_restrict" for b in finding.blockers
        ), [b.kind for b in finding.blockers]

    def test_one_blocked_target_blocks_the_whole_plan(self, db, mk):
        """Not partially applied: these accounts exist as a set, and a
        half-cleaned state is harder to reason about than either end."""
        mk(JENSON)
        creator = mk(CREATOR)
        real = mk("kelly@example.com")
        low, high = canonical_pair(creator.id, real.id)
        db.add(PeerThread(
            id=_uid("pt"), participant_a_user_id=low, participant_b_user_id=high,
        ))
        db.flush()

        plan = audit(db)
        jenson_finding = next(f for f in plan.findings if f.email == JENSON)
        assert jenson_finding.safe, "Jenson alone is clean"
        assert plan.safe is False, "but the plan is not"
        with pytest.raises(RuntimeError, match="refusing to apply"):
            apply_cleanup(db, plan)


class TestApplyRemovesOnlyTheTargets:
    def test_a_clean_target_is_deleted_with_its_dependents(
        self, db, mk, make_space, make_event,
    ):
        jenson = mk(JENSON, role="creator")
        space = make_space(creator=jenson, slug="jensons-test-community")
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=jenson.id,
            role=SpaceRole.creator, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.flush()
        user_id, space_id = jenson.id, space.id

        plan = audit(db)
        assert plan.safe
        result = apply_cleanup(db, plan)
        db.flush()

        assert db.scalar(
            text("SELECT count(*) FROM users WHERE id = :u"), {"u": user_id},
        ) == 0
        assert db.scalar(
            text("SELECT count(*) FROM spaces WHERE id = :s"), {"s": space_id},
        ) == 0
        assert db.scalar(
            text("SELECT count(*) FROM space_memberships WHERE user_id = :u"),
            {"u": user_id},
        ) == 0
        assert any(JENSON in u for u in result.users_deleted)
        assert len(result.spaces_deleted) == 1

    def test_a_creator_subscription_is_cleared_first(self, db, mk):
        """``creator_subscriptions.user_id`` RESTRICTs, so the user
        delete fails outright unless this goes first."""
        jenson = mk(JENSON, role="creator")
        plan_id = db.scalar(text("SELECT id FROM creator_plans LIMIT 1"))
        if plan_id is None:
            # ``fc_test`` was bootstrapped from a schema dump taken past
            # the migration that seeds the plans, so the table can be
            # empty. Make the one row this test needs rather than
            # depending on seed data that may not be there.
            plan_id = _uid("cpl")
            db.execute(text(
                "INSERT INTO creator_plans "
                "(id, slug, name, monthly_price_cents, "
                " transaction_fee_basis_points, collective_limit) "
                "VALUES (:i, :s, 'Test Plan', 1900, 500, 1)"
            ), {"i": plan_id, "s": f"test-plan-{uuid.uuid4().hex[:6]}"})
            db.flush()
        db.execute(text(
            "INSERT INTO creator_subscriptions "
            "(id, user_id, creator_plan_id, status, source, created_at) "
            "VALUES (:i, :u, :p, 'active', 'manual_grant', now())"
        ), {"i": _uid("cs"), "u": jenson.id, "p": plan_id})
        db.flush()

        plan = audit(db)
        finding = next(f for f in plan.findings if f.email == JENSON)
        assert any(
            d.ref == "creator_subscriptions.user_id" for d in finding.restricting()
        )
        assert finding.safe, "a test account's own grant is resolvable"

        result = apply_cleanup(db, plan)
        db.flush()
        assert result.subscriptions_deleted == 1
        assert db.scalar(
            text("SELECT count(*) FROM users WHERE id = :u"), {"u": jenson.id},
        ) == 0

    def test_real_users_and_their_data_are_untouched(
        self, db, mk, make_space, make_event,
    ):
        jenson = mk(JENSON)
        real = mk("kelly@example.com", name="Kelly Hamilton")
        real_space = make_space(creator=real, slug="embody-ish")
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=real_space.id, user_id=real.id,
            role=SpaceRole.creator, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.flush()

        apply_cleanup(db, audit(db))
        db.flush()

        assert db.get(User, real.id) is not None
        assert db.scalar(
            text("SELECT count(*) FROM spaces WHERE id = :s"),
            {"s": real_space.id},
        ) == 1
        assert db.scalar(
            text("SELECT count(*) FROM space_memberships WHERE user_id = :u"),
            {"u": real.id},
        ) == 1

    def test_a_second_apply_finds_nothing(self, db, mk):
        mk(JENSON)
        apply_cleanup(db, audit(db))
        db.flush()

        second = audit(db)
        assert all(not f.present for f in second.findings)
        with pytest.raises(RuntimeError):
            apply_cleanup(db, second)

    def test_foreign_key_integrity_survives(self, db, mk, make_space):
        """No orphans left behind. Checked by asking Postgres rather
        than by reasoning about the cascade order."""
        jenson = mk(JENSON, role="creator")
        space = make_space(creator=jenson, slug="jensons-test-community")
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=jenson.id,
            role=SpaceRole.creator, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.flush()

        apply_cleanup(db, audit(db))
        db.flush()

        # Any FK pointing at a users row that no longer exists would
        # have raised already; this re-checks the two biggest cascades
        # explicitly.
        for table, column in (
            ("space_memberships", "user_id"),
            ("event_bookings", "user_id"),
        ):
            orphans = db.scalar(text(
                f"SELECT count(*) FROM {table} t "
                f"LEFT JOIN users u ON u.id = t.{column} "
                f"WHERE t.{column} IS NOT NULL AND u.id IS NULL"
            ))
            assert orphans == 0, f"{table}.{column} has orphans"


class TestTomIsNeverTouched:
    @pytest.fixture
    def tom_with_everything(self, db, mk, make_space, make_event):
        tom = mk(TOM, role="creator", name="Tom Test")
        space = make_space(creator=tom, slug="toms-test-collective",
                           name="Tom's Test Collective")
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=tom.id,
            role=SpaceRole.creator, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.flush()
        return tom, space

    def test_tom_is_not_in_the_target_set(self, db, mk, tom_with_everything):
        mk(JENSON)
        plan = audit(db)
        assert TOM not in {f.email for f in plan.findings}

    def test_tom_survives_an_apply(self, db, mk, tom_with_everything):
        tom, space = tom_with_everything
        mk(JENSON)
        before = protected_snapshot(db)

        apply_cleanup(db, audit(db))
        db.flush()

        assert db.get(User, tom.id) is not None
        assert db.scalar(
            text("SELECT count(*) FROM spaces WHERE id = :s"), {"s": space.id},
        ) == 1
        assert verify_protected_intact(db, before) == []

    def test_the_tripwire_notices_if_tom_changes(
        self, db, mk, tom_with_everything,
    ):
        """The check has to be able to fail, or it is decoration."""
        tom, space = tom_with_everything
        before = protected_snapshot(db)
        db.execute(
            text("DELETE FROM space_memberships WHERE user_id = :u"),
            {"u": tom.id},
        )
        db.flush()

        problems = verify_protected_intact(db, before)
        assert problems
        assert any("memberships changed" in p for p in problems)

    def test_the_snapshot_tolerates_tom_being_absent(self, db, mk):
        """A legitimate state in a database that is not production."""
        snapshot = protected_snapshot(db)
        assert snapshot[TOM] == {"present": 0}
        assert verify_protected_intact(db, snapshot) == []

    def test_toms_hello_and_message_history_is_not_a_target(
        self, db, mk, tom_with_everything,
    ):
        tom, _space = tom_with_everything
        other = mk("someone@example.com")
        db.add(MemberHello(
            id=_uid("h"), from_user_id=tom.id, to_user_id=other.id,
        ))
        db.flush()
        before = protected_snapshot(db)
        assert before[TOM]["hellos_sent"] == 1

        mk(JENSON)
        apply_cleanup(db, audit(db))
        db.flush()

        assert verify_protected_intact(db, before) == []


class TestScopingToOneAccount:
    """``--only`` exists so one blocked account cannot strand a clean
    one. It must narrow and never widen, and narrowing has to make the
    shared-data checks *stricter*, not weaker."""

    def test_only_the_scoped_account_is_deleted(self, db, mk, make_space):
        jenson = mk(JENSON, role="creator")
        creator = mk(CREATOR)
        lindsey = mk(LINDSEY_TEST)
        space = make_space(creator=jenson, slug="jensons-test-community")
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=jenson.id,
            role=SpaceRole.creator, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.flush()

        plan = audit(db, apply_to=(JENSON,))
        assert plan.safe
        apply_cleanup(db, plan)
        db.flush()

        assert not _exists(db, jenson.id)
        assert _exists(db, creator.id), "Creator Test retained"
        assert _exists(db, lindsey.id), "Lindsey Test retained"

    def test_a_blocked_account_does_not_strand_a_clean_one(self, db, mk):
        """The reason this flag exists."""
        jenson = mk(JENSON)
        creator = mk(CREATOR)
        real = mk("kelly@example.com")
        # Creator Test is blocked by a shared conversation.
        low, high = canonical_pair(creator.id, real.id)
        db.add(PeerThread(
            id=_uid("pt"), participant_a_user_id=low, participant_b_user_id=high,
        ))
        db.flush()

        assert audit(db).safe is False, "the whole-set plan is blocked"
        scoped = audit(db, apply_to=(JENSON,))
        assert scoped.safe is True, "Jenson alone is clean"

        apply_cleanup(db, scoped)
        db.flush()
        assert not _exists(db, jenson.id)
        assert _exists(db, creator.id)

    def test_a_retained_target_becomes_an_outsider(self, db, mk):
        """The tightening, and the whole reason this is not just a skip.

        A conversation between two targets is fine when both are going
        and is data loss when only one is. Narrowing the scope has to
        turn the other end into an outsider.
        """
        jenson = mk(JENSON)
        creator = mk(CREATOR)
        low, high = canonical_pair(jenson.id, creator.id)
        db.add(PeerThread(
            id=_uid("pt"), participant_a_user_id=low, participant_b_user_id=high,
        ))
        db.flush()

        both = next(f for f in audit(db).findings if f.email == JENSON)
        assert both.safe, "both ends going: nothing is orphaned"

        alone = next(
            f for f in audit(db, apply_to=(JENSON,)).findings
            if f.email == JENSON
        )
        assert not alone.safe, "Creator Test is retained, so this is data loss"
        assert any(b.kind == "shared_peer_thread" for b in alone.blockers)

    def test_a_retained_target_in_a_collective_becomes_an_outsider(
        self, db, mk, make_space,
    ):
        """The shared 'Test Collective' shape: members who are other
        test accounts are insiders only while they are also going."""
        jenson = mk(JENSON, role="creator")
        creator = mk(CREATOR)
        space = make_space(creator=jenson, slug="test-collective",
                           name="Test Collective")
        for u in (jenson, creator):
            db.add(SpaceMembership(
                id=_uid("sm"), space_id=space.id, user_id=u.id,
                role=SpaceRole.learner, status=SpaceMembershipStatus.active,
                joined_at=datetime.utcnow(),
            ))
        db.flush()

        both = next(f for f in audit(db).findings if f.email == JENSON)
        assert both.safe

        alone = next(
            f for f in audit(db, apply_to=(JENSON,)).findings
            if f.email == JENSON
        )
        assert not alone.safe
        assert any(
            b.kind == "collective_has_outside_members" for b in alone.blockers
        )

    def test_the_scope_cannot_be_widened(self, db, mk):
        with pytest.raises(ValueError, match="not in the approved target set"):
            audit(db, apply_to=(TOM,))
        with pytest.raises(ValueError):
            audit(db, apply_to=("someone@else.com",))

    def test_retained_accounts_are_still_audited_for_context(self, db, mk):
        mk(JENSON)
        mk(CREATOR)
        plan = audit(db, apply_to=(JENSON,))
        assert {f.email for f in plan.findings} == set(TARGET_EMAILS)
        assert [f.email for f in plan.in_scope()] == [JENSON]
        assert CREATOR in {f.email for f in plan.retained}

    def test_a_retained_account_is_reported_as_skipped(self, db, mk):
        mk(JENSON)
        mk(CREATOR)
        result = apply_cleanup(db, audit(db, apply_to=(JENSON,)))
        assert any(CREATOR in s and "retained" in s for s in result.skipped)


class TestTheRecheckBeforeMutation:
    def test_an_unchanged_plan_passes(self, db, mk):
        mk(JENSON)
        plan = audit(db, apply_to=(JENSON,))
        assert recheck_unchanged(db, plan) == []

    def test_a_new_outside_member_is_caught(self, db, mk, make_space):
        """Somebody joining between the audit and the apply."""
        jenson = mk(JENSON, role="creator")
        space = make_space(creator=jenson, slug="jensons-test-community")
        plan = audit(db, apply_to=(JENSON,))
        assert plan.safe

        real = mk("kelly@example.com")
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=real.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.flush()

        problems = recheck_unchanged(db, plan)
        assert problems
        assert any("blocker appeared" in p for p in problems)

    def test_a_new_shared_conversation_is_caught(self, db, mk):
        jenson = mk(JENSON)
        plan = audit(db, apply_to=(JENSON,))
        assert plan.safe

        real = mk("kelly@example.com")
        low, high = canonical_pair(jenson.id, real.id)
        db.add(PeerThread(
            id=_uid("pt"), participant_a_user_id=low, participant_b_user_id=high,
        ))
        db.flush()

        assert any("blocker appeared" in p for p in recheck_unchanged(db, plan))

    def test_a_vanished_account_is_caught(self, db, mk):
        jenson = mk(JENSON)
        plan = audit(db, apply_to=(JENSON,))
        db.execute(text("DELETE FROM users WHERE id = :u"), {"u": jenson.id})
        db.flush()
        assert recheck_unchanged(db, plan) != []

    def test_an_email_pointing_at_a_different_account_is_caught(
        self, db, mk,
    ):
        """The address resolving somewhere new between audit and apply —
        the one thing that would make the whole report describe a
        different person."""
        jenson = mk(JENSON)
        plan = audit(db, apply_to=(JENSON,))
        original_id = jenson.id

        db.execute(text("DELETE FROM users WHERE id = :u"), {"u": original_id})
        db.flush()
        mk(JENSON)  # same email, new row

        problems = recheck_unchanged(db, plan)
        assert any("different account" in p for p in problems)

    def test_routine_activity_does_not_trip_it(self, db, mk):
        """A notification arriving is not a reason to refuse. Only
        identity and safety are compared, not every count."""
        jenson = mk(JENSON)
        plan = audit(db, apply_to=(JENSON,))
        db.execute(text(
            "INSERT INTO notifications "
            "(id, user_id, notification_type, title, message) "
            "VALUES (:i, :u, 'generic', 'Hi', 'Body')"
        ), {"i": _uid("n"), "u": jenson.id})
        db.flush()
        assert recheck_unchanged(db, plan) == []


class TestTheDeletionOutcomeCheck:
    """The post-delete verification, which had the scoping bug.

    It asserted that every account in ``TARGET_EMAILS`` was gone — true
    while every run deleted all three, and wrong the moment ``--only``
    could retain one. A correctly scoped Jenson-only apply failed on the
    two retained accounts still being present, which was the entire
    point of retaining them.

    Two obligations now, and they are opposite: in-scope accounts must
    be absent, retained accounts must still be there.
    """

    def test_whole_set_apply_requires_every_target_absent(self, db, mk):
        mk(JENSON)
        mk(CREATOR)
        mk(LINDSEY_TEST)

        plan = audit(db)
        apply_cleanup(db, plan)
        db.flush()

        assert verify_deletion_outcome(db, plan) == []
        for email in TARGET_EMAILS:
            assert db.scalar(
                text("SELECT count(*) FROM users WHERE lower(email) = :e"),
                {"e": email},
            ) == 0, email

    def test_jenson_only_passes_with_the_others_retained(
        self, db, mk, make_space,
    ):
        """The exact production scenario that failed."""
        jenson = mk(JENSON, role="creator")
        creator = mk(CREATOR)
        lindsey = mk(LINDSEY_TEST)
        tom = mk(TOM, name="Tom Test")
        space = make_space(creator=jenson, slug="jensons-test-community")
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=jenson.id,
            role=SpaceRole.creator, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.flush()
        before = protected_snapshot(db)

        plan = audit(db, apply_to=(JENSON,))
        assert plan.safe
        apply_cleanup(db, plan)
        db.flush()

        assert verify_deletion_outcome(db, plan) == [], (
            "a correctly scoped run must not be reported as a failure"
        )
        assert not _exists(db, jenson.id), "Jenson absent"
        assert _exists(db, creator.id), "Creator Test remains"
        assert _exists(db, lindsey.id), "Lindsey Test remains"
        assert _exists(db, tom.id), "Tom Test remains"
        assert verify_protected_intact(db, before) == []

    def test_only_the_scoped_account_is_required_absent(self, db, mk):
        """Scoped to a different approved target: the check follows the
        scope rather than the approved list."""
        jenson = mk(JENSON)
        creator = mk(CREATOR)
        lindsey = mk(LINDSEY_TEST)

        plan = audit(db, apply_to=(LINDSEY_TEST,))
        apply_cleanup(db, plan)
        db.flush()

        assert verify_deletion_outcome(db, plan) == []
        assert not _exists(db, lindsey.id)
        assert _exists(db, jenson.id)
        assert _exists(db, creator.id)

    def test_a_retained_account_disappearing_is_a_failure(self, db, mk):
        """The other direction. If the delete reached further than its
        scope, this is what notices."""
        jenson = mk(JENSON)
        creator = mk(CREATOR)

        plan = audit(db, apply_to=(JENSON,))
        apply_cleanup(db, plan)
        db.flush()
        assert verify_deletion_outcome(db, plan) == []

        # Simulate the cascade having reached a retained account.
        db.execute(text("DELETE FROM users WHERE id = :u"), {"u": creator.id})
        db.flush()

        problems = verify_deletion_outcome(db, plan)
        assert problems
        assert any(
            CREATOR in p and "retained but has disappeared" in p
            for p in problems
        ), problems

    def test_an_in_scope_account_surviving_is_a_failure(self, db, mk):
        """And the first direction still works — the check did not get
        narrowed into uselessness."""
        jenson = mk(JENSON)
        plan = audit(db, apply_to=(JENSON,))
        # Never applied, so Jenson is still there.
        problems = verify_deletion_outcome(db, plan)
        assert any(
            JENSON in p and "still present after delete" in p
            for p in problems
        ), problems

    def test_protected_tom_disappearing_is_a_failure(self, db, mk):
        tom = mk(TOM, name="Tom Test")
        mk(JENSON)
        before = protected_snapshot(db)
        assert before[TOM]["present"] == 1

        db.execute(text("DELETE FROM users WHERE id = :u"), {"u": tom.id})
        db.flush()

        problems = verify_protected_intact(db, before)
        assert problems
        assert any("presence changed" in p for p in problems)

    def test_the_script_rolls_back_on_any_verification_failure(self):
        """Source contract: every verification failure has to reach the
        rollback, not just the first one. The three checks raise or
        return 2, and both paths roll back."""
        src = (
            __import__("pathlib").Path("scripts/cleanup_production_test_accounts.py")
            .read_text()
        )
        code = __import__("re").sub(r'"""[\s\S]*?"""', "", src)
        code = __import__("re").sub(r"#.*", "", code)

        # The outcome check raises, and the except clause rolls back.
        assert "verify_deletion_outcome(db, plan)" in code
        assert "raise RuntimeError" in code
        tail = code[code.index("except Exception:"):]
        assert "db.rollback()" in tail
        assert "return 1" in tail

        # The pre-mutation re-check returns 2, and rolls back explicitly.
        recheck = code[code.index("recheck_unchanged(db, plan)"):]
        assert "db.rollback()" in recheck[:recheck.index("apply_cleanup")]

        # Nothing commits before the verifications.
        commit_at = code.index("db.commit()")
        for check in (
            "recheck_unchanged(db, plan)",
            "verify_deletion_outcome(db, plan)",
            "verify_protected_intact(db, before)",
        ):
            assert code.index(check) < commit_at, check

    def test_the_old_whole_list_assumption_is_gone(self):
        """The bug in one assertion: the check must not iterate the
        approved list where it means the scoped set."""
        src = (
            __import__("pathlib").Path("app/services/test_account_cleanup.py")
            .read_text()
        )
        fn = src[src.index("def verify_deletion_outcome"):]
        fn = fn[:fn.index("def verify_protected_intact")]
        code = __import__("re").sub(r'"""[\s\S]*?"""', "", fn)
        assert "in_scope" in code, "the outcome check must consult the scope"
        assert "TARGET_EMAILS" not in code, (
            "the outcome check must not reason about the approved list"
        )
