from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from fm27lab.application.experiment_material import DraftNotFound
from fm27lab.application.experiments import ResourceBlocked
from fm27lab.interfaces.http.common import ErrorEnvelope, require_token
from fm27lab.interfaces.http.routes.jobs import JobOutput

MAX_SEED = 0xFFFFFFFF
MAX_SEEDS = 10000
DRAFT_ID_PATTERN = r"^[A-Za-z0-9_-]+$"


class ExperimentSubmitInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    seeds: list[Annotated[int, Field(ge=0, le=MAX_SEED)]] = Field(
        min_length=1, max_length=MAX_SEEDS
    )
    draft_id: str = Field(min_length=1, max_length=64, pattern=DRAFT_ID_PATTERN)
    baseline_draft_id: str | None = Field(
        default=None, min_length=1, max_length=64, pattern=DRAFT_ID_PATTERN
    )
    workers: int = Field(ge=1, le=256)
    cpu_count: int = Field(ge=1)
    available_memory_bytes: int = Field(ge=0)
    free_disk_bytes: int = Field(ge=0)
    allow_oversubscription: bool = False

    @field_validator("seeds")
    @classmethod
    def validate_unique_seeds(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValueError("种子不能重复")
        return value


class ExperimentStartOutput(BaseModel):
    job: JobOutput


def register(app: FastAPI) -> None:
    def load_job(job_id: str) -> dict[str, Any]:
        try:
            value = app.state.jobs.get(job_id)
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail={"code": "validation_failed", "message": str(error), "retriable": False},
            ) from error
        if value is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": "任务不存在", "retriable": False},
            )
        return value

    def engine_unavailable(message: str) -> HTTPException:
        return HTTPException(
            status_code=503,
            detail={"code": "engine_unavailable", "message": message, "retriable": True},
        )

    @app.post(
        "/api/experiments",
        status_code=201,
        response_model=JobOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
        },
    )
    def submit_experiment(body: ExperimentSubmitInput, _: None = Depends(require_token)):
        try:
            return app.state.experiments.submit(
                {"seeds": body.seeds},
                workers=body.workers,
                name=body.name,
                cpu_count=body.cpu_count,
                available_memory_bytes=body.available_memory_bytes,
                free_disk_bytes=body.free_disk_bytes,
                allow_oversubscription=body.allow_oversubscription,
                draft_id=body.draft_id,
                baseline_draft_id=body.baseline_draft_id,
            )
        except DraftNotFound as error:
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": str(error), "retriable": False},
            ) from error
        except ResourceBlocked as error:
            raise HTTPException(
                status_code=409,
                detail={"code": error.code, "message": str(error), "retriable": True},
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail={"code": "validation_failed", "message": str(error), "retriable": False},
            ) from error

    @app.post(
        "/api/experiments/start",
        response_model=ExperimentStartOutput,
        responses={
            204: {"description": "没有待运行任务"},
            401: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
            503: {"model": ErrorEnvelope},
        },
    )
    def start_experiment(_: None = Depends(require_token)):
        try:
            started = app.state.experiments.start_next()
        except RuntimeError as error:
            raise engine_unavailable(str(error) or "引擎执行失败") from error
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "invalid_transition", "message": str(error), "retriable": False},
            ) from error
        if started is None:
            return Response(status_code=204)
        if started["status"] == "error":
            summary = started.get("summary")
            message = summary.get("error") if isinstance(summary, dict) else None
            raise engine_unavailable(message if isinstance(message, str) and message else "引擎执行失败")
        return {"job": started}

    @app.post(
        "/api/experiments/{job_id}/cancel",
        response_model=JobOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
        },
    )
    def cancel_experiment(job_id: str, _: None = Depends(require_token)):
        load_job(job_id)
        try:
            return app.state.experiments.cancel(job_id)
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "invalid_transition", "message": str(error), "retriable": False},
            ) from error

    @app.post(
        "/api/experiments/{job_id}/resume",
        response_model=JobOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
        },
    )
    def resume_experiment(job_id: str, _: None = Depends(require_token)):
        load_job(job_id)
        try:
            return app.state.experiments.resume(job_id)
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "invalid_transition", "message": str(error), "retriable": False},
            ) from error
