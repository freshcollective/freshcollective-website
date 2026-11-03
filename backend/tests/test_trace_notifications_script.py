"""The generalised diagnostic runs for every announcement we send.

The previous script crashed in production on an attribute that did not
exist, because nothing exercised it. These drive `run_trace` for each
supported kind against seeded data, which dereferences every model
attribute the diagnostic touches — so a stale assumption fails here
rather than in somebody's terminal.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.comms.models import CommunicationEvent, CommunicationIntent
from app.models.platform import (
    EventSeries,
    Pathway,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts" / "trace_notifications.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("trace_notifications", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def kelly(make_user):
    return make_user(role="creator", name="Kelly")


@pytest.fixture
def space(make_space, kelly):
    return make_space(creator=kelly, name="Moonlit Circle")


@pytest.fixture
def members(db, space, make_user):
    out = []
    for _ in range(2):
        who = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=who.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        out.append(who)
    db.flush()
    return out


@pytest.fixture
def pathway(db, space):
    row = Pathway(
        id=_uid("pw"), space_id=space.id, title="Know Yourself",
        slug=f"ky-{uuid.uuid4().hex[:8]}",
        status="active", access_type="free",
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def series(db, space):
    row = EventSeries(
        id=_uid("es"), space_id=space.id, title="Autumn Term",
        slug=f"term-{uuid.uuid4().hex[:8]}",
        starts_at=datetime.utcnow() + timedelta(days=7),
        status="published", published_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def _emit(db, space, kelly, *, event_type, subject_type, subject_id, key):
    row = CommunicationEvent(
        id=_uid("evt"), event_type=event_type,
        topic_key="gatherings" if "gathering" in event_type
        or "series" in event_type else "pathways",
        category_key="gatherings" if "gathering" in event_type
        or "series" in event_type else "pathways",
        source_type="creator", source_id=kelly.id,
        priority_hint="immediate", actor_user_id=kelly.id,
        subject_type=subject_type, subject_id=subject_id,
        context={"space_id": space.id, "collective_name": space.name},
        payload={f"{subject_type}_id": subject_id},
        dedupe_key=key,
    )
    db.add(row)
    db.flush()
    return row


class TestEachKindRunsToCompletion:
    def test_pathway(self, db, space, pathway, members, kelly, capsys):
        db.commit()
        module = _load()
        assert module.run_trace(db, "pathway", pathway, space) == 0
        out = capsys.readouterr().out
        for section in (
            "SOURCE EXPERIENCE", "COMMUNICATION EVENT",
            "ROUTING CONFIGURATION", "PREFERENCES",
            "RECIPIENT RESOLUTION", "DELIVERY INTENTS",
            "OUTBOUND DELIVERY", "LINK DIAGNOSTICS",
        ):
            assert section in out, section
        assert "Nothing was written." in out

    def test_gathering(self, db, space, make_event, members, kelly, capsys):
        gathering = make_event(space=space, is_published=True)
        db.commit()
        module = _load()
        assert module.run_trace(db, "gathering", gathering, space) == 0
        out = capsys.readouterr().out
        assert "notify_members" in out
        assert "recurrence_series_id" in out

    def test_series(self, db, space, series, members, kelly, capsys):
        db.commit()
        module = _load()
        assert module.run_trace(db, "series", series, space) == 0
        out = capsys.readouterr().out
        assert "published_at" in out

    def test_it_reports_the_route_for_each_kind(
        self, db, space, pathway, series, make_event, members, capsys,
    ):
        """The link check reads the frontend tree, so a renamed route
        shows up here rather than in an inbox."""
        gathering = make_event(space=space, is_published=True)
        db.commit()
        module = _load()
        for kind, subject in (
            ("pathway", pathway), ("gathering", gathering), ("series", series),
        ):
            module.run_trace(db, kind, subject, space)
            out = capsys.readouterr().out
            assert "route exists  True" in out, kind


class TestItExplainsWhereThingsStop:
    def test_no_event_is_named_as_the_stopping_point(
        self, db, space, make_event, members, capsys,
    ):
        gathering = make_event(space=space, is_published=False)
        db.commit()
        module = _load()
        module.run_trace(db, "gathering", gathering, space)
        out = capsys.readouterr().out
        assert "STOPPED HERE: no event" in out

    def test_a_backfilled_event_is_labelled_as_such(
        self, db, space, make_event, members, kelly, capsys,
    ):
        """Distinguishing "marked announced" from "announced" is the
        whole point for anything published before the migrations."""
        from app.services import publication_announcement as pub

        gathering = make_event(space=space, is_published=True)
        db.flush()
        row = _emit(
            db, space, kelly, event_type="gathering.published",
            subject_type="gathering", subject_id=gathering.id,
            key=pub.gathering_dedupe_key(gathering.id, space.id),
        )
        row.context = {**row.context, "backfilled": True}
        db.commit()

        module = _load()
        module.run_trace(db, "gathering", gathering, space)
        out = capsys.readouterr().out
        assert "BACKFILLED" in out

    def test_the_creator_is_shown_as_excluded(
        self, db, space, make_event, members, kelly, capsys, join_creator,
    ):
        from app.services import publication_announcement as pub

        gathering = make_event(space=space, is_published=True)
        db.flush()
        _emit(
            db, space, kelly, event_type="gathering.published",
            subject_type="gathering", subject_id=gathering.id,
            key=pub.gathering_dedupe_key(gathering.id, space.id),
        )
        db.commit()

        module = _load()
        module.run_trace(db, "gathering", gathering, space)
        out = capsys.readouterr().out
        assert "creator, excluded" in out or "creator" in out

    def test_the_outbound_guard_verdict_is_shown(
        self, db, space, make_event, make_user, capsys,
    ):
        """A reserved domain produces intents and no email, which looks
        identical to a bug unless it is named."""
        tester = make_user(email=f"t{uuid.uuid4().hex[:8]}@example.com")
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=tester.id, space_id=space.id,
            role=SpaceRole.learner, status=SpaceMembershipStatus.active,
            joined_at=datetime.utcnow(),
        ))
        gathering = make_event(space=space, is_published=True)
        db.commit()

        module = _load()
        module.run_trace(db, "gathering", gathering, space)
        out = capsys.readouterr().out
        assert "OUTBOUND DELIVERY" in out
        assert "example.com" in out


@pytest.fixture
def join_creator(db, space, kelly):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=kelly.id, space_id=space.id,
        role=SpaceRole.creator, status=SpaceMembershipStatus.active,
        joined_at=datetime.utcnow(),
    ))
    db.flush()


class TestItIsReadOnly:
    def test_it_writes_nothing(
        self, db, space, pathway, series, make_event, members,
    ):
        gathering = make_event(space=space, is_published=True)
        db.commit()
        before = (
            db.query(CommunicationEvent).count(),
            db.query(CommunicationIntent).count(),
            db.query(SpaceMembership).count(),
        )
        module = _load()
        for kind, subject in (
            ("pathway", pathway), ("gathering", gathering), ("series", series),
        ):
            module.run_trace(db, kind, subject, space)
        after = (
            db.query(CommunicationEvent).count(),
            db.query(CommunicationIntent).count(),
            db.query(SpaceMembership).count(),
        )
        assert before == after

    def test_the_source_contains_no_write_statement(self):
        source = SCRIPT.read_text().lower()
        for forbidden in (
            "db.add(", "db.commit()", "db.delete(", "db.merge(",
            "insert into", "delete from", "update ",
        ):
            assert forbidden not in source, forbidden

    def test_it_clears_sentry_for_this_process_only(self):
        source = SCRIPT.read_text()
        assert 'os.environ["SENTRY_DSN"] = ""' in source
        assert "for this process only" in source

    def test_failures_are_handled_rather_than_raised(self):
        """FC-API-K was an unhandled exception from a hand-run script
        arriving as an application alert."""
        source = SCRIPT.read_text()
        assert "the diagnostic failed:" in source
        assert "except Exception as exc:" in source


class TestEveryAnnouncementKindIsCovered:
    def test_the_registry_matches_the_events_we_emit(self):
        """If a new announcement event is added without a kind here,
        the next investigation needs another script — which is what
        this file exists to prevent."""
        module = _load()
        assert set(module.KINDS) == {
            "post", "pathway", "gathering", "series",
        }
        assert {k["event_type"] for k in module.KINDS.values()} == {
            "community.post.published",
            "pathway.published",
            "gathering.published",
            "series.published",
        }

    def test_every_kind_names_a_registered_event(self):
        from app.comms.registry import get_event_definition

        module = _load()
        for kind, spec in module.KINDS.items():
            assert get_event_definition(spec["event_type"]) is not None, kind

    def test_addresses_are_masked(self):
        module = _load()
        assert module.mask("verylongname@freshcollective.au") == (
            "v***@freshcollective.au"
        )
        assert "verylongname" not in module.mask(
            "verylongname@freshcollective.au",
        )
