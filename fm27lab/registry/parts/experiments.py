"""experiments 能力定义。"""

from __future__ import annotations

from fm27lab.registry.model import Capability

CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "experiments_submit",
        "提交实验批次",
        ("POST", "/api/experiments"),
        ("experiments", "submit"),
        "experiments_submit",
    ),
    Capability(
        "experiments_start",
        "启动下一个待运行实验",
        ("POST", "/api/experiments/start"),
        ("experiments", "start"),
        "experiments_start",
    ),
    Capability(
        "experiments_cancel",
        "取消实验任务",
        ("POST", "/api/experiments/{job_id}/cancel"),
        ("experiments", "cancel"),
        "experiments_cancel",
    ),
    Capability(
        "experiments_resume",
        "恢复实验任务",
        ("POST", "/api/experiments/{job_id}/resume"),
        ("experiments", "resume"),
        "experiments_resume",
    ),
)
