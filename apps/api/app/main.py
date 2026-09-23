"""FastAPI entrypoint: /api/v1 versioning, OpenAPI docs, CORS, rate limits, error envelope."""
from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import get_settings
from app.errors import error_response
from app.logging_config import new_request_id, request_id_ctx, setup_logging
from app.ratelimit import limiter
from app.routers import (
    audits, auth, competitors, gsc, health, keywords, organizations, overview,
    projects, providers, rankings, recommendations, reports, serp,
)

settings = get_settings()
setup_logging(settings.log_level)

if settings.app_env == "production" and settings.jwt_secret == "change-me-in-production-min-32-chars":
    raise RuntimeError("Refusing to boot: JWT_SECRET is still the dev default")

app = FastAPI(
    title="SEO Intelligence Platform",
    version="0.1.0",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    openapi_url="/api/v1/openapi.json",
)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return error_response(429, "RATE_LIMITED", "Rate limit exceeded. Try again later.")


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    # FastAPI HTTPException passes through with its own status; keep its message but wrap envelope
    from fastapi import HTTPException
    if isinstance(exc, HTTPException):
        return error_response(exc.status_code, "HTTP_ERROR", str(exc.detail))
    return error_response(500, "INTERNAL_ERROR", "An unexpected error occurred.")


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or new_request_id()
    request_id_ctx.set(rid)
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    # secure headers
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers["X-Process-Time"] = f"{(time.perf_counter()-start)*1000:.1f}ms"
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

prefix = settings.api_v1_prefix
app.include_router(health.router, prefix=prefix)
app.include_router(auth.router, prefix=prefix)
app.include_router(organizations.router, prefix=prefix)
app.include_router(projects.router, prefix=prefix)
app.include_router(audits.router, prefix=prefix)
app.include_router(overview.router, prefix=prefix)
app.include_router(providers.router, prefix=prefix)
app.include_router(serp.router, prefix=prefix)
app.include_router(keywords.router, prefix=prefix)
app.include_router(rankings.router, prefix=prefix)
app.include_router(competitors.router, prefix=prefix)
app.include_router(gsc.router, prefix=prefix)
app.include_router(recommendations.router, prefix=prefix)
app.include_router(reports.router, prefix=prefix)


@app.get("/")
def root():
    return {"name": settings.app_name, "version": "0.1.0", "docs": f"{prefix}/docs"}
