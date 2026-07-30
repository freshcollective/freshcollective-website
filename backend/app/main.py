import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.services.scheduled_publisher import start_publisher, stop_publisher

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
from app.webhooks.routes import router as webhooks_router
from app.messages.routes import creator_router as messages_creator_router, member_router as messages_member_router
from app.places.routes import router as places_router
from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiter (in-memory; swap for Redis-backed in production)
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Background loop for the scheduled community-post publisher. See
    # app/services/scheduled_publisher.py for the idempotency contract.
    start_publisher()
    try:
        yield
    finally:
        await stop_publisher()


app = FastAPI(
    title="Fresh Collective API",
    description="Member platform backend",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
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
app.include_router(webhooks_router)
app.include_router(notifications_router)
app.include_router(activities_router)
app.include_router(messages_creator_router)
app.include_router(messages_member_router)
app.include_router(places_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["system"])
async def health() -> dict:
    return {"status": "ok"}
