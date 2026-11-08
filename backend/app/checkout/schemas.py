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
    # Stage 4. A code, never an amount — the server prices it. Honoured
    # on all three shapes this endpoint serves (direct, Payment Option
    # pay-in-full, Payment Option instalments), so there is no door where
    # a member's valid code silently does nothing.
    discount_code: str | None = None


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
    # Stage 4 — §15 keeps Series purchasing on the existing arrangement
    # model, so a code here is a Payment Option code and goes through the
    # same hold as every other Option purchase.
    discount_code: str | None = None


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

    payment_option_id: str | None = None
    payment_option_schedule_id: str | None = None
    code: str

    # Stage 4 — the direct doors, which have no Payment Option.
    #
    # Exactly one shape must be named: an Option and its Schedule, OR a
    # direct kind and its experience. A request naming neither cannot be
    # priced, and one naming both would leave it ambiguous which price
    # the answer described. Enforced in the endpoint rather than by a
    # validator so the refusal can be a readable 422 detail.
    #
    # ``direct_kind`` is ``pathway`` or ``gathering``. A direct Offering
    # purchase is deliberately absent: that door already resolves to a
    # Payment Option server-side, so it previews as one.
    direct_kind: str | None = None
    direct_id: str | None = None

    # An Offering, named the way its door names it: by slug, because the
    # member knows which resource they want and has never heard of a
    # Payment Option.
    #
    # Resolved server-side to that Option and then priced as one — NOT as
    # a direct target. An Offering purchase genuinely is a Payment Option
    # purchase, so a code scoped to that Option must apply to it, and
    # treating it as "direct" would refuse the creator's own code.
    offering_space_slug: str | None = None
    offering_slug: str | None = None


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

    # Stage 4 — the instalment schedule, when the previewed arrangement
    # is a finite plan. §7: the member must see the ACTUAL discounted
    # schedule before agreeing to it, which means the real per-payment
    # figures rather than a total divided in the browser.
    #
    # ``installment_amount_cents`` is what instalments 1..N-1 cost and
    # ``final_installment_amount_cents`` the last, which absorbs any
    # rounding remainder. They are equal when the total divides evenly —
    # both are sent regardless, so a client renders accurately without
    # having to decide whether a remainder exists.
    #
    # All NULL for a pay-in-full preview, where ``final_amount_cents`` is
    # the whole answer.
    payment_mode: str | None = None
    installment_count: int | None = None
    installment_amount_cents: int | None = None
    final_installment_amount_cents: int | None = None


class OfferingCheckoutRequest(BaseModel):
    """Buy one paid Offering.

    The request names the **Offering**, not a Payment Option. That is
    the difference between this wrapper and
    ``POST /api/checkout``: a member browsing a Collective's
    catalogue knows which resource they want and has never heard of a
    Payment Option, so the server resolves the option from the
    Offering rather than making the client carry an id it would have
    to be told. It also means a client cannot name an option that
    sells something else.
    """

    space_slug: str
    offering_slug: str
    success_url: str
    cancel_url: str
    #: Optional. Validated server-side against the resolved option, so
    #: the existing space-scoped and option-scoped codes both work on
    #: an Offering with no change to the discount architecture.
    discount_code: str | None = None


class OfferingCheckoutResponse(BaseModel):
    """Where to send the browser, and what was created.

    ``free`` is always ``False`` here. A free Offering never reaches
    this endpoint — it has no Payment Option at all — and is claimed
    through ``POST /api/spaces/{slug}/offerings/{slug}/acquire``. The
    field exists for shape-compatibility with
    ``UnifiedCheckoutResponse`` so one client helper can read either.
    """

    checkout_url: str
    transaction_id: str
    free: bool = False
