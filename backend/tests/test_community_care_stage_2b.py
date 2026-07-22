"""
Stage 2B tests — member-facing Community Care intake.

Locks:

- Flag off returns 503 on both intake endpoints (no partial rollout).
- Member reports opens a case with the correct subject derived from
  the reported content (never trusted from the client).
- Members cannot report their own content.
- 'something_else' requires a note.
- Duplicate reports on the same subject attach to the same open case
  and increment report_count.
- Every intake writes a case_opened / report_attached event so the
  audit trail is identical to admin-seed intake.
- Reporter receives a routine severity notification acknowledgement.
- Content snapshot is captured at intake and survives edits / deletes.
- Creator support requests open a fresh creator_request case,
  associate the requesting creator, respect scope validation, and
  refuse when a non-owning creator names a foreign collective.
- Categories and scopes are validated against the shared enums so
  the schema, model, and CHECK constraints stay in lockstep.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException, Request
from pydantic import ValidationError

from app.community_care.routes import (
    submit_creator_support_request,
    submit_member_report,
)
from app.community_care.schemas import (
    CreatorSupportRequest,
    MemberReportRequest,
)
from app.core.config import settings
from app.models.community_care import (
    CommunityCareCase,
    CommunityCareCaseEvent,
    CommunityCareReport,
)
from app.models.notification import Notification
from app.models.platform import (
    CommunityPost,
    ConversationChannel,
    PostComment,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def care_enabled(monkeypatch):
    monkeypatch.setattr(settings, "community_care_enabled", True)
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """slowapi keeps process-wide in-memory rate-limit state which
    otherwise carries between tests and quickly exhausts the 10/hour
    ceiling. Reset the underlying storage before every test."""
    from app.community_care.routes import limiter as intake_limiter
    intake_limiter.reset()
    yield
    intake_limiter.reset()


@pytest.fixture
def fake_request():
    """Minimal Request object for the slowapi decorator on the routes.

    slowapi reads ``request.client.host`` for its default key_func. A
    plain scope with a ``client`` triple is enough for the decorator
    to run without hitting the network.
    """
    scope = {
        "type": "http",
        "client": ("127.0.0.1", 12345),
        "headers": [],
        "method": "POST",
        "path": "/api/community-care/reports",
    }
    return Request(scope)


@pytest.fixture
def make_channel(db):
    def _factory(space) -> ConversationChannel:
        c = ConversationChannel(
            id=f"ch_{uuid.uuid4().hex[:10]}",
            space_id=space.id,
            name="General",
            slug="general",
        )
        db.add(c)
        db.flush()
        return c
    return _factory


@pytest.fixture
def make_post(db, make_channel):
    def _factory(*, space, author, channel=None) -> CommunityPost:
        ch = channel or make_channel(space)
        p = CommunityPost(
            id=f"cp_{uuid.uuid4().hex[:10]}",
            space_id=space.id,
            author_id=author.id,
            channel_id=ch.id,
            title="Test post",
            body="Post body",
            post_type="discussion",
        )
        db.add(p)
        db.flush()
        return p
    return _factory


@pytest.fixture
def make_comment(db):
    def _factory(*, post, author) -> PostComment:
        c = PostComment(
            id=f"pc_{uuid.uuid4().hex[:10]}",
            post_id=post.id,
            author_id=author.id,
            body="A comment",
        )
        db.add(c)
        db.flush()
        return c
    return _factory


@pytest.fixture
def add_creator_membership(db):
    """Wire a user as the ``creator`` role on a given space via
    SpaceMembership so ``_resolve_creator_for_space`` finds them."""
    def _factory(*, user, space) -> SpaceMembership:
        m = SpaceMembership(
            id=f"sm_{uuid.uuid4().hex[:10]}",
            user_id=user.id,
            space_id=space.id,
            role=SpaceRole.creator,
            status=SpaceMembershipStatus.active,
        )
        db.add(m)
        db.flush()
        return m
    return _factory


# ---------------------------------------------------------------------------
# 1. Flag gate
# ---------------------------------------------------------------------------


class TestFlagGate:
    def test_flag_off_member_report_returns_503(
        self, db, make_user, make_space, make_post, fake_request
    ):
        reporter = make_user(role="user")
        author = make_user(role="user")
        space = make_space()
        post = make_post(space=space, author=author)
        with pytest.raises(HTTPException) as e:
            submit_member_report(
                fake_request,
                MemberReportRequest(
                    target_post_id=post.id,
                    category="spam_or_scam",
                ),
                current_user=reporter,
                db=db,
            )
        assert e.value.status_code == 503

    def test_flag_off_creator_support_returns_503(
        self, db, make_user, fake_request
    ):
        creator = make_user(role="creator")
        with pytest.raises(HTTPException) as e:
            submit_creator_support_request(
                fake_request,
                CreatorSupportRequest(
                    scope="community_wellbeing",
                    description="Please help.",
                ),
                current_user=creator,
                db=db,
            )
        assert e.value.status_code == 503


# ---------------------------------------------------------------------------
# 2. Member report — happy path
# ---------------------------------------------------------------------------


class TestMemberReportHappyPath:
    def test_report_on_post_opens_case_with_derived_subject(
        self,
        care_enabled,
        db,
        make_user,
        make_space,
        make_post,
        add_creator_membership,
        fake_request,
    ):
        reporter = make_user(role="user")
        author = make_user(role="user")
        creator_owner = make_user(role="creator")
        space = make_space(creator=creator_owner)
        add_creator_membership(user=creator_owner, space=space)
        post = make_post(space=space, author=author)

        ack = submit_member_report(
            fake_request,
            MemberReportRequest(
                target_post_id=post.id,
                category="harassment_or_bullying",
                reporter_note=None,
            ),
            current_user=reporter,
            db=db,
        )

        assert ack.received_at is not None
        cases = db.query(CommunityCareCase).all()
        assert len(cases) == 1
        c = cases[0]
        # Server derived these — client never provided them.
        assert c.subject_space_id == space.id
        assert c.subject_member_user_id == author.id
        assert c.subject_creator_user_id == creator_owner.id
        assert c.subject_post_id == post.id
        assert c.content_type == "post"
        assert c.category == "harassment_or_bullying"
        assert c.status == "new"
        assert c.priority == "low"
        assert c.report_count == 1
        # snapshot captured
        assert c.content_snapshot is not None
        assert c.content_snapshot["kind"] == "post"
        assert c.content_snapshot["body"] == "Post body"

    def test_report_on_comment_opens_case_from_comment(
        self,
        care_enabled,
        db,
        make_user,
        make_space,
        make_post,
        make_comment,
        fake_request,
    ):
        reporter = make_user(role="user")
        author_of_post = make_user(role="user")
        commenter = make_user(role="user")
        space = make_space()
        post = make_post(space=space, author=author_of_post)
        comment = make_comment(post=post, author=commenter)

        submit_member_report(
            fake_request,
            MemberReportRequest(
                target_comment_id=comment.id,
                category="inappropriate_content",
            ),
            current_user=reporter,
            db=db,
        )

        c = db.query(CommunityCareCase).one()
        assert c.content_type == "comment"
        assert c.subject_comment_id == comment.id
        assert c.subject_post_id is None
        assert c.subject_member_user_id == commenter.id
        assert c.subject_space_id == space.id


# ---------------------------------------------------------------------------
# 3. Guard rails
# ---------------------------------------------------------------------------


class TestReportGuards:
    def test_missing_both_targets_rejected(
        self, care_enabled, db, make_user, fake_request
    ):
        with pytest.raises(ValidationError):
            # Enforced at the schema level too, but keep the check
            # explicit — the endpoint's "exactly one" guard is a 422.
            MemberReportRequest(category="not_a_real_category")

        reporter = make_user(role="user")
        with pytest.raises(HTTPException) as e:
            submit_member_report(
                fake_request,
                MemberReportRequest(category="spam_or_scam"),
                current_user=reporter,
                db=db,
            )
        assert e.value.status_code == 422

    def test_both_targets_rejected(
        self,
        care_enabled,
        db,
        make_user,
        make_space,
        make_post,
        make_comment,
        fake_request,
    ):
        reporter = make_user(role="user")
        space = make_space()
        post = make_post(space=space, author=make_user())
        comment = make_comment(post=post, author=make_user())
        with pytest.raises(HTTPException) as e:
            submit_member_report(
                fake_request,
                MemberReportRequest(
                    target_post_id=post.id,
                    target_comment_id=comment.id,
                    category="spam_or_scam",
                ),
                current_user=reporter,
                db=db,
            )
        assert e.value.status_code == 422

    def test_reporting_own_post_refused(
        self, care_enabled, db, make_user, make_space, make_post, fake_request
    ):
        author = make_user(role="user")
        space = make_space()
        post = make_post(space=space, author=author)
        with pytest.raises(HTTPException) as e:
            submit_member_report(
                fake_request,
                MemberReportRequest(
                    target_post_id=post.id,
                    category="spam_or_scam",
                ),
                current_user=author,
                db=db,
            )
        assert e.value.status_code == 400

    def test_something_else_requires_note(
        self, care_enabled, db, make_user, make_space, make_post, fake_request
    ):
        reporter = make_user(role="user")
        space = make_space()
        post = make_post(space=space, author=make_user())
        # No note
        with pytest.raises(HTTPException) as e:
            submit_member_report(
                fake_request,
                MemberReportRequest(
                    target_post_id=post.id,
                    category="something_else",
                ),
                current_user=reporter,
                db=db,
            )
        assert e.value.status_code == 422

    def test_unknown_category_rejected_at_schema(self):
        with pytest.raises(ValidationError):
            MemberReportRequest(
                target_post_id="cp_xxx",
                category="not_a_category",
            )

    def test_missing_post_returns_404(
        self, care_enabled, db, make_user, fake_request
    ):
        reporter = make_user(role="user")
        with pytest.raises(HTTPException) as e:
            submit_member_report(
                fake_request,
                MemberReportRequest(
                    target_post_id="cp_does_not_exist",
                    category="spam_or_scam",
                ),
                current_user=reporter,
                db=db,
            )
        assert e.value.status_code == 404


# ---------------------------------------------------------------------------
# 4. Dedupe + audit trail + notification
# ---------------------------------------------------------------------------


class TestReportDedupeAndAudit:
    def test_second_report_on_same_post_attaches_to_open_case(
        self,
        care_enabled,
        db,
        make_user,
        make_space,
        make_post,
        fake_request,
    ):
        author = make_user(role="user")
        space = make_space()
        post = make_post(space=space, author=author)
        r1 = make_user(role="user")
        r2 = make_user(role="user")

        submit_member_report(
            fake_request,
            MemberReportRequest(target_post_id=post.id, category="spam_or_scam"),
            current_user=r1,
            db=db,
        )
        submit_member_report(
            fake_request,
            MemberReportRequest(target_post_id=post.id, category="misinformation"),
            current_user=r2,
            db=db,
        )

        cases = db.query(CommunityCareCase).all()
        assert len(cases) == 1
        assert cases[0].report_count == 2
        reports = (
            db.query(CommunityCareReport)
            .filter(CommunityCareReport.case_id == cases[0].id)
            .all()
        )
        assert len(reports) == 2
        # Both are stamped as member reports.
        assert all(r.reporter_kind == "member" for r in reports)

    def test_every_intake_writes_audit_events(
        self, care_enabled, db, make_user, make_space, make_post, fake_request
    ):
        author = make_user(role="user")
        space = make_space()
        post = make_post(space=space, author=author)
        reporter = make_user(role="user")

        submit_member_report(
            fake_request,
            MemberReportRequest(target_post_id=post.id, category="spam_or_scam"),
            current_user=reporter,
            db=db,
        )
        case = db.query(CommunityCareCase).one()
        events = (
            db.query(CommunityCareCaseEvent)
            .filter(CommunityCareCaseEvent.case_id == case.id)
            .order_by(CommunityCareCaseEvent.occurred_at.asc())
            .all()
        )
        kinds = [e.kind for e in events]
        assert "case_opened" in kinds
        assert "report_attached" in kinds
        # Actor is the reporter, never NULL.
        assert all(e.actor_user_id == reporter.id for e in events)

    def test_reporter_receives_routine_notification(
        self, care_enabled, db, make_user, make_space, make_post, fake_request
    ):
        reporter = make_user(role="user")
        author = make_user(role="user")
        space = make_space()
        post = make_post(space=space, author=author)
        submit_member_report(
            fake_request,
            MemberReportRequest(target_post_id=post.id, category="spam_or_scam"),
            current_user=reporter,
            db=db,
        )
        notifs = (
            db.query(Notification)
            .filter(Notification.user_id == reporter.id)
            .all()
        )
        assert len(notifs) == 1
        n = notifs[0]
        assert n.severity == "routine"
        assert n.notification_type == "community_care_report_received"
        # The reported person is never notified.
        author_notifs = (
            db.query(Notification)
            .filter(Notification.user_id == author.id)
            .all()
        )
        assert author_notifs == []


# ---------------------------------------------------------------------------
# 5. Snapshot immutability
# ---------------------------------------------------------------------------


class TestSnapshotImmutable:
    def test_snapshot_survives_source_post_deletion(
        self, care_enabled, db, make_user, make_space, make_post, fake_request
    ):
        author = make_user(role="user")
        reporter = make_user(role="user")
        space = make_space()
        post = make_post(space=space, author=author)

        submit_member_report(
            fake_request,
            MemberReportRequest(target_post_id=post.id, category="spam_or_scam"),
            current_user=reporter,
            db=db,
        )
        case = db.query(CommunityCareCase).one()
        snapshot_body = case.content_snapshot["body"]

        db.delete(post)
        db.flush()
        db.refresh(case)
        assert case.content_snapshot is not None
        assert case.content_snapshot["body"] == snapshot_body


# ---------------------------------------------------------------------------
# 6. Creator support intake
# ---------------------------------------------------------------------------


class TestCreatorSupportHappyPath:
    def test_creator_support_opens_creator_request_case(
        self, care_enabled, db, make_user, fake_request
    ):
        creator = make_user(role="creator")
        ack = submit_creator_support_request(
            fake_request,
            CreatorSupportRequest(
                scope="platform_feature",
                description="How do I toggle the member directory?",
            ),
            current_user=creator,
            db=db,
        )
        assert ack.case_number.startswith("CC-")
        case = db.query(CommunityCareCase).one()
        assert case.content_type == "creator_request"
        assert case.creator_request_scope == "platform_feature"
        assert case.subject_creator_user_id == creator.id
        assert case.status == "new"
        assert case.priority == "low"
        # No reports for a support request.
        assert case.report_count == 0

    def test_creator_support_records_description_on_case_opened_event(
        self, care_enabled, db, make_user, fake_request
    ):
        creator = make_user(role="creator")
        submit_creator_support_request(
            fake_request,
            CreatorSupportRequest(
                scope="community_wellbeing",
                description="Two members are in escalating conflict.",
            ),
            current_user=creator,
            db=db,
        )
        case = db.query(CommunityCareCase).one()
        events = (
            db.query(CommunityCareCaseEvent)
            .filter(CommunityCareCaseEvent.case_id == case.id)
            .all()
        )
        assert len(events) == 1
        assert events[0].kind == "case_opened"
        assert events[0].internal_note == "Two members are in escalating conflict."

    def test_creator_support_sends_routine_notification(
        self, care_enabled, db, make_user, fake_request
    ):
        creator = make_user(role="creator")
        submit_creator_support_request(
            fake_request,
            CreatorSupportRequest(
                scope="technical_issue",
                description="Cannot upload video.",
            ),
            current_user=creator,
            db=db,
        )
        notifs = (
            db.query(Notification)
            .filter(Notification.user_id == creator.id)
            .all()
        )
        assert len(notifs) == 1
        assert notifs[0].severity == "routine"
        assert notifs[0].notification_type == "community_care_creator_support_received"


class TestCreatorSupportGuards:
    def test_unknown_scope_rejected_at_schema(self):
        with pytest.raises(ValidationError):
            CreatorSupportRequest(scope="not_a_scope", description="…")

    def test_empty_description_rejected_at_schema(self):
        with pytest.raises(ValidationError):
            CreatorSupportRequest(scope="platform_feature", description="")

    def test_foreign_collective_refused(
        self,
        care_enabled,
        db,
        make_user,
        make_space,
        add_creator_membership,
        fake_request,
    ):
        their_creator = make_user(role="creator")
        their_space = make_space(creator=their_creator)
        add_creator_membership(user=their_creator, space=their_space)

        other_creator = make_user(role="creator")

        with pytest.raises(HTTPException) as e:
            submit_creator_support_request(
                fake_request,
                CreatorSupportRequest(
                    scope="member_concern",
                    subject_space_id=their_space.id,
                    description="I need help with X.",
                ),
                current_user=other_creator,
                db=db,
            )
        assert e.value.status_code == 403

    def test_missing_collective_returns_404(
        self, care_enabled, db, make_user, fake_request
    ):
        creator = make_user(role="creator")
        with pytest.raises(HTTPException) as e:
            submit_creator_support_request(
                fake_request,
                CreatorSupportRequest(
                    scope="member_concern",
                    subject_space_id="s_does_not_exist",
                    description="Help",
                ),
                current_user=creator,
                db=db,
            )
        assert e.value.status_code == 404

    def test_own_collective_allowed(
        self,
        care_enabled,
        db,
        make_user,
        make_space,
        add_creator_membership,
        fake_request,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        add_creator_membership(user=creator, space=space)

        submit_creator_support_request(
            fake_request,
            CreatorSupportRequest(
                scope="community_expectations",
                subject_space_id=space.id,
                description="Need help with expectations.",
            ),
            current_user=creator,
            db=db,
        )
        case = db.query(CommunityCareCase).one()
        assert case.subject_space_id == space.id
        assert case.subject_creator_user_id == creator.id
