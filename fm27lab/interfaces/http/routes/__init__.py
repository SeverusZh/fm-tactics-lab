from __future__ import annotations

from fastapi import FastAPI

from fm27lab.interfaces.http.routes import artifacts, drafts, jobs, pools, results, saves, system


def register_routes(app: FastAPI) -> None:
    system.register(app)
    pools.register(app)
    drafts.register(app)
    jobs.register(app)
    results.register(app)
    saves.register(app)
    artifacts.register(app)
