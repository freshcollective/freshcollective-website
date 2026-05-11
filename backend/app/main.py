import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.auth.routes import router as auth_router
from app.client.routes import router as client_router
from app.admin.routes import router as admin_router
from app.sales.routes import router as sales_router
from app.spaces.routes import router as spaces_router, me_router
from app.creator.routes import router as creator_router
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

app = FastAPI(
    title="Fresh Collective API",
    description="Member platform backend",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
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
app.include_router(sales_router)
app.include_router(spaces_router)
app.include_router(me_router)
app.include_router(creator_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["system"])
async def health() -> dict:
    return {"status": "ok"}
