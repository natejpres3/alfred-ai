from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, auth, learning, projects, settings, tutor
from app.config import get_settings
from app.services import workflow  # noqa: F401 - registers job handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=[s.public_web_url], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    for r in (auth.router, learning.router, projects.router, tutor.router, settings.router, admin.router):
        app.include_router(r)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    return app


app = create_app()
