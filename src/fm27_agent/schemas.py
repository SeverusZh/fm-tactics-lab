"""MCP tool, resource and prompt definitions for the fm27lab sidecar."""

SERVER_NAME = "fm27lab-mcp"
PROTOCOL_VERSIONS = ("2025-06-18", "2024-11-05")
LATEST_PROTOCOL = PROTOCOL_VERSIONS[0]

DRAFT_ID = {
    "type": "string",
    "pattern": "^dr_[0-9a-f]{12}$",
    "description": "草案标识，格式为 dr_ 加 12 位十六进制",
}
JOB_ID = {"type": "string", "minLength": 1, "description": "任务标识"}
SAVE_ID = {"type": "string", "minLength": 1, "description": "存档标识"}
CLUB_UID = {"type": "integer", "minimum": 0, "description": "俱乐部 UID"}
SIDE = {"type": "integer", "enum": [0, 1], "description": "球队侧 0 或 1，对应 scenario.teams 下标"}
PHASE = {
    "type": "string",
    "enum": ["in_possession", "out_of_possession"],
    "description": "比赛阶段",
}
WORKERS = {"type": "integer", "minimum": 1, "maximum": 4, "description": "并行原生会话数，上限由清单给出"}
EVENT_DETAILS = {
    "type": "boolean",
    "default": True,
    "description": "是否收集逐场事件明细",
}
WAIT = {"type": "boolean", "default": False, "description": "是否等待操作完成"}
TIMEOUT_SECONDS = {
    "type": "number",
    "minimum": 0,
    "default": 60,
    "description": "等待超时秒数，超时返回当前进度",
}
JOB_STATUS = {
    "type": "string",
    "enum": ["queued", "running", "complete", "error", "cancelled", "interrupted"],
    "description": "任务状态过滤",
}


def _object(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required)}


def _tool(name, description, input_schema):
    return {"name": name, "description": description, "inputSchema": input_schema}


_SEEDS = {
    "oneOf": [
        _object(
            {
                "start": {"type": "integer", "minimum": 0, "maximum": 4294967295},
                "count": {"type": "integer", "minimum": 1, "maximum": 10000},
            },
            required=("start", "count"),
        ),
        {
            "type": "array",
            "items": {"type": "integer", "minimum": 0, "maximum": 4294967295},
            "minItems": 1,
            "maxItems": 10000,
            "uniqueItems": True,
        },
    ],
    "description": "起始种子与数量 {start, count}，或 1 到 10000 个唯一整数",
}

_DRAFT_CREATE_PROPERTIES = {
    "source": {
        "type": "string",
        "enum": ["default", "save", "fmf", "job", "inline"],
        "description": "草案来源",
    },
    "name": {"type": "string", "maxLength": 100, "description": "草案名称"},
    "save_id": SAVE_ID,
    "club_uid": CLUB_UID,
    "tactic_index": {"type": "integer", "minimum": 0, "description": "存档战术序号"},
    "lineup": {
        "type": "array",
        "items": {"type": "integer", "minimum": 0},
        "description": "存档来源的可选首发列表",
    },
    "bench": {
        "type": "array",
        "items": {"type": "integer", "minimum": 0},
        "maxItems": 12,
        "description": "存档来源的可选替补列表",
    },
    "side": SIDE,
    "file_base64": {"type": "string", "description": "FMF 文件内容的 base64"},
    "file_path": {"type": "string", "minLength": 1, "description": "FMF 文件本机路径"},
    "base_scenario": {"type": "object", "description": "FMF 来源的基础场景"},
    "base_draft_id": DRAFT_ID,
    "job_id": JOB_ID,
    "variant": {"type": "string", "minLength": 1, "description": "任务导出中的方案名"},
    "scenario": {"type": "object", "description": "内联来源的 schema 4 场景"},
}

_DRAFT_EDIT_PROPERTIES = {
    "draft_id": DRAFT_ID,
    "op": {
        "type": "string",
        "enum": ["team_instruction", "mentality", "role", "player_instruction",
                 "lineup", "formation", "tactic_name"],
        "description": "语义编辑操作",
    },
    "side": SIDE,
    "phase": PHASE,
    "group": {"type": "string", "minLength": 1, "description": "指令组标识"},
    "option": {"type": "integer", "minimum": 0, "description": "指令选项"},
    "value": {
        "oneOf": [
            {"type": "integer", "minimum": 1, "maximum": 7},
            {"type": "string", "minLength": 1},
        ],
        "description": "mentality 取 1 到 7；tactic_name 取非空字符串",
    },
    "slot": {"type": "integer", "minimum": 0, "maximum": 10, "description": "位置序号"},
    "role": {"type": "string", "minLength": 1, "description": "位置角色"},
    "duty": {"type": "string", "minLength": 1, "description": "可选职责"},
    "starters": {
        "type": "array",
        "items": {"type": "integer", "minimum": 0},
        "minItems": 11,
        "maxItems": 11,
        "uniqueItems": True,
        "description": "11 名首发球员序号",
    },
    "bench": {
        "type": "array",
        "items": {"type": "integer", "minimum": 0},
        "maxItems": 12,
        "uniqueItems": True,
        "description": "0 到 12 名替补球员序号",
    },
    "positions": {
        "type": "array",
        "items": {"type": "string", "minLength": 1},
        "minItems": 11,
        "maxItems": 11,
        "uniqueItems": True,
        "description": "阶段阵型 11 个位置，必须含唯一 GK",
    },
}

_FMF_IMPORT_PROPERTIES = {
    "draft_id": DRAFT_ID,
    "side": SIDE,
    "file_base64": {"type": "string", "description": "FMF 文件内容的 base64"},
    "file_path": {"type": "string", "minLength": 1, "description": "FMF 文件本机路径"},
}

TOOLS = [
    _tool(
        "lab_status",
        "读取应用清单、引擎兼容状态、活动任务与存档活动状态。",
        _object({}),
    ),
    _tool(
        "engine_select",
        "设置 FM27 游戏根目录并执行兼容预检。",
        _object({"game_root": {"type": "string", "minLength": 1, "description": "游戏根目录"}},
                required=("game_root",)),
    ),
    _tool(
        "draft_create",
        "从默认场景、存档、战术文件、任务导出或内联场景创建草案。",
        _object(_DRAFT_CREATE_PROPERTIES, required=("source",)),
    ),
    _tool(
        "draft_get",
        "读取草案摘要；include_scenario 为真时附带完整场景。",
        _object(
            {
                "draft_id": DRAFT_ID,
                "include_scenario": {"type": "boolean", "default": False,
                                     "description": "是否返回完整场景"},
            },
            required=("draft_id",),
        ),
    ),
    _tool(
        "draft_edit",
        "对草案执行单步语义编辑，通过校验后落盘并返回变更摘要。",
        _object(_DRAFT_EDIT_PROPERTIES, required=("draft_id", "op")),
    ),
    _tool(
        "draft_validate",
        "校验草案并写入归一化场景，返回 valid、errors、records 与摘要。",
        _object({"draft_id": DRAFT_ID}, required=("draft_id",)),
    ),
    _tool(
        "draft_list",
        "列出全部草案摘要，按更新时间倒序。",
        _object({}),
    ),
    _tool(
        "draft_delete",
        "物理删除草案；已提交实验保存的场景快照不受影响。",
        _object({"draft_id": DRAFT_ID}, required=("draft_id",)),
    ),
    _tool(
        "career_import",
        "导入 .fm 存档并返回 save_id；wait 为真时等待到终态或超时。",
        _object(
            {
                "save_path": {"type": "string", "minLength": 1, "description": "存档文件路径"},
                "wait": WAIT,
                "timeout_seconds": TIMEOUT_SECONDS,
            },
            required=("save_path",),
        ),
    ),
    _tool(
        "career_status",
        "读取存档导入进度与元数据；省略 save_id 时返回当前存档状态。",
        _object({"save_id": SAVE_ID}),
    ),
    _tool(
        "career_team",
        "读取存档球队的球员、战术列表与选择。",
        _object({"save_id": SAVE_ID, "club_uid": CLUB_UID},
                required=("save_id", "club_uid")),
    ),
    _tool(
        "career_opponents",
        "扫描同联赛对手；wait 为真时等待完整报告或超时。",
        _object({"save_id": SAVE_ID, "club_uid": CLUB_UID, "wait": WAIT,
                 "timeout_seconds": TIMEOUT_SECONDS},
                required=("save_id", "club_uid")),
    ),
    _tool(
        "career_preview",
        "用草案场景预览指定对手，返回对手球队与来源。",
        _object(
            {
                "save_id": SAVE_ID,
                "club_uid": CLUB_UID,
                "key": {"type": "string", "minLength": 1, "description": "对手 key"},
                "draft_id": DRAFT_ID,
            },
            required=("save_id", "club_uid", "key", "draft_id"),
        ),
    ),
    _tool(
        "career_cancel",
        "取消存档导入或对手扫描。",
        {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["import", "opponents"],
                         "description": "取消类型"},
                "save_id": SAVE_ID,
                "club_uid": CLUB_UID,
            },
            "required": ["kind", "save_id"],
            "allOf": [{
                "if": {"properties": {"kind": {"const": "opponents"}},
                       "required": ["kind"]},
                "then": {"required": ["club_uid"]},
            }],
        },
    ),
    _tool(
        "experiment_run",
        "提交自由模式批次；提供 baseline_draft_id 时为同种子 A/B 对照实验。",
        _object(
            {
                "draft_id": DRAFT_ID,
                "baseline_draft_id": DRAFT_ID,
                "seeds": _SEEDS,
                "workers": WORKERS,
                "event_details": EVENT_DETAILS,
                "name": {"type": "string", "maxLength": 100, "description": "实验名称"},
            },
            required=("draft_id", "seeds"),
        ),
    ),
    _tool(
        "career_run",
        "提交存档对战批次；count 为每对手总场数，必须偶数且主客场各半。",
        _object(
            {
                "save_id": SAVE_ID,
                "club_uid": CLUB_UID,
                "draft_id": DRAFT_ID,
                "opponents": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                    "maxItems": 40,
                    "description": "对手 key 列表，来自 career_opponents",
                },
                "count": {"type": "integer", "minimum": 2, "maximum": 10000,
                          "multipleOf": 2, "description": "每对手总场数，必须偶数"},
                "first_seed": {"type": "integer", "minimum": 0, "maximum": 4294967295,
                               "description": "首场种子"},
                "baseline_draft_id": DRAFT_ID,
                "workers": WORKERS,
                "event_details": EVENT_DETAILS,
                "name": {"type": "string", "maxLength": 100, "description": "批次名称"},
            },
            required=("save_id", "club_uid", "draft_id", "opponents", "count", "first_seed"),
        ),
    ),
    _tool(
        "job_get",
        "读取任务详情与 runs 分页。",
        _object(
            {
                "job_id": JOB_ID,
                "runs_offset": {"type": "integer", "minimum": 0, "default": 0,
                                "description": "runs 起始偏移"},
                "runs_limit": {"type": "integer", "minimum": 1, "maximum": 200,
                               "default": 50, "description": "runs 分页大小"},
                "variant": {"type": "string", "minLength": 1, "description": "方案过滤"},
            },
            required=("job_id",),
        ),
    ),
    _tool(
        "job_wait",
        "轮询等待任务终态或超时；请求带 _meta.progressToken 时发送进度通知。",
        _object(
            {
                "job_id": JOB_ID,
                "timeout_seconds": {"type": "number", "minimum": 0, "maximum": 300,
                                    "default": 60, "description": "等待上限，最大 300 秒"},
                "poll_ms": {"type": "integer", "minimum": 50, "maximum": 60000,
                            "default": 1000, "description": "轮询间隔毫秒"},
            },
            required=("job_id",),
        ),
    ),
    _tool(
        "job_list",
        "按状态分页列出任务。",
        _object(
            {
                "status": JOB_STATUS,
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50,
                          "description": "分页大小"},
                "offset": {"type": "integer", "minimum": 0, "default": 0,
                           "description": "起始偏移"},
            }
        ),
    ),
    _tool(
        "job_action",
        "取消、续跑、删除或重命名任务。",
        {
            "type": "object",
            "properties": {
                "job_id": JOB_ID,
                "action": {"type": "string",
                           "enum": ["cancel", "resume", "delete", "rename"],
                           "description": "任务操作"},
                "workers": WORKERS,
                "name": {"type": "string", "maxLength": 100, "description": "新名称"},
            },
            "required": ["job_id", "action"],
            "allOf": [{
                "if": {"properties": {"action": {"const": "rename"}},
                       "required": ["action"]},
                "then": {"required": ["name"]},
            }],
        },
    ),
    _tool(
        "results_summary",
        "返回汇总指标、分数分布、配对差值、失败摘要与耗时。",
        _object({"job_id": JOB_ID}, required=("job_id",)),
    ),
    _tool(
        "results_matches",
        "逐场分页读取结果；指定 seed 时返回单场。",
        _object(
            {
                "job_id": JOB_ID,
                "variant": {"type": "string", "minLength": 1, "description": "方案过滤"},
                "seed": {"type": "integer", "minimum": 0, "maximum": 4294967295,
                         "description": "按种子读取单场"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50,
                          "description": "分页大小"},
                "offset": {"type": "integer", "minimum": 0, "default": 0,
                           "description": "起始偏移"},
                "include_events": {"type": "boolean", "default": False,
                                   "description": "是否保留逐场事件明细"},
            },
            required=("job_id",),
        ),
    ),
    _tool(
        "results_csv",
        "生成 CSV 写入 dataDir/agent/exports，返回 path、sha256 与 rows。",
        _object(
            {
                "job_id": JOB_ID,
                "out": {"type": "string", "minLength": 1,
                        "description": "dataDir/agent/exports 下的相对文件名，默认按 job_id 命名"},
            },
            required=("job_id",),
        ),
    ),
    _tool(
        "fmf_import",
        "把战术文件导入指定草案，校验并归一化后落盘。",
        {
            "type": "object",
            "properties": dict(_FMF_IMPORT_PROPERTIES),
            "required": ["draft_id", "side"],
            "oneOf": [{"required": ["file_base64"]}, {"required": ["file_path"]}],
        },
    ),
    _tool(
        "fmf_export",
        "从草案导出战术文件，返回 filename、path、sha256 与回读 report。",
        _object(
            {
                "draft_id": DRAFT_ID,
                "side": SIDE,
                "name": {"type": "string", "maxLength": 120, "description": "导出文件名"},
            },
            required=("draft_id", "side"),
        ),
    ),
    _tool(
        "setpiece_export",
        "从草案导出定位球文件，返回 filename、path、sha256 与回读 report。",
        _object(
            {
                "draft_id": DRAFT_ID,
                "side": SIDE,
                "type": {"type": "integer", "minimum": 0, "description": "定位球类型"},
                "variant": {"type": "integer", "minimum": 0, "description": "定位球变体"},
            },
            required=("draft_id", "side", "type", "variant"),
        ),
    ),
]

TOOL_BY_NAME = {tool["name"]: tool for tool in TOOLS}

RESOURCES = [
    {
        "uri": "fm27://manifest",
        "name": "manifest",
        "description": "应用清单、版本与能力",
        "mimeType": "application/json",
    },
    {
        "uri": "fm27://catalog",
        "name": "catalog",
        "description": "领域枚举与默认值",
        "mimeType": "application/json",
    },
    {
        "uri": "fm27://status",
        "name": "status",
        "description": "引擎兼容、活动任务与存档状态",
        "mimeType": "application/json",
    },
]

RESOURCE_TEMPLATES = [
    {
        "uriTemplate": "fm27://drafts/{draft_id}",
        "name": "draft",
        "description": "草案 JSON",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "fm27://jobs/{job_id}",
        "name": "job",
        "description": "任务摘要",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "fm27://jobs/{job_id}/export",
        "name": "job-export",
        "description": "任务汇总、方案与 provenance",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "fm27://jobs/{job_id}/logs/{name}",
        "name": "job-log",
        "description": "单场原始 JSONL 日志",
        "mimeType": "application/jsonl",
    },
    {
        "uriTemplate": "fm27://saves/{save_id}",
        "name": "save",
        "description": "存档导入状态与元数据",
        "mimeType": "application/json",
    },
]

PROMPTS = [
    {
        "name": "test_tactic_change",
        "description": "引导执行单变量对照实验，并用配对差值判断变化是否稳定。",
        "arguments": [
            {"name": "draft_id", "description": "待测草案标识", "required": True},
            {"name": "instruction", "description": "本次唯一的战术指令变更", "required": True},
            {"name": "seeds", "description": "起始种子与场数，格式 101:10", "required": False},
        ],
    },
    {
        "name": "compare_baseline_vs_current",
        "description": "引导读取基线与当前方案的配对差值并解释。",
        "arguments": [
            {"name": "baseline_draft_id", "description": "基线草案标识", "required": True},
            {"name": "draft_id", "description": "当前草案标识", "required": True},
            {"name": "seeds", "description": "起始种子与场数，格式 101:10", "required": False},
        ],
    },
    {
        "name": "opponent_sweep",
        "description": "引导存档多对手扫描与批次提交。",
        "arguments": [
            {"name": "save_id", "description": "存档标识", "required": True},
            {"name": "club_uid", "description": "俱乐部 UID", "required": True},
            {"name": "draft_id", "description": "待测草案标识", "required": True},
            {"name": "count", "description": "每个对手的场数，必须偶数", "required": False},
        ],
    },
]

PROMPT_BY_NAME = {prompt["name"]: prompt for prompt in PROMPTS}
