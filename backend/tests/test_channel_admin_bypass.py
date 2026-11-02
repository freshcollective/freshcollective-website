"""Platform administration is not member participation.

Reproduces the production report first, then pins the corrected
behaviour.

The report: the platform administrator, a member of Kelly's
Collective, could see and post in a channel linked only to a **draft**
Pathway they had never enrolled in, through the ordinary member
interface.

An earlier investigation concluded draft-Pathway channels were
unreachable by ordinary members. That conclusion was right and
incomplete: `can_view_channel` consults `is_caretaker` *before* it
looks at the channel type at all, and `is_caretaker` returns True for
`User.role == "admin"` anywhere on the platform. The draft check was
never reached.

There is a second bypass behind it — `compute_pathway_access` returns
True for a platform admin — so removing only the first would have
moved the leak rather than closed it. Both are covered here.

What must NOT change: a Collective's owner, and its creator/moderator
members, keep every channel in their own Collective.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import (
    get_current_user,
    get_optional_user,
    get_verified_current_user,
)
from app.db.session import get_db
from app.main import app
from app.models.platform import (
    ChannelExperienceLink,
    ChannelMembership,
    CommunityPost,
    ConversationChannel,
    Pathway,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services import channel_permissions as perms


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def kelly(make_user):
    """The Collective's owner."""
    return make_user(role="creator")


@pytest.fixture
def space(make_space, kelly):
    return make_space(creator=kelly, name="Nourish Connect Thrive")


@pytest.fixture
def join(db):
    def _join(space, user, role=SpaceRole.learner):
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=user.id, space_id=space.id,
            role=role, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        db.flush()
    return _join


@pytest.fixture
def draft_pathway(db, space):
    row = Pathway(
        id=_uid("pw"), space_id=space.id, title="Daring Heart",
        slug=f"daring-heart-{uuid.uuid4().hex[:6]}",
        status="draft", access_type="one_time",
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def channel(db, space, draft_pathway):
    row = ConversationChannel(
        id=_uid("ch"), space_id=space.id, name="Daring Heart",
        slug=f"daring-heart-{uuid.uuid4().hex[:6]}",
        channel_type="pathway", pathway_id=draft_pathway.id,
        member_posting_allowed=True,
    )
    db.add(row)
    db.flush()
    db.add(ChannelExperienceLink(
        id=_uid("cel"), channel_id=row.id, pathway_id=draft_pathway.id,
    ))
    db.flush()
    return row


@pytest.fixture
def admin(db, make_user, join, space):
    """The platform administrator, participating as an ordinary member
    of somebody else's Collective."""
    user = make_user(role="admin")
    join(space, user)
    return user


def _client(db, user):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user
    app.dependency_overrides[get_verified_current_user] = lambda: user
    return TestClient(app)


@pytest.fixture
def as_user(db):
    made: list[None] = []

    def _as(user):
        made.append(None)
        return _client(db, user)
    yield _as
    app.dependency_overrides.clear()


class TestTheProductionReport:
    """The behaviour as observed, asserted as the corrected outcome."""

    def test_admin_cannot_view_a_draft_pathway_channel(
        self, db, space, channel, admin,
    ):
        db.commit()
        assert perms.can_view_channel(admin, channel, space, db) is False, (
            "a global admin role is not participation in this Collective"
        )

    def test_admin_cannot_post_in_it(self, db, space, channel, admin):
        db.commit()
        assert perms.can_post(admin, channel, space, db) is False

    def test_the_draft_check_is_actually_reached(
        self, db, space, channel, admin, draft_pathway,
    ):
        """The first investigation's conclusion, now true for an admin.

        `is_caretaker` used to answer before the channel type was
        consulted, so this predicate was never asked.
        """
        assert perms.qualifies_through_any_linked_experience(
            admin, channel, space, db,
        ) is False

    def test_it_is_absent_from_the_member_channel_list(
        self, db, space, channel, admin, as_user,
    ):
        db.commit()
        r = as_user(admin).get(f"/api/spaces/{space.slug}/channels")
        assert r.status_code == 200, r.text
        assert channel.id not in [c["id"] for c in r.json()]


class TestDirectAccessIsAlsoRefused:
    """Hiding it from navigation is not the fix — §4."""

    @pytest.fixture
    def post(self, db, space, channel, kelly):
        row = CommunityPost(
            id=_uid("cp"), space_id=space.id, channel_id=channel.id,
            author_id=kelly.id, body="Said among the enrolled",
            is_visible=True, publication_status="published",
        )
        db.add(row)
        db.commit()
        return row

    def test_the_channel_feed(self, db, space, channel, admin, as_user, post):
        r = as_user(admin).get(
            f"/api/spaces/{space.slug}/community?channel={channel.slug}",
        )
        assert r.status_code == 404, r.text

    def test_an_individual_post(self, db, space, admin, as_user, post):
        r = as_user(admin).get(f"/api/spaces/{space.slug}/community/{post.id}")
        assert r.status_code == 404, r.text

    def test_creating_a_conversation(
        self, db, space, channel, admin, as_user, post,
    ):
        r = as_user(admin).post(
            f"/api/spaces/{space.slug}/community",
            json={"body": "Hello", "channel_slug": channel.slug},
        )
        assert r.status_code in (403, 404), r.text

    def test_search(self, db, space, channel, admin, as_user, post):
        r = as_user(admin).get(
            f"/api/spaces/{space.slug}/community/search"
            f"?q=enrolled&channel={channel.slug}",
        )
        if r.status_code == 200:
            body = r.json()
            found = str(body)
            assert post.id not in found, "search leaked a refused channel"
        else:
            assert r.status_code == 404

    def test_mention_autocomplete(
        self, db, space, channel, admin, as_user, post,
    ):
        r = as_user(admin).get(
            f"/api/spaces/{space.slug}/members/search?q=a&channel={channel.slug}",
        )
        assert r.status_code == 404, r.text


class TestOrdinaryMembersWereNeverAffected:
    """Scope of the defect — §7.2."""

    def test_an_unenrolled_member_is_refused(
        self, db, space, channel, join, make_user,
    ):
        member = make_user()
        join(space, member)
        db.commit()
        assert perms.can_view_channel(member, channel, space, db) is False
        assert perms.can_post(member, channel, space, db) is False

    def test_collective_membership_alone_is_not_enough(
        self, db, space, channel, join, make_user,
    ):
        member = make_user()
        join(space, member)
        db.commit()
        assert perms.qualifies_through_any_linked_experience(
            member, channel, space, db,
        ) is False


class TestLegitimateAccessIsUntouched:
    """§2 and §5 — what must keep working."""

    def test_the_owner_keeps_their_own_channel(
        self, db, space, channel, kelly,
    ):
        db.commit()
        assert perms.can_view_channel(kelly, channel, space, db) is True
        assert perms.can_post(kelly, channel, space, db) is True

    def test_a_moderator_keeps_it(
        self, db, space, channel, join, make_user,
    ):
        mod = make_user()
        join(space, mod, role=SpaceRole.moderator)
        db.commit()
        assert perms.can_view_channel(mod, channel, space, db) is True

    def test_a_space_creator_membership_keeps_it(
        self, db, space, channel, join, make_user,
    ):
        co = make_user()
        join(space, co, role=SpaceRole.creator)
        db.commit()
        assert perms.can_view_channel(co, channel, space, db) is True

    def test_an_explicitly_added_member_keeps_it(
        self, db, space, channel, join, make_user,
    ):
        """§3 — a creator may add whoever they choose."""
        guest = make_user()
        join(space, guest)
        db.add(ChannelMembership(
            id=_uid("chm"), channel_id=channel.id, user_id=guest.id,
            role="member", source="manual", status="active",
        ))
        db.commit()
        assert perms.can_view_channel(guest, channel, space, db) is True
        assert perms.can_post(guest, channel, space, db) is True

    def test_a_previously_admitted_member_keeps_it(
        self, db, space, channel, join, make_user,
    ):
        """§3 and §5 — retained membership survives, including the
        EMBODY rows already backfilled."""
        alum = make_user()
        join(space, alum)
        db.add(ChannelMembership(
            id=_uid("chm"), channel_id=channel.id, user_id=alum.id,
            role="member", source="experience", status="active",
        ))
        db.commit()
        assert perms.can_view_channel(alum, channel, space, db) is True

    def test_an_admin_who_is_a_real_channel_member_keeps_it(
        self, db, space, channel, admin,
    ):
        """The fix removes the role bypass, not the person.

        An administrator who legitimately joined is still a member.
        """
        db.add(ChannelMembership(
            id=_uid("chm"), channel_id=channel.id, user_id=admin.id,
            role="member", source="experience", status="active",
        ))
        db.commit()
        assert perms.can_view_channel(admin, channel, space, db) is True

    def test_a_creator_removal_still_denies(
        self, db, space, channel, join, make_user,
    ):
        removed = make_user()
        join(space, removed)
        db.add(ChannelMembership(
            id=_uid("chm"), channel_id=channel.id, user_id=removed.id,
            role="member", source="experience", status="removed",
            removed_reason="creator", removed_at=datetime.utcnow(),
        ))
        db.commit()
        assert perms.can_view_channel(removed, channel, space, db) is False

    def test_a_removal_denies_an_admin_too(
        self, db, space, channel, admin,
    ):
        db.add(ChannelMembership(
            id=_uid("chm"), channel_id=channel.id, user_id=admin.id,
            role="member", source="experience", status="removed",
            removed_reason="creator", removed_at=datetime.utcnow(),
        ))
        db.commit()
        assert perms.can_view_channel(admin, channel, space, db) is False


class TestPublishedPathwaysBehaveTheSameWay:
    """Publication is not what gates the channel — acquisition is."""

    @pytest.fixture
    def published(self, db, space, channel, draft_pathway):
        draft_pathway.status = "active"
        draft_pathway.access_type = "one_time"
        db.commit()
        return channel

    def test_an_unenrolled_member_is_still_refused(
        self, db, space, published, join, make_user,
    ):
        member = make_user()
        join(space, member)
        db.commit()
        assert perms.can_view_channel(member, published, space, db) is False

    def test_the_admin_is_still_refused(self, db, space, published, admin):
        db.commit()
        assert perms.can_view_channel(admin, published, space, db) is False

    def test_an_entitlement_holder_is_allowed(
        self, db, space, published, draft_pathway, join, make_user,
    ):
        from app.models.platform import EntitlementStatus, PathwayEntitlement

        buyer = make_user()
        join(space, buyer)
        db.add(PathwayEntitlement(
            id=_uid("pe"), user_id=buyer.id, space_id=space.id,
            pathway_id=draft_pathway.id, status=EntitlementStatus.active,
            source="admin",
        ))
        db.commit()
        assert perms.can_view_channel(buyer, published, space, db) is True


class TestOpenChannelsAreUnaffected:
    """An admin who is a member is still a member."""

    def test_an_admin_sees_an_open_channel(self, db, space, admin):
        open_ch = ConversationChannel(
            id=_uid("ch"), space_id=space.id, name="Common Ground",
            slug=f"common-{uuid.uuid4().hex[:6]}", channel_type="open",
        )
        db.add(open_ch)
        db.commit()
        assert perms.can_view_channel(admin, open_ch, space, db) is True
        assert perms.can_post(admin, open_ch, space, db) is True

    def test_an_admin_does_not_see_a_private_channel_they_are_not_in(
        self, db, space, admin,
    ):
        private = ConversationChannel(
            id=_uid("ch"), space_id=space.id, name="Inner Circle",
            slug=f"inner-{uuid.uuid4().hex[:6]}", channel_type="private",
        )
        db.add(private)
        db.commit()
        assert perms.can_view_channel(admin, private, space, db) is False


class TestAdministrativeReachIsPreserved:
    """The other direction of the same risk — §2 and §5.

    Narrowing the global role must not take away the administrative
    access that World Management, support and Community Care depend on.
    Each of these broke while I was narrowing it, which is why they are
    pinned here rather than assumed.
    """

    @pytest.fixture
    def outsider_admin(self, make_user):
        """A platform admin with NO membership in this Collective."""
        return make_user(role="admin")

    @pytest.fixture
    def open_channel(self, db, space):
        row = ConversationChannel(
            id=_uid("ch"), space_id=space.id, name="Common Room",
            slug=f"common-{uuid.uuid4().hex[:6]}", channel_type="general",
            is_default=True, is_system=True,
        )
        db.add(row)
        db.commit()
        return row

    def test_an_unrestricted_channel_opens_without_membership(
        self, db, space, open_channel, outsider_admin,
    ):
        """Creator Studio and Community Care read this endpoint for
        Collectives the admin has never joined."""
        assert perms.can_view_channel(
            outsider_admin, open_channel, space, db,
        ) is True

    def test_and_they_can_act_in_it(
        self, db, space, open_channel, outsider_admin,
    ):
        """Hiding reported content requires reading and acting on the
        post — see test_community_care_stage_2c."""
        assert perms.can_post(
            outsider_admin, open_channel, space, db,
        ) is True

    def test_but_a_restricted_channel_does_not_open(
        self, db, space, channel, outsider_admin,
    ):
        assert perms.can_view_channel(
            outsider_admin, channel, space, db,
        ) is False

    def test_management_operations_still_answer_to_the_global_role(
        self, db, space, channel, outsider_admin,
    ):
        """Archiving, deleting and managing members stay available.

        These are deliberate administrative actions on named
        Collectives, not participation in a conversation, so they keep
        the wider predicate.
        """
        assert perms.can_manage_members(
            outsider_admin, channel, space, db,
        ) is True
        assert perms.can_archive(
            outsider_admin, channel, space, db,
        ) is True

    def test_the_distinction_in_one_assertion(
        self, db, space, channel, outsider_admin,
    ):
        """Manage it, yes. Be in it, no."""
        assert perms.can_manage_members(
            outsider_admin, channel, space, db,
        ) is True
        assert perms.can_view_channel(
            outsider_admin, channel, space, db,
        ) is False
