"""Old Render links: corrected where they are navigation, left where
they are history.

Three kinds of row carried ``fc-web-q950.onrender.com`` after the
custom-domain cutover, and they get three different answers:

  * **Sent and delivered communication intents** (188 in production) —
    untouched. They record what was actually sent. Editing them would
    make the history say something that never happened, and the
    member's copy is in their inbox either way.

  * **In-app notifications** (25) — rewritten. These are not records,
    they are live navigation: the row *is* the link, and tapping it
    today takes a member to a hostname that is not the product.

  * **Historical event payloads** (95 across 9 types) — untouched, and
    the risk they carry closed at the other end instead.
    ``CommunicationEvent`` is documented as "an immutable record that
    something communication-worthy happened" whose payload holds
    "structured facts … never rendered content". Absolute URLs went in
    anyway. Rather than rewrite the ledger, ``route_event``
    canonicalises the origin on the way out, so an old event re-routed
    today produces a link on today's public domain while its record
    keeps saying what it said.

The last of those is the one with teeth, and most of this file is about
proving it: an event carrying the old host must not be able to produce
a new email or a new notification carrying the old host.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_render_link_remediation.py
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import app.comms.templates  # noqa: F401 — registers every template
import app.models.community_care  # noqa: F401
from app.comms import Source, emit
from app.comms.intents import DELIVERY_MODE_LIVE
from app.comms.models import CommunicationIntent
from app.comms.routing.resolver import ResolvedRecipient
from app.comms.routing.routing import (
    _canonicalise_recipient_links,
    route_event,
)
from app.core.config import settings
from app.core.url_policy import canonicalise_origin, replace_origin
from app.services import notification_link_canonicalisation as nlc

OLD = "https://fc-web-q950.onrender.com"
PUBLIC = "https://freshcollective.au"


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def production_like(monkeypatch):
    """The public domain configured, the Render host still correct for
    CORS — what fc-api sees today."""
    monkeypatch.setattr(settings, "public_app_url", PUBLIC, raising=False)
    monkeypatch.setattr(settings, "frontend_origin", OLD, raising=False)
    return settings


# ---------------------------------------------------------------------------
# The primitives
# ---------------------------------------------------------------------------


class TestOriginRewriting:
    @pytest.mark.parametrize("path", [
        "/reset-password?token=X",
        "/spaces/embody/events/e1",
        "/spaces/embody/community/p1?highlight=c2#comment-3",
        "/checkout/complete?token=a&b=c%20d",
        "/",
    ])
    def test_everything_after_the_origin_is_preserved(self, path):
        """Only the origin was ever wrong. A reset token, a highlight
        anchor, an encoded query — all of it has to come through
        byte-identical."""
        assert replace_origin(OLD + path, OLD, PUBLIC) == PUBLIC + path
        assert canonicalise_origin(OLD + path, PUBLIC) == PUBLIC + path

    @pytest.mark.parametrize("url", [
        "https://connect.stripe.com/setup/abc",
        "https://api.resend.com/emails",
        "https://example.test/page?x=1",
        "/spaces/embody",
        "mailto:hello@freshcollective.au",
        "",
        None,
    ])
    def test_nothing_else_is_rewritten(self, url):
        """A Stripe link repointed at our own domain would simply be
        broken, and relative in-app paths have no origin to correct."""
        assert replace_origin(url, OLD, PUBLIC) == url
        assert canonicalise_origin(url, PUBLIC) == url

    @pytest.mark.parametrize("relative", [
        "/redirect?next=https://fc-web-q950.onrender.com/dashboard",
        "/spaces/embody?return=http://localhost:3000/x",
        "/go/localhost",
    ])
    def test_a_relative_url_stays_relative_even_when_it_mentions_a_host(
        self, relative,
    ):
        """In-app navigation is stored relative by design, and a
        relative path has no origin to correct.

        These carry a non-public host *inside* the path or query, which
        is the only shape where the absolute-URL guard is load-bearing:
        without it the marker matches and a relative link silently
        becomes absolute.
        """
        assert canonicalise_origin(relative, PUBLIC) == relative
        assert replace_origin(relative, OLD, PUBLIC) == relative

    def test_the_strict_form_leaves_other_render_subdomains_alone(self):
        """``replace_origin`` edits stored records, so it matches one
        exact origin. Another service's Render host is somebody else's
        URL."""
        other = "https://some-other-app.onrender.com/x"
        assert replace_origin(other, OLD, PUBLIC) == other

    def test_the_canonicalising_form_does_move_them(self):
        """``canonicalise_origin`` guards content being generated now,
        where any non-public host is wrong regardless of which one."""
        assert canonicalise_origin(
            "https://some-other-app.onrender.com/x", PUBLIC,
        ) == f"{PUBLIC}/x"

    def test_a_port_is_part_of_the_origin(self):
        assert replace_origin(
            "http://localhost:3000/a", "http://localhost:3000", PUBLIC,
        ) == f"{PUBLIC}/a"
        # Different port, different origin — left alone by the strict form.
        assert replace_origin(
            "http://localhost:9999/a", "http://localhost:3000", PUBLIC,
        ) == "http://localhost:9999/a"


# ---------------------------------------------------------------------------
# The route-time guard — the one with teeth
# ---------------------------------------------------------------------------


class TestAnOldEventCannotProduceAnOldLink:
    """The requirement, stated directly.

    An event carrying ``https://fc-web-q950.onrender.com/…`` must not
    be able to produce a newly-routed email or notification carrying
    that host.
    """

    #: Every event type the production audit found, with the context key
    #: each one's resolver copies the URL into. Parameterised so a new
    #: affected type cannot be covered by accident.
    AFFECTED = [
        ("gathering.booking.confirmed", "gathering_url"),
        ("account.email_verification_requested", "verify_url"),
        ("account.welcome_after_signup", "next_url"),
        ("purchase.completed", "member_url"),
        ("collective.purchase.received", "cta_url"),
        ("account.password_reset_requested", "reset_url"),
        ("creator.plan_activated", "next_url"),
        ("access.suspended", "cta_url"),
        ("gathering.multi_booking.confirmed", "cta_url"),
    ]

    @pytest.mark.parametrize(
        "event_type,context_key", AFFECTED,
        ids=[t for t, _ in AFFECTED],
    )
    def test_the_context_is_canonicalised_for_every_affected_type(
        self, production_like, event_type, context_key,
    ):
        recipient = ResolvedRecipient(
            user_id="u_1", role_in_event="recipient",
            human_reason="A test said so.",
            template_context={context_key: f"{OLD}/some/path?token=X"},
        )
        corrected = _canonicalise_recipient_links(recipient)
        assert corrected.template_context[context_key] == (
            f"{PUBLIC}/some/path?token=X"
        )
        assert "onrender.com" not in str(corrected.template_context)

    def test_the_resolvers_recipient_is_not_mutated(self, production_like):
        """A new object, so nothing a resolver handed over is edited in
        place — the event and anything derived from it stay as they
        were."""
        original = {"reset_url": f"{OLD}/reset-password?token=X"}
        recipient = ResolvedRecipient(
            user_id="u_1", role_in_event="recipient",
            human_reason="A test said so.", template_context=original,
        )
        corrected = _canonicalise_recipient_links(recipient)
        assert corrected is not recipient
        assert original["reset_url"] == f"{OLD}/reset-password?token=X"

    def test_non_string_context_values_survive(self, production_like):
        recipient = ResolvedRecipient(
            user_id="u_1", role_in_event="recipient", human_reason="x",
            template_context={
                "reset_url": f"{OLD}/r", "count": 3, "flag": True,
                "items": ["a", "b"], "nothing": None,
            },
        )
        context = _canonicalise_recipient_links(recipient).template_context
        assert context["count"] == 3
        assert context["flag"] is True
        assert context["items"] == ["a", "b"]
        assert context["nothing"] is None
        assert context["reset_url"] == f"{PUBLIC}/r"

    def test_an_unaffected_context_is_returned_unchanged(self, production_like):
        """No new object when there is nothing to correct."""
        recipient = ResolvedRecipient(
            user_id="u_1", role_in_event="recipient", human_reason="x",
            template_context={"url": f"{PUBLIC}/ok", "n": 1},
        )
        assert _canonicalise_recipient_links(recipient) is recipient

    def test_routing_a_historical_event_end_to_end(
        self, db, make_user, production_like,
    ):
        """The whole chain, from a stored event to a persisted intent.

        An old ``account.password_reset_requested`` event — payload
        exactly as production has it — routed live today. The rendered
        subject, HTML body and text body are all asserted, because the
        original bug lived in the text body as well as the button.
        """
        user = make_user()
        db.flush()
        event = emit(
            db,
            event_type="account.password_reset_requested",
            source_type=Source.FRESH_COLLECTIVE,
            actor_user_id=user.id,
            subject_type="password_reset",
            payload={"reset_url": f"{OLD}/reset-password?token=tok-abc123"},
        )
        db.flush()

        result = route_event(db, event, delivery_mode=DELIVERY_MODE_LIVE)
        assert result.intent_ids, result.skipped

        for intent_id in result.intent_ids:
            intent = db.get(CommunicationIntent, intent_id)
            rendered = " ".join([
                intent.payload_subject or "",
                intent.payload_body_html or "",
                intent.payload_body_text or "",
                str(intent.template_context or {}),
                str(intent.payload_metadata or {}),
            ])
            assert "onrender.com" not in rendered, (
                f"intent {intent_id} ({intent.channel}) carries the old host"
            )
            assert f"{PUBLIC}/reset-password?token=tok-abc123" in rendered, (
                f"intent {intent_id} ({intent.channel}) lost the link"
            )

        # And the event itself is untouched — history stays truthful.
        db.refresh(event)
        assert event.payload["reset_url"] == (
            f"{OLD}/reset-password?token=tok-abc123"
        )

    def test_the_stored_event_payload_is_never_written(
        self, db, make_user, production_like,
    ):
        """``CommunicationEvent`` is declared immutable, and routing must
        honour that even while correcting what it emits."""
        user = make_user()
        db.flush()
        event = emit(
            db,
            event_type="account.welcome_after_signup",
            source_type=Source.FRESH_COLLECTIVE,
            actor_user_id=user.id,
            subject_type="user",
            payload={"next_url": f"{OLD}/dashboard", "first_name": "Sam"},
        )
        db.flush()
        before = db.execute(text(
            "SELECT CAST(payload AS text) FROM communication_events "
            "WHERE id = :i"
        ), {"i": event.id}).scalar()

        route_event(db, event, delivery_mode=DELIVERY_MODE_LIVE)

        after = db.execute(text(
            "SELECT CAST(payload AS text) FROM communication_events "
            "WHERE id = :i"
        ), {"i": event.id}).scalar()
        assert after == before
        assert "onrender.com" in after

    def test_external_links_in_a_routed_event_survive(self, production_like):
        """A Stripe URL in a template context must reach the member
        intact. Repointing one at our own domain would break it."""
        stripe_url = "https://connect.stripe.com/setup/s/abc123"
        recipient = ResolvedRecipient(
            user_id="u_1", role_in_event="recipient", human_reason="x",
            template_context={"cta_url": stripe_url},
        )
        corrected = _canonicalise_recipient_links(recipient)
        assert corrected.template_context["cta_url"] == stripe_url


# ---------------------------------------------------------------------------
# In-app notification cleanup
# ---------------------------------------------------------------------------


@pytest.fixture
def notification(db, make_user):
    def _make(url: str, *, title: str = "A thing", message: str = "Happened"):
        user = make_user()
        db.flush()
        nid = _uid("n")
        db.execute(text(
            "INSERT INTO notifications "
            "(id, user_id, notification_type, title, message, url, is_read, "
            " created_at) "
            "VALUES (:i, :u, 'booking_confirmed', :t, :m, :url, false, now())"
        ), {"i": nid, "u": user.id, "t": title, "m": message, "url": url})
        db.flush()
        return nid
    return _make


def _url_of(db, nid: str) -> str | None:
    return db.execute(text(
        "SELECT url FROM notifications WHERE id = :i"
    ), {"i": nid}).scalar()


class TestNotificationLinkCleanup:
    def test_the_old_host_is_found_and_the_rewrite_is_described(
        self, db, notification, production_like,
    ):
        nid = notification(f"{OLD}/spaces/embody/events/e1?ref=x#top")
        findings, mentions = nlc.audit(db)

        mine = [f for f in findings if f.notification_id == nid]
        assert len(mine) == 1
        finding = mine[0]
        assert finding.safe
        assert finding.new_url == f"{PUBLIC}/spaces/embody/events/e1?ref=x#top"
        assert mentions == []

    def test_the_audit_writes_nothing(self, db, notification, production_like):
        nid = notification(f"{OLD}/a")
        nlc.audit(db)
        assert _url_of(db, nid) == f"{OLD}/a"

    def test_apply_rewrites_only_the_origin(
        self, db, notification, production_like,
    ):
        nid = notification(f"{OLD}/reset-password?token=X#frag")
        findings, _ = nlc.audit(db)
        updated = nlc.apply(db, [f for f in findings if f.safe])
        assert nid in [f.notification_id for f in updated]
        assert _url_of(db, nid) == f"{PUBLIC}/reset-password?token=X#frag"

    def test_another_render_subdomain_is_reported_not_rewritten(
        self, db, notification, production_like,
    ):
        """Strictly one origin. A host nobody expected is worth
        understanding, not guessing at."""
        nid = notification("https://some-other-app.onrender.com/x")
        findings, _ = nlc.audit(db)
        finding = next(f for f in findings if f.notification_id == nid)
        assert not finding.safe
        assert any("is not" in w for w in finding.warnings)

        updated = nlc.apply(db, findings)
        assert _url_of(db, nid) == "https://some-other-app.onrender.com/x"
        # And it is not reported as fixed. A tool that claims to have
        # corrected a row it deliberately skipped is worse than one that
        # skips loudly — the operator stops looking.
        assert nid not in [f.notification_id for f in updated]

    @pytest.mark.parametrize("url", [
        "https://connect.stripe.com/setup/abc",
        "/spaces/embody/events/e1",
        "https://freshcollective.au/already/right",
    ])
    def test_other_links_are_not_even_selected(
        self, db, notification, production_like, url,
    ):
        nid = notification(url)
        findings, _ = nlc.audit(db)
        assert nid not in [f.notification_id for f in findings]
        nlc.apply(db, findings)
        assert _url_of(db, nid) == url

    def test_nothing_but_the_url_is_written(
        self, db, notification, production_like,
    ):
        nid = notification(f"{OLD}/a", title="Keep me", message="And me")
        row_before = db.execute(text(
            "SELECT notification_type, title, message, is_read, created_at "
            "FROM notifications WHERE id = :i"
        ), {"i": nid}).first()

        findings, _ = nlc.audit(db)
        nlc.apply(db, [f for f in findings if f.safe])

        row_after = db.execute(text(
            "SELECT notification_type, title, message, is_read, created_at "
            "FROM notifications WHERE id = :i"
        ), {"i": nid}).first()
        assert row_after == row_before

    def test_a_row_changed_since_the_audit_is_skipped(
        self, db, notification, production_like,
    ):
        """The update is guarded on the URL it was audited with, so a
        concurrent change is left alone rather than clobbered."""
        nid = notification(f"{OLD}/a")
        findings, _ = nlc.audit(db)

        db.execute(text("UPDATE notifications SET url = :u WHERE id = :i"),
                   {"u": "/moved/elsewhere", "i": nid})
        db.flush()

        updated = nlc.apply(db, [f for f in findings if f.safe])
        assert nid not in [f.notification_id for f in updated]
        assert _url_of(db, nid) == "/moved/elsewhere"

    def test_the_old_host_in_notification_text_is_reported_not_rewritten(
        self, db, notification, production_like,
    ):
        """Content, not navigation. A person decides."""
        nid = notification("/relative", message=f"See {OLD}/somewhere")
        findings, mentions = nlc.audit(db)
        assert nid not in [f.notification_id for f in findings]
        assert nid in [m.notification_id for m in mentions]
        assert any(m.column == "message" for m in mentions)

    def test_re_running_is_a_no_op(self, db, notification, production_like):
        nid = notification(f"{OLD}/a")
        findings, _ = nlc.audit(db)
        nlc.apply(db, [f for f in findings if f.safe])

        again, _ = nlc.audit(db)
        assert nid not in [f.notification_id for f in again]
        assert nlc.apply(db, again) == []
        assert _url_of(db, nid) == f"{PUBLIC}/a"

    def test_remaining_reaches_zero(self, db, notification, production_like):
        for _ in range(3):
            notification(f"{OLD}/x")
        findings, _ = nlc.audit(db)
        assert nlc.remaining(db) >= 3
        nlc.apply(db, [f for f in findings if f.safe])
        assert nlc.remaining(db) == 0


class TestTheToolRefusesTheWrongDestination:
    def test_a_non_https_public_address_is_refused(self, monkeypatch):
        """The obvious way to do real damage with this tool is to run it
        where the public address is localhost."""
        monkeypatch.setattr(settings, "public_app_url", None, raising=False)
        monkeypatch.setattr(
            settings, "frontend_origin", "http://localhost:3000", raising=False,
        )
        reason = nlc.destination_is_usable()
        assert reason is not None
        assert "not an https origin" in reason

    def test_the_old_host_as_destination_is_refused(self, monkeypatch):
        monkeypatch.setattr(settings, "public_app_url", OLD, raising=False)
        reason = nlc.destination_is_usable()
        assert reason is not None
        assert "nothing to move" in reason

    def test_the_real_configuration_is_accepted(self, production_like):
        assert nlc.destination_is_usable() is None


# ---------------------------------------------------------------------------
# What must stay untouched
# ---------------------------------------------------------------------------


class TestEmailHistoryIsNotTouched:
    def test_no_code_path_writes_to_a_sent_or_delivered_intent_body(self):
        """A source contract. The 188 sent/delivered intents are the
        record of what went out, and nothing in this remediation may
        rewrite a rendered body."""
        import pathlib

        backend = pathlib.Path(__file__).resolve().parent.parent
        offenders: list[str] = []
        for name in (
            "app/services/notification_link_canonicalisation.py",
            "scripts/canonicalise_notification_links.py",
            "app/comms/routing/routing.py",
            "app/core/url_policy.py",
        ):
            for i, line in enumerate(
                (backend / name).read_text(encoding="utf-8").splitlines(), 1,
            ):
                code = line.split("#", 1)[0]
                if "UPDATE communication_intents" in code:
                    offenders.append(f"{name}:{i}")
                if "UPDATE communication_events" in code:
                    offenders.append(f"{name}:{i}")
        assert offenders == [], offenders

    def test_the_notification_tool_only_updates_one_table_and_column(self):
        import pathlib
        import re

        source = (
            pathlib.Path(__file__).resolve().parent.parent
            / "app/services/notification_link_canonicalisation.py"
        ).read_text(encoding="utf-8")
        updates = re.findall(r"UPDATE\s+(\w+)\s+SET\s+(\w+)", source)
        assert updates == [("notifications", "url")], updates


class TestTheToolIsNotScheduled:
    def test_it_is_absent_from_the_blueprint(self):
        import pathlib

        blueprint = (
            pathlib.Path(__file__).resolve().parent.parent.parent / "render.yaml"
        )
        assert "canonicalise_notification_links" not in blueprint.read_text()
