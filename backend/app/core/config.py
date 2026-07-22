from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 7
    frontend_origin: str = "http://localhost:3000"
    app_env: str = "development"

    # Stripe — set both values in .env before accepting real payments.
    # Leave blank/unset in development to disable Stripe endpoints gracefully.
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None

    # Standalone Gathering ticket sales — hard-off by default. Even when
    # set to True, the checkout endpoint additionally refuses to create a
    # Session in live Stripe mode unless the operator has explicitly
    # confirmed the payout / merchant-of-record decision. See
    # docs/dev-testing-safety.md and the Stage 1 audit for details.
    standalone_gathering_sales_enabled: bool = False

    # Stripe Checkout Session lifetime for standalone Gathering tickets, in
    # minutes. Stripe supports 30–1440 minutes; we default to the platform
    # minimum so abandoned holds free up capacity quickly. Any change must
    # also fit within Stripe's supported range.
    gathering_checkout_expiry_minutes: int = 30

    # Email (Resend) — optional; if unset, email sending is skipped gracefully.
    resend_api_key: str | None = None
    email_from: str = "Fresh Collective <notifications@mail.freshcollective.com>"

    # Platform owner — the founder / operator of Fresh Collective. Surfaces
    # as the "Owner" role badge in World Management. Only one person ever
    # holds this. Platform staff without founder status get the "admin"
    # role in the DB and render as their own badge, not Owner.
    platform_owner_email: str | None = None

    # Platform timezone — the local frame Fresh Collective operates in.
    # All period boundaries (month, financial year) are anchored here
    # rather than at UTC midnight, so "This month" and "This FY" mean
    # what the operator experiences on the wall clock, not what UTC says.
    # The Australian financial year runs 1 July → 30 June in this zone.
    platform_timezone: str = "Australia/Sydney"

    # Community Care — Stage 2A ships review muscle behind this flag.
    # When False (the default), the /api/admin/community-care/* endpoints
    # respond with 503 so a half-built surface can't be discovered by
    # accident. Flip to True only when the review UI has been signed off
    # and the caretakers on rota are ready to work cases.
    community_care_enabled: bool = False

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def stripe_enabled(self) -> bool:
        return bool(self.stripe_secret_key and self.stripe_webhook_secret)

    @property
    def stripe_mode(self) -> str:
        """'live' when STRIPE_SECRET_KEY starts with sk_live_, 'test' otherwise."""
        if self.stripe_secret_key and self.stripe_secret_key.startswith("sk_live_"):
            return "live"
        return "test"


settings = Settings()
