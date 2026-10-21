"""Public discovery of Offerings — Phase C, section 2.

Anonymous visitors browse a Collective's catalogue and read any
published Offering, without a session. That is the product premise:
*people discover creators through their Offerings*, which cannot
happen if finding one requires already belonging.

What must stay shut while that door is open is the whole point of this
file:

  * drafts are invisible to everyone but the people running the
    Collective, and invisible as a **404** so a guessed slug cannot be
    confirmed;
  * retired Offerings are readable (people own them) but absent from
    the catalogue (nothing is on sale);
  * no caller without an entitlement learns a storage key, a download
    URL, or anything about a file that has not passed validation;
  * no caller at all learns the Payment Option behind a paid Offering,
    because that id is a route around the Offering-specific purchase
    guards.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.models.offering import (
    Offering,
    OfferingEntitlement,
    OfferingEntitlementSource,
    OfferingEntitlementStatus,
    OfferingFile,
    OfferingFileValidationStatus as FVS,
    OfferingPricingKind,
    OfferingStatus,
)
from app.models.platform import SpaceMembership, SpaceMembershipStatus
from app.services import offering_covers as covers
from app.spaces import _offering_member_routes as member_api


def _uid(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _flag_on(offerings_enabled):
    """Every test here calls a handler directly, so the route gate is
    bypassed — but ``area_access`` reads the flag inside the request."""


def _offering(db, space, **kw) -> Offering:
    defaults = dict(
        id=_uid("off"), space_id=space.id,
        created_by_user_id=space.creator_id,
        slug=f"o-{uuid.uuid4().hex[:8]}",
        title="Morning Pages Workbook",
        summary="Twelve weeks of gentle daily pages.",
        default_cover_key=covers.DEFAULT_COVERS[0].key,
        status=OfferingStatus.published.value,
        pricing_kind=OfferingPricingKind.free.value,
        price_cents=None,
        published_at=datetime.utcnow(),
    )
    defaults.update(kw)
    off = Offering(**defaults)
    db.add(off)
    db.flush()
    return off


def _file(db, offering, **kw) -> OfferingFile:
    defaults = dict(
        id=_uid("of"), offering_id=offering.id,
        storage_key=f"offering-files/{offering.id}/{uuid.uuid4().hex}_workbook.pdf",
        original_filename="workbook.pdf",
        content_type="application/pdf",
        byte_size=8192, sort_order=0, resource_count=1,
        validation_status=FVS.passed.value,
        validated_at=datetime.utcnow(),
    )
    defaults.update(kw)
    f = OfferingFile(**defaults)
    db.add(f)
    db.flush()
    return f


def _own(db, user, offering, space) -> OfferingEntitlement:
    e = OfferingEntitlement(
        id=_uid("oe"), user_id=user.id, offering_id=offering.id,
        space_id=space.id,
        source=OfferingEntitlementSource.free.value,
        status=OfferingEntitlementStatus.active.value,
        acquired_at=datetime.utcnow(),
    )
    db.add(e)
    db.flush()
    return e


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------


class TestTheCatalogueIsPublic:

    def test_an_anonymous_visitor_sees_published_offerings(
        self, db, make_space,
    ):
        space = make_space()
        off = _offering(db, space)
        _file(db, off)
        out = member_api.list_member_offerings(
            space.slug, db=db, current_user=None,
        )
        assert [c["slug"] for c in out] == [off.slug]
        card = out[0]
        assert card["title"] == "Morning Pages Workbook"
        assert card["summary"] == "Twelve weeks of gentle daily pages."
        # The category was chosen but no administrator has uploaded its
        # World Artwork in this database, so the resolved cover is null
        # and the card renders its gradient.
        assert card["cover_image_url"] is None
        assert card["price_label"] == "Free"
        assert card["category_label"] == "PDF"
        assert card["viewer_owns"] is False

    def test_a_card_shows_the_shared_artwork_once_an_admin_uploads_it(
        self, db, make_space,
    ):
        """The point of moving defaults into World Artwork: an upload
        reaches every Offering using that category, with nothing stored
        on the Offering and nothing to backfill."""
        from app.models.platform import PlatformArtwork
        space = make_space()
        chosen = covers.DEFAULT_COVERS[0]
        off = _offering(db, space, default_cover_key=chosen.key)
        _file(db, off)
        db.add(PlatformArtwork(
            key=chosen.artwork_key,
            image_url="/api/uploads/platform-artwork/x/hero.webp",
        ))
        db.flush()
        [card] = member_api.list_member_offerings(
            space.slug, db=db, current_user=None,
        )
        assert card["cover_image_url"] == (
            "/api/uploads/platform-artwork/x/hero.webp"
        )

    def test_replacing_the_shared_artwork_updates_the_card(
        self, db, make_space,
    ):
        """Stated requirement, and the reason the Offering stores a key
        rather than a URL."""
        from app.models.platform import PlatformArtwork
        space = make_space()
        chosen = covers.DEFAULT_COVERS[0]
        off = _offering(db, space, default_cover_key=chosen.key)
        _file(db, off)
        row = PlatformArtwork(
            key=chosen.artwork_key,
            image_url="/api/uploads/platform-artwork/x/first.webp",
        )
        db.add(row)
        db.flush()
        [card] = member_api.list_member_offerings(
            space.slug, db=db, current_user=None,
        )
        assert card["cover_image_url"].endswith("first.webp")

        # An administrator replaces it. The Offering is not touched.
        row.image_url = "/api/uploads/platform-artwork/x/second.webp"
        db.flush()
        [card] = member_api.list_member_offerings(
            space.slug, db=db, current_user=None,
        )
        assert card["cover_image_url"].endswith("second.webp")
        db.refresh(off)
        assert off.cover_image_url is None, "nothing was written to the Offering"

    def test_a_creator_upload_is_unaffected_by_the_shared_artwork(
        self, db, make_space,
    ):
        """The other half: changing a shared default must not change a
        creator-customised cover."""
        from app.models.platform import PlatformArtwork
        space = make_space()
        chosen = covers.DEFAULT_COVERS[0]
        mine = "/api/uploads/offering-covers/off_x/abc_mine.webp"
        off = _offering(
            db, space, default_cover_key=chosen.key, cover_image_url=mine,
        )
        _file(db, off)
        row = PlatformArtwork(
            key=chosen.artwork_key,
            image_url="/api/uploads/platform-artwork/x/first.webp",
        )
        db.add(row)
        db.flush()
        [card] = member_api.list_member_offerings(
            space.slug, db=db, current_user=None,
        )
        assert card["cover_image_url"] == mine
        row.image_url = "/api/uploads/platform-artwork/x/second.webp"
        db.flush()
        [card] = member_api.list_member_offerings(
            space.slug, db=db, current_user=None,
        )
        assert card["cover_image_url"] == mine, (
            "a shared-artwork change altered a creator's own cover"
        )

    def test_a_paid_offering_states_its_price(self, db, make_space):
        space = make_space()
        off = _offering(
            db, space,
            pricing_kind=OfferingPricingKind.one_time.value,
            price_cents=2400,
        )
        _file(db, off)
        [card] = member_api.list_member_offerings(
            space.slug, db=db, current_user=None,
        )
        assert card["price_label"] == "$24"
        assert card["price_cents"] == 2400

    def test_a_price_with_cents_keeps_them(self, db, make_space):
        space = make_space()
        off = _offering(
            db, space,
            pricing_kind=OfferingPricingKind.one_time.value,
            price_cents=1950,
        )
        _file(db, off)
        [card] = member_api.list_member_offerings(
            space.slug, db=db, current_user=None,
        )
        assert card["price_label"] == "$19.50"

    def test_a_draft_is_absent_even_for_its_owner(
        self, db, make_space, make_user,
    ):
        """Drafts belong in Creator Studio. A creator who could see
        their draft here would be able to share a catalogue URL that
        works only for them."""
        from app.models.user import User
        space = make_space()
        owner = db.query(User).filter(User.id == space.creator_id).one()
        _offering(db, space, status=OfferingStatus.draft.value)
        assert member_api.list_member_offerings(
            space.slug, db=db, current_user=owner,
        ) == []

    def test_a_retired_offering_is_absent(self, db, make_space):
        """The catalogue is what is on sale. Its page stays readable —
        see ``TestTheDetailPage``."""
        space = make_space()
        _offering(
            db, space, status=OfferingStatus.retired.value,
            retired_at=datetime.utcnow(),
        )
        assert member_api.list_member_offerings(
            space.slug, db=db, current_user=None,
        ) == []

    def test_an_offering_with_no_approved_files_is_listed_but_not_acquirable(
        self, db, make_space,
    ):
        """Vanishing from the catalogue while a replacement file is
        being checked would look to its creator like deletion."""
        space = make_space()
        off = _offering(db, space)
        _file(db, off, validation_status=FVS.pending.value, validated_at=None)
        [card] = member_api.list_member_offerings(
            space.slug, db=db, current_user=None,
        )
        assert card["slug"] == off.slug
        assert card["has_downloadable_files"] is False
        assert card["file_count"] == 0

    def test_a_card_never_names_a_storage_key_or_a_payment_option(
        self, db, make_space,
    ):
        import json
        space = make_space()
        off = _offering(
            db, space,
            pricing_kind=OfferingPricingKind.one_time.value,
            price_cents=2400,
        )
        f = _file(db, off)
        blob = json.dumps(
            member_api.list_member_offerings(
                space.slug, db=db, current_user=None,
            ),
            default=str,
        )
        assert f.storage_key not in blob
        assert "payment_option" not in blob
        assert "offering-files/" not in blob

    def test_the_viewer_sees_what_they_already_own(
        self, db, make_space, make_user,
    ):
        space = make_space()
        buyer = make_user()
        mine = _offering(db, space)
        theirs = _offering(db, space)
        _file(db, mine)
        _file(db, theirs)
        _own(db, buyer, mine, space)
        out = member_api.list_member_offerings(
            space.slug, db=db, current_user=buyer,
        )
        owned = {c["slug"]: c["viewer_owns"] for c in out}
        assert owned[mine.slug] is True
        assert owned[theirs.slug] is False

    def test_offerings_from_another_collective_do_not_leak_in(
        self, db, make_space,
    ):
        a, b = make_space(), make_space()
        mine = _offering(db, a)
        _offering(db, b)
        _file(db, mine)
        out = member_api.list_member_offerings(
            a.slug, db=db, current_user=None,
        )
        assert [c["slug"] for c in out] == [mine.slug]

    def test_the_catalogue_closes_with_the_feature_flag(
        self, db, make_space, monkeypatch,
    ):
        """One switch, every surface. The flag drops ``offerings`` from
        ``area_access``, so the route 404s for the same reason the tab
        disappears."""
        from app.core.config import settings
        space = make_space()
        off = _offering(db, space)
        _file(db, off)
        monkeypatch.setattr(settings, "offerings_enabled", False)
        with pytest.raises(HTTPException) as e:
            member_api.list_member_offerings(
                space.slug, db=db, current_user=None,
            )
        assert e.value.status_code == 404


class TestCategoryLabels:
    """Derived from the files, never from the cover image — the covers
    are illustrations, and a photograph of headphones means "this is
    audio", not "headphones are included"."""

    @pytest.mark.parametrize("content_type,expected", [
        ("application/pdf", "PDF"),
        ("audio/mpeg", "Audio"),
        ("application/zip", "Bundle"),
        ("text/csv", "Spreadsheet"),
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         "Spreadsheet"),
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         "Document"),
    ])
    def test_a_single_type_names_itself(
        self, db, make_space, content_type, expected,
    ):
        space = make_space()
        off = _offering(db, space)
        _file(db, off, content_type=content_type)
        [card] = member_api.list_member_offerings(
            space.slug, db=db, current_user=None,
        )
        assert card["category_label"] == expected

    def test_mixed_types_say_so(self, db, make_space):
        space = make_space()
        off = _offering(db, space)
        _file(db, off, content_type="application/pdf")
        _file(db, off, content_type="audio/mpeg", sort_order=1)
        [card] = member_api.list_member_offerings(
            space.slug, db=db, current_user=None,
        )
        assert card["category_label"] == "Multiple formats"

    def test_a_zip_alongside_anything_is_still_a_bundle(self, db, make_space):
        space = make_space()
        off = _offering(db, space)
        _file(db, off, content_type="application/zip")
        _file(db, off, content_type="application/pdf", sort_order=1)
        [card] = member_api.list_member_offerings(
            space.slug, db=db, current_user=None,
        )
        assert card["category_label"] == "Bundle"

    def test_no_files_falls_back_rather_than_guessing(self, db, make_space):
        space = make_space()
        _offering(db, space)
        [card] = member_api.list_member_offerings(
            space.slug, db=db, current_user=None,
        )
        assert card["category_label"] == "Digital download"

    def test_the_cover_category_never_decides_the_file_category(
        self, db, make_space,
    ):
        """An Offering in the "Audio & meditations" *cover* category whose
        file is a PDF still reads "PDF".

        Two different notions of category share a word: the shared cover
        artwork a creator picks, and what the files actually are. The
        card's label must come from the files — otherwise a creator's
        choice of picture would misdescribe what a member downloads.
        """
        audio_cover = next(
            c for c in covers.DEFAULT_COVERS if c.key == "audio"
        )
        space = make_space()
        off = _offering(db, space, default_cover_key=audio_cover.key)
        _file(db, off, content_type="application/pdf")
        [card] = member_api.list_member_offerings(
            space.slug, db=db, current_user=None,
        )
        assert card["category_label"] == "PDF"


# ---------------------------------------------------------------------------
# The detail page
# ---------------------------------------------------------------------------


class TestTheDetailPage:

    def test_an_anonymous_visitor_reads_the_whole_page(self, db, make_space):
        space = make_space()
        off = _offering(db, space)
        _file(db, off, description="The twelve-week workbook.")
        out = member_api.get_member_offering(
            space.slug, off.slug, db=db, current_user=None,
        )
        assert out["title"] == "Morning Pages Workbook"
        assert out["price_label"] == "Free"
        assert out["file_count"] == 1
        assert out["files"][0]["name"] == "workbook.pdf"
        assert out["files"][0]["description"] == "The twelve-week workbook."
        assert out["can_acquire"] is True
        # Offered an account at the point of acquiring, not a wall.
        assert out["requires_account"] is True
        assert out["will_join_collective"] is True

    def test_an_anonymous_visitor_gets_no_download_url(self, db, make_space):
        space = make_space()
        off = _offering(db, space)
        f = _file(db, off)
        out = member_api.get_member_offering(
            space.slug, off.slug, db=db, current_user=None,
        )
        assert out["files"][0]["download_url"] is None
        assert out["viewer_owns"] is False
        import json
        assert f.storage_key not in json.dumps(out, default=str)

    def test_a_draft_is_a_404_for_a_stranger(self, db, make_space):
        space = make_space()
        off = _offering(db, space, status=OfferingStatus.draft.value)
        with pytest.raises(HTTPException) as e:
            member_api.get_member_offering(
                space.slug, off.slug, db=db, current_user=None,
            )
        assert e.value.status_code == 404

    def test_a_retired_offering_still_renders_and_says_so(
        self, db, make_space,
    ):
        """It stops selling, not serving. A 404 would look deleted to
        the people who own it."""
        from app.services import offering_acquisition as acq
        space = make_space()
        off = _offering(
            db, space, status=OfferingStatus.retired.value,
            retired_at=datetime.utcnow(),
        )
        _file(db, off)
        out = member_api.get_member_offering(
            space.slug, off.slug, db=db, current_user=None,
        )
        assert out["status"] == "retired"
        assert out["can_acquire"] is False
        assert out["acquire_blocked"] == acq.REASON_RETIRED
        assert out["acquire_message"]

    def test_an_owner_is_given_their_downloads_not_a_price(
        self, db, make_space, make_user,
    ):
        space = make_space()
        buyer = make_user()
        off = _offering(db, space)
        f = _file(db, off)
        _own(db, buyer, off, space)
        out = member_api.get_member_offering(
            space.slug, off.slug, db=db, current_user=buyer,
        )
        assert out["viewer_owns"] is True
        assert out["can_acquire"] is False, "already theirs"
        assert out["acquire_blocked"] is None, "owning is not a refusal"
        assert out["files"][0]["download_url"] == f"/api/uploads/{f.storage_key}"

    def test_an_unvalidated_file_is_described_to_nobody(
        self, db, make_space, make_user,
    ):
        space = make_space()
        buyer = make_user()
        off = _offering(db, space)
        _file(db, off)
        _file(
            db, off, original_filename="secret.pdf", sort_order=1,
            validation_status=FVS.quarantined.value,
            quarantined_at=datetime.utcnow(),
        )
        _own(db, buyer, off, space)
        out = member_api.get_member_offering(
            space.slug, off.slug, db=db, current_user=buyer,
        )
        assert [f["name"] for f in out["files"]] == ["workbook.pdf"]

    def test_the_membership_notice_is_silent_for_an_existing_member(
        self, db, make_space, make_user,
    ):
        space = make_space()
        member = make_user()
        db.add(SpaceMembership(
            id=_uid("sm"), space_id=space.id, user_id=member.id,
            role="learner", status=SpaceMembershipStatus.active,
            source="joined", joined_at=datetime.utcnow(),
        ))
        db.flush()
        off = _offering(db, space)
        _file(db, off)
        out = member_api.get_member_offering(
            space.slug, off.slug, db=db, current_user=member,
        )
        assert out["will_join_collective"] is False
        assert out["can_acquire"] is True

    def test_a_collective_that_manages_its_own_membership_promises_nothing(
        self, db, make_space, make_user,
    ):
        """World Builders and friends compute membership from platform
        eligibility. The page must not promise a join that
        ``membership_grant`` would decline."""
        space = make_space(auto_grant_role="creator")
        off = _offering(db, space)
        _file(db, off)
        out = member_api.get_member_offering(
            space.slug, off.slug, db=db, current_user=make_user(),
        )
        assert out["will_join_collective"] is False

    def test_the_detail_page_closes_with_the_feature_flag(
        self, db, make_space, monkeypatch,
    ):
        from app.core.config import settings
        space = make_space()
        off = _offering(db, space)
        _file(db, off)
        monkeypatch.setattr(settings, "offerings_enabled", False)
        with pytest.raises(HTTPException) as e:
            member_api.get_member_offering(
                space.slug, off.slug, db=db, current_user=None,
            )
        assert e.value.status_code == 404


class TestExistingPublicSurfacesAreUnchanged:
    """Section 12's regression line: adding a public area must not have
    disturbed the two that were already public."""

    def test_public_pathways_are_still_listable_anonymously(
        self, db, make_space,
    ):
        from app.models.platform import Pathway, PathwayType
        from app.spaces.routes import list_pathways
        space = make_space()
        db.add(Pathway(
            id=_uid("pw"), space_id=space.id, slug="p1", title="Practice",
            status="active", access_type="free",
            pathway_type=PathwayType.guided_experience,
        ))
        db.flush()
        out = list_pathways(space.slug, db=db, current_user=None)
        assert [p.slug for p in out] == ["p1"]

    def test_the_offerings_area_is_public_and_reachable(self, db, make_space):
        from app.spaces import area_access, area_policies
        space = make_space()
        resolved = area_access.resolve_area_access(db, space, None)
        assert resolved.can_reach(area_policies.AREA_OFFERINGS)
        assert resolved.can_reach(area_policies.AREA_ABOUT)
        # And the members-only ones stayed members-only for a stranger.
        assert not resolved.can_reach(area_policies.AREA_CONVERSATIONS)
        assert not resolved.can_reach(area_policies.AREA_HOME)

    def test_the_flag_drops_only_offerings_from_the_reachable_set(
        self, db, make_space, monkeypatch,
    ):
        from app.core.config import settings
        from app.spaces import area_access, area_policies
        space = make_space()
        before = set(area_access.resolve_area_access(db, space, None).reachable)
        monkeypatch.setattr(settings, "offerings_enabled", False)
        after = set(area_access.resolve_area_access(db, space, None).reachable)
        assert before - after == {area_policies.AREA_OFFERINGS}
