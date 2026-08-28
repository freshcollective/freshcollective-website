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

    # Stripe recurring Price IDs for Creator subscriptions. These live in
    # Stripe (Products → Prices) and are looked up by env var so no ID is
    # ever hard-coded in application source. Leave unset in development
    # when Stripe itself is not configured — the checkout service reports
    # an isolated "not configured" state rather than pretending to work.
    stripe_price_id_creator: str | None = None
    stripe_price_id_pro: str | None = None

    # Absolute base URL of the public frontend, used to build Stripe
    # success/cancel URLs. Defaults to `frontend_origin` when unset;
    # split as a distinct setting so a future CDN-fronted deployment can
    # override the payment return URL without changing CORS.
    public_app_url: str | None = None

    # Standalone Gathering ticket sales — hard-off by default. Even when
    # set to True, the checkout endpoint additionally refuses to create a
    # Session in live Stripe mode unless the operator has explicitly
    # confirmed the payout / merchant-of-record decision. See
    # docs/dev-testing-safety.md and the Stage 1 audit for details.
    standalone_gathering_sales_enabled: bool = False

    # FIP4A — public member checkout for finite payment plans
    # (``PaymentOptionSchedule.schedule_type='recurring_installments'``).
    # Hard-off by default. When True, member surfaces (Pathway detail
    # checkout, Series ways-to-join) present published recurring
    # schedules alongside pay-in-full choices and the unified
    # /api/checkout endpoint opens the existing FIP2 setup flow.
    #
    # Backend remains authoritative: the flag is consumed by
    # ``_schedule_is_member_checkoutable`` in ``spaces/routes.py`` and
    # surfaces to the frontend as the per-schedule
    # ``is_member_checkoutable`` field. The frontend never
    # independently decides checkoutability from an env var.
    #
    # Production-readiness prerequisites (before flipping to True in
    # live) are recorded in
    # ``docs/finite-payment-plans-stripe-config.md`` §5–§6:
    # external grace-expiry scheduler in place, Dashboard retry
    # setting confirmed "Leave the subscription past due".
    finite_plan_member_checkout_enabled: bool = False

    # Stripe Checkout Session lifetime for standalone Gathering tickets, in
    # minutes. Stripe supports 30–1440 minutes; we default to the platform
    # minimum so abandoned holds free up capacity quickly. Any change must
    # also fit within Stripe's supported range.
    gathering_checkout_expiry_minutes: int = 30

    # Email (Resend).
    #
    #   RESEND_API_KEY  — when unset, all email sends log a WARN and skip;
    #                     use this for local development.
    #   EMAIL_FROM      — RFC 5322 sender used on every message. When
    #                     unset, sends fail loudly with an ERROR (no
    #                     silent fallback to another domain). Format:
    #                     "Display Name <address@domain>".
    #   EMAIL_REPLY_TO  — optional distinct Reply-To. When unset,
    #                     replies go to EMAIL_FROM (the usual case).
    resend_api_key: str | None = None
    email_from: str | None = None
    email_reply_to: str | None = None
    # Resend inbound webhook secret (Svix format, e.g. "whsec_...").
    # When unset, the /api/webhooks/comms/resend receiver refuses
    # every payload with a 401 — no accidental "signature verified"
    # state in development.
    resend_webhook_secret: str | None = None

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

    # Communications Layer — rollout control (Milestone 5c).
    #
    #   COMMS_SHADOW      — when True, every emit() at an instrumented
    #                       trigger site also drives the M5b routing
    #                       pipeline in shadow mode. The legacy
    #                       communication path remains authoritative;
    #                       shadow observations never dispatch. Default
    #                       False keeps the new pipeline entirely dormant
    #                       in production.
    #   COMMS_LIVE_TOPICS — comma-separated topic and/or category keys
    #                       promoted to live routing. For each key in
    #                       this list, the legacy trigger no-ops and
    #                       the routing pipeline creates delivery_mode=
    #                       'live' intents that the worker dispatches.
    #                       Cutover is config-controlled only; there is
    #                       no database toggle or admin UI that can
    #                       flip a topic live. Recommended cutover
    #                       order: direct_messages, gatherings,
    #                       pathways, conversations, account,
    #                       moderation, creator_updates,
    #                       platform_updates. Requires 3 consecutive
    #                       UTC days of 100% shadow parity per the
    #                       admin parity report before promotion.
    comms_shadow: bool = False
    # R2A cutover (2026-08-23) — the four flows migrated in that
    # milestone are always live. Every emit for these topics routes
    # through the Communications Layer; the legacy trigger paths
    # for the same events no-op via ``is_event_live()`` guards.
    #
    # Any deployment that must keep a topic on the legacy path
    # (e.g. a rollback) can override this env var to omit that
    # topic. Adding a topic here is a code change, deliberately —
    # topic promotion should always ride a PR.
    #
    # Topic keys:
    #   * security      — account.password_reset_requested
    #   * account       — collective.invitation.sent  (invite emails
    #                     ride the same preference-locked account
    #                     category as password reset),
    #                     account.welcome_after_signup,
    #                     creator.plan_activated
    #   * gatherings    — gathering.booking.confirmed
    #   * conversations — community.post.published,
    #                     community.comment.created
    #   * purchases     — purchase.completed, payment.instalment_failed,
    #                     access.suspended, payment.recovered,
    #                     purchase.plan_completed (all R3 events;
    #                     category is default-enabled + locked)
    comms_live_topics: str = "security,account,gatherings,conversations,purchases"
    # Minimum age (seconds) an event must reach before the shadow
    # reconciler will attempt to compare it. Gives both the legacy
    # BackgroundTasks trigger and the shadow routing task time to
    # complete before parity is assessed. Configurable so cron
    # cadence and infrastructure latency can be tuned without a code
    # change; default 60 seconds is conservative.
    comms_reconciler_min_event_age_seconds: int = 60

    # Community Care — Stage 2A ships review muscle behind this flag.
    # When False (the default), the /api/admin/community-care/* endpoints
    # respond with 503 so a half-built surface can't be discovered by
    # accident. Flip to True only when the review UI has been signed off
    # and the caretakers on rota are ready to work cases.
    community_care_enabled: bool = False

    # Discovery, Connection & Belonging — the peer pillar (Your World,
    # Explore Collectives, Discover Places, Ways to Connect). Phase 0
    # ships the data foundation only; nothing user-visible is gated by
    # this flag yet. Later phases add API endpoints and navigation
    # entries that will refuse to render when this is False.
    # See docs/foundations/discovery-connection-belonging-v1.1.md.
    discovery_pillar_enabled: bool = False

    # Location autocomplete provider for the Place & Feel picker.
    # Currently only 'nominatim' (OpenStreetMap) is supported. The
    # provider abstraction (app/services/location_providers) lets a
    # future adapter (Mapbox, Google Places, OpenCage) slot in
    # without touching routes, models or the Creator UI.
    location_provider: str = "nominatim"
    # Contact address advertised in the picker's outbound requests
    # (Nominatim requires a truthful UA identifying the operator).
    # Falls back to platform_owner_email if unset.
    location_provider_contact: str | None = None

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

    @property
    def resolved_public_app_url(self) -> str:
        """Base URL used to construct Stripe success/cancel URLs.
        Falls back to `frontend_origin` when the dedicated
        `public_app_url` is unset."""
        return (self.public_app_url or self.frontend_origin).rstrip("/")


settings = Settings()
