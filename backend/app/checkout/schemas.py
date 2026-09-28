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
    #: Optional discount code, exactly as the member typed it. Only the
    #: code travels — never an amount. The server re-validates it and
    #: recomputes the price from the Payment Option, so a client that
    #: sent a figure could not influence what is charged even if it
    #: tried, and one that sends a code already shown as valid by the
    #: preview may still be refused if it expired in between.
    discount_code: str | None = None
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


# ---------------------------------------------------------------------------
# Discount preview — POST /api/checkout/discount-preview
# ---------------------------------------------------------------------------


class DiscountPreviewRequest(BaseModel):
    """What a code would do to this offer's price.

    Names the same Option and Schedule as the checkout that follows,
    because the price being discounted has to come from the same place
    the charge will.
    """

    payment_option_id: str
    payment_option_schedule_id: str
    code: str


class DiscountPreviewResponse(BaseModel):
    """The answer, valid or not, always as a 200.

    A code that does not exist, has expired or does not apply here is a
    normal answer to a reasonable question — not a transport failure. If
    the endpoint returned 4xx for those, the frontend could not tell an
    unrecognised code from a dropped connection, and the member would
    see "something went wrong" when the truth is "that code expired on
    Sunday".

    Amounts are present only when ``valid``. There is no partial
    pricing: an invalid code has no amounts to show, and sending zeroes
    would invite a client to render them.
    """

    valid: bool
    #: The code as stored — trimmed and upper-cased — so the field can
    #: show the member the canonical form of what they typed.
    code: str
    #: Machine-readable rejection reason when invalid: ``not_found``,
    #: ``inactive``, ``expired``, ``limit_reached``, ``wrong_collective``,
    #: ``wrong_payment_option``, ``currency_mismatch``, ``not_purchasable``,
    #: ``below_minimum``.
    reason: str | None = None
    #: Plain-language reason, safe to show a member as-is.
    message: str | None = None

    original_amount_cents: int | None = None
    discount_amount_cents: int | None = None
    final_amount_cents: int | None = None
    currency: str | None = None
