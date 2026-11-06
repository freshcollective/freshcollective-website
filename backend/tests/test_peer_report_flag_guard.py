"""Peer reporting is closed while Community Care is closed.

The gap
-------
``POST /api/messages/{thread_id}/report`` was the one Community Care
intake path without ``ensure_flag_on()``. All sixteen other Community
Care routes have it; this one, added later in a different module with
the Ways to Connect work, did not.

The consequence was not a 500 or a crash. It was worse in a quieter
way: with ``COMMUNITY_CARE_ENABLED=false`` a member could report
somebody from a conversation, receive a ``CC-YYYY-NNNN`` case number
implying their report was tracked, and have a real case written — while
every admin review endpoint answered 503, so nobody could open it.
Accepting a report is a promise to look at it. The promise now gets
refused honestly instead of kept on paper.

What these tests pin is that refusing costs nothing and leaves nothing
behind, that blocking — the control that actually protects somebody
right now — is completely unaffected, and that the original workflow
still works the moment the flag is on.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import get_current_user, get_verified_current_user
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.community_care import (
    CommunityCareCase,
    CommunityCareCaseEvent,
    CommunityCareReport,
)
from app.models.member_blocks import MemberBlock
from app.models.notification import Notification
from app.models.peer_messages import PeerMessage

MSG = "/api/messages"


# ---------------------------------------------------------------------------
# Harness — the same shape ``test_member_blocks_and_reports`` uses, so a
# behavioural difference here is a real one and not a fixture artefact.
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_verified_current_user] = lambda: user


def _uid(prefix: str) -> str:
    import uuid

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _named(db, user, name):
    from app.models.platform import CreatorProfile

    db.add(CreatorProfile(user_id=user.id, display_name=name, is_public=True))
    db.flush()


@pytest.fixture
def connected(db, make_user):
    """Two members with a mutual hello, which is what permits a thread.

    Same construction as ``test_member_blocks_and_reports`` so a
    behavioural difference here is a real one rather than a fixture
    artefact.
    """
    def _go(name_a="Alice", name_b="Bob"):
        a, b = make_user(), make_user()
        _named(db, a, name_a)
        _named(db, b, name_b)
        from app.models.connections import MemberHello

        for frm, to in ((a, b), (b, a)):
            db.add(MemberHello(
                id=_uid("h"), from_user_id=frm.id, to_user_id=to.id,
            ))
        db.flush()
        return a, b

    return _go


def _thread(client, a, b) -> str:
    as_user(a)
    res = client.post(f"{MSG}/open", json={"user_id": b.id})
    assert res.status_code in (200, 201), res.text
    return res.json()["thread_id"]


def _send(client, tid, body="something upsetting"):
    res = client.post(f"{MSG}/{tid}/messages", json={"body": body})
    assert res.status_code in (200, 201), res.text


def _report(client, tid, **over):
    payload = {"category": "harassment_or_bullying", **over}
    return client.post(f"{MSG}/{tid}/report", json=payload)


@pytest.fixture
def care_off(monkeypatch):
    monkeypatch.setattr(settings, "community_care_enabled", False)


@pytest.fixture
def care_on(monkeypatch):
    monkeypatch.setattr(settings, "community_care_enabled", True)


@pytest.fixture
def conversation(client, connected):
    a, b = connected()
    tid = _thread(client, a, b)
    as_user(a)
    _send(client, tid)
    return a, b, tid


# ---------------------------------------------------------------------------
# 1. Disabled — the refusal
# ---------------------------------------------------------------------------


class TestWhileCommunityCareIsDisabled:
    def test_the_report_is_refused(self, client, conversation, care_off):
        _a, _b, tid = conversation
        res = _report(client, tid)
        assert res.status_code == 503, res.text

    def test_it_is_the_same_guard_every_other_route_uses(
        self, client, conversation, care_off,
    ):
        """Not a second flag and not a second message — the shared
        ``ensure_flag_on`` detail, so there is one rule to change when
        the feature is enabled."""
        from app.community_care.shared import ensure_flag_on
        from fastapi import HTTPException

        _a, _b, tid = conversation
        res = _report(client, tid)

        with pytest.raises(HTTPException) as expected:
            ensure_flag_on()
        assert res.json()["detail"] == expected.value.detail
        assert res.status_code == expected.value.status_code

    def test_no_case_is_written(self, client, db, conversation, care_off):
        _a, _b, tid = conversation
        before = db.query(CommunityCareCase).count()
        _report(client, tid)
        db.expire_all()
        assert db.query(CommunityCareCase).count() == before

    def test_no_report_row_is_written(self, client, db, conversation, care_off):
        _a, _b, tid = conversation
        before = db.query(CommunityCareReport).count()
        _report(client, tid)
        db.expire_all()
        assert db.query(CommunityCareReport).count() == before

    def test_no_case_event_is_written(self, client, db, conversation, care_off):
        """The audit trail must not record an intake that did not
        happen."""
        _a, _b, tid = conversation
        before = db.query(CommunityCareCaseEvent).count()
        _report(client, tid)
        db.expire_all()
        assert db.query(CommunityCareCaseEvent).count() == before

    def test_no_case_number_is_allocated(self, client, db, conversation, care_off):
        """Case numbers are allocated by counting existing rows for the
        year, so a wasted allocation would show up as a gap in the
        sequence later. Nothing is handed back to the member either."""
        _a, _b, tid = conversation
        res = _report(client, tid)
        assert "case_number" not in res.text
        db.expire_all()
        assert db.query(CommunityCareCase).count() == 0

    def test_no_notification_is_triggered(self, client, db, conversation, care_off):
        _a, _b, tid = conversation
        before = db.query(Notification).count()
        _report(client, tid)
        db.expire_all()
        assert db.query(Notification).count() == before

    def test_it_refuses_before_looking_at_anything(
        self, client, db, conversation, care_off,
    ):
        """The guard is the first statement in the body, ahead of thread
        lookup, category validation and the snapshot. Asserted through
        an invalid category: with the guard first that is a 503, and if
        validation ran first it would be a 422. The distinction matters
        because the snapshot copies up to thirty private messages, and
        a refusal must not read them."""
        _a, _b, tid = conversation
        res = _report(client, tid, category="not_a_real_category")
        assert res.status_code == 503, res.text

    def test_repeated_attempts_leave_nothing_behind(
        self, client, db, conversation, care_off,
    ):
        _a, _b, tid = conversation
        for _ in range(5):
            assert _report(client, tid).status_code == 503
        db.expire_all()
        assert db.query(CommunityCareCase).count() == 0
        assert db.query(CommunityCareReport).count() == 0


# ---------------------------------------------------------------------------
# 2. Disabled — what still works
# ---------------------------------------------------------------------------


class TestBlockingIsUnaffected:
    """Blocking is the control that protects somebody *now*. It has
    nothing to do with Community Care and must not be touched by any of
    this."""

    def test_a_member_can_still_block(self, client, db, conversation, care_off):
        a, b, tid = conversation
        as_user(a)
        res = client.post(f"{MSG}/{tid}/block")
        assert res.status_code in (200, 201, 204), res.text
        db.expire_all()
        assert db.query(MemberBlock).filter(
            MemberBlock.blocker_user_id == a.id,
            MemberBlock.blocked_user_id == b.id,
        ).count() == 1

    def test_the_block_still_stops_messaging(
        self, client, db, connected, care_off,
    ):
        """404 rather than 403, deliberately: the blocked person is
        never told they were blocked, so the conversation simply stops
        existing for them. Mirrors
        ``test_the_blocked_person_cannot_send``."""
        a, b = connected()
        tid = _thread(client, a, b)
        as_user(a)
        client.post(f"{MSG}/{tid}/block")
        db.expire_all()

        as_user(b)
        res = client.post(f"{MSG}/{tid}/messages", json={"body": "hello?"})
        assert res.status_code == 404, res.text

    def test_a_member_can_still_unblock(self, client, db, conversation, care_off):
        a, _b, tid = conversation
        as_user(a)
        client.post(f"{MSG}/{tid}/block")
        res = client.delete(f"{MSG}/{tid}/block")
        assert res.status_code in (200, 204), res.text

    def test_blocking_without_reporting_is_still_possible(
        self, client, db, conversation, care_off,
    ):
        """The two were always independent. Closing reporting must not
        make blocking conditional on it."""
        a, _b, tid = conversation
        as_user(a)
        assert client.post(f"{MSG}/{tid}/block").status_code in (200, 201, 204)
        assert _report(client, tid).status_code == 503


class TestTheRestOfMessagingIsUnaffected:
    def test_reading_a_thread_still_works(self, client, conversation, care_off):
        _a, _b, tid = conversation
        res = client.get(f"{MSG}/{tid}")
        assert res.status_code == 200, res.text
        assert res.json()["messages"]

    def test_sending_still_works(self, client, db, conversation, care_off):
        _a, _b, tid = conversation
        before = db.query(PeerMessage).count()
        res = client.post(f"{MSG}/{tid}/messages", json={"body": "still talking"})
        assert res.status_code in (200, 201), res.text
        db.expire_all()
        assert db.query(PeerMessage).count() == before + 1

    def test_opening_a_new_thread_still_works(self, client, connected, care_off):
        a, b = connected()
        assert _thread(client, a, b)

    def test_the_thread_says_reporting_is_unavailable(
        self, client, conversation, care_off,
    ):
        """The client is told, rather than left to discover it by
        submitting a form. The backend answers because the backend flag
        is the only thing that decides it."""
        _a, _b, tid = conversation
        body = client.get(f"{MSG}/{tid}").json()
        assert body["can_report"] is False
        # And the controls that do work are still advertised.
        assert body["can_send"] is True
        assert body["blocked_by_me"] is False


# ---------------------------------------------------------------------------
# 3. Enabled — the designed workflow, unchanged
# ---------------------------------------------------------------------------


class TestWhenCommunityCareIsEnabled:
    def test_a_report_works_as_designed(self, client, db, conversation, care_on):
        _a, _b, tid = conversation
        res = _report(client, tid)
        assert res.status_code == 201, res.text
        assert res.json()["case_number"]
        db.expire_all()
        assert db.query(CommunityCareCase).count() == 1
        assert db.query(CommunityCareReport).count() == 1

    def test_the_thread_says_reporting_is_available(
        self, client, conversation, care_on,
    ):
        _a, _b, tid = conversation
        assert client.get(f"{MSG}/{tid}").json()["can_report"] is True

    def test_validation_still_applies(self, client, conversation, care_on):
        """With the flag on, an unknown category is a 422 again — which
        is what proves the 503 above was the guard and not validation
        happening to fire first."""
        _a, _b, tid = conversation
        assert _report(
            client, tid, category="not_a_real_category",
        ).status_code == 422

    def test_something_else_still_requires_an_explanation(
        self, client, conversation, care_on,
    ):
        _a, _b, tid = conversation
        assert _report(client, tid, category="something_else").status_code == 422

    def test_a_non_participant_is_still_refused(
        self, client, db, connected, make_user, care_on,
    ):
        """Permissions are unchanged by the guard — and an outsider gets
        404, not 503, because who may report is a different question
        from whether reporting is open."""
        a, b = connected()
        tid = _thread(client, a, b)
        outsider = make_user(role="user")
        as_user(outsider)
        assert _report(client, tid).status_code == 404

    def test_two_reports_still_share_one_case(
        self, client, db, conversation, care_on,
    ):
        _a, _b, tid = conversation
        first = _report(client, tid, category="spam_or_scam")
        second = _report(client, tid, category="unsafe_behaviour")
        assert first.status_code == 201
        assert second.status_code == 201
        db.expire_all()
        assert db.query(CommunityCareCase).count() == 1
        assert db.query(CommunityCareReport).count() == 2


# ---------------------------------------------------------------------------
# 4. The guard is not missing anywhere else
# ---------------------------------------------------------------------------


class TestEveryIntakeIsGuarded:
    def test_no_community_care_write_path_is_left_unguarded(self):
        """This defect was one route in a different module forgetting a
        guard the rest of the system applies. Asserted on the AST so a
        future intake added somewhere new has to be noticed.

        The rule: a module that writes a ``CommunityCareCase`` or
        ``CommunityCareReport`` must also reference ``ensure_flag_on``,
        either directly or through the route that calls into it.
        """
        import ast
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1] / "app"
        offenders = []
        for path in root.rglob("*.py"):
            src = path.read_text()
            tree = ast.parse(src)
            writes = any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id in {"CommunityCareCase", "CommunityCareReport"}
                for n in ast.walk(tree)
            )
            if not writes:
                continue
            rel = path.relative_to(root).as_posix()
            # ``peer_reports`` is a helper: its guard lives on the route
            # that calls it, which this suite verifies behaviourally
            # above.
            guarded = "ensure_flag_on" in src or rel in {
                "community_care/peer_reports.py",
            }
            if not guarded:
                offenders.append(rel)
        assert offenders == [], (
            f"these modules create Community Care rows with no flag "
            f"guard: {offenders}"
        )

    def test_the_peer_route_itself_references_the_guard(self):
        import pathlib

        route = (
            pathlib.Path(__file__).resolve().parents[1]
            / "app" / "peer_messages" / "routes.py"
        )
        src = route.read_text()
        assert "ensure_flag_on()" in src
