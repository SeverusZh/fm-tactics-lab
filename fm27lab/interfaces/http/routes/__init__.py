from __future__ import annotations

from fastapi import FastAPI

from fm27lab.interfaces.http.routes import (
    artifacts,
    catalog,
    draft_attributes,
    drafts,
    experiments,
    fmf,
    jobs,
    pools,
    results,
    saves,
    settings,
    system,
)


def register_routes(app: FastAPI) -> None:
    system.register(app)
    catalog.register(app)
    pools.register(app)
    drafts.register(app)
    draft_attributes.register(app)
    fmf.register(app)
    jobs.register(app)
    experiments.register(app)
    results.register(app)
    saves.register(app)
    artifacts.register(app)
    settings.register(app)
