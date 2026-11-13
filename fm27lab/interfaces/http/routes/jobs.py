from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from fm27lab.application.jobs import JobService
from fm27lab.interfaces.http.common import ID_PATTERN, ErrorEnvelope, _query_integer, require_token


class JobCreateInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    kind: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    config: dict[str, Any] = Field(default_factory=dict)
    workers: int = Field(default=1, ge=1, le=256)
    total: int = Field(default=0, ge=0)


class JobUpdateInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    status: str | None = None
    completed: int | None = Field(default=None, ge=0)
    summary: dict[str, Any] | None = None
    name: str | None = Field(default=None, min_length=1, max_length=100)


class JobBatchActionInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    action: Literal["cancel", "delete"]
    ids: list[Annotated[str, StringConstraints(pattern=ID_PATTERN)]] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        if len(set(self.ids)) != len(self.ids):
            raise ValueError("ids 不得重复")
        return self


class JobOutput(BaseModel):
    id: str
    kind: str
    status: str
    name: str | None
    config: dict[str, Any]
    summary: dict[str, Any]
    workers: int
    total: int
    completed: int
    created_at: str
    started_at: str | None
    finished_at: str | None


class JobListOutput(BaseModel):
    items: list[JobOutput]
    total: int
    next_offset: int | None


class JobRunOutput(BaseModel):
    job_id: str
    sequence: int
    variant: str
    seed: int
    score: list[int] | None
    verified: bool
    stats: dict[str, Any]
    events: dict[str, Any] | None
    log_path: str | None
    created_at: str


class JobRunListOutput(BaseModel):
    items: list[JobRunOutput]
    total: int
    next_offset: int | None


class JobBatchFailureOutput(BaseModel):
    id: str
    code: str
    message: str


class JobBatchActionOutput(BaseModel):
    succeeded: list[str]
    failed: list[JobBatchFailureOutput]


class JobBatchDeleteInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    ids: list[Annotated[str, StringConstraints(pattern=ID_PATTERN)]] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        if len(set(self.ids)) != len(self.ids):
            raise ValueError("ids 不得重复")
        return self


class JobBatchDeleteFailureOutput(BaseModel):
    id: str
    error: str


class JobBatchDeleteOutput(BaseModel):
    deleted: list[str]
    failed: list[JobBatchDeleteFailureOutput]


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

    @app.get(
        "/api/jobs",
        response_model=JobListOutput,
        responses={400: {"model": ErrorEnvelope}, 401: {"model": ErrorEnvelope}},
    )
    def list_jobs(
        status: Annotated[str | None, Query()] = None,
        limit: Annotated[
            str,
            Query(json_schema_extra={"type": "integer", "minimum": 1, "maximum": 256, "default": 50}),
        ] = "50",
        offset: Annotated[
            str,
            Query(json_schema_extra={"type": "integer", "minimum": 0, "maximum": 2**31 - 1, "default": 0}),
        ] = "0",
        _: None = Depends(require_token),
    ):
        try:
            return app.state.jobs.list(
                status=status,
                limit=_query_integer(limit, "limit", 1, 256),
                offset=_query_integer(offset, "offset", 0, 2**31 - 1),
            )
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail={"code": "validation_failed", "message": str(error), "retriable": False},
            ) from error

    @app.post(
        "/api/jobs",
        status_code=201,
        response_model=JobOutput,
        responses={400: {"model": ErrorEnvelope}, 401: {"model": ErrorEnvelope}},
    )
    def create_job(body: JobCreateInput, _: None = Depends(require_token)):
        try:
            return app.state.jobs.create(body.kind, body.name, body.config, body.workers, body.total)
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail={"code": "validation_failed", "message": str(error), "retriable": False},
            ) from error

    def cancel_failure(job_id: str) -> JobBatchFailureOutput | None:
        try:
            value = app.state.jobs.cancel(job_id)
        except ValueError:
            return JobBatchFailureOutput(
                id=job_id,
                code="invalid_transition",
                message="任务状态不允许该流转",
            )
        if value is None:
            return JobBatchFailureOutput(id=job_id, code="not_found", message="任务不存在")
        return None

    def delete_failure(job_id: str) -> JobBatchFailureOutput | None:
        try:
            deleted = app.state.jobs.delete(job_id)
        except ValueError as error:
            return JobBatchFailureOutput(
                id=job_id,
                code="validation_failed",
                message=str(error) or "任务标识无效",
            )
        if not deleted:
            return JobBatchFailureOutput(id=job_id, code="not_found", message="任务不存在")
        return None

    @app.post(
        "/api/jobs/actions",
        response_model=JobBatchActionOutput,
        responses={400: {"model": ErrorEnvelope}, 401: {"model": ErrorEnvelope}},
    )
    def batch_job_actions(body: JobBatchActionInput, _: None = Depends(require_token)):
        failure_handler = cancel_failure if body.action == "cancel" else delete_failure
        succeeded: list[str] = []
        failed: list[JobBatchFailureOutput] = []
        for job_id in body.ids:
            failure = failure_handler(job_id)
            if failure is None:
                succeeded.append(job_id)
            else:
                failed.append(failure)
        return JobBatchActionOutput(succeeded=succeeded, failed=failed)

    @app.delete(
        "/api/jobs",
        response_model=JobBatchDeleteOutput,
        responses={400: {"model": ErrorEnvelope}, 401: {"model": ErrorEnvelope}},
    )
    def batch_delete_jobs(body: JobBatchDeleteInput, _: None = Depends(require_token)):
        return app.state.jobs.batch_delete(body.ids)

    @app.get(
        "/api/jobs/{job_id}",
        response_model=JobOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def get_job(job_id: str, _: None = Depends(require_token)):
        return load_job(job_id)

    @app.patch(
        "/api/jobs/{job_id}",
        response_model=JobOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
        },
    )
    def update_job(job_id: str, body: JobUpdateInput, _: None = Depends(require_token)):
        changes = body.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "validation_failed",
                    "message": "任务更新至少需要一项字段",
                    "retriable": False,
                },
            )
        if "status" in changes:
            status = changes["status"]
            if not isinstance(status, str) or status not in JobService.TRANSITIONS:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "validation_failed", "message": "任务状态无效", "retriable": False},
                )
        if "completed" in changes and type(changes["completed"]) is not int:
            raise HTTPException(
                status_code=400,
                detail={"code": "validation_failed", "message": "任务进度无效", "retriable": False},
            )
        if "summary" in changes and not isinstance(changes["summary"], dict):
            raise HTTPException(
                status_code=400,
                detail={"code": "validation_failed", "message": "任务摘要必须是对象", "retriable": False},
            )
        current = load_job(job_id)
        # 状态机与进度越界都由服务层抛 ValueError，路由层按状态机区分 409 与 400。
        if "status" in changes and changes["status"] not in JobService.TRANSITIONS[current["status"]]:
            raise HTTPException(
                status_code=409,
                detail={"code": "invalid_transition", "message": "任务状态不允许该流转", "retriable": False},
            )
        if "completed" in changes and not 0 <= changes["completed"] <= current["total"]:
            raise HTTPException(
                status_code=400,
                detail={"code": "validation_failed", "message": "任务进度无效", "retriable": False},
            )
        try:
            value = app.state.jobs.update(job_id, changes)
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

    @app.post(
        "/api/jobs/{job_id}/cancel",
        response_model=JobOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
            409: {"model": ErrorEnvelope},
        },
    )
    def cancel_job(job_id: str, _: None = Depends(require_token)):
        load_job(job_id)
        try:
            value = app.state.jobs.cancel(job_id)
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "invalid_transition", "message": "任务状态不允许该流转", "retriable": False},
            ) from error
        if value is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": "任务不存在", "retriable": False},
            )
        return value

    @app.delete(
        "/api/jobs/{job_id}",
        status_code=204,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def delete_job(job_id: str, _: None = Depends(require_token)):
        try:
            deleted = app.state.jobs.delete(job_id)
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail={"code": "validation_failed", "message": str(error), "retriable": False},
            ) from error
        if not deleted:
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": "任务不存在", "retriable": False},
            )
        return Response(status_code=204)

    @app.get(
        "/api/jobs/{job_id}/runs",
        response_model=JobRunListOutput,
        responses={
            400: {"model": ErrorEnvelope},
            401: {"model": ErrorEnvelope},
            404: {"model": ErrorEnvelope},
        },
    )
    def list_job_runs(
        job_id: str,
        limit: Annotated[
            str,
            Query(json_schema_extra={"type": "integer", "minimum": 1, "maximum": 200, "default": 50}),
        ] = "50",
        offset: Annotated[
            str,
            Query(json_schema_extra={"type": "integer", "minimum": 0, "maximum": 2**31 - 1, "default": 0}),
        ] = "0",
        _: None = Depends(require_token),
    ):
        try:
            limit_value = _query_integer(limit, "limit", 1, 200)
            offset_value = _query_integer(offset, "offset", 0, 2**31 - 1)
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail={"code": "validation_failed", "message": str(error), "retriable": False},
            ) from error
        load_job(job_id)
        try:
            return app.state.jobs.runs(job_id, limit=limit_value, offset=offset_value)
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail={"code": "validation_failed", "message": str(error), "retriable": False},
            ) from error
