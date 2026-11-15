"""jobs 能力定义。"""

from __future__ import annotations

from fm27lab.registry.model import Capability

CAPABILITIES: tuple[Capability, ...] = (
    Capability("jobs_list", "分页列出实验任务", ("GET", "/api/jobs"), ("jobs", "list"), "jobs_list"),
    Capability("jobs_get", "查看单个实验任务", ("GET", "/api/jobs/{job_id}"), ("jobs", "get"), "jobs_get"),
    Capability("jobs_create", "创建实验任务", ("POST", "/api/jobs"), ("jobs", "create"), "jobs_create"),
    Capability(
        "jobs_update",
        "更新任务状态、进度或摘要",
        ("PATCH", "/api/jobs/{job_id}"),
        ("jobs", "update"),
        "jobs_update",
    ),
    Capability(
        "jobs_cancel",
        "取消实验任务",
        ("POST", "/api/jobs/{job_id}/cancel"),
        ("jobs", "cancel"),
        "jobs_cancel",
    ),
    Capability(
        "jobs_delete",
        "删除实验任务及其逐场记录",
        ("DELETE", "/api/jobs/{job_id}"),
        ("jobs", "delete"),
        "jobs_delete",
    ),
    Capability(
        "jobs_batch_actions",
        "批量取消或删除实验任务",
        ("POST", "/api/jobs/actions"),
        ("jobs", "batch-action"),
        "jobs_batch_actions",
    ),
    Capability(
        "jobs_batch_delete",
        "批量删除实验任务",
        ("DELETE", "/api/jobs"),
        ("jobs", "batch-delete"),
        "jobs_batch_delete",
    ),
    Capability(
        "jobs_runs",
        "分页查看任务逐场记录",
        ("GET", "/api/jobs/{job_id}/runs"),
        ("jobs", "runs"),
        "jobs_runs",
    ),
    Capability(
        "jobs_summary",
        "查看任务结果汇总",
        ("GET", "/api/jobs/{job_id}/summary"),
        ("jobs", "summary"),
        None,
    ),
    Capability(
        "jobs_export",
        "导出任务结果 CSV",
        ("GET", "/api/jobs/{job_id}/export.csv"),
        ("jobs", "export"),
        "jobs_export",
    ),
    Capability(
        "jobs_pool_summary",
        "查看任务客队战术池汇总",
        ("GET", "/api/jobs/{job_id}/pool-summary"),
        ("jobs", "pool-summary"),
        "jobs_pool_summary",
    ),
)
