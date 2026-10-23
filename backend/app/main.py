import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.rate_limit import client_ip_for_rate_limit
from app.checkout.stripe_client import (
    assert_api_version,
    installed_api_version,
    installed_package_version,
)

from app.services.scheduled_publisher import start_publisher, stop_publisher
from app.services.finite_plan_reconciler import (
    start_reconciler as start_finite_plan_reconciler,
    stop_reconciler as stop_finite_plan_reconciler,
)
from app.services.offering_validation_worker import (
    start_offering_validation_worker,
    stop_offering_validation_worker,
)

from app.auth.routes import router as auth_router
from app.notifications.routes import router as notifications_router
from app.activities.routes import router as activities_router
from app.client.routes import router as client_router
from app.admin.routes import router as admin_router
from app.admin.access_revocation import router as admin_access_revocation_router
from app.admin.email_templates import router as admin_email_templates_router
from app.admin.plan_cancellation import router as admin_plan_cancellation_router
from app.admin.payout_batch_routes import router as admin_payout_batch_router
from app.creator.refund_routes import router as creator_refund_router
from app.creator.connect_routes import router as creator_connect_router
from app.admin.connect_routes import router as admin_connect_router
from app.creator.plan_cancellation_routes import router as creator_plan_cancellation_router
from app.admin.atlas import router as admin_atlas_router
from app.admin.physical_locations import router as admin_physical_locations_router
from app.admin.community_care.routes import router as admin_community_care_router
from app.community_care.routes import router as community_care_router
from app.admin.world_guide.routes import router as admin_world_guide_router
from app.world_guide.routes import router as world_guide_router
from app.admin.brand_assets import (
    admin_router as admin_brand_assets_router,
    public_router as public_brand_assets_router,
)
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
# Offerings creator management (Phase B4). A separate router so the
# feature-flag dependency is attached once, at the router, rather than
# remembered in each handler.
from app.creator._offering_routes import router as creator_offerings_router
from app.creator._offering_file_routes import (
    router as creator_offering_files_router,
)
from app.creator._offering_about_routes import (
    router as creator_offering_about_router,
)
from app.creator._welcome_email_routes import (
    router as creator_welcome_email_router,
)
from app.spaces._offering_member_routes import (
    router as member_offerings_router,
    me_router as member_collection_router,
)
from app.creator.attendance import router as creator_attendance_router
from app.creator.build_your_collective import router as build_your_collective_router
from app.creator.community_start import router as creator_community_start_router
from app.uploads.routes import uploads_router
from app.checkout.routes import router as checkout_router
from app.commerce.finite_plan_repair_routes import router as finite_plan_repair_router
from app.purchases.routes import router as purchases_router
from app.webhooks.routes import router as webhooks_router
from app.webhooks.connect_routes import router as webhooks_v2_router
from app.messages.routes import creator_router as messages_creator_router, member_router as messages_member_router
from app.peer_messages.routes import router as peer_messages_router
from app.places.routes import router as places_router
from app.ways_to_connect.routes import router as ways_to_connect_router
from app.comms.routes import (
    router as comms_admin_router,
    member_router as comms_member_router,
    internal_router as comms_internal_router,
    webhook_router as comms_webhook_router,
)
from app.core.config import settings
from app.core.observability import init_sentry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Error reporting
# ---------------------------------------------------------------------------
# Before ``FastAPI(...)`` on purpose: the SDK's FastAPI integration
# patches Starlette's middleware stack at init, so an app constructed
# first would not be instrumented.
#
# A no-op when ``SENTRY_DSN`` is unset, which is every local run and the
# whole test suite. No custom middleware and no per-site capture calls —
# the integration covers unhandled requests and the logging integration
# covers the ``logger.exception`` paths. See app/core/observability.py.
init_sentry("fc-api")

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
    # Offerings B5 — structural validation of uploaded Offering files.
    # The third in-process loop, on the same pattern as the two above.
    # A Render cron would cost $1/month minimum per service and start
    # work no sooner; this costs nothing and picks a file up within
    # ~20 seconds. Inspection runs via ``asyncio.to_thread`` so it
    # never blocks the event loop serving API requests. See
    # app/services/offering_validation_worker.py for the claim,
    # lease and retry contract.
    start_offering_validation_worker()
    # Stripe status at boot — makes Render logs the source of truth
    # when verifying a deploy. Boot-time config guards
    # (``_check_stripe_configuration`` in ``core/config.py``) already
    # refuse to instantiate ``Settings`` for mis-configured combos,
    # so at this point we only report the resolved state.
    # The API version is part of that resolved state and belongs in the
    # same line: FC sets none of its own, so the pinned SDK decides what
    # every request is sent under. Printing it makes "which API version
    # is production on?" answerable from the logs instead of from
    # requirements.txt plus a reading of the SDK internals.
    #
    # ``assert_api_version`` is local — two module attributes, no network
    # call — so this adds no boot-time dependency on Stripe being
    # reachable. It raises only on a major version change; see its
    # docstring for why refusing to boot is the safer failure there.
    stripe_version_notes = assert_api_version()
    logger.info(
        "Stripe: enabled=%s mode=%s app_env=%s sdk=%s api_version=%s",
        settings.stripe_enabled, settings.stripe_mode, settings.app_env,
        installed_package_version(), installed_api_version(),
    )
    # Offerings rollout state, on one line, so "is the pilot on and for
    # whom?" is answerable from the Render log rather than by reading two
    # environment variables and inferring how they combine.
    from app.services.offering_pilot import describe as _offerings_describe
    logger.info("%s", _offerings_describe())
    for note in stripe_version_notes:
        # Not fatal, but never quiet: a same-major version drift still
        # means this code is running against an API it was not tested
        # against.
        logger.critical("Stripe version drift: %s", note)
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
        await stop_offering_validation_worker()
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


# ---------------------------------------------------------------------------
# Offerings B5 — refuse an oversized upload before the body is parsed
# ---------------------------------------------------------------------------
#
# This has to be middleware, and that is the only reason it is not a
# route dependency: FastAPI parses a multipart body when it resolves the
# route's ``UploadFile`` parameter, and it resolves dependencies *after*
# that. A ``Depends`` guard would therefore run once the whole body had
# already been spooled to disk — too late to be a defence.
#
# Starlette spools a request body past 1 MB to a temporary file, so an
# unbounded upload is a disk-exhaustion vector rather than a memory one:
# the handler's own limit check (``offering_upload.received``) counts
# bytes as they are copied and is authoritative, but it only runs once
# Starlette has finished receiving. This closes that window by reading
# one header.
#
# Content-Length is client-supplied and therefore not trusted as proof of
# anything — a client that omits it or lies gets through here and is
# caught by the counting check downstream. What this stops is the honest
# large upload, which is the common case.
#
# 413, not 503: a refusal outside Sentry's captured 500–599 range, and
# the status that actually means "your request body is too big".

#: The platform ceiling plus room for multipart framing (boundaries, part
#: headers, the description field). Not a plan limit — plans are enforced
#: per creator downstream; this is the absolute maximum any upload
#: request may be.
_MAX_UPLOAD_REQUEST_BYTES = (50 * 1024 * 1024) + (1024 * 1024)


def _is_offering_file_upload(method: str, path: str) -> bool:
    """A POST to any Offering file endpoint.

    Deliberately not "any upload endpoint": every other upload surface in
    the platform enforces its own smaller limit in its handler, and
    widening this to them would be a behaviour change nobody asked for in
    this phase.

    Deliberately *broader*, though, than the matching rule in
    ``frontend/src/lib/uploadRouting.ts``, which covers only the two
    endpoints that actually carry a file. The asymmetry is intentional
    and the two rules are solving opposite problems:

      * There, a loose match would extend a 30-second timeout to 120
        seconds for a small JSON call, so the cost of over-matching is a
        browser connection held open four times too long. Precision is
        the safe direction.
      * Here, a loose match only refuses an absurdly large body on an
        endpoint that should never receive one — ``…/files/reorder``
        takes a list of ids. Over-matching costs nothing, and
        *under*-matching would leave a path on which a 5 GB body is
        spooled to disk before any handler sees it. Generosity is the
        safe direction.
    """
    if method != "POST":
        return False
    return "/offerings/" in path and (
        path.endswith("/files") or "/files/" in path
    )


@app.middleware("http")
async def limit_offering_upload_size(request, call_next):
    if _is_offering_file_upload(request.method.upper(), request.url.path):
        raw = request.headers.get("content-length")
        try:
            declared = int(raw) if raw else 0
        except ValueError:
            declared = 0
        if declared > _MAX_UPLOAD_REQUEST_BYTES:
            return JSONResponse(
                status_code=413,
                content={
                    "detail": {
                        "reason": "file_too_large",
                        "message": (
                            "That upload is too large. Each file must be "
                            "50 MB or smaller, and your plan may allow less."
                        ),
                    }
                },
            )
    return await call_next(request)

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
app.include_router(admin_access_revocation_router)
app.include_router(admin_plan_cancellation_router)
app.include_router(admin_payout_batch_router)
app.include_router(creator_refund_router)
app.include_router(creator_connect_router)
app.include_router(admin_connect_router)
app.include_router(creator_plan_cancellation_router)
app.include_router(admin_atlas_router)
app.include_router(admin_physical_locations_router)
app.include_router(admin_community_care_router)
app.include_router(community_care_router)
app.include_router(admin_world_guide_router)
app.include_router(world_guide_router)
app.include_router(admin_platform_artwork_router)
app.include_router(public_platform_artwork_router)
app.include_router(admin_brand_assets_router)
app.include_router(public_brand_assets_router)
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
app.include_router(creator_offerings_router)
app.include_router(creator_offering_files_router)
app.include_router(creator_offering_about_router)
app.include_router(creator_welcome_email_router)
app.include_router(member_offerings_router)
app.include_router(member_collection_router)
app.include_router(creator_attendance_router)
app.include_router(build_your_collective_router)
app.include_router(creator_community_start_router)
app.include_router(uploads_router)
app.include_router(invites_router)
app.include_router(checkout_router)
app.include_router(finite_plan_repair_router)
app.include_router(purchases_router)
app.include_router(webhooks_router)
app.include_router(webhooks_v2_router)
app.include_router(notifications_router)
app.include_router(activities_router)
app.include_router(messages_creator_router)
app.include_router(messages_member_router)
app.include_router(peer_messages_router)
app.include_router(places_router)
app.include_router(ways_to_connect_router)
app.include_router(comms_admin_router)
app.include_router(comms_member_router)
app.include_router(comms_internal_router)
app.include_router(comms_webhook_router)
app.include_router(admin_email_templates_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["system"])
async def health() -> dict:
    return {"status": "ok"}
