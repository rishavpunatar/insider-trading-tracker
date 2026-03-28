from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from insider_tracker.config import load_settings
from insider_tracker.db import build_engine, build_session_factory, init_db
from insider_tracker.services.tracker import TrackerRuntime, TrackerService


logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    settings = load_settings()
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    init_db(engine)

    service = TrackerService(settings=settings, session_factory=session_factory)
    runtime = TrackerRuntime(service=service)

    templates = Jinja2Templates(directory=str(Path(__file__).parent / "web" / "templates"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime.start()
        try:
            yield
        finally:
            runtime.stop()

    app = FastAPI(title="Insider Trading Tracker", lifespan=lifespan)
    app.state.settings = settings
    app.state.tracker_service = service
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "web" / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        data = service.get_dashboard_data()
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "summary": data["summary"],
                "filings": data["filings"],
            },
        )

    @app.get("/filings/{filing_id}", response_class=HTMLResponse)
    def filing_detail(request: Request, filing_id: int):
        filing = service.get_filing_detail(filing_id)
        if filing is None:
            raise HTTPException(status_code=404, detail="Filing not found")
        return templates.TemplateResponse(
            "detail.html",
            {
                "request": request,
                "filing": filing,
            },
        )

    @app.get("/api/filings")
    def list_filings():
        return JSONResponse(content=service.list_filings())

    @app.get("/api/filings/{filing_id}")
    def filing_detail_json(filing_id: int):
        filing = service.get_filing_detail(filing_id)
        if filing is None:
            raise HTTPException(status_code=404, detail="Filing not found")
        return JSONResponse(content=filing)

    @app.post("/api/admin/run-discovery")
    def run_discovery():
        result = service.run_discovery_cycle()
        return JSONResponse(content=result.__dict__)

    @app.post("/api/admin/run-due-snapshots")
    def run_due_snapshots():
        result = service.process_due_snapshots()
        return JSONResponse(content=result.__dict__)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "environment": settings.app_env,
            "database_url": settings.database_url,
        }

    return app

