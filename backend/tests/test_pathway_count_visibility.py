"""Pathway counts agree with what the Pathways tab actually lists.

The bug: a Collective whose only Pathway was a draft advertised
"1 pathway" on Explore and "1 pathway" on its own page, while its
Pathways tab correctly said "No pathways yet". Worse, the draft row
travelled in full — title and all — inside the anonymous
``/api/spaces/{slug}`` payload.

Three surfaces disagreed because each decided for itself:

    Pathways tab    status IN (active, coming_soon)   ← correct
    Explore card    status != 'archived'              ← counted drafts
    SpaceResponse   unfiltered ORM relationship       ← counted everything

They now read one predicate from ``spaces/pathway_visibility.py``, and
these tests pin both halves: drafts never reach a public surface, and
published Pathways are NOT hidden merely for being paid.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.models.platform import (
    Pathway,
    PathwayType,
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceRole,
)
from app.spaces import pathway_visibility
from app.spaces.routes import get_space, hydrate_public_space_cards, list_pathways


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _pathway(db, space, *, status="active", access_type="free", title=None) -> Pathway:
    p = Pathway(
        id=_uid("pw"),
        space_id=space.id,
        slug=f"pw-{uuid.uuid4().hex[:8]}",
        title=title or f"Pathway {status}",
        status=status,
        access_type=access_type,
        pathway_type=PathwayType.guided_experience,
        pricing_mode="legacy",
        currency="AUD",
    )
    db.add(p)
    db.flush()
    return p


def _member(db, space, user, role=SpaceRole.learner):
    db.add(SpaceMembership(
        id=_uid("sm"), space_id=space.id, user_id=user.id,
        role=role, status=SpaceMembershipStatus.active,
    ))
    db.flush()


@pytest.fixture
def public_space(db, make_space):
    return make_space(status="active", is_public=True)


def _card_count(db, space) -> int:
    [card] = hydrate_public_space_cards([space], db)
    return card.pathway_count


def _detail_pathways(db, space, user=None):
    return get_space(space.slug, db=db, current_user=user).pathways


def _tab_slugs(db, space, user=None):
    return [p.slug for p in list_pathways(space.slug, db=db, current_user=user)]


# ---------------------------------------------------------------------------
# A draft must never reach a public surface
# ---------------------------------------------------------------------------


class TestADraftIsNotAdvertised:
    """The reported bug, from all three directions."""

    def test_explore_counts_zero(self, db, public_space):
        _pathway(db, public_space, status="draft", title="Know Yourself")
        assert _card_count(db, public_space) == 0

    def test_the_collective_page_counts_zero(self, db, public_space):
        _pathway(db, public_space, status="draft", title="Know Yourself")
        assert _detail_pathways(db, public_space) == []

    def test_the_draft_title_is_not_in_the_anonymous_payload(
        self, db, public_space,
    ):
        """The part that was more than a wrong number. The About page
        never rendered the title, but the payload carried it."""
        _pathway(db, public_space, status="draft", title="Know Yourself")
        titles = [p.title for p in _detail_pathways(db, public_space)]
        assert "Know Yourself" not in titles

    def test_the_tab_already_agreed(self, db, public_space):
        _pathway(db, public_space, status="draft")
        assert _tab_slugs(db, public_space) == []

    def test_a_plain_member_sees_no_draft_either(
        self, db, public_space, make_user,
    ):
        member = make_user()
        _member(db, public_space, member)
        _pathway(db, public_space, status="draft")
        assert _detail_pathways(db, public_space, member) == []

    def test_archived_is_excluded_too(self, db, public_space):
        _pathway(db, public_space, status="archived")
        assert _card_count(db, public_space) == 0
        assert _detail_pathways(db, public_space) == []


# ---------------------------------------------------------------------------
# A published Pathway IS counted — including a paid one
# ---------------------------------------------------------------------------


class TestPublishedPathwaysAreCounted:

    def test_active_counts(self, db, public_space):
        _pathway(db, public_space, status="active")
        assert _card_count(db, public_space) == 1
        assert len(_detail_pathways(db, public_space)) == 1

    def test_coming_soon_counts(self, db, public_space):
        """A published state the creator chooses deliberately, and one
        the Pathways tab has always shown."""
        _pathway(db, public_space, status="coming_soon")
        assert _card_count(db, public_space) == 1

    @pytest.mark.parametrize(
        "access_type",
        # The five values production actually holds. ``access_type`` is a
        # plain String column, not an enum, and ``included_with_offer``
        # -- the one EMBODY uses -- is named only in the
        # PaymentOption join table, so it is easy to miss when reading
        # the access rules alone.
        ["free", "included", "one_time", "subscription", "included_with_offer"],
    )
    def test_access_does_not_hide_a_published_pathway(
        self, db, public_space, access_type,
    ):
        """The half that is easy to get wrong in the other direction.

        Access decides whether a Pathway is UNLOCKED, not whether it is
        LISTED — ``list_pathways`` returns ``has_access`` per row and
        renders a locked card. Hiding paid Pathways from the counts
        would make them disagree with the tab again, and would hide a
        Collective's paid offering from the visitors it is meant to
        attract.
        """
        _pathway(db, public_space, status="active", access_type=access_type)
        assert _card_count(db, public_space) == 1
        assert len(_detail_pathways(db, public_space)) == 1

    def test_a_mixed_Collective_counts_only_the_listed_ones(
        self, db, public_space,
    ):
        _pathway(db, public_space, status="active")
        _pathway(db, public_space, status="coming_soon")
        _pathway(db, public_space, status="draft")
        _pathway(db, public_space, status="archived")
        assert _card_count(db, public_space) == 2
        assert len(_detail_pathways(db, public_space)) == 2


# ---------------------------------------------------------------------------
# The creator keeps their drafts
# ---------------------------------------------------------------------------


class TestCaretakersStillSeeEverything:

    def test_the_owner_sees_their_draft(self, db, public_space, make_user):
        from app.models.user import User
        owner = db.query(User).filter(User.id == public_space.creator_id).one()
        _pathway(db, public_space, status="draft", title="Know Yourself")

        titles = [p.title for p in _detail_pathways(db, public_space, owner)]
        assert "Know Yourself" in titles

    def test_the_owner_sees_their_draft_in_the_tab(
        self, db, public_space,
    ):
        from app.models.user import User
        owner = db.query(User).filter(User.id == public_space.creator_id).one()
        draft = _pathway(db, public_space, status="draft")
        assert draft.slug in _tab_slugs(db, public_space, owner)

    def test_a_moderator_sees_drafts(self, db, public_space, make_user):
        mod = make_user()
        _member(db, public_space, mod, role=SpaceRole.moderator)
        _pathway(db, public_space, status="draft")
        assert len(_detail_pathways(db, public_space, mod)) == 1

    def test_the_public_CARD_never_shows_drafts_even_to_the_owner(
        self, db, public_space,
    ):
        """The Explore listing is the anonymous public view. A creator's
        own count of their drafts belongs in Creator Studio, which
        derives it separately and deliberately."""
        _pathway(db, public_space, status="draft")
        assert _card_count(db, public_space) == 0


# ---------------------------------------------------------------------------
# Lifecycle: unpublishing and access changes
# ---------------------------------------------------------------------------


class TestLifecycle:

    def test_unpublishing_removes_it_from_the_counts(self, db, public_space):
        p = _pathway(db, public_space, status="active")
        assert _card_count(db, public_space) == 1

        p.status = "draft"
        db.flush()
        assert _card_count(db, public_space) == 0
        assert _detail_pathways(db, public_space) == []

    def test_publishing_adds_it(self, db, public_space):
        p = _pathway(db, public_space, status="draft")
        assert _card_count(db, public_space) == 0

        p.status = "active"
        db.flush()
        assert _card_count(db, public_space) == 1

    def test_changing_access_moves_nothing(self, db, public_space):
        """Access was never part of the predicate, so changing it
        cannot change a count — it only changes whether the listed
        Pathway is locked."""
        p = _pathway(db, public_space, status="active", access_type="free")
        before = _card_count(db, public_space)

        p.access_type = "one_time"
        db.flush()
        assert _card_count(db, public_space) == before == 1

    def test_no_count_is_stored(self, db, public_space):
        """Read at query time, so every lifecycle move lands on the
        next request with nothing to invalidate."""
        import inspect
        from app.spaces import routes
        src = inspect.getsource(routes.hydrate_public_space_cards)
        assert "pathway_visibility.LISTED_STATUSES" in src


# ---------------------------------------------------------------------------
# The three surfaces cannot drift apart again
# ---------------------------------------------------------------------------


class TestOneRuleThreeCallers:

    def test_the_count_and_the_tab_agree(self, db, public_space):
        for status in ("active", "coming_soon", "draft", "archived"):
            _pathway(db, public_space, status=status)
        assert _card_count(db, public_space) == len(_tab_slugs(db, public_space))

    def test_the_detail_payload_and_the_tab_agree(self, db, public_space):
        for status in ("active", "coming_soon", "draft", "archived"):
            _pathway(db, public_space, status=status)
        assert (
            {p.slug for p in _detail_pathways(db, public_space)}
            == set(_tab_slugs(db, public_space))
        )

    def test_the_predicate_filters_status_and_not_access(self):
        """Stated as a test because it is the decision most likely to
        be 'corrected' by somebody assuming paid means hidden."""
        assert pathway_visibility.LISTED_STATUSES == ("active", "coming_soon")
        import inspect
        import re
        src = inspect.getsource(pathway_visibility)
        # Comment-stripped: the module docstring explains at length why
        # access is NOT filtered, so a raw search would match the
        # explanation and pass vacuously.
        code = re.sub(r'"""[\s\S]*?"""', "", src)
        code = re.sub(r"#.*$", "", code, flags=re.M)
        assert "access_type" not in code, "the predicate reads access_type"

    def test_every_caller_reads_the_shared_module(self):
        import inspect
        from app.spaces import routes
        for fn in (
            routes.hydrate_public_space_cards,
            routes.list_pathways,
            routes.get_space,
        ):
            assert "pathway_visibility" in inspect.getsource(fn), fn.__name__


# ---------------------------------------------------------------------------
# The detail endpoints — found while verifying the counts fix
# ---------------------------------------------------------------------------


class TestADraftCannotBeFetchedDirectly:
    """The counts were the symptom; these were the exposure.

    ``get_pathway`` and ``get_pathway_overview`` both looked a Pathway up
    by slug with no status gate, and ``/overview`` takes an *optional*
    user. So an anonymous caller who knew the slug received the draft
    Pathway's title, description, price and every step title — and the
    public Collective payload handed out the slug.

    Confirmed against production before the fix: an unauthenticated GET
    of ``/api/spaces/life-in-full-colour/pathways/know-yourself/overview``
    returned HTTP 200, ``status='draft'`` and 15 step titles.
    """

    def _overview(self, db, space, slug, user=None):
        from app.spaces.routes import get_pathway_overview
        return get_pathway_overview(space.slug, slug, db=db, current_user=user)

    def _detail(self, db, space, slug, user):
        from app.spaces.routes import get_pathway
        return get_pathway(space.slug, slug, db=db, current_user=user)

    def test_anonymous_overview_of_a_draft_is_404(self, db, public_space):
        p = _pathway(db, public_space, status="draft", title="Know Yourself")
        with pytest.raises(HTTPException) as exc:
            self._overview(db, public_space, p.slug)
        assert exc.value.status_code == 404

    def test_the_step_titles_do_not_leak(self, db, public_space):
        """The specific payload that leaked: the ordered outline of
        unreleased creative work."""
        from app.models.platform import PathwayStep
        p = _pathway(db, public_space, status="draft")
        db.add(PathwayStep(
            id=_uid("st"), pathway_id=p.id, slug="s1",
            title="Why Knowing Yourself Matters", position=1,
            content_type="text", is_required=True,
        ))
        db.flush()
        with pytest.raises(HTTPException):
            self._overview(db, public_space, p.slug)

    def test_an_ordinary_member_cannot_fetch_a_draft(self, db, public_space, make_user):
        member = make_user()
        _member(db, public_space, member)
        p = _pathway(db, public_space, status="draft")
        with pytest.raises(HTTPException) as exc:
            self._overview(db, public_space, p.slug, member)
        assert exc.value.status_code == 404

    def test_any_authenticated_stranger_cannot_fetch_a_draft(
        self, db, public_space, make_user,
    ):
        """``get_pathway`` has no membership gate at all — signing up was
        enough to read any Collective's drafts."""
        stranger = make_user()
        p = _pathway(db, public_space, status="draft")
        with pytest.raises(HTTPException) as exc:
            self._detail(db, public_space, p.slug, stranger)
        assert exc.value.status_code == 404

    def test_archived_is_hidden_from_the_detail_endpoints_too(
        self, db, public_space,
    ):
        p = _pathway(db, public_space, status="archived")
        with pytest.raises(HTTPException):
            self._overview(db, public_space, p.slug)

    def test_404_not_403_so_the_slug_is_not_confirmed(self, db, public_space):
        """A 403 would tell a stranger the slug names something real."""
        p = _pathway(db, public_space, status="draft")
        with pytest.raises(HTTPException) as exc:
            self._overview(db, public_space, p.slug)
        assert exc.value.status_code == 404, "403 confirms the draft exists"

    # -- the other side: nothing published became harder to reach --

    @pytest.mark.parametrize(
        "access_type",
        # The five values production actually holds. ``access_type`` is a
        # plain String column, not an enum, and ``included_with_offer``
        # -- the one EMBODY uses -- is named only in the
        # PaymentOption join table, so it is easy to miss when reading
        # the access rules alone.
        ["free", "included", "one_time", "subscription", "included_with_offer"],
    )
    def test_a_published_pathway_is_still_reachable_anonymously(
        self, db, public_space, access_type,
    ):
        """Discoverability is not entitlement. A paid Pathway's detail
        page must still load for a stranger — that is the page they buy
        it from — and it reports ``user_has_access`` separately."""
        p = _pathway(db, public_space, status="active", access_type=access_type)
        got = self._overview(db, public_space, p.slug)
        assert got.slug == p.slug
        assert got.user_has_access is False or access_type == "free"

    def test_coming_soon_detail_still_loads(self, db, public_space):
        p = _pathway(db, public_space, status="coming_soon")
        assert self._overview(db, public_space, p.slug).slug == p.slug

    def test_the_owner_can_still_preview_their_draft(self, db, public_space):
        """The Creator Studio Preview flow. Caretakers are why this is a
        viewer check and not a blanket status filter."""
        from app.models.user import User
        owner = db.query(User).filter(User.id == public_space.creator_id).one()
        p = _pathway(db, public_space, status="draft", title="Know Yourself")
        assert self._overview(db, public_space, p.slug, owner).title == "Know Yourself"
        assert self._detail(db, public_space, p.slug, owner).slug == p.slug

    def test_a_moderator_can_preview_a_draft(self, db, public_space, make_user):
        mod = make_user()
        _member(db, public_space, mod, role=SpaceRole.moderator)
        p = _pathway(db, public_space, status="draft")
        assert self._overview(db, public_space, p.slug, mod).slug == p.slug

    def test_the_detail_gate_reads_the_shared_module(self):
        import inspect
        from app.spaces import routes
        src = inspect.getsource(routes._get_listed_pathway_or_404)
        assert "pathway_visibility.is_listed" in src
        assert "viewer_sees_all_pathways" in src

    def test_progress_reads_the_shared_module_too(self):
        """A fourth hand-written copy of the status list lived here."""
        import inspect
        from app.spaces import routes
        src = inspect.getsource(routes.list_pathways_progress)
        assert "pathway_visibility.listed_pathway_filter" in src
        assert '["active", "coming_soon"]' not in src


class TestPurchaseIsUnaffected:

    def test_checkout_still_requires_an_active_pathway(self):
        """Checkout had its own ``status != 'active'`` refusal already,
        so a draft was never purchasable and nothing here changed it."""
        import inspect
        from app.checkout import routes as checkout_routes
        src = inspect.getsource(checkout_routes)
        assert 'not available for purchase' in src
