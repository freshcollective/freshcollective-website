import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.rate_limit import client_ip_for_rate_limit

from app.services.scheduled_publisher import start_publisher, stop_publisher
from app.services.finite_plan_reconciler import (
    start_reconciler as start_finite_plan_reconciler,
    stop_reconciler as stop_finite_plan_reconciler,
)

from app.auth.routes import router as auth_router
from app.notifications.routes import router as notifications_router
from app.activities.routes import router as activities_router
from app.client.routes import router as client_router
from app.admin.routes import router as admin_router
from app.admin.atlas import router as admin_atlas_router
from app.admin.physical_locations import router as admin_physical_locations_router
from app.admin.community_care.routes import router as admin_community_care_router
from app.community_care.routes import router as community_care_router
from app.admin.world_guide.routes import router as admin_world_guide_router
from app.world_guide.routes import router as world_guide_router
from app.admin.platform_artwork import (
    admin_router as admin_platform_artwork_router,
    public_router as public_platform_artwork_router,
)
from app.sales.routes import router as sales_router
from app.spaces.routes import router as spaces_router, me_router, public_router, invites_router
from app.community.routes import router as community_router
from app.community.channels import (
    member_router as channels_member_router,
    creator_router as channels_creator_router,
)
from app.members.routes import members_router, profiles_router
from app.creator.routes import router as creator_router
from app.creator.build_your_collective import router as build_your_collective_router
from app.uploads.routes import uploads_router
from app.checkout.routes import router as checkout_router
from app.commerce.finite_plan_repair_routes import router as finite_plan_repair_router
from app.purchases.routes import router as purchases_router
from app.webhooks.routes import router as webhooks_router
from app.messages.routes import creator_router as messages_creator_router, member_router as messages_member_router
from app.places.routes import router as places_router
from app.comms.routes import (
    router as comms_admin_router,
    member_router as comms_member_router,
    internal_router as comms_internal_router,
    webhook_router as comms_webhook_router,
)
from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiter (in-memory; swap for Redis-backed in production)
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=client_ip_for_rate_limit)

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Background loop for the scheduled community-post publisher. See
    # app/services/scheduled_publisher.py for the idempotency contract.
    start_publisher()
    # FIP3 — grace-expiry sweeper for finite payment plans. Same
    # in-process asyncio pattern as the publisher; the sweep itself
    # is idempotent and safe under duplicate execution. See
    # app/services/finite_plan_reconciler.py.
    start_finite_plan_reconciler()
    # Comms M6 — surface a config gap that would otherwise fail silently
    # until the first real webhook fired. Outbound email still works
    # without this secret; delivery/bounce/complaint webhooks do not.
    # Never fatal — local dev without a Resend account is legitimate.
    if settings.resend_api_key and not settings.resend_webhook_secret:
        logger.warning(
            "Resend outbound sending is configured (RESEND_API_KEY set) "
            "but RESEND_WEBHOOK_SECRET is unset — outbound email still "
            "works, but delivery-status webhooks cannot be verified and "
            "will be rejected with HTTP 401."
        )
    try:
        yield
    finally:
        await stop_finite_plan_reconciler()
        await stop_publisher()


# SEC-003 — disable interactive API docs and the OpenAPI schema in
# production so unauthenticated visitors cannot enumerate the admin,
# internal, and webhook routes. Local development keeps them enabled
# so /docs remains the day-to-day API reference for the team.
app = FastAPI(
    title="Fresh Collective API",
    description="Member platform backend",
    version="0.1.0",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ---------------------------------------------------------------------------
# CORS — must be configured before routes are registered
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,   # Required for cookies to be sent cross-origin
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# SEC-011 Stage A — transport/content security headers
# ---------------------------------------------------------------------------
# fc-api serves JSON and files, never HTML documents (SEC-003 disables
# /docs, /redoc, /openapi.json in production). Only the headers that
# make sense on non-document responses are emitted here:
#
#   * Strict-Transport-Security — locks the client to HTTPS for the
#     configured origin. No ``includeSubDomains`` or ``preload`` in
#     Stage A per SEC-011 policy amendment 1; revisit when Fresh
#     Collective moves to its real production apex domain.
#
#   * X-Content-Type-Options: nosniff — refuse to reinterpret a
#     response as a different MIME type. Especially important on
#     /api/uploads/* where creators upload user content.
#
#   * Referrer-Policy: strict-origin-when-cross-origin — standard
#     modern default. Same-origin gets full referer; cross-origin
#     gets origin only; downgrades get nothing. Protects any
#     query-parameter tokens from leaking to third parties on
#     subsequent navigation.
#
# CSP, Permissions-Policy, X-Frame-Options, and frame-ancestors are
# deliberately NOT emitted here — they don't apply to JSON APIs.
# fc-web owns those on document responses.
# ---------------------------------------------------------------------------


_TRANSPORT_SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("Strict-Transport-Security", "max-age=31536000"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
)


@app.middleware("http")
async def add_transport_security_headers(request, call_next):
    """Attach the SEC-011 Stage A transport/content headers to every
    response. Middleware runs after the endpoint returns, so any
    endpoint-set header wins on collision — which is intentional for
    ``/api/uploads/*`` which adds its own ``Cross-Origin-Resource-
    Policy`` header on top of these defaults."""
    response = await call_next(request)
    for name, value in _TRANSPORT_SECURITY_HEADERS:
        # setdefault semantics — never overwrite an endpoint's own
        # header value if one is already present.
        response.headers.setdefault(name, value)
    return response

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth_router)
app.include_router(client_router)
app.include_router(admin_router)
app.include_router(admin_atlas_router)
app.include_router(admin_physical_locations_router)
app.include_router(admin_community_care_router)
app.include_router(community_care_router)
app.include_router(admin_world_guide_router)
app.include_router(world_guide_router)
app.include_router(admin_platform_artwork_router)
app.include_router(public_platform_artwork_router)
app.include_router(sales_router)
app.include_router(spaces_router)
app.include_router(me_router)
app.include_router(public_router)
app.include_router(community_router)
app.include_router(channels_member_router)
app.include_router(channels_creator_router)
app.include_router(members_router)
app.include_router(profiles_router)
app.include_router(creator_router)
app.include_router(build_your_collective_router)
app.include_router(uploads_router)
app.include_router(invites_router)
app.include_router(checkout_router)
app.include_router(finite_plan_repair_router)
app.include_router(purchases_router)
app.include_router(webhooks_router)
app.include_router(notifications_router)
app.include_router(activities_router)
app.include_router(messages_creator_router)
app.include_router(messages_member_router)
app.include_router(places_router)
app.include_router(comms_admin_router)
app.include_router(comms_member_router)
app.include_router(comms_internal_router)
app.include_router(comms_webhook_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["system"])
async def health() -> dict:
    return {"status": "ok"}
