"""Regression: PathwayCreateRequest must accept ``currency=null`` for
non-paid access types.

The NewPathway form on the frontend explicitly sends ``currency: null``
whenever the selected access type is ``free`` or ``included``. Before
the fix, the schema declared ``currency: str = 'AUD'`` (non-nullable
with a default), so Pydantic rejected the request with a 422 before
the route ever ran — meaning even the collective owner saw
"Could not create pathway. Please try again." with no server log.

The ``pathways.currency`` DB column is already nullable, so the
correct contract is ``currency: str | None``.
"""

from __future__ import annotations

import pytest

from app.creator.routes import create_pathway
from app.creator.schemas import PathwayCreateRequest


class TestPathwayCreateAcceptsNullCurrency:
    def test_schema_accepts_null_currency_for_free(self):
        body = PathwayCreateRequest(
            title="Free pathway",
            access_type="free",
            currency=None,
        )
        assert body.currency is None
        assert body.access_type == "free"

    def test_schema_accepts_null_currency_for_included(self):
        body = PathwayCreateRequest(
            title="Included pathway",
            access_type="included",
            currency=None,
        )
        assert body.currency is None
        assert body.access_type == "included"

    def test_schema_default_currency_still_aud(self):
        body = PathwayCreateRequest(title="Default")
        assert body.currency == "AUD"

    def test_schema_still_accepts_explicit_currency_for_paid(self):
        body = PathwayCreateRequest(
            title="Paid pathway",
            access_type="one_time",
            price_cents=2500,
            currency="USD",
        )
        assert body.currency == "USD"


class TestPathwayCreateEndToEnd:
    """The route itself must accept the same body and persist the pathway."""

    def test_create_free_pathway_with_null_currency(
        self, db, make_user, make_space
    ):
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        body = PathwayCreateRequest(
            title="Free pathway end-to-end",
            access_type="free",
            currency=None,
            create_channel=False,
        )
        result = create_pathway(
            slug=space.slug,
            body=body,
            db=db,
            current_user=owner,
        )
        assert result["title"] == "Free pathway end-to-end"
        assert result["access_type"] == "free"

    def test_create_included_pathway_with_null_currency(
        self, db, make_user, make_space
    ):
        owner = make_user(role="creator")
        space = make_space(creator=owner)
        body = PathwayCreateRequest(
            title="Included pathway end-to-end",
            access_type="included",
            currency=None,
            create_channel=False,
        )
        result = create_pathway(
            slug=space.slug,
            body=body,
            db=db,
            current_user=owner,
        )
        assert result["title"] == "Included pathway end-to-end"
        assert result["access_type"] == "included"
