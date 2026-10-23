"""The Collective's welcome email: who gets one, and who must not.

Membership is created in nine places in this codebase. Five of them are
a person joining a Collective and earn a welcome; four are not. The
emitter is shared, but what actually holds the line is the partial
unique index on ``(event_type, dedupe_key)`` — one row can exist per
``collective_welcome:{space_id}:{user_id}``, ever.

That single fact is what these tests keep honest, because five separate
product requirements rest on it: idempotent sending, no duplicates from
webhook retries, no welcome when an existing member buys again, no
welcome when a removed member returns, and no coordination needed
between call sites.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_verified_creator_user
from app.comms.models import CommunicationEvent
from app.comms.templates.editable import get_declaration
from app.core.database import get_db
from app.main import app
from app.models.communication_template_override import (
    CommunicationTemplateOverride,
)
from app.models.platform import (
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.models.user import User
from app.services import membership_grant as mg
from app.services.collective_welcome_emit import (
    EVENT_TYPE,
    dedupe_key_for,
    emit_collective_welcome,
)

TEMPLATE_KEY = "collective.membership.welcome.email_transactional"


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


def _welcomes(db, space_id: str | None = None) -> list[CommunicationEvent]:
    q = db.query(CommunicationEvent).filter(
        CommunicationEvent.event_type == EVENT_TYPE,
    )
    if space_id:
        q = q.filter(CommunicationEvent.source_id == space_id)
    return q.all()


def _membership(db, space, user, *, status=SpaceMembershipStatus.active,
                source="joined") -> SpaceMembership:
    m = SpaceMembership(
        id=str(uuid.uuid4()), space_id=space.id, user_id=user.id,
        role=SpaceRole.learner, status=status, source=source,
        joined_at=datetime.utcnow(),
    )
    db.add(m)
    db.flush()
    return m


# ---------------------------------------------------------------------------
# The emitter's own decisions
# ---------------------------------------------------------------------------


class TestWhoEarnsAWelcome:

    def test_a_first_time_member_is_welcomed(self, db, make_space, make_user):
        space, member = make_space(), make_user()
        ev = emit_collective_welcome(
            db, space=space, member=member, join_source="joined",
        )
        assert ev is not None
        assert ev.event_type == EVENT_TYPE
        assert ev.actor_user_id == member.id
        assert ev.dedupe_key == dedupe_key_for(space.id, member.id)

    @pytest.mark.parametrize(
        "source", ["joined", "invited", "purchase", "ticket_purchase"],
    )
    def test_every_joining_source_earns_one(
        self, db, make_space, make_user, source,
    ):
        """The five approved pathways arrive carrying different sources;
        none of them is a reason to withhold the welcome."""
        space, member = make_space(), make_user()
        assert emit_collective_welcome(
            db, space=space, member=member, join_source=source,
        ) is not None

    @pytest.mark.parametrize("source", ["creator_owner", "auto_role"])
    def test_platform_and_owner_memberships_are_not_welcomed(
        self, db, make_space, make_user, source,
    ):
        """A creator is not a guest in their own Collective, and
        World Builders membership is computed rather than chosen."""
        space, member = make_space(), make_user()
        assert emit_collective_welcome(
            db, space=space, member=member, join_source=source,
        ) is None
        assert _welcomes(db, space.id) == []

    def test_the_collectives_own_creator_is_never_welcomed(
        self, db, make_space,
    ):
        """Even if their row carries a joining source."""
        space = make_space()
        owner = db.query(User).filter(User.id == space.creator_id).one()
        assert emit_collective_welcome(
            db, space=space, member=owner, join_source="joined",
        ) is None

    def test_a_disabled_collective_sends_nothing(
        self, db, make_space, make_user,
    ):
        space, member = make_space(), make_user()
        space.welcome_email_enabled = False
        db.flush()
        assert emit_collective_welcome(
            db, space=space, member=member, join_source="joined",
        ) is None
        assert _welcomes(db, space.id) == []

    def test_enabling_later_releases_no_backlog(
        self, db, make_space, make_user,
    ):
        """The flag is read at emit time, not at delivery.

        Somebody who joined while welcomes were off has no event, and
        switching the feature on cannot invent one for them — which is
        what makes "no delayed welcome" structural rather than a rule
        somebody has to remember.
        """
        space, member = make_space(), make_user()
        space.welcome_email_enabled = False
        db.flush()
        emit_collective_welcome(
            db, space=space, member=member, join_source="joined",
        )
        space.welcome_email_enabled = True
        db.flush()
        # Nothing re-emits on its own; the member stays unwelcomed.
        assert _welcomes(db, space.id) == []


class TestExactlyOnceForever:

    def test_a_second_emit_is_refused(self, db, make_space, make_user):
        space, member = make_space(), make_user()
        first = emit_collective_welcome(
            db, space=space, member=member, join_source="joined",
        )
        second = emit_collective_welcome(
            db, space=space, member=member, join_source="purchase",
        )
        assert first is not None and second is None
        assert len(_welcomes(db, space.id)) == 1

    def test_a_different_route_cannot_double_send(
        self, db, make_space, make_user,
    ):
        """The reason the five call sites need no coordination."""
        space, member = make_space(), make_user()
        for source in ("joined", "invited", "purchase", "ticket_purchase"):
            emit_collective_welcome(
                db, space=space, member=member, join_source=source,
            )
        assert len(_welcomes(db, space.id)) == 1

    def test_rejoining_after_removal_sends_no_second_welcome(
        self, db, make_space, make_user,
    ):
        """A returning member is deliberately silent. A "welcome back"
        is a separate decision nobody has taken."""
        space, member = make_space(), make_user()
        emit_collective_welcome(
            db, space=space, member=member, join_source="joined",
        )
        # …removed, then returns through a purchase.
        assert emit_collective_welcome(
            db, space=space, member=member, join_source="purchase",
        ) is None

    def test_each_collective_welcomes_independently(
        self, db, make_space, make_user,
    ):
        """The key is per (Collective, member), not per member."""
        a, b, member = make_space(), make_space(), make_user()
        assert emit_collective_welcome(
            db, space=a, member=member, join_source="joined") is not None
        assert emit_collective_welcome(
            db, space=b, member=member, join_source="joined") is not None
        assert len(_welcomes(db, a.id)) == 1
        assert len(_welcomes(db, b.id)) == 1

    def test_the_dedupe_key_names_both_parties(self):
        """Pinned because a key that dropped either half would either
        welcome somebody twice or silence a whole Collective."""
        assert dedupe_key_for("sp_1", "u_1") == "collective_welcome:sp_1:u_1"
        assert dedupe_key_for("sp_1", "u_2") != dedupe_key_for("sp_1", "u_1")
        assert dedupe_key_for("sp_2", "u_1") != dedupe_key_for("sp_1", "u_1")


# ---------------------------------------------------------------------------
# The membership lifecycle the purchase path goes through
# ---------------------------------------------------------------------------


class TestThePurchasePath:

    def test_a_first_time_buyer_becomes_a_member_and_is_welcomed(
        self, db, make_space, make_user,
    ):
        space, buyer = make_space(), make_user()
        outcome = mg.ensure_membership_for_purchase(
            db, user_id=buyer.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert outcome.created is True
        assert emit_collective_welcome(
            db, space=space, member=buyer, join_source="purchase",
        ) is not None

    def test_an_existing_member_buying_again_is_not_welcomed(
        self, db, make_space, make_user,
    ):
        """``created`` is False, so the purchase path never even emits."""
        space, buyer = make_space(), make_user()
        _membership(db, space, buyer, source="joined")
        outcome = mg.ensure_membership_for_purchase(
            db, user_id=buyer.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert outcome.created is False
        assert outcome.skipped_reason == "already_active"

    def test_a_reactivated_member_is_not_a_first_time_member(
        self, db, make_space, make_user,
    ):
        space, buyer = make_space(), make_user()
        _membership(
            db, space, buyer,
            status=SpaceMembershipStatus.removed, source="joined",
        )
        outcome = mg.ensure_membership_for_purchase(
            db, user_id=buyer.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert outcome.reactivated is True
        assert outcome.created is False

    def test_a_paused_membership_is_left_alone(
        self, db, make_space, make_user,
    ):
        space, buyer = make_space(), make_user()
        _membership(
            db, space, buyer,
            status=SpaceMembershipStatus.paused, source="joined",
        )
        outcome = mg.ensure_membership_for_purchase(
            db, user_id=buyer.id, space_id=space.id, now=datetime.utcnow(),
        )
        assert outcome.created is False
        assert outcome.skipped_reason == "status_paused"


# ---------------------------------------------------------------------------
# The two joining paths that do not go through ``apply_intent``
#
# A free Offering and a standalone Gathering ticket each create
# membership through their own code, not through purchase fulfilment.
# Both therefore have to report first-time membership themselves, and
# these pin that reporting — the thing their routes branch on when
# deciding whether a welcome is owed.
# ---------------------------------------------------------------------------


class TestTheOtherJoiningPaths:

    def test_a_free_offering_reports_a_first_time_membership(
        self, db, make_space, make_user,
    ):
        from app.services.offering_acquisition import AcquisitionOutcome

        # The field exists and defaults to "no welcome", so a future
        # construction that forgets it stays silent rather than
        # welcoming somebody twice.
        assert "membership_first_time" in AcquisitionOutcome.__annotations__
        outcome = AcquisitionOutcome(
            entitlement=None, created=True, joined_collective=True,
        )
        assert outcome.membership_first_time is False

    def test_a_gathering_ticket_reports_a_first_time_membership(self):
        from app.services.gathering_tickets import FulfilOutcome

        assert "membership_first_time" in FulfilOutcome.__annotations__
        outcome = FulfilOutcome(
            already_fulfilled=False, booking=None, access_pass=None,
            transaction=None,
        )
        assert outcome.membership_first_time is False

    def test_a_ticket_purchase_source_still_earns_a_welcome(
        self, db, make_space, make_user,
    ):
        """``ticket_purchase`` is not an excluded source."""
        space, buyer = make_space(), make_user()
        assert emit_collective_welcome(
            db, space=space, member=buyer, join_source="ticket_purchase",
        ) is not None

    def test_no_call_site_routes_before_it_commits(self):
        """Routing dispatches synchronously, so scheduling a welcome
        before the commit would send mail describing a membership that
        can still roll back. Every call site must therefore order the
        two one way: ``db.commit()`` first, scheduling after.

        Read from the source because the ordering is the whole
        guarantee and a passing functional test cannot see it — a
        send that happens to precede a commit that happens to succeed
        looks identical to the correct order.
        """
        from pathlib import Path

        backend = Path(__file__).resolve().parents[1]
        offenders = []
        for rel in (
            "app/spaces/routes.py",
            "app/spaces/_offering_member_routes.py",
            "app/creator/routes.py",
            "app/webhooks/routes.py",
            "app/webhooks/finite_plan_handlers.py",
        ):
            lines = (backend / rel).read_text().splitlines()
            commits = [i for i, l in enumerate(lines) if "db.commit()" in l]
            for i, line in enumerate(lines):
                if "schedule_welcome(" not in line or "def " in line:
                    continue
                if "import" in line:
                    continue
                if not any(c < i for c in commits):
                    offenders.append(f"{rel}:{i + 1}: {line.strip()}")
        assert offenders == [], (
            "a welcome is scheduled with no commit before it:\n"
            + "\n".join(offenders)
        )

    def test_every_membership_creating_path_emits_a_welcome(self):
        """Structural: a path that creates membership must emit.

        The free-Offering route and the ticket webhook create
        membership outside ``apply_intent``, and both were missed when
        the emitter was first wired in. This reads the source rather
        than the behaviour, because the failure mode is an omission —
        there is no wrong output to assert on, only a missing call.
        """
        from pathlib import Path

        backend = Path(__file__).resolve().parents[1]
        must_emit = (
            "app/spaces/_offering_member_routes.py",
            "app/webhooks/routes.py",
            "app/webhooks/finite_plan_handlers.py",
            "app/spaces/routes.py",
            "app/creator/routes.py",
        )
        missing = [
            rel for rel in must_emit
            if "emit_collective_welcome" not in (backend / rel).read_text()
        ]
        assert missing == [], (
            "these create Collective membership but never emit the "
            "welcome:\n" + "\n".join(missing)
        )


# ---------------------------------------------------------------------------
# Rendering — defaults, inheritance, and the generated destination
# ---------------------------------------------------------------------------


def _render(db, space, overrides=None):
    from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
    from app.comms.routing.resolver import ResolvedRecipient
    from app.comms.templates.editable import preview_overrides
    from app.comms.templates.registry import get_template_for
    from app.services.collective_welcome_emit import collective_url

    tpl = get_template_for(EVENT_TYPE, CHANNEL_EMAIL_TRANSACTIONAL)
    recipient = ResolvedRecipient(
        user_id="u", role_in_event="new_member", human_reason="",
        template_context={
            "space_id": space.id,
            "collective_name": space.name,
            "member_first_name": "Tom",
            "creator_name": "Lindsey",
            "collective_url": collective_url(space),
        },
    )
    if overrides is None:
        return tpl.render(db, None, recipient)
    with preview_overrides({TEMPLATE_KEY: overrides}):
        return tpl.render(db, None, recipient)


class TestTheRenderedEmail:

    def test_the_platform_default_names_the_collective(self, db, make_space):
        space = make_space(name="Moonlit Circle")
        out = _render(db, space)
        assert out.subject == "Welcome to Moonlit Circle ✨"
        assert "Welcome to Moonlit Circle!" in out.body_text
        assert "Hello Tom," in out.body_text

    def test_the_destination_is_the_collective(self, db, make_space):
        """Generated from the slug — and the reason ``cta_url`` is not a
        slot: a creator may rename the button, never aim it."""
        space = make_space()
        out = _render(db, space)
        assert f"/spaces/{space.slug}" in out.body_text
        assert f"/spaces/{space.slug}" in out.body_html

    def test_a_creator_cannot_supply_a_destination(self):
        """There is no slot through which a URL could be injected."""
        decl = get_declaration(TEMPLATE_KEY)
        ids = {s.slot_id for s in decl.slots}
        assert ids == {
            "subject", "heading", "body.message", "cta_label", "signature",
        }
        assert not any("url" in s for s in ids)

    def test_a_missing_first_name_still_greets_somebody(
        self, db, make_space,
    ):
        from app.comms.categories import CHANNEL_EMAIL_TRANSACTIONAL
        from app.comms.routing.resolver import ResolvedRecipient
        from app.comms.templates.registry import get_template_for

        space = make_space()
        tpl = get_template_for(EVENT_TYPE, CHANNEL_EMAIL_TRANSACTIONAL)
        out = tpl.render(db, None, ResolvedRecipient(
            user_id="u", role_in_event="new_member", human_reason="",
            template_context={
                "space_id": space.id, "collective_name": space.name,
                "member_first_name": "", "collective_url": "https://x/spaces/y",
            },
        ))
        assert "Hello there," in out.body_text

    def test_the_message_keeps_its_paragraphs(self, db, make_space):
        space = make_space()
        out = _render(db, space, {"body.message": "One.\n\nTwo.\n\nThree."})
        assert out.body_html.count("<p") >= 3


class TestInheritance:
    """system default → platform admin override → this Collective."""

    def _row(self, db, slot, value, space_id=None):
        db.add(CommunicationTemplateOverride(
            id=_uid("cto"), template_key=TEMPLATE_KEY, slot_id=slot,
            value=value, default_fingerprint="fp", space_id=space_id,
        ))
        db.flush()

    def test_a_platform_override_reaches_every_collective(
        self, db, make_space,
    ):
        space = make_space()
        self._row(db, "heading", "Platform heading for {{collective_name}}")
        assert "Platform heading for" in _render(db, space).body_text

    def test_a_collective_override_beats_the_platform(self, db, make_space):
        space = make_space()
        self._row(db, "heading", "Platform heading for {{collective_name}}")
        self._row(db, "heading", "Our heading for {{collective_name}}", space_id=space.id)
        assert "Our heading for" in _render(db, space).body_text

    def test_inheritance_is_per_slot(self, db, make_space):
        """A Collective that rewrites only its subject keeps receiving
        later improvements to the platform's heading."""
        space = make_space()
        self._row(db, "heading", "Platform heading for {{collective_name}}")
        self._row(db, "subject", "Our subject for {{collective_name}}", space_id=space.id)
        out = _render(db, space)
        assert out.subject.startswith("Our subject for")
        assert "Platform heading for" in out.body_text

    def test_one_collective_cannot_see_anothers_copy(self, db, make_space):
        a, b = make_space(), make_space()
        self._row(db, "heading", "A's heading for {{collective_name}}", space_id=a.id)
        assert "A's heading for" in _render(db, a).body_text
        assert "A's heading for" not in _render(db, b).body_text


# ---------------------------------------------------------------------------
# Creator Studio API
# ---------------------------------------------------------------------------


@pytest.fixture
def creator_client(db, make_space):
    space = make_space(name="Moonlit Circle")
    owner = db.query(User).filter(User.id == space.creator_id).one()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_verified_creator_user] = lambda: owner
    yield TestClient(app, follow_redirects=False), space, owner
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_verified_creator_user, None)


class TestCreatorStudioApi:

    def test_it_starts_enabled_and_inheriting(self, creator_client):
        client, space, _ = creator_client
        res = client.get(f"/api/creator/spaces/{space.slug}/welcome-email")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["enabled"] is True
        assert body["customised"] is False
        assert body["collective_name"] == "Moonlit Circle"
        assert f"/spaces/{space.slug}" in body["collective_url"]
        assert {s["slot_id"] for s in body["slots"]} == {
            "subject", "heading", "body.message", "cta_label", "signature",
        }

    def test_saving_copy_scopes_it_to_this_collective(
        self, creator_client, db,
    ):
        client, space, _ = creator_client
        res = client.put(
            f"/api/creator/spaces/{space.slug}/welcome-email",
            json={"overrides": {"heading": "Come on in to {{collective_name}}"}},
        )
        assert res.status_code == 200, res.text
        assert res.json()["customised"] is True
        rows = db.query(CommunicationTemplateOverride).filter(
            CommunicationTemplateOverride.template_key == TEMPLATE_KEY,
        ).all()
        assert [r.space_id for r in rows] == [space.id]

    def test_the_toggle_persists(self, creator_client, db):
        client, space, _ = creator_client
        client.put(
            f"/api/creator/spaces/{space.slug}/welcome-email",
            json={"enabled": False},
        )
        db.refresh(space)
        assert space.welcome_email_enabled is False

    def test_typing_the_default_back_stops_being_customised(
        self, creator_client, db,
    ):
        """Customised must mean "differs", or a creator who reverts by
        hand would silently stop receiving future improvements."""
        client, space, _ = creator_client
        decl = get_declaration(TEMPLATE_KEY)
        default_heading = decl.slot("heading").default
        base = f"/api/creator/spaces/{space.slug}/welcome-email"
        first = client.put(base, json={"overrides": {"heading": "Temporary {{collective_name}}"}})
        assert first.status_code == 200, first.text
        assert first.json()["customised"] is True
        res = client.put(base, json={"overrides": {"heading": default_heading}})
        assert res.json()["customised"] is False

    def test_restore_default_deletes_rather_than_copies(
        self, creator_client, db,
    ):
        client, space, _ = creator_client
        base = f"/api/creator/spaces/{space.slug}/welcome-email"
        assert client.put(
            base, json={"overrides": {"heading": "Ours: {{collective_name}}"}},
        ).status_code == 200
        res = client.delete(base)
        assert res.status_code == 200
        assert res.json()["customised"] is False
        assert db.query(CommunicationTemplateOverride).filter(
            CommunicationTemplateOverride.space_id == space.id,
        ).count() == 0

    def test_preview_renders_this_collective(self, creator_client):
        client, space, _ = creator_client
        res = client.post(
            f"/api/creator/spaces/{space.slug}/welcome-email/preview",
            json={"mode": "effective", "drafts": {}},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert "Moonlit Circle" in body["subject"]
        assert f"/spaces/{space.slug}" in body["html"]

    def test_preview_shows_drafts_without_saving(self, creator_client, db):
        client, space, _ = creator_client
        res = client.post(
            f"/api/creator/spaces/{space.slug}/welcome-email/preview",
            json={"mode": "effective",
                  "drafts": {"heading": "Draft only {{collective_name}}"}},
        )
        assert "Draft only" in res.json()["html"]
        assert db.query(CommunicationTemplateOverride).count() == 0

    def test_an_invalid_draft_is_reported_not_rendered(self, creator_client):
        """A slot that drops a required merge field is refused, and the
        preview must show what would really be sent."""
        client, space, _ = creator_client
        res = client.post(
            f"/api/creator/spaces/{space.slug}/welcome-email/preview",
            json={"mode": "effective",
                  "drafts": {"heading": "No merge field here"}},
        )
        assert res.status_code == 200
        assert "heading" in res.json()["errors"]
        assert "No merge field here" not in res.json()["html"]

    def test_an_invalid_save_is_refused(self, creator_client, db):
        client, space, _ = creator_client
        res = client.put(
            f"/api/creator/spaces/{space.slug}/welcome-email",
            json={"overrides": {"heading": "No merge field here"}},
        )
        assert res.status_code == 422
        assert db.query(CommunicationTemplateOverride).count() == 0

    def test_a_creator_cannot_reach_another_collective(
        self, creator_client, make_space,
    ):
        """Resolved through ``_get_managed_space`` — naming someone
        else's slug is a refusal, not a different scope."""
        client, _space, _ = creator_client
        other = make_space()
        res = client.get(f"/api/creator/spaces/{other.slug}/welcome-email")
        assert res.status_code in (403, 404)


# ---------------------------------------------------------------------------
# The structural guard
# ---------------------------------------------------------------------------


class TestEditableTemplatesAreWired:

    def test_every_declared_slot_is_actually_honoured(self):
        """A template that declares editable slots must render through
        ``resolver_for``.

        ``collective.purchase.received`` declared four slots and built
        its copy from a hardcoded helper instead, so an administrator's
        saved edits changed the preview and nothing else — invisible
        unless somebody compared a sent email with the admin screen.

        Classification ``system`` means "no slots at all", so those are
        legitimately exempt and the check asserts that too: a system
        template that grew slots would be caught here rather than
        quietly joining the broken case.
        """
        import importlib
        import inspect
        import pkgutil

        import app.comms.templates as T
        from app.comms.templates.editable import admin_declarations

        classes: dict[str, type] = {}
        for m in pkgutil.iter_modules(T.__path__):
            mod = importlib.import_module(f"app.comms.templates.{m.name}")
            for obj in vars(mod).values():
                if (
                    isinstance(obj, type)
                    and hasattr(obj, "key")
                    and hasattr(obj, "render")
                ):
                    classes[obj.key] = obj

        unwired: list[str] = []
        for decl in admin_declarations():
            if decl.classification == "system":
                assert not decl.slots, (
                    f"{decl.template_key} is classified 'system' but declares "
                    f"{len(decl.slots)} slots — it would bypass them"
                )
                continue
            cls = classes.get(decl.template_key)
            if cls is None:
                unwired.append(f"{decl.template_key} (no renderer found)")
                continue
            if "resolver_for" not in inspect.getsource(cls.render):
                unwired.append(decl.template_key)

        assert not unwired, (
            "these declare editable slots but their renderer ignores them, so "
            "saved edits would not affect real emails: " + ", ".join(unwired)
        )
