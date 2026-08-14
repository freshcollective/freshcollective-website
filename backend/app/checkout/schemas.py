from pydantic import BaseModel


class PathwayCheckoutRequest(BaseModel):
    pathway_id: str
    # Frontend constructs these URLs; {CHECKOUT_SESSION_ID} is replaced by Stripe
    success_url: str
    cancel_url: str
    # Optional: when set, price and metadata come from this payment option
    payment_option_id: str | None = None
    # Optional: when set, price and checkout mode come from this schedule
    payment_option_schedule_id: str | None = None


class PathwayCheckoutResponse(BaseModel):
    checkout_url: str


class GatheringSeriesCheckoutRequest(BaseModel):
    """Pay-in-full purchase of a Gathering Series pass.

    ``payment_option_id`` selects the tier (Awaken / Activate / Empower);
    ``payment_option_schedule_id`` selects the pay-in-full Schedule under
    that tier. Recurring instalments are rejected with 503 until Phase B
    of the checkout work lands.
    """

    series_id: str
    payment_option_id: str
    payment_option_schedule_id: str
    success_url: str
    cancel_url: str


class GatheringSeriesCheckoutResponse(BaseModel):
    checkout_url: str


# ---------------------------------------------------------------------------
# Unified checkout (B4B) — POST /api/checkout
#
# Kind-agnostic. The request never names a Pathway / Series /
# Gathering directly — the ``PaymentOption`` (identified by
# ``payment_option_id`` + ``payment_option_schedule_id``) is
# authoritative. What the purchase includes is derived at
# fulfilment time from ``PaymentOption.grants``.
# ---------------------------------------------------------------------------


class UnifiedCheckoutRequest(BaseModel):
    payment_option_id: str
    payment_option_schedule_id: str
    # Frontend constructs these URLs; ``{CHECKOUT_SESSION_ID}`` is
    # replaced by Stripe for the paid path. The free path returns
    # the caller's ``success_url`` verbatim as ``checkout_url``.
    success_url: str
    cancel_url: str


class UnifiedCheckoutResponse(BaseModel):
    """Response for :http:post:`/api/checkout`.

    The frontend redirects the browser to ``checkout_url``
    regardless of whether the option was paid (Stripe-hosted URL)
    or free (the request's ``success_url``). ``free`` and
    ``transaction_id`` are informational — the frontend can use
    ``free`` to skip a "redirecting to payment…" spinner, and
    ``transaction_id`` to reconcile in post-purchase state.
    """

    checkout_url: str
    transaction_id: str
    free: bool = False
