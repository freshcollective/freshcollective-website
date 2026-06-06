from pydantic import BaseModel, HttpUrl


class PathwayCheckoutRequest(BaseModel):
    pathway_id: str
    # Frontend constructs these URLs; {CHECKOUT_SESSION_ID} is replaced by Stripe
    success_url: str
    cancel_url: str


class PathwayCheckoutResponse(BaseModel):
    checkout_url: str
