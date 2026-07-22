"""
Stage 2A tests for the Community Care admin surface.

Locks:

- Flag-off returns 503 on every endpoint (no partial rollout by accident).
- Case CRUD basics: create via seed, list, detail.
- Duplicate report attaches to the same open case; report_count grows.
- Priority is set by admins only — every priority_changed event has an
  ``actor_user_id`` (never NULL).
- Every mutation appends a ``community_care_case_events`` row.
- Close with resolution actions creates action rows + status transition;
  no-action close routes to ``closed_no_action``.
- Snapshots are captured at report time and survive later source deletion.
- Wellbeing rule follows the locked ladder (§6).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.admin.community_care.routes import (
    add_note,
    assign_reviewer,
    close_case,
    get_case,
    get_overview,
    list_case_events,
    list_cases,
    seed_report,
    update_priority,
    update_status,
)
from app.admin.community_care.schemas import (
    AddNoteRequest,
    AdminSeedReportRequest,
    AssignReviewerRequest,
    CloseCaseRequest,
    ResolutionAction,
    UpdatePriorityRequest,
    UpdateStatusRequest,
)
from app.core.config import settings
from app.models.community_care import (
    CommunityCareAction,
    CommunityCareCase,
    CommunityCareCaseEvent,
    CommunityCareCaseNote,
    CommunityCareReport,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def care_enabled(monkeypatch):
    """Turn the flag on for the duration of a test."""
    monkeypatch.setattr(settings, "community_care_enabled", True)
    yield
    # monkeypatch handles teardown


# ---------------------------------------------------------------------------
# 1. Flag-off returns 503 on every endpoint
# ---------------------------------------------------------------------------


class TestFlagGate:
    def test_flag_off_overview_returns_503(self, db, make_user):
        admin = make_user(role="admin")
        # Flag is False by default (via .env → community_care_enabled unset)
        with pytest.raises(HTTPException) as e:
            get_overview(_=admin, db=db)
        assert e.value.status_code == 503

    def test_flag_off_list_returns_503(self, db, make_user):
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as e:
            list_cases(_=admin, db=db)
        assert e.value.status_code == 503

    def test_flag_off_seed_report_returns_503(self, db, make_user):
        admin = make_user(role="admin")
        req = AdminSeedReportRequest(
            reporter_kind="admin",
            content_type="member_behaviour",
            target_member_user_id=make_user(role="user").id,
            category="harassment_or_bullying",
        )
        with pytest.raises(HTTPException) as e:
            seed_report(req, admin=admin, db=db)
        assert e.value.status_code == 503


# ---------------------------------------------------------------------------
# 2. Case creation via seed + duplicate report handling
# ---------------------------------------------------------------------------


class TestSeedAndDedupe:
    def test_seed_report_opens_a_case_with_correct_defaults(
        self, db, make_user, care_enabled
    ):
        admin = make_user(role="admin")
        reported = make_user(role="user", name="Simone")

        detail = seed_report(
            AdminSeedReportRequest(
                reporter_kind="admin",
                content_type="member_behaviour",
                target_member_user_id=reported.id,
                category="harassment_or_bullying",
            ),
            admin=admin, db=db,
        )
        assert detail.status == "new"
        assert detail.priority == "low"          # opens at low, per spec
        assert detail.report_count == 1
        assert detail.case_number.startswith("CC-")
        assert detail.category == "harassment_or_bullying"

    def test_case_number_format_ccyyyy_nnnn(self, db, make_user, care_enabled):
        admin = make_user(role="admin")
        u = make_user(role="user")
        first = seed_report(
            AdminSeedReportRequest(
                reporter_kind="admin",
                content_type="member_behaviour",
                target_member_user_id=u.id,
                category="spam_or_scam",
            ),
            admin=admin, db=db,
        )
        second_user = make_user(role="user")
        second = seed_report(
            AdminSeedReportRequest(
                reporter_kind="admin",
                content_type="member_behaviour",
                target_member_user_id=second_user.id,
                category="spam_or_scam",
            ),
            admin=admin, db=db,
        )
        # Both look like CC-{YYYY}-{4-digit}
        import re
        pat = re.compile(r"^CC-\d{4}-\d{4}$")
        assert pat.match(first.case_number)
        assert pat.match(second.case_number)
        # Sequential within the same year
        assert int(second.case_number.split("-")[-1]) == int(first.case_number.split("-")[-1]) + 1

    def test_second_report_on_same_member_attaches_to_open_case(
        self, db, make_user, care_enabled
    ):
        admin = make_user(role="admin")
        reported = make_user(role="user")

        first = seed_report(
            AdminSeedReportRequest(
                reporter_kind="admin",
                content_type="member_behaviour",
                target_member_user_id=reported.id,
                category="harassment_or_bullying",
            ),
            admin=admin, db=db,
        )
        second = seed_report(
            AdminSeedReportRequest(
                reporter_kind="admin",
                content_type="member_behaviour",
                target_member_user_id=reported.id,
                category="hate_or_discrimination",
            ),
            admin=admin, db=db,
        )
        # Same case, report_count incremented
        assert second.id == first.id
        assert second.report_count == 2
        # Both reports attached
        assert (
            db.query(CommunityCareReport)
            .filter(CommunityCareReport.case_id == first.id)
            .count()
            == 2
        )

    def test_something_else_requires_note(self, db, make_user, care_enabled):
        admin = make_user(role="admin")
        u = make_user(role="user")
        with pytest.raises(HTTPException) as e:
            seed_report(
                AdminSeedReportRequest(
                    reporter_kind="admin",
                    content_type="member_behaviour",
                    target_member_user_id=u.id,
                    category="something_else",
                    reporter_note=None,
                ),
                admin=admin, db=db,
            )
        assert e.value.status_code == 422


# ---------------------------------------------------------------------------
# 3. Priority is human-only
# ---------------------------------------------------------------------------


class TestPriorityIsHumanOnly:
    def test_priority_change_records_actor(self, db, make_user, care_enabled):
        admin = make_user(role="admin", name="Lindsey")
        reported = make_user(role="user")
        case_detail = seed_report(
            AdminSeedReportRequest(
                reporter_kind="admin",
                content_type="member_behaviour",
                target_member_user_id=reported.id,
                category="harassment_or_bullying",
            ),
            admin=admin, db=db,
        )
        update_priority(
            case_detail.id,
            UpdatePriorityRequest(priority="high", reason="repeated pattern"),
            admin=admin, db=db,
        )
        events = (
            db.query(CommunityCareCaseEvent)
            .filter(
                CommunityCareCaseEvent.case_id == case_detail.id,
                CommunityCareCaseEvent.kind == "priority_changed",
            )
            .all()
        )
        assert len(events) == 1
        # Locked: every priority_changed event has an actor
        assert events[0].actor_user_id == admin.id
        assert events[0].actor_user_id is not None

    def test_invalid_priority_rejected_by_schema(self):
        with pytest.raises(Exception):
            UpdatePriorityRequest(priority="critical")


# ---------------------------------------------------------------------------
# 4. Every mutation writes a case event
# ---------------------------------------------------------------------------


class TestAuditTrail:
    def test_seed_writes_case_opened_and_report_attached(
        self, db, make_user, care_enabled
    ):
        admin = make_user(role="admin")
        u = make_user(role="user")
        detail = seed_report(
            AdminSeedReportRequest(
                reporter_kind="admin",
                content_type="member_behaviour",
                target_member_user_id=u.id,
                category="spam_or_scam",
            ),
            admin=admin, db=db,
        )
        events = (
            db.query(CommunityCareCaseEvent)
            .filter(CommunityCareCaseEvent.case_id == detail.id)
            .order_by(CommunityCareCaseEvent.occurred_at.asc())
            .all()
        )
        assert [e.kind for e in events] == ["case_opened", "report_attached"]

    def test_assign_then_status_then_note_then_close_writes_events(
        self, db, make_user, care_enabled
    ):
        admin = make_user(role="admin")
        reviewer = make_user(role="admin")
        u = make_user(role="user")
        detail = seed_report(
            AdminSeedReportRequest(
                reporter_kind="admin",
                content_type="member_behaviour",
                target_member_user_id=u.id,
                category="spam_or_scam",
            ),
            admin=admin, db=db,
        )
        assign_reviewer(detail.id, AssignReviewerRequest(reviewer_user_id=reviewer.id), admin=admin, db=db)
        update_status(detail.id, UpdateStatusRequest(status="reviewing"), admin=admin, db=db)
        add_note(detail.id, AddNoteRequest(body="Followed up in Slack."), admin=admin, db=db)
        close_case(detail.id, CloseCaseRequest(resolution_actions=[]), admin=admin, db=db)

        kinds = [
            e.kind
            for e in db.query(CommunityCareCaseEvent)
            .filter(CommunityCareCaseEvent.case_id == detail.id)
            .order_by(CommunityCareCaseEvent.occurred_at.asc())
            .all()
        ]
        assert kinds == [
            "case_opened", "report_attached",
            "assigned", "status_changed", "note_added",
            "closed",
        ]


# ---------------------------------------------------------------------------
# 5. Close with resolution outcomes
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_with_no_actions_is_closed_no_action(
        self, db, make_user, care_enabled
    ):
        admin = make_user(role="admin")
        u = make_user(role="user")
        detail = seed_report(
            AdminSeedReportRequest(
                reporter_kind="admin", content_type="member_behaviour",
                target_member_user_id=u.id, category="spam_or_scam",
            ),
            admin=admin, db=db,
        )
        result = close_case(detail.id, CloseCaseRequest(resolution_actions=[]), admin=admin, db=db)
        assert result.status == "closed_no_action"

    def test_close_with_explicit_no_further_action_is_closed_no_action(
        self, db, make_user, care_enabled
    ):
        admin = make_user(role="admin")
        u = make_user(role="user")
        detail = seed_report(
            AdminSeedReportRequest(
                reporter_kind="admin", content_type="member_behaviour",
                target_member_user_id=u.id, category="spam_or_scam",
            ),
            admin=admin, db=db,
        )
        result = close_case(
            detail.id,
            CloseCaseRequest(
                resolution_actions=[
                    ResolutionAction(kind="no_further_action", reason="reviewed"),
                ],
                resolution_summary="Nothing warranting action.",
            ),
            admin=admin, db=db,
        )
        assert result.status == "closed_no_action"
        assert (
            db.query(CommunityCareAction)
            .filter(CommunityCareAction.case_id == detail.id)
            .count()
            == 1
        )

    def test_close_with_multiple_resolutions_creates_multiple_action_rows(
        self, db, make_user, make_space, care_enabled
    ):
        """Creator cancellation + per-collective closure — case-by-case,
        never cascading. Model must support multiple resolution rows."""
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        detail = seed_report(
            AdminSeedReportRequest(
                reporter_kind="admin",
                content_type="creator_request",
                subject_creator_user_id=creator.id,
                subject_space_id=space.id,
                category="something_else",
                reporter_note="Serious concern raised via creator support",
            ),
            admin=admin, db=db,
        )
        # Stage 2D — resolution outcomes require the operational
        # case_summary to be present. Set it directly on the ORM row
        # so this Stage 2A test does not depend on the Stage 2D
        # summary endpoint.
        case = db.query(CommunityCareCase).filter(CommunityCareCase.id == detail.id).one()
        case.case_summary = "Review complete; outcomes recorded."
        db.flush()
        result = close_case(
            detail.id,
            CloseCaseRequest(
                resolution_actions=[
                    ResolutionAction(
                        kind="creator_account_cancellation",
                        reason="serious breach",
                        affected_user_id=creator.id,
                    ),
                    ResolutionAction(
                        kind="collective_closure_removal",
                        reason="content harm",
                        affected_space_id=space.id,
                    ),
                ],
            ),
            admin=admin, db=db,
        )
        assert result.status == "resolved"
        kinds = sorted(a.kind for a in db.query(CommunityCareAction)
                       .filter(CommunityCareAction.case_id == detail.id).all())
        assert kinds == ["collective_closure_removal", "creator_account_cancellation"]

    def test_double_close_refused(self, db, make_user, care_enabled):
        admin = make_user(role="admin")
        u = make_user(role="user")
        detail = seed_report(
            AdminSeedReportRequest(
                reporter_kind="admin", content_type="member_behaviour",
                target_member_user_id=u.id, category="spam_or_scam",
            ),
            admin=admin, db=db,
        )
        close_case(detail.id, CloseCaseRequest(resolution_actions=[]), admin=admin, db=db)
        with pytest.raises(HTTPException) as e:
            close_case(detail.id, CloseCaseRequest(resolution_actions=[]), admin=admin, db=db)
        assert e.value.status_code == 409

    def test_status_endpoint_refuses_to_set_terminal_states(
        self, db, make_user, care_enabled
    ):
        admin = make_user(role="admin")
        u = make_user(role="user")
        detail = seed_report(
            AdminSeedReportRequest(
                reporter_kind="admin", content_type="member_behaviour",
                target_member_user_id=u.id, category="spam_or_scam",
            ),
            admin=admin, db=db,
        )
        with pytest.raises(HTTPException) as e:
            update_status(detail.id, UpdateStatusRequest(status="resolved"), admin=admin, db=db)
        assert e.value.status_code == 422


# ---------------------------------------------------------------------------
# 6. Wellbeing rule
# ---------------------------------------------------------------------------


class TestWellbeingRule:
    def test_healthy_when_no_high_or_immediate(self, db, make_user, care_enabled):
        admin = make_user(role="admin")
        u = make_user(role="user")
        seed_report(
            AdminSeedReportRequest(
                reporter_kind="admin", content_type="member_behaviour",
                target_member_user_id=u.id, category="spam_or_scam",
            ),
            admin=admin, db=db,
        )
        # priority is low by default
        overview = get_overview(_=admin, db=db)
        assert overview.overall_wellbeing == "healthy"
        assert overview.overall_wellbeing_label == "Healthy"

    def test_needs_attention_when_a_high_case_is_open(
        self, db, make_user, care_enabled
    ):
        admin = make_user(role="admin")
        u = make_user(role="user")
        detail = seed_report(
            AdminSeedReportRequest(
                reporter_kind="admin", content_type="member_behaviour",
                target_member_user_id=u.id, category="harassment_or_bullying",
            ),
            admin=admin, db=db,
        )
        update_priority(detail.id, UpdatePriorityRequest(priority="high"), admin=admin, db=db)
        overview = get_overview(_=admin, db=db)
        assert overview.overall_wellbeing == "needs_attention"

    def test_needs_care_when_an_immediate_case_is_open(
        self, db, make_user, care_enabled
    ):
        admin = make_user(role="admin")
        u = make_user(role="user")
        detail = seed_report(
            AdminSeedReportRequest(
                reporter_kind="admin", content_type="member_behaviour",
                target_member_user_id=u.id, category="unsafe_behaviour",
            ),
            admin=admin, db=db,
        )
        update_priority(detail.id, UpdatePriorityRequest(priority="immediate"), admin=admin, db=db)
        overview = get_overview(_=admin, db=db)
        assert overview.overall_wellbeing == "needs_care"

    def test_closed_immediate_case_does_not_affect_wellbeing(
        self, db, make_user, care_enabled
    ):
        admin = make_user(role="admin")
        u = make_user(role="user")
        detail = seed_report(
            AdminSeedReportRequest(
                reporter_kind="admin", content_type="member_behaviour",
                target_member_user_id=u.id, category="unsafe_behaviour",
            ),
            admin=admin, db=db,
        )
        update_priority(detail.id, UpdatePriorityRequest(priority="immediate"), admin=admin, db=db)
        close_case(detail.id, CloseCaseRequest(resolution_actions=[]), admin=admin, db=db)
        overview = get_overview(_=admin, db=db)
        assert overview.overall_wellbeing == "healthy"


# ---------------------------------------------------------------------------
# 7. Snapshot immutability
# ---------------------------------------------------------------------------


class TestSnapshotImmutable:
    def test_snapshot_survives_source_deletion(
        self, db, make_user, make_space, care_enabled
    ):
        """When a post is deleted from the DB after being reported, the
        case's ``content_snapshot`` must still contain what was seen at
        report time — the review cannot rely on the live source."""
        from app.models.platform import CommunityPost, ConversationChannel

        admin = make_user(role="admin")
        author = make_user(role="user")
        space = make_space(creator=make_user(role="creator"))
        channel = ConversationChannel(
            id=f"ch_{uuid.uuid4().hex[:10]}",
            space_id=space.id,
            name="General",
            slug="general",
        )
        db.add(channel)
        db.flush()
        post = CommunityPost(
            id=f"cp_{uuid.uuid4().hex[:10]}",
            space_id=space.id,
            author_id=author.id,
            channel_id=channel.id,
            title="Test post",
            body="Original body copied into snapshot",
            post_type="discussion",
        )
        db.add(post)
        db.flush()

        detail = seed_report(
            AdminSeedReportRequest(
                reporter_kind="admin",
                content_type="post",
                target_post_id=post.id,
                target_member_user_id=author.id,
                category="inappropriate_content",
            ),
            admin=admin, db=db,
        )
        # Delete the source
        db.delete(post)
        db.commit()

        # Snapshot still visible on the case
        case = db.query(CommunityCareCase).filter(CommunityCareCase.id == detail.id).one()
        assert case.content_snapshot is not None
        assert case.content_snapshot["body"] == "Original body copied into snapshot"
        assert case.content_snapshot["kind"] == "post"
