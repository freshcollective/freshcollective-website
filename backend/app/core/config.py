import re

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Cloudflare R2 account IDs are 32-character hex strings — the value
# shown as "Account ID" in the R2 dashboard. Case-insensitive because
# DNS is case-insensitive and R2 accepts either form as the endpoint
# subdomain.
_R2_ACCOUNT_ID_RE = re.compile(r"[a-fA-F0-9]{32}")


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

    # SEC-010 Step 2 — shared authentication credential for the BFF's
    # X-Fc-Client-IP claim. When set on both fc-web and fc-api (same
    # value, entered via each service's Render Environment page), the
    # BFF forwards ``X-Fc-Bff-Auth: <secret>`` + ``X-Fc-Client-IP: <ip>``
    # on outbound calls; fc-api's rate-limit key function trusts the
    # forwarded client IP only after ``secrets.compare_digest`` verifies
    # the credential. When None (local dev, or unset in production for
    # any reason), the authenticated branch is skipped entirely and
    # every request is treated as public-path traffic — the header is
    # silently ignored, never trusted.
    #
    # Rotation: generate a new value, paste on fc-api, paste on fc-web.
    # Sequential restarts create a ~90-second window where limiter
    # accuracy briefly degrades but no security regression occurs.
    internal_bff_secret: str | None = None

    # SEC-007 — shared authentication credential for the four
    # ``/api/internal/*`` endpoints (dispatch-due, reconcile-shadow,
    # dev-test-send, send-event-reminders). Previously these endpoints
    # authenticated by string-comparing ``X-Internal-Token`` against
    # ``jwt_secret``, which conflated two distinct identity systems:
    # possession of the internal-endpoint credential would also mint
    # arbitrary user/admin session JWTs.
    #
    # Independent from ``jwt_secret`` and ``internal_bff_secret`` by
    # design — different trust domains with different rotation
    # cadences and blast radii. Do NOT reuse. Do NOT log. Compared
    # only via ``secrets.compare_digest``; see
    # ``app.core.internal_auth.verify_internal_token``.
    #
    # When None (unset), every ``/api/internal/*`` request fails
    # closed with 401 regardless of the presented token — better to
    # reject a legitimate cron than silently fall back to a more-
    # privileged credential.
    internal_comms_secret: str | None = None

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

    # Cloudflare R2 — persistent object storage. All six variables must
    # be present for R2 mode to activate; when any are unset the storage
    # module falls back to writing to the local filesystem
    # (``backend/uploads/``) so local dev and tests do not require R2
    # credentials. See ``app/core/storage.py`` and ``app/uploads/routes.py``.
    #
    #   * R2_ACCOUNT_ID          — Cloudflare account ID (subdomain of
    #                              the S3-compatible endpoint URL)
    #   * R2_ACCESS_KEY_ID       — Access key issued for the FC token
    #   * R2_SECRET_ACCESS_KEY   — Secret component; never logged
    #   * R2_BUCKET_PRIVATE      — private bucket ("fc-media")
    #   * R2_BUCKET_PUBLIC       — public bucket ("fc-media-public"),
    #                              scope-limited to ``platform-artwork/*``
    #                              keys — matches the current split in
    #                              ``uploads/routes.py``.
    #   * R2_PUBLIC_BASE_URL     — https origin the public bucket is
    #                              reachable at (R2.dev URL initially;
    #                              custom domain later)
    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket_private: str | None = None
    r2_bucket_public: str | None = None
    r2_public_base_url: str | None = None

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_r2_enabled(self) -> bool:
        """R2 storage mode is active iff every credential + bucket name +
        public URL is set. Missing any one falls back to filesystem
        (dev/test-friendly). Boolean is checked at every call site — see
        the module docstring in ``app/core/storage.py``.

        Production safety is enforced separately by
        ``_check_r2_configuration`` below — production boots refuse
        to start with an incomplete R2 config, and any environment
        refuses to start with a partial one. Those checks fire before
        this property ever returns False in a production process."""
        return all(
            v
            for v in (
                self.r2_account_id,
                self.r2_access_key_id,
                self.r2_secret_access_key,
                self.r2_bucket_private,
                self.r2_bucket_public,
                self.r2_public_base_url,
            )
        )

    @model_validator(mode="after")
    def _check_r2_configuration(self) -> "Settings":
        """Refuse to boot if R2 is misconfigured in a way that would
        silently downgrade production uploads to ephemeral disk, or
        in a way that would surface as an opaque boto3 error at
        upload time instead of a clear error at deploy time.

        Rules fired at Settings() instantiation (i.e., fc-api boot):

          1. **Trim whitespace on every R2 var.** Copy-paste from the
             Render dashboard commonly picks up trailing newlines or
             spaces which turn into invalid hostnames or keys later.
             Idempotent when values are already clean.

          2. **Production requires full R2.** If ``APP_ENV=production``
             and any R2 variable is missing, raise. On Render this
             aborts the deploy — the previous fc-api image continues
             to serve, so no upload ever lands on the ephemeral disk
             in a production-marked container.

          3. **No partial config anywhere.** If any R2 variable is set
             AND any other is missing, raise regardless of env. Catches
             half-configured local dev before it silently mixes R2
             writes with filesystem reads (or vice versa).

          4. **R2_ACCOUNT_ID format.** Cloudflare R2 account IDs are
             32-character hex strings. The value is interpolated into
             ``https://{id}.r2.cloudflarestorage.com`` as the S3 API
             endpoint (``core/storage.py``). Anything else — a template
             placeholder like ``<account>``, a full URL pasted in,
             surrounding quotes — makes boto3's hostname validator
             reject the endpoint at upload time with a cryptic
             ``Invalid endpoint`` message. Catching the format at
             boot surfaces the problem clearly, names the env var,
             and fails the deploy so the previous image keeps serving.

        Local dev and every existing test remain unaffected because
        they set zero R2 variables — the ``no-R2-and-not-production``
        branch is silent and returns the filesystem fallback.
        """
        # Rule 1 — trim whitespace on every R2 var in place.
        for name in (
            "r2_account_id",
            "r2_access_key_id",
            "r2_secret_access_key",
            "r2_bucket_private",
            "r2_bucket_public",
            "r2_public_base_url",
        ):
            raw = getattr(self, name)
            if raw is not None and raw != raw.strip():
                object.__setattr__(self, name, raw.strip())

        r2_vars = {
            "R2_ACCOUNT_ID": self.r2_account_id,
            "R2_ACCESS_KEY_ID": self.r2_access_key_id,
            "R2_SECRET_ACCESS_KEY": self.r2_secret_access_key,
            "R2_BUCKET_PRIVATE": self.r2_bucket_private,
            "R2_BUCKET_PUBLIC": self.r2_bucket_public,
            "R2_PUBLIC_BASE_URL": self.r2_public_base_url,
        }
        # Post-trim: whitespace-only values are now empty strings,
        # which the ``if v`` truthiness check correctly treats as
        # missing.
        present = sorted(k for k, v in r2_vars.items() if v)
        missing = sorted(k for k, v in r2_vars.items() if not v)

        # Rule 2 — production requires the full set.
        if self.app_env == "production" and missing:
            raise ValueError(
                "R2 storage is required in production but is not fully "
                f"configured. Missing env vars: {', '.join(missing)}. "
                "Set every R2_* env var on fc-api, or set "
                "APP_ENV=development if this environment is intentionally "
                "using the filesystem fallback (never for production)."
            )

        # Rule 3 — partial config is always an error.
        if present and missing:
            raise ValueError(
                "R2 storage is partially configured. Missing env vars: "
                f"{', '.join(missing)}. Either set every R2_* env var, "
                f"or unset {', '.join(present)} to fall back to "
                "filesystem storage. Refusing to boot with a mix — "
                "would silently direct some uploads at R2 and others "
                "at ephemeral disk."
            )

        # Rule 4 — R2_ACCOUNT_ID must be a 32-char hex string.
        # Only applied when the value is present; the presence/partial
        # rules above own the missing-value cases.
        if self.r2_account_id and not _R2_ACCOUNT_ID_RE.fullmatch(
            self.r2_account_id
        ):
            raise ValueError(
                "R2_ACCOUNT_ID must be a 32-character hex string (the "
                "value shown as 'Account ID' in the Cloudflare R2 "
                "dashboard) — not a URL, not surrounded by ``<>``, no "
                f"embedded whitespace. Received {len(self.r2_account_id)} "
                "characters. Fix the R2_ACCOUNT_ID env var on fc-api "
                "in the Render dashboard and redeploy."
            )

        return self

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
