"""FastAPI application entrypoint. Multi-router surface + static frontend."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .responses import err
from .routers import auth, billing, clips, jobs, publish, stream
from .worker import start_worker

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    start_worker()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=f"{settings.app_name} SaaS", version="0.1.0", lifespan=lifespan)

    # Multi-router surface — pinned FastAPI keeps every include_router sub-route.
    app.include_router(auth.router)
    app.include_router(jobs.router)
    app.include_router(clips.router)
    app.include_router(stream.router)
    app.include_router(billing.router)
    app.include_router(publish.router)

    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/health")
    def health():
        return {"ok": True, "data": {"status": "healthy", "service": settings.app_name}}

    @app.get("/")
    def index():
        return FileResponse(str(WEB_DIR / "index.html"))

    @app.get("/dashboard")
    def dashboard():
        return FileResponse(str(WEB_DIR / "dashboard.html"))

    @app.exception_handler(404)
    async def not_found(request, exc):  # noqa: ANN001
        if request.url.path.startswith("/api/"):
            return err("not_found", "Resource not found.", status_code=404)
        return JSONResponse({"ok": False, "error": {"code": "not_found",
                             "message": "Not found"}}, status_code=404)

    return app


app = create_app()
