from __future__ import annotations

from fastapi import FastAPI

from fm27lab.interfaces.http.routes import (
    artifacts,
    catalog,
    draft_attributes,
    drafts,
    engine,
    experiments,
    fmf,
    jobs,
    pools,
    results,
    save_import,
    save_tactics,
    saves,
    settings,
    system,
    tactics,
)


def register_routes(app: FastAPI) -> None:
    system.register(app)
    engine.register(app)
    catalog.register(app)
    tactics.register(app)
    pools.register(app)
    drafts.register(app)
    draft_attributes.register(app)
    fmf.register(app)
    jobs.register(app)
    experiments.register(app)
    results.register(app)
    save_import.register(app)
    save_tactics.register(app)
    saves.register(app)
    artifacts.register(app)
    settings.register(app)
