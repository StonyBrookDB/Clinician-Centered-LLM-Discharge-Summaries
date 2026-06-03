"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, FileResponse

from eval_v2.config import TEMPLATES_DIR, STATIC_DIR, BASE_DIR, is_highlights_enabled
from eval_v2.auth.manager import manager, get_current_user_optional
from eval_v2.auth.routes import router as auth_router
from eval_v2.routes.overview import router as overview_router
from eval_v2.routes.ratings import router as ratings_router
from eval_v2.routes.documents import router as documents_router
from eval_v2.routes.highlights import router as highlights_router
from eval_v2.routes.annotations import router as annotations_router
from eval_v2.routes.incidental_findings import router as incidental_findings_router
from eval_v2.routes.note_search import router as note_search_router
from eval_v2.services.db_backup import start_periodic_db_backups, stop_periodic_db_backups


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start/stop background services on app lifecycle."""
    await start_periodic_db_backups(app)
    try:
        yield
    finally:
        await stop_periodic_db_backups(app)


app = FastAPI(title="Discharge Summary Evaluation System", lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Set up Jinja2 templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# Static asset routes (defined before routers to ensure they're matched first)
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Serve the favicon."""
    return FileResponse(BASE_DIR / "favicon.ico")


@app.get("/logo.jpg", include_in_schema=False)
async def logo():
    """Serve the logo image."""
    return FileResponse(BASE_DIR / "logo.jpg")


# Include routers
app.include_router(auth_router)
app.include_router(overview_router)
app.include_router(ratings_router)
app.include_router(documents_router)
if is_highlights_enabled():
    app.include_router(highlights_router)
app.include_router(annotations_router)
app.include_router(incidental_findings_router)
app.include_router(note_search_router)


@app.get("/")
async def root(request: Request, user: dict | None = Depends(get_current_user_optional)):
    """Root route - redirect to overview if logged in, otherwise to login."""
    if user:
        return RedirectResponse(url="/overview", status_code=302)
    return RedirectResponse(url="/login", status_code=302)
