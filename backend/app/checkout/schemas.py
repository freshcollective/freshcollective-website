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
