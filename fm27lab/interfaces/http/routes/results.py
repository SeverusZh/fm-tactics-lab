from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, Field

from fm27lab.adapters.storage_sqlite.repositories import JobRepository
from fm27lab.application.results import ResultsService
from fm27lab.interfaces.http.common import ErrorEnvelope, _query_integer, require_token
from fm27lab.interfaces.http.routes.jobs import JobOutput


class JobMetricsOutput(BaseModel):
    n: int
    wins: int
    draws: int
    losses: int
    win_rate: float
    win_interval: list[float]
    goals_for: float
    goals_against: float
    points: float
    xg: float | None
    xga: float | None
    possession: float | None
    shots: float | None
    pass_completion: float | None


class PairedOutput(BaseModel):
    n: int
    goal_difference_delta: float | None


class ResultsSummaryOutput(BaseModel):
    job: JobOutput
    metrics: JobMetricsOutput | None
    paired: PairedOutput


class PoolSummaryEntryOutput(BaseModel):
    index: int
    name: str
    weight: int
    probability: float | None
    roster: bool


class PoolSummaryUniformOutput(BaseModel):
    enabled: bool
    attribute_value: int


class PoolSummaryOutput(BaseModel):
    enabled: bool
    entry_count: int
    mode: str | None = None
    rounds: int | None = None
    players: str | None = None
    uniform: PoolSummaryUniformOutput | None = None
    entries: list[PoolSummaryEntryOutput] | None = None
    draws: dict[str, int] = Field(default_factory=dict)


def _validation_error(error: ValueError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"code": "validation_failed", "message": str(error), "retriable": False},
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "not_found", "message": "任务不存在", "retriable": False},
    )


def register(app: FastAPI) -> None:
    def results() -> ResultsService:
        service = getattr(app.state, "results", None)
        if service is None:
            service = ResultsService(JobRepository(app.state.database))
            app.state.results = service
        return service

    @app.get(
        "/api/jobs/{job_id}/summary",
        response_model=ResultsSummaryOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def job_summary(
        job_id: str,
        side: Annotated[
            Any,
            Query(
                json_schema_extra={
                    "type": "integer",
                    "enum": [0, 1],
                    "minimum": 0,
                    "maximum": 1,
                    "default": 0,
                }
            ),
        ] = 0,
        _: None = Depends(require_token),
    ):
        try:
            side_value = _query_integer(str(side), "side", 0, 1)
        except ValueError as error:
            raise _validation_error(error) from error
        try:
            summary = results().summary(job_id, side=side_value)
        except ValueError as error:
            raise _validation_error(error) from error
        if summary is None:
            raise _not_found()
        return summary

    @app.get(
        "/api/jobs/{job_id}/pool-summary",
        response_model=PoolSummaryOutput,
        response_model_exclude_unset=True,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def job_pool_summary(job_id: str, _: None = Depends(require_token)):
        try:
            summary = results().pool_summary(job_id)
        except ValueError as error:
            raise _validation_error(error) from error
        if summary is None:
            raise _not_found()
        return summary

    @app.get(
        "/api/jobs/{job_id}/export.csv",
        responses={
            200: {
                "description": "任务结果 CSV",
                "content": {"text/csv": {"schema": {"type": "string"}}},
            },
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def export_job_csv(job_id: str, _: None = Depends(require_token)):
        try:
            text = results().export_csv(job_id)
        except ValueError as error:
            raise _validation_error(error) from error
        if text is None:
            raise _not_found()
        return Response(
            content=text.encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="job-{job_id}.csv"'},
        )
