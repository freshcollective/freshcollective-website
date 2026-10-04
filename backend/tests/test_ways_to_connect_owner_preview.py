"""Private production preview for the Platform Owner — Ways to Connect.

The launch flag stays off for everybody. A signed-in Platform Owner can
nevertheless use the real production feature, so it can be tested before
the flag is flipped for all members.

The gate bypasses exactly one thing: the launch flag. Everything else —
eligibility, the mutual-hello requirement, thread participation, blocks
— still applies to the owner, because none of those consult it. Those
are the tests that matter most here, since a preview that quietly
relaxed authorisation would be worse than no preview.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.connections import MemberHello
from app.models.platform import (
    BookingStatus,
    CreatorProfile,
    EventBooking,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.ways_to_connect.routes import ways_to_connect_available

URL = "/api/ways-to-connect"
NOW = datetime.utcnow()


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user):
    app.dependency_overrides[get_current_user] = lambda: user


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ways_to_connect_enabled", True)


def _named(db, user, name):
    db.add(CreatorProfile(user_id=user.id, display_name=name, is_public=True))
    db.flush()


@pytest.fixture
def eligible_with(db, make_user, make_space, make_event):
    """Give ``viewer`` a genuinely eligible peer: two attended Gatherings."""
    def _make(viewer, name="Bob"):
        other = make_user()
        _named(db, other, name)
        space = make_space(show_member_directory=True)
        for u in (viewer, other):
            db.add(SpaceMembership(
                id=_uid("sm"), user_id=u.id, space_id=space.id,
                role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            ))
        for n, days in enumerate((14, 45)):
            ev = make_event(
                space=space,
                starts_at=NOW - timedelta(days=days),
                ends_at=NOW - timedelta(days=days) + timedelta(hours=1),
                title=f"Shared {n + 1}",
            )
            ev.attendance_completed_at = NOW - timedelta(days=days)
            for u in (viewer, other):
                db.add(EventBooking(
                    id=_uid("bk"), event_id=ev.id, user_id=u.id,
                    status=BookingStatus.confirmed, attendance_status="attended",
                ))
        db.flush()
        return other
    return _make


# ---------------------------------------------------------------------------
# The gate itself
# ---------------------------------------------------------------------------


class TestTheGate:
    def test_the_owner_is_allowed_while_the_flag_is_off(self, make_user):
        owner = make_user(role="admin")
        assert settings.ways_to_connect_enabled is False
        assert ways_to_connect_available(owner) is True

    def test_an_ordinary_member_is_not(self, make_user):
        assert ways_to_connect_available(make_user()) is False
        assert ways_to_connect_available(make_user(role="creator")) is False

    def test_with_the_flag_on_everybody_is_allowed(self, make_user, flag_on):
        """And the owner has no remaining difference."""
        for user in (make_user(), make_user(role="creator"), make_user(role="admin")):
            assert ways_to_connect_available(user) is True

    def test_it_reuses_the_canonical_owner_check(self):
        """Not an email comparison, not a hard-coded id, no query string
        or cookie back door."""
        import pathlib
        import re

        src = pathlib.Path("app/ways_to_connect/routes.py").read_text()
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        gate = code[code.index("def ways_to_connect_available"):]
        gate = gate[: gate.index("\ndef ")]
        assert "is_platform_owner" in gate
        for smell in ("@", "lindsey", "LINDSEY", "preview_token", "request.", "cookie"):
            assert smell not in gate, f"suspicious gate input: {smell}"


# ---------------------------------------------------------------------------
# With the flag off
# ---------------------------------------------------------------------------


class TestFlagOff:
    def test_the_owner_can_read_their_own_ways_to_connect(
        self, client, db, make_user, eligible_with,
    ):
        owner = make_user(role="admin")
        eligible_with(owner)
        as_user(owner)

        res = client.get(URL)
        assert res.status_code == 200, res.text
        assert res.json()["featured_count"] >= 1

    def test_the_owner_can_say_hello(self, client, db, make_user, eligible_with):
        owner = make_user(role="admin")
        other = eligible_with(owner)
        as_user(owner)

        res = client.post(f"{URL}/{other.id}/hello")
        assert res.status_code == 200, res.text
        assert res.json()["relationship"] == "outgoing"

    def test_an_ordinary_member_still_gets_the_unavailable_response(
        self, client, db, make_user, eligible_with,
    ):
        member = make_user()
        other = eligible_with(member)
        as_user(member)

        assert client.get(URL).status_code == 503
        assert client.post(f"{URL}/{other.id}/hello").status_code == 503

    def test_the_unavailable_wording_is_unchanged(self, client, db, make_user):
        """An ordinary member must see exactly what they saw before the
        preview existed."""
        as_user(make_user())
        assert (
            client.get(URL).json()["detail"]
            == "Ways to Connect is not yet enabled on this deployment."
        )

    def test_a_creator_is_not_an_owner(self, client, db, make_user):
        """Only the collapsed admin role previews. ``creator`` is not a
        Platform Owner."""
        as_user(make_user(role="creator"))
        assert client.get(URL).status_code == 503

    def test_an_unauthenticated_visitor_is_refused_as_before(self, client, db):
        app.dependency_overrides.pop(get_current_user, None)
        assert client.get(URL).status_code in (401, 403)

    def test_a_member_cannot_bypass_the_gate_by_calling_the_api_directly(
        self, client, db, make_user, eligible_with,
    ):
        """The point of enforcing it server-side: revealing the page was
        never the gate."""
        member = make_user()
        other = eligible_with(member)
        as_user(member)
        assert client.post(f"{URL}/{other.id}/hello").status_code == 503
        assert db.query(MemberHello).count() == 0


# ---------------------------------------------------------------------------
# The owner bypasses the flag and nothing else
# ---------------------------------------------------------------------------


class TestOwnerBypassesOnlyTheFlag:
    def test_eligibility_still_applies_to_the_owner(
        self, client, db, make_user, make_space, make_event,
    ):
        """One shared Gathering is one signal; the threshold is two. The
        owner is subject to it like anybody else."""
        owner = make_user(role="admin")
        other = make_user()
        _named(db, other, "Bob")
        space = make_space(show_member_directory=True)
        for u in (owner, other):
            db.add(SpaceMembership(
                id=_uid("sm"), user_id=u.id, space_id=space.id,
                role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            ))
        ev = make_event(
            space=space,
            starts_at=NOW - timedelta(days=14),
            ends_at=NOW - timedelta(days=14) + timedelta(hours=1),
            title="Only one",
        )
        ev.attendance_completed_at = NOW - timedelta(days=14)
        for u in (owner, other):
            db.add(EventBooking(
                id=_uid("bk"), event_id=ev.id, user_id=u.id,
                status=BookingStatus.confirmed, attendance_status="attended",
            ))
        db.flush()
        as_user(owner)

        assert client.get(URL).json()["featured_count"] == 0
        assert client.post(f"{URL}/{other.id}/hello").status_code == 404

    def test_the_owner_cannot_hello_a_stranger(
        self, client, db, make_user, eligible_with,
    ):
        owner = make_user(role="admin")
        eligible_with(owner)
        stranger = make_user()
        _named(db, stranger, "Stranger")
        db.flush()
        as_user(owner)
        assert client.post(f"{URL}/{stranger.id}/hello").status_code == 404

    def test_the_owner_cannot_hello_themselves(
        self, client, db, make_user, eligible_with,
    ):
        owner = make_user(role="admin")
        eligible_with(owner)
        as_user(owner)
        assert client.post(f"{URL}/{owner.id}/hello").status_code == 400

    def test_the_owner_needs_a_mutual_hello_to_message(
        self, client, db, make_user, eligible_with,
    ):
        """Peer messaging is authorised by the mutual connection, which
        the preview does not touch."""
        owner = make_user(role="admin")
        other = eligible_with(owner)
        as_user(owner)
        client.post(f"{URL}/{other.id}/hello")      # one-sided only

        res = client.post("/api/messages/open", json={"user_id": other.id})
        assert res.status_code == 404

    def test_the_owner_can_message_once_mutual(
        self, client, db, make_user, eligible_with,
    ):
        owner = make_user(role="admin")
        other = eligible_with(owner)
        as_user(owner)
        client.post(f"{URL}/{other.id}/hello")
        db.add(MemberHello(
            id=_uid("h"), from_user_id=other.id, to_user_id=owner.id,
        ))
        db.flush()

        res = client.post("/api/messages/open", json={"user_id": other.id})
        assert res.status_code == 200, res.text

    def test_a_block_still_stops_the_owner(
        self, client, db, make_user, eligible_with,
    ):
        """Platform Owner is not exempt from somebody else's boundary."""
        from app.services import member_block_service as blocks

        owner = make_user(role="admin")
        other = eligible_with(owner)
        for frm, to in ((owner, other), (other, owner)):
            db.add(MemberHello(
                id=_uid("h"), from_user_id=frm.id, to_user_id=to.id,
            ))
        db.flush()
        as_user(owner)
        tid = client.post(
            "/api/messages/open", json={"user_id": other.id},
        ).json()["thread_id"]

        blocks.block(db, other.id, owner.id)
        db.flush()

        assert client.post(
            f"/api/messages/{tid}/messages", json={"body": "hello"},
        ).status_code == 404
        assert client.post(f"{URL}/{other.id}/hello").status_code == 404

    def test_the_owner_cannot_read_somebody_elses_conversation(
        self, client, db, make_user, eligible_with,
    ):
        """No impersonation, and no privileged read: the owner sees only
        their own conversations."""
        a, b = make_user(), make_user()
        _named(db, a, "Alice")
        _named(db, b, "Bob")
        for frm, to in ((a, b), (b, a)):
            db.add(MemberHello(
                id=_uid("h"), from_user_id=frm.id, to_user_id=to.id,
            ))
        db.flush()
        as_user(a)
        tid = client.post(
            "/api/messages/open", json={"user_id": b.id},
        ).json()["thread_id"]

        owner = make_user(role="admin")
        as_user(owner)
        assert client.get(f"/api/messages/{tid}").status_code == 404
        assert client.get("/api/messages").json() == []


# ---------------------------------------------------------------------------
# With the flag on
# ---------------------------------------------------------------------------


class TestFlagOn:
    def test_an_ordinary_eligible_member_works_normally(
        self, client, db, make_user, eligible_with, flag_on,
    ):
        member = make_user()
        other = eligible_with(member)
        as_user(member)

        assert client.get(URL).json()["featured_count"] >= 1
        assert client.post(f"{URL}/{other.id}/hello").status_code == 200

    def test_the_owner_has_no_extra_privileges(
        self, client, db, make_user, eligible_with, flag_on,
    ):
        """Same answers as any member: the preview clause is simply
        redundant once the flag is on."""
        owner = make_user(role="admin")
        stranger = make_user()
        _named(db, stranger, "Stranger")
        db.flush()
        as_user(owner)

        assert client.get(URL).json()["featured_count"] == 0
        assert client.post(f"{URL}/{stranger.id}/hello").status_code == 404
