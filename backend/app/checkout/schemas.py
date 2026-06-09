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
