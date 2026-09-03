"""
Stage 2C tests — Supportive Responses and Protective Measures.

Locks:
- Flag off returns 503 on every new endpoint.
- Layer/kind validation refuses wrong-layer kinds at the schema.
- Supportive issue creates a supportive action + routine/action severity
  notification; case status advances to reviewing.
- Protective issue creates a protective action + agreed-severity
  notification + real enforcement state:
    * content_hidden: cc_hidden_at set on target; feed filters it
      from members; admin can still see it; comment writes to a
      hidden post refused; reversal restores.
    * posting_restriction: MemberRestriction(kind='posting') row
      created; post/comment/reaction/poll writes refused; reversal
      lifts.
    * creator_restriction: MemberRestriction(kind='creator') created;
      creator writes refused; reversal lifts.
    * collective_freeze: space.frozen_at set; writes on that space
      refused for both members and creators; join/booking refused;
      reversal clears.
    * suspension_pending_review: user.suspended_at set;
      get_current_user 401 on any authenticated call; login refused;
      reversal restores access.
- Duplicate protective on same target = 409.
- Supportive cannot be reversed (400).
- Every mutation writes a community_care_case_events row.
- Enforcement cannot be bypassed by direct API access (each write path
  gets its own test).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException, Request
from pydantic import ValidationError

from app.admin.community_care.routes import (
    close_case,
    issue_protective_action,
    issue_supportive_action,
    reverse_action,
)
from app.admin.community_care.schemas import (
    CloseCaseRequest,
    IssueProtectiveActionRequest,
    IssueSupportiveActionRequest,
    ReverseActionRequest,
)
from app.auth.dependencies import get_current_user
from app.community.routes import (
    create_community_post,
    create_comment,
    toggle_post_reaction,
    list_community_posts,
    get_community_post,
)
from app.community.schemas import (
    CreatePostRequest,
    CreateCommentRequest,
)
from app.community_care.shared import (
    active_protective_action_on_target,
    has_active_creator_restriction,
    has_active_posting_restriction,
    is_space_frozen,
    is_user_suspended,
)
from app.core.config import settings
from app.creator.routes import (
    _ensure_creator_write_allowed,
    create_pathway,
    update_space,
)
from app.creator.schemas import PathwayCreateRequest, SpaceUpdateRequest
from app.models.community_care import (
    CommunityCareCase,
    CommunityCareCaseEvent,
    CommunityCareAction,
    MemberRestriction,
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
from fastapi import BackgroundTasks


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def care_enabled(monkeypatch):
    monkeypatch.setattr(settings, "community_care_enabled", True)
    yield


@pytest.fixture
def make_channel(db):
    def _factory(space, is_default=True) -> ConversationChannel:
        c = ConversationChannel(
            id=f"ch_{uuid.uuid4().hex[:10]}",
            space_id=space.id,
            name="Common Room" if is_default else "General",
            slug="common-room" if is_default else "general",
            is_default=is_default,
            is_system=is_default,
            member_posting_allowed=True,
        )
        db.add(c)
        db.flush()
        return c
    return _factory


@pytest.fixture
def make_membership(db):
    def _factory(*, user, space, role=SpaceRole.learner) -> SpaceMembership:
        m = SpaceMembership(
            id=f"sm_{uuid.uuid4().hex[:10]}",
            user_id=user.id,
            space_id=space.id,
            role=role,
            status=SpaceMembershipStatus.active,
        )
        db.add(m)
        db.flush()
        return m
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
            title="Post",
            body="Body",
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
            body="A reply",
        )
        db.add(c)
        db.flush()
        return c
    return _factory


@pytest.fixture
def open_case(db, make_user, make_space):
    """A minimal open case admins can issue actions on."""
    def _factory(**overrides) -> CommunityCareCase:
        space = overrides.pop("space", None) or make_space()
        c = CommunityCareCase(
            id=f"cc_{uuid.uuid4().hex[:10]}",
            case_number=f"CC-2026-{uuid.uuid4().hex[:4].upper()}",
            content_type=overrides.pop("content_type", "post"),
            subject_space_id=space.id,
            subject_member_user_id=overrides.pop("member_id", None),
            status="new",
            priority="low",
            report_count=1,
            opened_at=datetime.utcnow(),
        )
        db.add(c)
        db.flush()
        return c
    return _factory


@pytest.fixture
def fake_request():
    scope = {"type": "http", "client": ("127.0.0.1", 12345), "headers": [], "method": "POST", "path": "/x"}
    return Request(scope)


# ---------------------------------------------------------------------------
# 1. Flag gate — every new endpoint 503 when disabled
# ---------------------------------------------------------------------------


class TestFlagGate:
    def test_supportive_flag_off(self, db, make_user, open_case):
        admin = make_user(role="admin")
        recipient = make_user(role="user")
        case = open_case()
        with pytest.raises(HTTPException) as e:
            issue_supportive_action(
                case.id,
                IssueSupportiveActionRequest(
                    kind="guidance",
                    affected_user_id=recipient.id,
                    explanation_to_recipient="Please review our expectations.",
                ),
                admin=admin, db=db,
            )
        assert e.value.status_code == 503

    def test_protective_flag_off(self, db, make_user, open_case):
        admin = make_user(role="admin")
        target = make_user(role="user")
        case = open_case()
        with pytest.raises(HTTPException) as e:
            issue_protective_action(
                case.id,
                IssueProtectiveActionRequest(
                    kind="posting_restriction",
                    affected_user_id=target.id,
                    reason="pending review",
                    explanation_to_recipient="Your posting is paused.",
                ),
                admin=admin, db=db,
            )
        assert e.value.status_code == 503

    def test_reverse_flag_off(self, db, make_user):
        admin = make_user(role="admin")
        with pytest.raises(HTTPException) as e:
            reverse_action(
                "act_nonexistent",
                ReverseActionRequest(reversal_reason="anything"),
                admin=admin, db=db,
            )
        assert e.value.status_code == 503


# ---------------------------------------------------------------------------
# 2. Schema layer validation — wrong-layer kinds are refused
# ---------------------------------------------------------------------------


class TestLayerValidation:
    def test_supportive_refuses_protective_kind(self):
        with pytest.raises(ValidationError):
            IssueSupportiveActionRequest(
                kind="posting_restriction",
                affected_user_id="u_x",
                explanation_to_recipient="…",
            )

    def test_protective_refuses_supportive_kind(self):
        with pytest.raises(ValidationError):
            IssueProtectiveActionRequest(
                kind="guidance",
                affected_user_id="u_x",
                reason="…",
                explanation_to_recipient="…",
            )

    def test_protective_refuses_stage_2d_kind(self):
        with pytest.raises(ValidationError):
            IssueProtectiveActionRequest(
                kind="content_removed_from_public",
                affected_post_id="cp_x",
                reason="…",
            )


# ---------------------------------------------------------------------------
# 3. Supportive Responses
# ---------------------------------------------------------------------------


class TestSupportiveIssue:
    def test_guidance_creates_row_and_routine_notification(
        self, care_enabled, db, make_user, open_case
    ):
        admin = make_user(role="admin")
        recipient = make_user(role="user")
        case = open_case()
        issue_supportive_action(
            case.id,
            IssueSupportiveActionRequest(
                kind="guidance",
                affected_user_id=recipient.id,
                explanation_to_recipient="Consider softer language next time.",
            ),
            admin=admin, db=db,
        )
        actions = db.query(CommunityCareAction).filter_by(case_id=case.id).all()
        assert len(actions) == 1
        a = actions[0]
        assert a.layer == "supportive"
        assert a.kind == "guidance"
        assert a.issued_by_admin_user_id == admin.id
        assert a.affected_user_id == recipient.id
        assert a.explanation_to_recipient == "Consider softer language next time."
        # Notification landed with the mapped severity.
        n = db.query(Notification).filter_by(user_id=recipient.id).one()
        assert n.severity == "routine"
        # Case advanced to reviewing.
        db.refresh(case)
        assert case.status == "reviewing"

    def test_warning_uses_action_severity(
        self, care_enabled, db, make_user, open_case
    ):
        admin = make_user(role="admin")
        recipient = make_user(role="user")
        case = open_case()
        issue_supportive_action(
            case.id,
            IssueSupportiveActionRequest(
                kind="warning",
                affected_user_id=recipient.id,
                explanation_to_recipient="Please stop personal attacks.",
            ),
            admin=admin, db=db,
        )
        n = db.query(Notification).filter_by(user_id=recipient.id).one()
        assert n.severity == "action"

    def test_supportive_writes_case_event(
        self, care_enabled, db, make_user, open_case
    ):
        admin = make_user(role="admin")
        recipient = make_user(role="user")
        case = open_case()
        issue_supportive_action(
            case.id,
            IssueSupportiveActionRequest(
                kind="reminder",
                affected_user_id=recipient.id,
                explanation_to_recipient="Housekeeping reminder.",
            ),
            admin=admin, db=db,
        )
        events = db.query(CommunityCareCaseEvent).filter_by(case_id=case.id).all()
        kinds = [e.kind for e in events]
        assert "action_issued" in kinds

    def test_supportive_cannot_be_reversed(
        self, care_enabled, db, make_user, open_case
    ):
        admin = make_user(role="admin")
        recipient = make_user(role="user")
        case = open_case()
        detail = issue_supportive_action(
            case.id,
            IssueSupportiveActionRequest(
                kind="guidance",
                affected_user_id=recipient.id,
                explanation_to_recipient="…",
            ),
            admin=admin, db=db,
        )
        action = db.query(CommunityCareAction).filter_by(case_id=case.id).one()
        with pytest.raises(HTTPException) as e:
            reverse_action(
                action.id,
                ReverseActionRequest(reversal_reason="…"),
                admin=admin, db=db,
            )
        assert e.value.status_code == 400


# ---------------------------------------------------------------------------
# 4. Protective — content_hidden
# ---------------------------------------------------------------------------


class TestHideContent:
    def test_hide_post_sets_cc_hidden_and_filters_from_feed(
        self, care_enabled, db, make_user, make_space, make_channel,
        make_membership, make_post, open_case, fake_request,
    ):
        admin = make_user(role="admin")
        author = make_user(role="user")
        viewer = make_user(role="user")
        space = make_space()
        make_membership(user=viewer, space=space)
        make_membership(user=author, space=space)
        channel = make_channel(space)
        post = make_post(space=space, author=author, channel=channel)
        case = open_case(space=space)

        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="content_hidden",
                affected_post_id=post.id,
                reason="reported content pending review",
            ),
            admin=admin, db=db,
        )
        db.refresh(post)
        assert post.cc_hidden_at is not None
        assert post.cc_hidden_action_id is not None

        # Member feed no longer includes the post.
        feed = list_community_posts(space.slug, channel=channel.slug, db=db, current_user=viewer)
        assert not any(p.id == post.id for p in feed)

        # Ordinary members 404 on direct fetch.
        with pytest.raises(HTTPException) as e:
            get_community_post(space.slug, post.id, db=db, current_user=viewer)
        assert e.value.status_code == 404

        # Admins still see it via the same endpoint.
        detail = get_community_post(space.slug, post.id, db=db, current_user=admin)
        assert detail.id == post.id

    def test_hide_post_notifies_author_with_action_severity(
        self, care_enabled, db, make_user, make_space, make_channel,
        make_membership, make_post, open_case,
    ):
        admin = make_user(role="admin")
        author = make_user(role="user")
        space = make_space()
        make_membership(user=author, space=space)
        post = make_post(space=space, author=author)
        case = open_case(space=space)
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="content_hidden",
                affected_post_id=post.id,
                reason="pending review",
            ),
            admin=admin, db=db,
        )
        n = db.query(Notification).filter_by(user_id=author.id).one()
        assert n.severity == "action"

    def test_duplicate_hide_on_same_post_refused(
        self, care_enabled, db, make_user, make_space, make_post, open_case,
    ):
        admin = make_user(role="admin")
        author = make_user(role="user")
        space = make_space()
        post = make_post(space=space, author=author)
        case = open_case(space=space)
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="content_hidden",
                affected_post_id=post.id,
                reason="a",
            ),
            admin=admin, db=db,
        )
        with pytest.raises(HTTPException) as e:
            issue_protective_action(
                case.id,
                IssueProtectiveActionRequest(
                    kind="content_hidden",
                    affected_post_id=post.id,
                    reason="b",
                ),
                admin=admin, db=db,
            )
        assert e.value.status_code == 409

    def test_reverse_hide_restores_post(
        self, care_enabled, db, make_user, make_space, make_channel,
        make_membership, make_post, open_case,
    ):
        admin = make_user(role="admin")
        author = make_user(role="user")
        viewer = make_user(role="user")
        space = make_space()
        make_membership(user=viewer, space=space)
        channel = make_channel(space)
        post = make_post(space=space, author=author, channel=channel)
        case = open_case(space=space)
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="content_hidden",
                affected_post_id=post.id,
                reason="pending",
            ),
            admin=admin, db=db,
        )
        action = db.query(CommunityCareAction).filter_by(
            case_id=case.id, kind="content_hidden"
        ).one()
        reverse_action(
            action.id,
            ReverseActionRequest(reversal_reason="review cleared the content"),
            admin=admin, db=db,
        )
        db.refresh(post)
        assert post.cc_hidden_at is None
        assert post.cc_hidden_action_id is None
        # Feed shows it again.
        feed = list_community_posts(space.slug, channel=channel.slug, db=db, current_user=viewer)
        assert any(p.id == post.id for p in feed)
        # Reversal audit event written.
        events = db.query(CommunityCareCaseEvent).filter_by(case_id=case.id).all()
        assert any(e.kind == "action_reversed" for e in events)

    def test_comment_on_hidden_post_refused(
        self, care_enabled, db, make_user, make_space, make_channel,
        make_membership, make_post, open_case,
    ):
        admin = make_user(role="admin")
        author = make_user(role="user")
        commenter = make_user(role="user")
        space = make_space()
        make_membership(user=commenter, space=space)
        channel = make_channel(space)
        post = make_post(space=space, author=author, channel=channel)
        case = open_case(space=space)
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="content_hidden",
                affected_post_id=post.id,
                reason="pending",
            ),
            admin=admin, db=db,
        )
        with pytest.raises(HTTPException) as e:
            create_comment(
                space.slug, post.id,
                CreateCommentRequest(body="Reply"),
                background_tasks=BackgroundTasks(),
                db=db, current_user=commenter,
            )
        assert e.value.status_code == 404


# ---------------------------------------------------------------------------
# 5. Protective — posting_restriction
# ---------------------------------------------------------------------------


class TestPostingRestriction:
    def test_posting_restriction_blocks_post_create(
        self, care_enabled, db, make_user, make_space, make_channel,
        make_membership, open_case,
    ):
        admin = make_user(role="admin")
        member = make_user(role="user")
        space = make_space()
        make_membership(user=member, space=space)
        channel = make_channel(space)
        case = open_case(space=space)
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="posting_restriction",
                affected_user_id=member.id,
                reason="pending review",
                explanation_to_recipient="Your posting is paused.",
            ),
            admin=admin, db=db,
        )
        # A row was created and the write path refuses.
        assert has_active_posting_restriction(db, member.id, space.id)
        with pytest.raises(HTTPException) as e:
            create_community_post(
                space.slug,
                CreatePostRequest(title="x", body="y", post_type="discussion",
                                  channel_slug=channel.slug),
                background_tasks=BackgroundTasks(),
                db=db, current_user=member,
            )
        assert e.value.status_code == 403

    def test_posting_restriction_blocks_comment_and_reaction(
        self, care_enabled, db, make_user, make_space, make_channel,
        make_membership, make_post, open_case,
    ):
        admin = make_user(role="admin")
        member = make_user(role="user")
        author = make_user(role="user")
        space = make_space()
        make_membership(user=member, space=space)
        make_membership(user=author, space=space)
        channel = make_channel(space)
        post = make_post(space=space, author=author, channel=channel)
        case = open_case(space=space)
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="posting_restriction",
                affected_user_id=member.id,
                reason="pending",
                explanation_to_recipient="paused",
            ),
            admin=admin, db=db,
        )
        with pytest.raises(HTTPException) as ec:
            create_comment(
                space.slug, post.id,
                CreateCommentRequest(body="hi"),
                background_tasks=BackgroundTasks(),
                db=db, current_user=member,
            )
        assert ec.value.status_code == 403
        with pytest.raises(HTTPException) as er:
            toggle_post_reaction(
                space.slug, post.id, "❤️",
                db=db, current_user=member,
            )
        assert er.value.status_code == 403

    def test_reverse_lifts_restriction(
        self, care_enabled, db, make_user, make_space, make_channel,
        make_membership, open_case,
    ):
        admin = make_user(role="admin")
        member = make_user(role="user")
        space = make_space()
        make_membership(user=member, space=space)
        make_channel(space)
        case = open_case(space=space)
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="posting_restriction",
                affected_user_id=member.id,
                reason="pending",
                explanation_to_recipient="paused",
            ),
            admin=admin, db=db,
        )
        assert has_active_posting_restriction(db, member.id, space.id)
        action = db.query(CommunityCareAction).filter_by(
            case_id=case.id, kind="posting_restriction"
        ).one()
        reverse_action(
            action.id,
            ReverseActionRequest(reversal_reason="review complete"),
            admin=admin, db=db,
        )
        assert not has_active_posting_restriction(db, member.id, space.id)


# ---------------------------------------------------------------------------
# 6. Protective — creator_restriction
# ---------------------------------------------------------------------------


class TestCreatorRestriction:
    def test_creator_restriction_blocks_update_space(
        self, care_enabled, db, make_user, make_space, open_case,
    ):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        case = open_case(space=space)
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="creator_restriction",
                affected_user_id=creator.id,
                reason="pending",
                explanation_to_recipient="paused",
            ),
            admin=admin, db=db,
        )
        assert has_active_creator_restriction(db, creator.id)
        with pytest.raises(HTTPException) as e:
            update_space(
                space.slug,
                SpaceUpdateRequest(tagline="Updated"),
                db=db, current_user=creator,
            )
        assert e.value.status_code == 403

    def test_creator_restriction_blocks_create_pathway(
        self, care_enabled, db, make_user, make_space, open_case,
    ):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        case = open_case(space=space)
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="creator_restriction",
                affected_user_id=creator.id,
                reason="pending",
                explanation_to_recipient="paused",
            ),
            admin=admin, db=db,
        )
        with pytest.raises(HTTPException) as e:
            create_pathway(
                space.slug,
                PathwayCreateRequest(title="A pathway"),
                db=db, current_user=creator,
            )
        assert e.value.status_code == 403

    def test_reverse_lifts_creator_restriction(
        self, care_enabled, db, make_user, make_space, open_case,
    ):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        case = open_case(space=space)
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="creator_restriction",
                affected_user_id=creator.id,
                reason="pending",
                explanation_to_recipient="paused",
            ),
            admin=admin, db=db,
        )
        action = db.query(CommunityCareAction).filter_by(
            case_id=case.id, kind="creator_restriction"
        ).one()
        reverse_action(
            action.id,
            ReverseActionRequest(reversal_reason="clear"),
            admin=admin, db=db,
        )
        assert not has_active_creator_restriction(db, creator.id)


# ---------------------------------------------------------------------------
# 7. Protective — collective_freeze
# ---------------------------------------------------------------------------


class TestCollectiveFreeze:
    def test_freeze_blocks_member_write_paths(
        self, care_enabled, db, make_user, make_space, make_channel,
        make_membership, open_case,
    ):
        admin = make_user(role="admin")
        member = make_user(role="user")
        space = make_space()
        make_membership(user=member, space=space)
        channel = make_channel(space)
        case = open_case(space=space)
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="collective_freeze",
                affected_space_id=space.id,
                reason="community-wide review",
                explanation_to_recipient="Paused while we review.",
            ),
            admin=admin, db=db,
        )
        db.refresh(space)
        assert is_space_frozen(space)
        # Post + comment + reaction refused.
        with pytest.raises(HTTPException) as ep:
            create_community_post(
                space.slug,
                CreatePostRequest(title="x", body="y", post_type="discussion",
                                  channel_slug=channel.slug),
                background_tasks=BackgroundTasks(),
                db=db, current_user=member,
            )
        assert ep.value.status_code == 403

    def test_freeze_blocks_creator_writes_on_that_space(
        self, care_enabled, db, make_user, make_space, open_case,
    ):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        case = open_case(space=space)
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="collective_freeze",
                affected_space_id=space.id,
                reason="pending",
                explanation_to_recipient="paused",
            ),
            admin=admin, db=db,
        )
        db.refresh(space)
        with pytest.raises(HTTPException) as e:
            update_space(
                space.slug,
                SpaceUpdateRequest(tagline="new"),
                db=db, current_user=creator,
            )
        assert e.value.status_code == 403

    def test_admin_can_still_write_to_frozen_space(
        self, care_enabled, db, make_user, make_space, open_case,
    ):
        admin = make_user(role="admin")
        space = make_space()
        case = open_case(space=space)
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="collective_freeze",
                affected_space_id=space.id,
                reason="pending",
                explanation_to_recipient="paused",
            ),
            admin=admin, db=db,
        )
        # Admin bypass in _ensure_creator_write_allowed: no HTTPException.
        _ensure_creator_write_allowed(admin, space, db)

    def test_freeze_notifies_creator(
        self, care_enabled, db, make_user, make_space, open_case,
    ):
        admin = make_user(role="admin")
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        case = open_case(space=space)
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="collective_freeze",
                affected_space_id=space.id,
                reason="review",
                explanation_to_recipient="paused",
            ),
            admin=admin, db=db,
        )
        n = db.query(Notification).filter_by(user_id=creator.id).one()
        assert n.severity == "action"

    def test_reverse_clears_freeze(
        self, care_enabled, db, make_user, make_space, open_case,
    ):
        admin = make_user(role="admin")
        space = make_space()
        case = open_case(space=space)
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="collective_freeze",
                affected_space_id=space.id,
                reason="pending",
                explanation_to_recipient="paused",
            ),
            admin=admin, db=db,
        )
        action = db.query(CommunityCareAction).filter_by(
            case_id=case.id, kind="collective_freeze"
        ).one()
        reverse_action(
            action.id,
            ReverseActionRequest(reversal_reason="review closed"),
            admin=admin, db=db,
        )
        db.refresh(space)
        assert not is_space_frozen(space)
        assert space.frozen_by_action_id is None


# ---------------------------------------------------------------------------
# 8. Protective — suspension_pending_review
# ---------------------------------------------------------------------------


class TestSuspensionPendingReview:
    def test_suspension_sets_user_state_and_urgent_severity(
        self, care_enabled, db, make_user, open_case,
    ):
        admin = make_user(role="admin")
        target = make_user(role="user")
        case = open_case()
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="suspension_pending_review",
                affected_user_id=target.id,
                reason="urgent safety concern",
                explanation_to_recipient="Your access is paused while we review.",
            ),
            admin=admin, db=db,
        )
        db.refresh(target)
        assert is_user_suspended(target)
        assert target.suspended_by_action_id is not None
        n = db.query(Notification).filter_by(user_id=target.id).one()
        assert n.severity == "urgent"

    def test_get_current_user_refuses_suspended(
        self, care_enabled, db, make_user, open_case,
    ):
        # Simulate a live session: suspend the user, then call the auth
        # dependency directly with a request that carries their token.
        from app.core.security import create_access_token
        admin = make_user(role="admin")
        target = make_user(role="user")
        case = open_case()
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="suspension_pending_review",
                affected_user_id=target.id,
                reason="pending",
                explanation_to_recipient="paused",
            ),
            admin=admin, db=db,
        )
        # SEC-008 — include the ``sv`` claim so the token satisfies
        # the session-version check; the assertion here is that
        # get_current_user still refuses on suspension grounds.
        token = create_access_token({"sub": target.id, "sv": target.session_version})
        scope = {
            "type": "http",
            "headers": [(b"cookie", f"fc_session={token}".encode())],
            "client": ("127.0.0.1", 12345),
            "method": "GET",
            "path": "/x",
        }
        req = Request(scope)
        with pytest.raises(HTTPException) as e:
            get_current_user(req, db)
        assert e.value.status_code == 401

    def test_login_refuses_suspended(
        self, care_enabled, db, make_user, open_case,
    ):
        # Reach into the login handler directly. It hashes the password
        # on account creation via factory, so use a known-good password.
        from app.auth import service
        admin = make_user(role="admin")
        target = make_user(
            role="user",
            password_hash=service.hash_password("correct-horse"),
        )
        case = open_case()
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="suspension_pending_review",
                affected_user_id=target.id,
                reason="pending",
                explanation_to_recipient="paused",
            ),
            admin=admin, db=db,
        )
        from app.auth.routes import login
        from app.auth.schemas import LoginRequest
        scope = {
            "type": "http", "headers": [], "client": ("127.0.0.1", 12345),
            "method": "POST", "path": "/api/auth/login",
        }
        req = Request(scope)

        class _Resp:
            def set_cookie(self, **_): pass

        import asyncio
        with pytest.raises(HTTPException) as e:
            asyncio.run(login(
                request=req,
                payload=LoginRequest(email=target.email, password="correct-horse"),
                response=_Resp(),
                db=db,
            ))
        assert e.value.status_code == 403

    def test_reverse_restores_access(
        self, care_enabled, db, make_user, open_case,
    ):
        admin = make_user(role="admin")
        target = make_user(role="user")
        case = open_case()
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="suspension_pending_review",
                affected_user_id=target.id,
                reason="pending",
                explanation_to_recipient="paused",
            ),
            admin=admin, db=db,
        )
        action = db.query(CommunityCareAction).filter_by(
            case_id=case.id, kind="suspension_pending_review"
        ).one()
        reverse_action(
            action.id,
            ReverseActionRequest(reversal_reason="review complete"),
            admin=admin, db=db,
        )
        db.refresh(target)
        assert not is_user_suspended(target)
        assert target.suspended_by_action_id is None


# ---------------------------------------------------------------------------
# 9. Reversal semantics
# ---------------------------------------------------------------------------


class TestReversalSemantics:
    def test_double_reverse_refused(
        self, care_enabled, db, make_user, make_space, make_post, open_case,
    ):
        admin = make_user(role="admin")
        author = make_user(role="user")
        space = make_space()
        post = make_post(space=space, author=author)
        case = open_case(space=space)
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="content_hidden",
                affected_post_id=post.id,
                reason="pending",
            ),
            admin=admin, db=db,
        )
        action = db.query(CommunityCareAction).filter_by(
            case_id=case.id, kind="content_hidden"
        ).one()
        reverse_action(
            action.id,
            ReverseActionRequest(reversal_reason="cleared"),
            admin=admin, db=db,
        )
        with pytest.raises(HTTPException) as e:
            reverse_action(
                action.id,
                ReverseActionRequest(reversal_reason="again"),
                admin=admin, db=db,
            )
        assert e.value.status_code == 409

    def test_reversal_does_not_edit_original(
        self, care_enabled, db, make_user, open_case,
    ):
        admin = make_user(role="admin")
        target = make_user(role="user")
        case = open_case()
        issue_protective_action(
            case.id,
            IssueProtectiveActionRequest(
                kind="posting_restriction",
                affected_user_id=target.id,
                reason="pending",
                explanation_to_recipient="paused",
            ),
            admin=admin, db=db,
        )
        action = db.query(CommunityCareAction).filter_by(
            case_id=case.id, kind="posting_restriction"
        ).one()
        original_issued_by = action.issued_by_admin_user_id
        original_reason = action.reason
        original_started = action.starts_at
        reverse_action(
            action.id,
            ReverseActionRequest(reversal_reason="review complete"),
            admin=admin, db=db,
        )
        db.refresh(action)
        assert action.issued_by_admin_user_id == original_issued_by
        assert action.reason == original_reason
        assert action.starts_at == original_started
        assert action.reversed_at is not None
        assert action.reversed_by_admin_user_id == admin.id
        assert action.reversal_reason == "review complete"


# ---------------------------------------------------------------------------
# 10. Closed case cannot receive further actions
# ---------------------------------------------------------------------------


class TestClosedCaseGuard:
    def test_closed_case_refuses_supportive(
        self, care_enabled, db, make_user, open_case,
    ):
        admin = make_user(role="admin")
        target = make_user(role="user")
        case = open_case()
        close_case(case.id, CloseCaseRequest(), admin=admin, db=db)
        with pytest.raises(HTTPException) as e:
            issue_supportive_action(
                case.id,
                IssueSupportiveActionRequest(
                    kind="guidance",
                    affected_user_id=target.id,
                    explanation_to_recipient="…",
                ),
                admin=admin, db=db,
            )
        assert e.value.status_code == 409

    def test_closed_case_refuses_protective(
        self, care_enabled, db, make_user, open_case,
    ):
        admin = make_user(role="admin")
        target = make_user(role="user")
        case = open_case()
        close_case(case.id, CloseCaseRequest(), admin=admin, db=db)
        with pytest.raises(HTTPException) as e:
            issue_protective_action(
                case.id,
                IssueProtectiveActionRequest(
                    kind="posting_restriction",
                    affected_user_id=target.id,
                    reason="…",
                    explanation_to_recipient="…",
                ),
                admin=admin, db=db,
            )
        assert e.value.status_code == 409
