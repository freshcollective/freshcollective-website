"""The themes change, exercised through the route the UI actually calls.

BI-1 shipped with the producer tested directly but not through
``PATCH /api/creator/spaces/{slug}`` — which is the only path that writes
``spaces.themes``, and the one Creator Studio's settings form uses. A
production theme change then produced no event, so this file closes that
gap: the six properties below are asserted against the real HTTP route,
not against the producer in isolation.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import app.models.community_care  # noqa: F401
from app.auth.dependencies import (
    get_creator_user,
    get_current_user,
    get_verified_creator_user,
    get_verified_current_user,
)
from app.core.database import get_db
from app.main import app
from app.models.business_event import BusinessEvent
from app.models.platform import SpaceMembership, SpaceMembershipStatus, SpaceRole

URL = "/api/creator/spaces/{slug}"


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(user):
    for dep in (
        get_current_user, get_verified_current_user,
        get_creator_user, get_verified_creator_user,
    ):
        app.dependency_overrides[dep] = lambda u=user: u


@pytest.fixture
def owned(db, make_user, make_space):
    creator = make_user(role="creator")
    space = make_space(creator=creator, themes=["Wellbeing"])
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=creator.id, space_id=space.id,
        role=SpaceRole.creator, status=SpaceMembershipStatus.active,
    ))
    db.commit()
    as_user(creator)
    return space, creator


def theme_events(db, space):
    return (
        db.query(BusinessEvent)
        .filter(
            BusinessEvent.event_type == "collective.themes_changed",
            BusinessEvent.subject_id == space.id,
        )
        .order_by(BusinessEvent.sequence_number)
        .all()
    )


class TestThemesChangeThroughTheRoute:
    def test_a_real_change_records_exactly_one_event(self, client, db, owned):
        space, _creator = owned
        res = client.patch(
            URL.format(slug=space.slug), json={"themes": ["Wellbeing", "Movement"]},
        )
        assert res.status_code == 200, res.text
        assert len(theme_events(db, space)) == 1

    def test_the_event_names_the_right_collective(self, client, db, owned):
        space, creator = owned
        client.patch(URL.format(slug=space.slug), json={"themes": ["Movement"]})
        [e] = theme_events(db, space)
        assert e.space_id == space.id
        assert e.creator_user_id == creator.id

    def test_the_payload_carries_before_and_after(self, client, db, owned):
        space, _creator = owned
        client.patch(
            URL.format(slug=space.slug), json={"themes": ["Movement", "Creativity"]},
        )
        [e] = theme_events(db, space)
        assert e.payload["from_themes"] == ["Wellbeing"]
        assert e.payload["to_themes"] == ["Movement", "Creativity"]
        assert e.payload["added"] == ["Creativity", "Movement"]
        assert e.payload["removed"] == ["Wellbeing"]

    def test_the_event_is_committed_not_merely_flushed(self, client, db, owned):
        """The route commits; the event must be inside that commit."""
        space, _creator = owned
        client.patch(URL.format(slug=space.slug), json={"themes": ["Movement"]})
        db.expire_all()
        assert len(theme_events(db, space)) == 1
        db.refresh(space)
        assert space.themes == ["Movement"]

    def test_saving_without_a_real_change_records_nothing(self, client, db, owned):
        """Resubmitting the same selection is not a business event.

        This is the behaviour to be sure of before concluding anything
        from an empty table: a save that changes nothing correctly
        produces no row.
        """
        space, _creator = owned
        res = client.patch(
            URL.format(slug=space.slug), json={"themes": ["Wellbeing"]},
        )
        assert res.status_code == 200, res.text
        assert theme_events(db, space) == []

    def test_omitting_themes_entirely_records_nothing(self, client, db, owned):
        """Saving another field must not fabricate a theme change."""
        space, _creator = owned
        res = client.patch(URL.format(slug=space.slug), json={"tagline": "Hello"})
        assert res.status_code == 200, res.text
        assert theme_events(db, space) == []

    def test_repeated_real_changes_record_distinct_events(self, client, db, owned):
        space, _creator = owned
        client.patch(URL.format(slug=space.slug), json={"themes": ["Movement"]})
        client.patch(URL.format(slug=space.slug), json={"themes": ["Creativity"]})
        client.patch(URL.format(slug=space.slug), json={"themes": ["Leadership"]})
        got = theme_events(db, space)
        assert len(got) == 3
        assert len({e.dedupe_key for e in got}) == 3
        assert [e.payload["to_themes"] for e in got] == [
            ["Movement"], ["Creativity"], ["Leadership"],
        ]

    def test_clearing_every_theme_is_a_change(self, client, db, owned):
        space, _creator = owned
        client.patch(URL.format(slug=space.slug), json={"themes": []})
        [e] = theme_events(db, space)
        assert e.payload["to_themes"] == []
        assert e.payload["removed"] == ["Wellbeing"]

    def test_a_collective_starting_with_no_themes_still_records(
        self, client, db, make_user, make_space,
    ):
        """``themes`` is nullable, and NULL → something is a change."""
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        space.themes = None
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=creator.id, space_id=space.id,
            role=SpaceRole.creator, status=SpaceMembershipStatus.active,
        ))
        db.commit()
        as_user(creator)
        client.patch(URL.format(slug=space.slug), json={"themes": ["Wellbeing"]})
        [e] = theme_events(db, space)
        assert e.payload["from_themes"] == []
        assert e.payload["to_themes"] == ["Wellbeing"]


class TestPublicationThroughTheRoute:
    def test_publishing_a_draft_records_the_event_and_the_date(
        self, client, db, make_user, make_space,
    ):
        """The other lifecycle transition this route owns."""
        creator = make_user(role="creator")
        space = make_space(creator=creator, status="draft")
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=creator.id, space_id=space.id,
            role=SpaceRole.creator, status=SpaceMembershipStatus.active,
        ))
        db.commit()
        as_user(creator)

        res = client.patch(URL.format(slug=space.slug), json={"status": "active"})
        assert res.status_code == 200, res.text
        rows = (
            db.query(BusinessEvent)
            .filter(
                BusinessEvent.subject_id == space.id,
                BusinessEvent.event_type == "collective.published",
            )
            .all()
        )
        assert len(rows) == 1
        db.refresh(space)
        assert space.first_published_at is not None

    def test_resaving_an_active_collective_records_nothing(
        self, client, db, owned,
    ):
        space, _creator = owned
        res = client.patch(URL.format(slug=space.slug), json={"status": "active"})
        assert res.status_code == 200, res.text
        assert (
            db.query(BusinessEvent)
            .filter(BusinessEvent.subject_id == space.id)
            .count() == 0
        )


class TestTheRealFrontendPayload:
    """The exact body ``CollectiveSettingsForm`` sends.

    The minimal ``{"themes": [...]}`` test above is not what production
    sends: the settings form submits name, slug, tagline, description,
    about_content, themes, and — for creator-managed Collectives —
    is_public, status and the whole pricing block, every time. A defect
    that only appears with the full payload would be invisible to the
    minimal test, so this class drives the real shape.

    Themes are pre-populated with Moonlit Circle's production values so
    the comparison starts from a realistic non-empty list.
    """

    MOONLIT = ["Inner Work", "Spirituality", "Reflection"]

    def _body(self, space, themes):
        """What the form sends for a creator-managed Collective."""
        return {
            "name": space.name,
            "slug": space.slug,
            "tagline": space.tagline,
            "description": space.description,
            "about_content": space.about_content,
            "themes": themes,
            "is_public": space.is_public,
            "status": getattr(space.status, "value", space.status),
            "pricing_type": space.pricing_type,
            "pricing_amount_cents": space.pricing_amount_cents,
            "pricing_currency": "AUD",
            "pricing_note": space.pricing_note,
            "has_paid_internal_content": space.has_paid_internal_content,
            "included_access_summary": space.included_access_summary,
            "paid_content_summary": space.paid_content_summary,
        }

    @pytest.fixture
    def moonlit(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator, themes=list(self.MOONLIT))
        db.add(SpaceMembership(
            id=_uid("sm"), user_id=creator.id, space_id=space.id,
            role=SpaceRole.creator, status=SpaceMembershipStatus.active,
        ))
        db.commit()
        as_user(creator)
        return space

    def test_adding_a_theme(self, client, db, moonlit):
        body = self._body(moonlit, self.MOONLIT + ["Movement"])
        res = client.patch(URL.format(slug=moonlit.slug), json=body)
        assert res.status_code == 200, res.text
        [e] = theme_events(db, moonlit)
        assert e.payload["added"] == ["Movement"]
        assert e.payload["removed"] == []

    def test_removing_a_theme(self, client, db, moonlit):
        body = self._body(moonlit, ["Inner Work", "Spirituality"])
        res = client.patch(URL.format(slug=moonlit.slug), json=body)
        assert res.status_code == 200, res.text
        [e] = theme_events(db, moonlit)
        assert e.payload["removed"] == ["Reflection"]
        assert e.payload["added"] == []

    def test_replacing_one_theme_with_another(self, client, db, moonlit):
        body = self._body(moonlit, ["Inner Work", "Spirituality", "Creativity"])
        res = client.patch(URL.format(slug=moonlit.slug), json=body)
        assert res.status_code == 200, res.text
        [e] = theme_events(db, moonlit)
        assert e.payload["added"] == ["Creativity"]
        assert e.payload["removed"] == ["Reflection"]

    def test_saving_unchanged_themes_records_nothing(self, client, db, moonlit):
        """The one silent path in the whole route.

        If production's save was not a net change, this is exactly what
        happened — and it is correct behaviour, not a defect.
        """
        body = self._body(moonlit, list(self.MOONLIT))
        res = client.patch(URL.format(slug=moonlit.slug), json=body)
        assert res.status_code == 200, res.text
        assert theme_events(db, moonlit) == []

    def test_reordering_the_same_set_records_nothing(self, client, db, moonlit):
        """Order is click order, not meaning.

        The comparison is set-based, so re-saving the same selection in a
        different order is not a recategorisation. Recording it would put
        an event with empty ``added`` and ``removed`` into any report
        counting category changes.
        """
        body = self._body(moonlit, ["Reflection", "Inner Work", "Spirituality"])
        res = client.patch(URL.format(slug=moonlit.slug), json=body)
        assert res.status_code == 200, res.text
        assert theme_events(db, moonlit) == []
        # The new order is still saved — only the event is suppressed.
        db.refresh(moonlit)
        assert set(moonlit.themes) == set(self.MOONLIT)

    def test_a_reorder_that_also_adds_still_records(self, client, db, moonlit):
        """Set comparison must not swallow a real change made alongside
        a reorder."""
        body = self._body(
            moonlit, ["Reflection", "Movement", "Inner Work", "Spirituality"],
        )
        res = client.patch(URL.format(slug=moonlit.slug), json=body)
        assert res.status_code == 200, res.text
        [e] = theme_events(db, moonlit)
        assert e.payload["added"] == ["Movement"]
        assert e.payload["removed"] == []

    def test_changing_another_setting_only_records_nothing(
        self, client, db, moonlit,
    ):
        """Saving the tagline, with themes resubmitted unchanged."""
        body = self._body(moonlit, list(self.MOONLIT))
        body["tagline"] = "A new tagline"
        res = client.patch(URL.format(slug=moonlit.slug), json=body)
        assert res.status_code == 200, res.text
        assert theme_events(db, moonlit) == []
        db.refresh(moonlit)
        assert moonlit.tagline == "A new tagline"
        # The row was updated even though no event was recorded — which
        # is exactly the production observation.
        assert moonlit.themes == self.MOONLIT

    def test_the_full_payload_still_commits_the_event(self, client, db, moonlit):
        """Guards against the full shape breaking the commit."""
        body = self._body(moonlit, self.MOONLIT + ["Movement"])
        res = client.patch(URL.format(slug=moonlit.slug), json=body)
        assert res.status_code == 200, res.text
        db.expire_all()
        assert len(theme_events(db, moonlit)) == 1
