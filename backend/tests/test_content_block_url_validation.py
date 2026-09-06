"""SEC-016-1 — route-level URL validation for content-block sinks.

Every write path that stores ``embed_url`` on a block whose renderer
puts the URL inside ``<a href>`` (link, video_embed) or ``<img src>``
(image) must apply the shared ``content_url`` validators. This test
locks that behaviour across:

  * ``create_step_block`` / ``update_step_block``
    (PathwayStepBlock — Guided Experience + Knowledge Guide steps)
  * ``create_about_block`` / ``update_about_block``
    (PathwayAboutBlock — pathway About pages)
  * ``create_event_about_block`` / ``update_event_about_block``
    (event-scoped About blocks — polymorphic owner_kind='event')
  * ``create_series_about_block`` / ``update_series_about_block``
    (series-scoped About blocks — polymorphic owner_kind='event_series')

Hostile-payload matrix intentionally covers scheme casing and
whitespace tricks that a naive ``startswith`` check would let through.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.creator._event_about_routes import (
    create_event_about_block,
    update_event_about_block,
)
from app.creator._gathering_series_routes import (
    create_series_about_block,
    update_series_about_block,
)
from app.creator.routes import (
    create_about_block,
    create_step_block,
    update_about_block,
    update_step_block,
)
from app.creator.schemas import (
    AboutBlockCreateRequest,
    AboutBlockUpdateRequest,
    StepBlockCreateRequest,
    StepBlockUpdateRequest,
)
from app.models.platform import (
    Event,
    EventSeries,
    Pathway,
    PathwayStep,
    PathwayType,
    StepContentType,
)


# ---------------------------------------------------------------------------
# Payload matrix
# ---------------------------------------------------------------------------

HOSTILE_URLS: list[str] = [
    "javascript:alert(1)",
    "JavaScript:alert(1)",
    "JAVASCRIPT:alert(1)",
    "  javascript:alert(1)  ",
    "\tjavascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(\"xss\")",
    "file:///etc/passwd",
    "blob:https://evil/xxx",
    "ftp://evil.example.com",
    "//evil.example.com/x",     # protocol-relative
    "  //evil.example.com/x",   # protocol-relative with whitespace
]


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _pathway_and_step(db: Session, space) -> PathwayStep:
    p = Pathway(
        id=_uid("pw"),
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="p",
        status="active",
        pathway_type=PathwayType.guided_experience,
    )
    db.add(p)
    db.flush()
    s = PathwayStep(
        id=_uid("pst"),
        pathway_id=p.id,
        slug=f"step-{uuid.uuid4().hex[:8]}",
        title="s",
        position=0,
        content_type=StepContentType.text,
    )
    db.add(s)
    db.flush()
    return s


def _pathway(db: Session, space) -> Pathway:
    p = Pathway(
        id=_uid("pw"),
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title="p",
        status="active",
        pathway_type=PathwayType.guided_experience,
    )
    db.add(p)
    db.flush()
    return p


def _event(db: Session, space) -> Event:
    ev = Event(
        id=_uid("ev"),
        space_id=space.id,
        created_by_id=space.creator_id,
        title="Session",
        starts_at=datetime.utcnow() + timedelta(days=7),
        ends_at=datetime.utcnow() + timedelta(days=7, hours=1),
        location_type="zoom",
        is_published=True,
        status="active",
        requires_booking=False,
        capacity=20,
        booking_access_type="included_with_collective",
        gathering_type="workshop",
        attendance_format="online",
    )
    db.add(ev)
    db.flush()
    return ev


def _series(db: Session, space) -> EventSeries:
    s = EventSeries(
        id=_uid("es"),
        space_id=space.id,
        slug=f"es-{uuid.uuid4().hex[:8]}",
        title="Series",
        starts_at=datetime.utcnow() + timedelta(days=7),
        ends_at=datetime.utcnow() + timedelta(days=30),
        status="published",
    )
    db.add(s)
    db.flush()
    return s


# ---------------------------------------------------------------------------
# PathwayStepBlock — create
# ---------------------------------------------------------------------------


class TestStepBlockCreate:
    @pytest.mark.parametrize("kind", ["link", "video_embed"])
    @pytest.mark.parametrize("bad", HOSTILE_URLS)
    def test_hostile_nav_url_rejected_on_create(
        self, db, make_user, make_space, kind, bad,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        step = _pathway_and_step(db, space)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_step_block(
                slug=space.slug,
                pathway_slug=step.pathway.slug,
                step_slug=step.slug,
                body=StepBlockCreateRequest(
                    block_type=kind, embed_url=bad,
                ),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400

    @pytest.mark.parametrize("bad", HOSTILE_URLS + ["mailto:hi@example.com"])
    def test_hostile_media_url_rejected_on_image_create(
        self, db, make_user, make_space, bad,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        step = _pathway_and_step(db, space)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_step_block(
                slug=space.slug,
                pathway_slug=step.pathway.slug,
                step_slug=step.slug,
                body=StepBlockCreateRequest(
                    block_type="image", embed_url=bad,
                ),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400

    def test_safe_nav_url_accepted_on_create(self, db, make_user, make_space):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        step = _pathway_and_step(db, space)
        db.commit()

        block = create_step_block(
            slug=space.slug,
            pathway_slug=step.pathway.slug,
            step_slug=step.slug,
            body=StepBlockCreateRequest(
                block_type="link", embed_url="https://example.com/x",
            ),
            db=db, current_user=creator,
        )
        assert block.embed_url == "https://example.com/x"

    def test_mailto_allowed_on_link_but_not_image(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        step = _pathway_and_step(db, space)
        db.commit()

        link = create_step_block(
            slug=space.slug,
            pathway_slug=step.pathway.slug,
            step_slug=step.slug,
            body=StepBlockCreateRequest(
                block_type="link", embed_url="mailto:hi@example.com",
            ),
            db=db, current_user=creator,
        )
        assert link.embed_url == "mailto:hi@example.com"

        with pytest.raises(HTTPException) as exc:
            create_step_block(
                slug=space.slug,
                pathway_slug=step.pathway.slug,
                step_slug=step.slug,
                body=StepBlockCreateRequest(
                    block_type="image", embed_url="mailto:hi@example.com",
                ),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# PathwayStepBlock — patch
# ---------------------------------------------------------------------------


class TestStepBlockUpdate:
    @pytest.mark.parametrize("kind", ["link", "video_embed"])
    @pytest.mark.parametrize("bad", HOSTILE_URLS)
    def test_hostile_nav_url_rejected_on_patch(
        self, db, make_user, make_space, kind, bad,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        step = _pathway_and_step(db, space)
        db.commit()

        # Start with a benign URL, patch to hostile — must be refused.
        block = create_step_block(
            slug=space.slug,
            pathway_slug=step.pathway.slug,
            step_slug=step.slug,
            body=StepBlockCreateRequest(
                block_type=kind, embed_url="https://example.com/x",
            ),
            db=db, current_user=creator,
        )
        with pytest.raises(HTTPException) as exc:
            update_step_block(
                slug=space.slug,
                pathway_slug=step.pathway.slug,
                step_slug=step.slug,
                block_id=block.id,
                body=StepBlockUpdateRequest(embed_url=bad),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400

    def test_hostile_media_url_rejected_on_image_patch(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        step = _pathway_and_step(db, space)
        db.commit()

        block = create_step_block(
            slug=space.slug,
            pathway_slug=step.pathway.slug,
            step_slug=step.slug,
            body=StepBlockCreateRequest(
                block_type="image", embed_url="https://example.com/x.jpg",
            ),
            db=db, current_user=creator,
        )
        with pytest.raises(HTTPException) as exc:
            update_step_block(
                slug=space.slug,
                pathway_slug=step.pathway.slug,
                step_slug=step.slug,
                block_id=block.id,
                body=StepBlockUpdateRequest(embed_url="javascript:alert(1)"),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400

    def test_clearing_url_via_patch_is_allowed(self, db, make_user, make_space):
        # Existing behaviour — creators can save a stub block with no URL.
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        step = _pathway_and_step(db, space)
        db.commit()

        block = create_step_block(
            slug=space.slug,
            pathway_slug=step.pathway.slug,
            step_slug=step.slug,
            body=StepBlockCreateRequest(
                block_type="link", embed_url="https://example.com",
            ),
            db=db, current_user=creator,
        )
        updated = update_step_block(
            slug=space.slug,
            pathway_slug=step.pathway.slug,
            step_slug=step.slug,
            block_id=block.id,
            body=StepBlockUpdateRequest(embed_url=""),
            db=db, current_user=creator,
        )
        assert updated.embed_url == ""


# ---------------------------------------------------------------------------
# PathwayAboutBlock — pathway About page
# ---------------------------------------------------------------------------


class TestPathwayAboutBlock:
    @pytest.mark.parametrize("kind", ["link", "video_embed"])
    @pytest.mark.parametrize("bad", HOSTILE_URLS)
    def test_hostile_nav_url_rejected_on_create(
        self, db, make_user, make_space, kind, bad,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_about_block(
                slug=space.slug,
                pathway_slug=pathway.slug,
                body=AboutBlockCreateRequest(block_type=kind, embed_url=bad),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400

    def test_hostile_image_url_rejected_on_create(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_about_block(
                slug=space.slug,
                pathway_slug=pathway.slug,
                body=AboutBlockCreateRequest(
                    block_type="image", embed_url="javascript:alert(1)",
                ),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400

    def test_hostile_nav_url_rejected_on_patch(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        pathway = _pathway(db, space)
        db.commit()

        block = create_about_block(
            slug=space.slug,
            pathway_slug=pathway.slug,
            body=AboutBlockCreateRequest(
                block_type="link", embed_url="https://example.com",
            ),
            db=db, current_user=creator,
        )
        with pytest.raises(HTTPException) as exc:
            update_about_block(
                slug=space.slug,
                pathway_slug=pathway.slug,
                block_id=block.id,
                body=AboutBlockUpdateRequest(embed_url="JavaScript:alert(1)"),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Event-scoped About blocks
# ---------------------------------------------------------------------------


class TestEventAboutBlock:
    @pytest.mark.parametrize("kind", ["link", "video_embed"])
    def test_hostile_nav_url_rejected_on_create(
        self, db, make_user, make_space, kind,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = _event(db, space)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_event_about_block(
                slug=space.slug,
                event_id=event.id,
                body=AboutBlockCreateRequest(
                    block_type=kind, embed_url="javascript:alert(1)",
                ),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400

    def test_hostile_image_url_rejected_on_create(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = _event(db, space)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_event_about_block(
                slug=space.slug,
                event_id=event.id,
                body=AboutBlockCreateRequest(
                    block_type="image", embed_url="data:text/html,x",
                ),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400

    def test_hostile_nav_url_rejected_on_patch(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        event = _event(db, space)
        db.commit()

        block = create_event_about_block(
            slug=space.slug,
            event_id=event.id,
            body=AboutBlockCreateRequest(
                block_type="link", embed_url="https://example.com",
            ),
            db=db, current_user=creator,
        )
        with pytest.raises(HTTPException) as exc:
            update_event_about_block(
                slug=space.slug,
                event_id=event.id,
                block_id=block.id,
                body=AboutBlockUpdateRequest(embed_url="//evil.example.com/x"),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Series-scoped About blocks
# ---------------------------------------------------------------------------


class TestSeriesAboutBlock:
    @pytest.mark.parametrize("kind", ["link", "video_embed"])
    def test_hostile_nav_url_rejected_on_create(
        self, db, make_user, make_space, kind,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        series = _series(db, space)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_series_about_block(
                slug=space.slug,
                series_slug=series.slug,
                body=AboutBlockCreateRequest(
                    block_type=kind, embed_url="javascript:alert(1)",
                ),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400

    def test_hostile_image_url_rejected_on_create(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        series = _series(db, space)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_series_about_block(
                slug=space.slug,
                series_slug=series.slug,
                body=AboutBlockCreateRequest(
                    block_type="image", embed_url="file:///etc/passwd",
                ),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400

    def test_hostile_nav_url_rejected_on_patch(
        self, db, make_user, make_space,
    ):
        creator = make_user(role="creator")
        space = make_space(creator=creator)
        series = _series(db, space)
        db.commit()

        block = create_series_about_block(
            slug=space.slug,
            series_slug=series.slug,
            body=AboutBlockCreateRequest(
                block_type="link", embed_url="https://example.com",
            ),
            db=db, current_user=creator,
        )
        with pytest.raises(HTTPException) as exc:
            update_series_about_block(
                slug=space.slug,
                series_slug=series.slug,
                block_id=block.id,
                body=AboutBlockUpdateRequest(embed_url="vbscript:msgbox(1)"),
                db=db, current_user=creator,
            )
        assert exc.value.status_code == 400
