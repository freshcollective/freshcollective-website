"""Members out as a spreadsheet, invitations in from one.

Neither half invents anything. The export borrows the CSV conventions
the attendance export proved; the import creates ordinary
``SpaceInvitation`` rows by the same rules ``create_invitation``
applies one at a time, so an imported invitation is indistinguishable
from a typed one.

The things worth testing are the ones that would be wrong quietly: a
spreadsheet that runs a formula when opened, an import that invites
somebody twice, a creator reaching a Collective they do not manage, and
an imported contact list turning up somewhere it should not.

No email leaves the process: the Collective's invitation event is
routed through the Communications Layer, and ``conftest`` tripwires the
Resend SDK.
"""
from __future__ import annotations

import csv
import io
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
from app.models.platform import (
    SpaceInvitation,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.services.member_csv import (
    MAX_CSV_BYTES,
    MAX_CSV_ROWS,
    CsvFormatError,
    parse_member_csv,
    sniff_columns,
)

EXPORT = "/api/creator/spaces/{slug}/members/export.csv"
TEMPLATE = "/api/creator/spaces/{slug}/members/import-template.csv"
PREVIEW = "/api/creator/spaces/{slug}/members/import/preview"
IMPORT = "/api/creator/spaces/{slug}/members/import"


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


def _join(db, user, space, role=SpaceRole.learner):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=role, status=SpaceMembershipStatus.active,
    ))
    db.flush()


@pytest.fixture
def collective(db, make_user, make_space):
    creator = make_user(role="creator", name="Ada Leader")
    space = make_space(creator=creator)
    _join(db, creator, space, role=SpaceRole.creator)
    member = make_user(name="Mem Ber", email=f"mem-{uuid.uuid4().hex[:8]}@fc.test")
    _join(db, member, space)
    db.commit()
    return space, creator, member


def upload(client, url, text: str, **form):
    return client.post(
        url,
        files={"file": ("members.csv", text.encode("utf-8"), "text/csv")},
        data=form,
    )


# ---------------------------------------------------------------------------
# Reading somebody else's export
# ---------------------------------------------------------------------------

class TestReadingACsv:
    def test_the_plain_two_column_shape(self):
        out = parse_member_csv(b"Name,Email\nAda,ada@example.com\n")
        assert [(r.name, r.email) for r in out.rows] == [("Ada", "ada@example.com")]

    @pytest.mark.parametrize("heading", [
        "Email", "email", "E-mail", "Email Address", "EMAIL_ADDRESS",
        "Member Email", "Primary Email",
    ])
    def test_email_headings_other_platforms_use(self, heading):
        out = parse_member_csv(f"Name,{heading}\nAda,ada@example.com\n".encode())
        assert [r.email for r in out.rows] == ["ada@example.com"]

    @pytest.mark.parametrize("heading", ["Name", "Full Name", "Display Name"])
    def test_name_headings(self, heading):
        out = parse_member_csv(f"{heading},Email\nAda Lovelace,a@example.com\n".encode())
        assert out.rows[0].name == "Ada Lovelace"

    def test_first_and_last_name_columns_are_joined(self):
        out = parse_member_csv(
            b"First Name,Last Name,Email\nAda,Lovelace,ada@example.com\n")
        assert out.rows[0].name == "Ada Lovelace"

    def test_a_missing_last_name_is_not_a_trailing_space(self):
        out = parse_member_csv(b"First Name,Last Name,Email\nAda,,ada@example.com\n")
        assert out.rows[0].name == "Ada"

    def test_an_excel_byte_order_mark_is_eaten(self):
        out = parse_member_csv("﻿Name,Email\nAda,ada@example.com\n".encode("utf-8"))
        assert out.email_column == "Email"
        assert len(out.rows) == 1

    def test_semicolon_and_tab_files_are_read(self):
        for text in ("Name;Email\nAda;ada@example.com\n",
                     "Name\tEmail\nAda\tada@example.com\n"):
            out = parse_member_csv(text.encode())
            assert [r.email for r in out.rows] == ["ada@example.com"], text

    def test_email_only_is_enough(self):
        out = parse_member_csv(b"Email\nada@example.com\n")
        assert out.rows[0].name is None

    def test_addresses_are_lowercased_and_trimmed(self):
        out = parse_member_csv(b"Email\n  Ada@Example.COM  \n")
        assert out.rows[0].email == "ada@example.com"

    def test_invalid_addresses_are_counted_by_line_not_echoed(self):
        out = parse_member_csv(
            b"Email\nnot-an-email\nada@example.com\nalso bad\n")
        assert [r.email for r in out.rows] == ["ada@example.com"]
        assert out.invalid_lines == [2, 4]

    def test_duplicates_keep_the_first_and_record_the_rest(self):
        out = parse_member_csv(
            b"Email\nada@example.com\nADA@example.com\ngrace@example.com\n")
        assert [r.email for r in out.rows] == ["ada@example.com", "grace@example.com"]
        assert out.duplicate_lines == [3]

    def test_blank_trailing_lines_are_not_errors(self):
        out = parse_member_csv(b"Name,Email\nAda,ada@example.com\n,\n\n")
        assert len(out.rows) == 1
        assert out.invalid_lines == []

    def test_an_unknown_email_column_asks_rather_than_guessing(self):
        with pytest.raises(CsvFormatError) as exc:
            parse_member_csv(b"Person,Contact Point\nAda,ada@example.com\n")
        assert "email column" in str(exc.value).lower()

    def test_the_creator_can_name_the_columns_themselves(self):
        out = parse_member_csv(
            b"Person,Contact Point\nAda,ada@example.com\n",
            email_column="Contact Point", name_column="Person",
        )
        assert [(r.name, r.email) for r in out.rows] == [("Ada", "ada@example.com")]

    def test_an_empty_file_says_so(self):
        with pytest.raises(CsvFormatError):
            parse_member_csv(b"")

    def test_a_file_over_the_size_limit_is_refused(self):
        with pytest.raises(CsvFormatError) as exc:
            parse_member_csv(b"x" * (MAX_CSV_BYTES + 1))
        assert "MB" in str(exc.value)

    def test_a_very_long_file_is_truncated_and_says_so(self):
        rows = "\n".join(f"a{i}@example.com" for i in range(MAX_CSV_ROWS + 50))
        out = parse_member_csv(f"Email\n{rows}\n".encode())
        assert len(out.rows) == MAX_CSV_ROWS
        assert out.truncated is True

    def test_sniffing_reports_what_it_found(self):
        assert sniff_columns(["Full Name", "E-mail"]) == ("E-mail", "Full Name")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class TestExport:
    def _rows(self, res):
        text = res.text
        assert text.startswith("﻿"), "Excel needs the byte-order mark"
        return list(csv.reader(io.StringIO(text[1:])))

    def test_it_lists_members_and_pending_invitations_apart(
        self, client, db, collective,
    ):
        space, creator, member = collective
        db.add(SpaceInvitation(
            id=_uid("inv"), space_id=space.id, email="waiting@example.com",
            name="Waiting Person", role=SpaceRole.learner,
            invited_by_id=creator.id, token=_uid("tok"),
        ))
        db.commit()

        as_user(creator)
        res = client.get(EXPORT.format(slug=space.slug))
        assert res.status_code == 200
        rows = self._rows(res)
        assert rows[0] == ["Name", "Email", "Role", "Status", "Joined or invited (UTC)"]
        by_email = {r[1]: r for r in rows[1:]}
        assert by_email[member.email][3] == "Member"
        # An invitee is not a member, and the file must not imply it.
        assert by_email["waiting@example.com"][3] == "Invitation not sent"

    def test_a_sent_invitation_reads_as_invited(self, client, db, collective):
        from datetime import datetime

        space, creator, _m = collective
        db.add(SpaceInvitation(
            id=_uid("inv"), space_id=space.id, email="sent@example.com",
            role=SpaceRole.learner, invited_by_id=creator.id,
            token=_uid("tok"), sent_at=datetime.utcnow(),
        ))
        db.commit()
        as_user(creator)
        rows = self._rows(client.get(EXPORT.format(slug=space.slug)))
        assert {r[1]: r[3] for r in rows[1:]}["sent@example.com"] == "Invited"

    def test_a_formula_cannot_run_when_the_file_is_opened(
        self, client, db, collective, make_user,
    ):
        space, creator, _m = collective
        nasty = make_user(name="=cmd|'/c calc'!A1", email="nasty@example.com")
        _join(db, nasty, space)
        db.commit()
        as_user(creator)
        rows = self._rows(client.get(EXPORT.format(slug=space.slug)))
        cell = {r[1]: r[0] for r in rows[1:]}["nasty@example.com"]
        assert cell.startswith("'="), "a leading = must be neutralised"

    def test_it_carries_nothing_sensitive(self, client, collective):
        space, creator, _m = collective
        as_user(creator)
        res = client.get(EXPORT.format(slug=space.slug))
        lowered = res.text.lower()
        for forbidden in ("password", "hash", "stripe", "card", "token", "secret"):
            assert forbidden not in lowered, forbidden

    def test_the_filename_names_the_collective_and_the_day(self, client, collective):
        from datetime import datetime

        space, creator, _m = collective
        as_user(creator)
        res = client.get(EXPORT.format(slug=space.slug))
        disposition = res.headers["content-disposition"]
        assert space.slug in disposition
        assert datetime.utcnow().date().isoformat() in disposition
        assert res.headers["cache-control"] == "private, max-age=0, no-store"

    def test_another_collective_is_never_in_the_file(
        self, client, db, collective, make_user, make_space,
    ):
        space, creator, _m = collective
        other_space = make_space(creator=make_user(role="creator"))
        stranger = make_user(name="Else Where", email="elsewhere@example.com")
        _join(db, stranger, other_space)
        db.commit()
        as_user(creator)
        assert "elsewhere@example.com" not in client.get(
            EXPORT.format(slug=space.slug)).text


# ---------------------------------------------------------------------------
# Preview — and the promise that nothing happens yet
# ---------------------------------------------------------------------------

class TestPreview:
    def test_it_counts_each_kind(self, client, db, collective):
        space, creator, member = collective
        db.add(SpaceInvitation(
            id=_uid("inv"), space_id=space.id, email="pending@example.com",
            role=SpaceRole.learner, invited_by_id=creator.id, token=_uid("tok"),
        ))
        db.commit()
        as_user(creator)
        text = (
            "Name,Email\n"
            "New One,new1@example.com\n"
            "New Two,new2@example.com\n"
            f"Already In,{member.email}\n"
            "Already Asked,pending@example.com\n"
            "Twice,new1@example.com\n"
            "Broken,not-an-email\n"
        )
        res = upload(client, PREVIEW.format(slug=space.slug), text)
        assert res.status_code == 200
        body = res.json()
        assert body["valid"] == 4
        assert body["invalid"] == 1
        assert body["duplicates"] == 1
        assert body["already_member"] == 1
        assert body["already_invited"] == 1
        assert body["invitable"] == 2
        assert body["collective_name"] == space.name

    def test_it_writes_nothing(self, client, db, collective):
        space, creator, _m = collective
        before = db.query(SpaceInvitation).count()
        as_user(creator)
        upload(client, PREVIEW.format(slug=space.slug),
               "Email\nnobody@example.com\n")
        assert db.query(SpaceInvitation).count() == before

    def test_it_reports_line_numbers_and_not_values(self, client, collective):
        space, creator, _m = collective
        as_user(creator)
        res = upload(client, PREVIEW.format(slug=space.slug),
                     "Email\nbroken-one\ngood@example.com\n")
        body = res.json()
        assert body["invalid_lines"] == [2]
        assert "broken-one" not in res.text

    def test_it_offers_the_headings_when_the_guess_fails(self, client, collective):
        """Not an error — a question, with the answers to choose from."""
        space, creator, _m = collective
        as_user(creator)
        res = upload(client, PREVIEW.format(slug=space.slug),
                     "Person,Contact Point\nAda,ada@example.com\n")
        assert res.status_code == 200
        body = res.json()
        assert body["needs_email_column"] is True
        assert body["headings"] == ["Person", "Contact Point"]
        assert body["email_column"] is None
        assert body["invitable"] == 0
        assert "email column" in body["message"].lower()

    def test_an_unreadable_file_is_still_an_error(self, client, collective):
        space, creator, _m = collective
        as_user(creator)
        res = upload(client, PREVIEW.format(slug=space.slug), "   \n")
        assert res.status_code == 422

    def test_named_columns_are_honoured(self, client, collective):
        space, creator, _m = collective
        as_user(creator)
        res = upload(
            client, PREVIEW.format(slug=space.slug),
            "Person,Contact Point\nAda,ada@example.com\n",
            email_column="Contact Point", name_column="Person",
        )
        assert res.status_code == 200
        assert res.json()["invitable"] == 1


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

class TestImport:
    def test_it_creates_one_invitation_each(self, client, db, collective):
        space, creator, _m = collective
        as_user(creator)
        res = upload(client, IMPORT.format(slug=space.slug),
                     "Name,Email\nAda,ada@example.com\nGrace,grace@example.com\n")
        assert res.status_code == 201
        assert res.json()["invited"] == 2

        invites = db.query(SpaceInvitation).filter(
            SpaceInvitation.space_id == space.id).all()
        assert {i.email for i in invites} == {"ada@example.com", "grace@example.com"}
        assert {i.name for i in invites} == {"Ada", "Grace"}
        # Ordinary invitations: a token to accept with, and marked sent.
        assert all(i.token and i.sent_at for i in invites)
        assert all(i.role == SpaceRole.learner for i in invites)

    def test_importing_the_same_file_twice_invites_nobody_twice(
        self, client, db, collective,
    ):
        space, creator, _m = collective
        as_user(creator)
        text = "Email\nada@example.com\ngrace@example.com\n"
        first = upload(client, IMPORT.format(slug=space.slug), text).json()
        second = upload(client, IMPORT.format(slug=space.slug), text).json()

        assert first["invited"] == 2
        assert second["invited"] == 0
        assert second["already_invited"] == 2
        assert db.query(SpaceInvitation).filter(
            SpaceInvitation.space_id == space.id).count() == 2

    def test_an_existing_member_is_skipped_not_invited(self, client, db, collective):
        space, creator, member = collective
        as_user(creator)
        res = upload(client, IMPORT.format(slug=space.slug),
                     f"Email\n{member.email}\nnew@example.com\n").json()
        assert res["invited"] == 1
        assert res["already_member"] == 1
        assert db.query(SpaceInvitation).filter(
            SpaceInvitation.email == member.email).count() == 0

    def test_an_existing_account_is_invited_without_an_account_being_made(
        self, client, db, collective, make_user,
    ):
        """Somebody who already uses Fresh Collective, elsewhere."""
        from app.models.user import User

        space, creator, _m = collective
        outsider = make_user(name="Has Account", email="hasaccount@example.com")
        before = db.query(User).count()

        as_user(creator)
        res = upload(client, IMPORT.format(slug=space.slug),
                     f"Email\n{outsider.email}\n").json()
        assert res["invited"] == 1
        # An invitation, not an account and not a membership.
        assert db.query(User).count() == before
        assert db.query(SpaceMembership).filter(
            SpaceMembership.user_id == outsider.id,
            SpaceMembership.space_id == space.id,
        ).count() == 0

    def test_it_never_creates_a_membership(self, client, db, collective):
        space, creator, _m = collective
        before = db.query(SpaceMembership).filter(
            SpaceMembership.space_id == space.id).count()
        as_user(creator)
        upload(client, IMPORT.format(slug=space.slug),
               "Email\na@example.com\nb@example.com\nc@example.com\n")
        assert db.query(SpaceMembership).filter(
            SpaceMembership.space_id == space.id).count() == before

    def test_imported_invitations_appear_in_the_existing_pending_list(
        self, client, collective,
    ):
        space, creator, _m = collective
        as_user(creator)
        upload(client, IMPORT.format(slug=space.slug), "Email\nada@example.com\n")
        listed = client.get(f"/api/creator/spaces/{space.slug}/invitations")
        assert listed.status_code == 200
        assert "ada@example.com" in [i["email"] for i in listed.json()]

    def test_an_imported_invitation_can_be_cancelled_like_any_other(
        self, client, db, collective,
    ):
        space, creator, _m = collective
        as_user(creator)
        upload(client, IMPORT.format(slug=space.slug), "Email\nada@example.com\n")
        inv = db.query(SpaceInvitation).filter(
            SpaceInvitation.email == "ada@example.com").one()
        res = client.delete(
            f"/api/creator/spaces/{space.slug}/invitations/{inv.id}")
        assert res.status_code == 204

    def test_a_large_file_is_capped_and_says_so(self, client, db, collective):
        space, creator, _m = collective
        as_user(creator)
        rows = "\n".join(f"big{i}@example.com" for i in range(MAX_CSV_ROWS + 10))
        res = upload(client, IMPORT.format(slug=space.slug), f"Email\n{rows}\n").json()
        assert res["truncated"] is True
        assert res["invited"] == MAX_CSV_ROWS

    def test_invalid_rows_do_not_stop_the_rest(self, client, collective):
        space, creator, _m = collective
        as_user(creator)
        res = upload(client, IMPORT.format(slug=space.slug),
                     "Email\nbroken\nok@example.com\nalso broken\n").json()
        assert res["invited"] == 1
        assert res["invalid"] == 2


# ---------------------------------------------------------------------------
# Who may do any of this
# ---------------------------------------------------------------------------

class TestAuthorisation:
    def test_an_ordinary_member_cannot_export(self, client, collective):
        space, _creator, member = collective
        as_user(member)
        assert client.get(EXPORT.format(slug=space.slug)).status_code in (403, 404)

    def test_an_ordinary_member_cannot_import(self, client, collective):
        space, _creator, member = collective
        as_user(member)
        assert upload(
            client, IMPORT.format(slug=space.slug), "Email\na@example.com\n",
        ).status_code in (403, 404)

    def test_a_creator_of_another_collective_cannot(
        self, client, collective, make_user,
    ):
        space, _creator, _m = collective
        stranger = make_user(role="creator", name="Other Creator")
        as_user(stranger)
        assert client.get(EXPORT.format(slug=space.slug)).status_code in (403, 404)
        assert upload(
            client, IMPORT.format(slug=space.slug), "Email\na@example.com\n",
        ).status_code in (403, 404)

    def test_a_moderator_can(self, client, db, collective, make_user):
        space, _creator, _m = collective
        mod = make_user(role="creator", name="Mod Erator")
        _join(db, mod, space, role=SpaceRole.moderator)
        db.commit()
        as_user(mod)
        assert client.get(EXPORT.format(slug=space.slug)).status_code == 200

    def test_an_import_lands_only_in_the_named_collective(
        self, client, db, collective, make_user, make_space,
    ):
        space, creator, _m = collective
        other = make_space(creator=creator)
        _join(db, creator, other, role=SpaceRole.creator)
        db.commit()

        as_user(creator)
        upload(client, IMPORT.format(slug=space.slug), "Email\nada@example.com\n")
        assert db.query(SpaceInvitation).filter(
            SpaceInvitation.space_id == other.id).count() == 0

    def test_the_template_is_offered_to_managers_only(self, client, collective):
        space, creator, member = collective
        as_user(creator)
        res = client.get(TEMPLATE.format(slug=space.slug))
        assert res.status_code == 200
        assert "Email" in res.text
        as_user(member)
        assert client.get(
            TEMPLATE.format(slug=space.slug)).status_code in (403, 404)


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

class TestInvitationDelivery:
    """An imported invitation is sent the way a typed one is.

    Nothing reaches a mail provider from here: the event is emitted and
    routing is handed to a background task the test client never runs.
    What matters is that the event is the *same* event, because every
    safeguard — preferences, suppressions, the delivery guard — hangs
    off the event type and not off the endpoint that raised it.
    """

    def _events(self, db, space):
        from app.comms.models import CommunicationEvent

        return (
            db.query(CommunicationEvent)
            .filter(
                CommunicationEvent.event_type == "collective.invitation.sent",
                CommunicationEvent.context["space_id"].as_string() == space.id,
            )
            .all()
        )

    def test_one_invitation_event_each(self, client, db, collective):
        space, creator, _m = collective
        as_user(creator)
        upload(client, IMPORT.format(slug=space.slug),
               "Email\nada@example.com\ngrace@example.com\n")

        events = self._events(db, space)
        assert len(events) == 2
        addresses = {e.payload["recipient_email"] for e in events}
        assert addresses == {"ada@example.com", "grace@example.com"}

    def test_the_event_carries_what_the_template_needs(self, client, db, collective):
        space, creator, _m = collective
        as_user(creator)
        upload(client, IMPORT.format(slug=space.slug), "Email\nada@example.com\n")

        from app.core.public_url import public_app_url

        event = self._events(db, space)[0]
        inv = db.query(SpaceInvitation).filter(
            SpaceInvitation.email == "ada@example.com").one()
        assert event.payload["collective_name"] == space.name
        assert event.payload["inviter_name"] == (creator.name or creator.email)
        # Absolute, and built the one way every other email link is —
        # a relative path here arrives in an inbox as a dead link.
        assert event.payload["accept_url"] == public_app_url(f"/invites/{inv.token}")
        assert event.subject_type == "invitation"

    def test_a_preview_emits_nothing(self, client, db, collective):
        space, creator, _m = collective
        as_user(creator)
        upload(client, PREVIEW.format(slug=space.slug), "Email\nada@example.com\n")
        assert self._events(db, space) == []

    def test_skipped_rows_are_not_emailed(self, client, db, collective):
        space, creator, member = collective
        as_user(creator)
        upload(client, IMPORT.format(slug=space.slug),
               f"Email\n{member.email}\nada@example.com\n")
        addresses = {e.payload["recipient_email"] for e in self._events(db, space)}
        assert addresses == {"ada@example.com"}


class TestARacingImport:
    """Two imports of overlapping lists, and the one that loses.

    ``space_invitations`` is unique on (space_id, email), so a row that
    slipped past classification because another request created it
    first fails on the way in. The import must then change nothing at
    all, rather than leaving a creator with half a file imported and no
    way to tell which half.
    """

    def test_it_fails_whole_and_leaves_nothing_behind(
        self, client, db, collective, monkeypatch,
    ):
        import app.creator.routes as routes

        space, creator, _m = collective
        db.add(SpaceInvitation(
            id=_uid("inv"), space_id=space.id, email="taken@example.com",
            role=SpaceRole.learner, invited_by_id=creator.id, token=_uid("tok"),
        ))
        db.commit()

        # Stand in for the other request having committed between this
        # one's classification and its own write.
        real = routes._classify_import

        def blind(db_, space_, parsed):
            _invitable, buckets = real(db_, space_, parsed)
            return list(parsed.rows), buckets

        monkeypatch.setattr(routes, "_classify_import", blind)

        as_user(creator)
        res = upload(client, IMPORT.format(slug=space.slug),
                     "Email\nnew@example.com\ntaken@example.com\n")
        assert res.status_code == 409
        assert "nothing was changed" in res.json()["detail"]
        # The row that would have been written is not there. (The count
        # of surviving rows is not worth asserting: this suite's
        # rollback also discards the fixture's own, which production's
        # would not.)
        assert db.query(SpaceInvitation).filter(
            SpaceInvitation.email == "new@example.com").count() == 0
