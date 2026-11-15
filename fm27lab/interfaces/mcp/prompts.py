"""MCP 提示词：引导受控实验设计与客队战术池复盘的中文模板。"""

from __future__ import annotations

from fm27lab.interfaces.mcp.protocol import McpPrompt, McpPromptArgument

DEFAULT_BASELINE = "默认取候选草案当前版本"
DEFAULT_SEEDS = "默认从 101 起连续 200 场"
DEFAULT_FOCUS = "默认关注胜率、净胜球与失球"


def build_prompts() -> list[McpPrompt]:
    return [_experiment_design(), _pool_review()]


def _experiment_design() -> McpPrompt:
    return McpPrompt(
        name="experiment-design",
        description="引导设计单变量受控战术对比实验，并说明样本量与判读口径。",
        arguments=(
            McpPromptArgument("draft_id", "候选草案标识", True),
            McpPromptArgument("instruction", "本次唯一的战术指令变更", True),
            McpPromptArgument("baseline_draft_id", "基线草案标识", False),
            McpPromptArgument("seeds", "起始种子与场数，格式 101:200", False),
        ),
        handler=_render_experiment_design,
    )


def _render_experiment_design(arguments: dict[str, str]) -> str:
    draft_id = arguments["draft_id"]
    instruction = arguments["instruction"]
    baseline = arguments.get("baseline_draft_id", DEFAULT_BASELINE)
    seeds = arguments.get("seeds", DEFAULT_SEEDS)
    return (
        "你正在为 FM Tactics Lab 设计一次受控战术对比实验。\n"
        f"- 候选草案：{draft_id}\n"
        f"- 本次唯一变量：{instruction}\n"
        f"- 基线草案：{baseline}\n"
        f"- 种子范围：{seeds}\n"
        "\n执行顺序：\n"
        "1. 调用 drafts_list 与 drafts_get 读取候选与基线场景，确认首发名单、针对性指令只保留上述唯一变量。\n"
        "2. 需要改动时调用 drafts_update 修改候选草案，不要同时调整多个变量。\n"
        f"3. 调用 jobs_create 提交实验任务：kind 填 experiment（必填），config 中注明 draft_id={draft_id}、"
        f"基线、种子范围 {seeds}，并给出 workers 与 total。\n"
        "4. 调用 jobs_get 或 jobs_list 轮询任务状态与进度，完成后调用 jobs_runs 读取逐场记录。\n"
        "5. 判读：先小样本校准流程，再用 200 场以上筛选；确认结论前至少复现两个独立种子块，"
        "并报告配对差值与置信区间。\n"
        "报告时列出基线、唯一变量、种子范围、样本量与结论，并说明未控制的因素。\n"
    )


def _pool_review() -> McpPrompt:
    return McpPrompt(
        name="pool-review",
        description="引导复盘客队战术池的抽签分布与逐条表现，判断结论能否外推。",
        arguments=(
            McpPromptArgument("job_id", "待复盘任务标识", True),
            McpPromptArgument("focus", "重点关注的指标", False),
        ),
        handler=_render_pool_review,
    )


def _render_pool_review(arguments: dict[str, str]) -> str:
    job_id = arguments["job_id"]
    focus = arguments.get("focus", DEFAULT_FOCUS)
    return (
        f"你正在复盘 FM Tactics Lab 任务 {job_id} 的客队战术池抽签结果。\n"
        f"- 重点关注：{focus}\n"
        "\n执行顺序：\n"
        "1. 调用 jobs_get 读取任务配置中的 away_tactic_pool，确认模式、条目与权重，"
        "并记下 entries 的下标与名称映射；pools_list 对应独立的战术池库，未必与任务内联池同源。\n"
        "2. 检查抽签分布是否符合模式：random 按权重分配，rotation 按顺序轮换。\n"
        "3. 调用 jobs_runs 读取逐场记录，按 stats.tactic_pool_entry 中的 index "
        '（整数或 {"index": n}）分组，再用 entries 映射成名称，比较胜率、净胜球与失球。\n'
        "4. 区分差异来自样本量不足、抽签分布偏差还是单一战术克制；样本不足时补足种子后再下结论。\n"
        "报告时列出每个条目的出场次数与对应指标，并说明结论能否外推到其他战术。\n"
    )
