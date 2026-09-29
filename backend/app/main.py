"""GTA 7 Fuel Supply Intelligence & Resilience Platform - backend entrypoint."""
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from . import engine as engine_mod
from .config import get_settings
from .db import init_db
from .logging_setup import setup_logging
from .metrics import REQUEST_WINDOW
from .routers.api import router as api_router
from .routers.ops_api import router as ops_router

settings = get_settings()
setup_logging(settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    engine_mod.engine = engine_mod.Engine()
    await engine_mod.engine.start()
    yield
    await engine_mod.engine.stop()


app = FastAPI(title="GTA 7 Fuel Supply Intelligence & Resilience Platform", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def timing(request: Request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        if request.url.path.startswith("/api") and request.url.path != "/api/stream":
            REQUEST_WINDOW.add(time.perf_counter() - start, status)


app.include_router(api_router)
app.include_router(ops_router)
Instrumentator(excluded_handlers=["/metrics", "/api/stream"]).instrument(app).expose(app, include_in_schema=False)
