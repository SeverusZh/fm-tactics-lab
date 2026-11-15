export type JsonRecord = { [key: string]: unknown };

export type TunnelRequest = {
  method: string;
  path: string;
  query: URLSearchParams;
  body: JsonRecord | null;
};

export const HEALTH: JsonRecord = {
  status: "ok",
  api: "fm27lab/v2",
  version: "2.0.0.dev0",
  database: "ready",
};

const HOME_POSITIONS = ["GK", "DR", "DL", "DC", "DC", "DMC", "MC", "MC", "AMR", "AML", "ST"];
const AWAY_POSITIONS = ["GK", "DL", "DR", "DC", "DC", "DMC", "MC", "MC", "AML", "AMR", "ST"];

const IN_POSSESSION_ROLES = [
  "GK_ROLE_1",
  "FB_ROLE_1",
  "FB_ROLE_1",
  "CB_ROLE_1",
  "CB_ROLE_1",
  "DM_ROLE_1",
  "CM_ROLE_1",
  "CM_ROLE_1",
  "WING_ROLE_1",
  "WING_ROLE_1",
  "ST_ROLE_1",
];

const OUT_OF_POSSESSION_ROLES = [
  "GK_ROLE_2",
  "FB_ROLE_2",
  "FB_ROLE_2",
  "CB_ROLE_2",
  "CB_ROLE_2",
  "DM_ROLE_2",
  "CM_ROLE_2",
  "CM_ROLE_2",
  "WING_ROLE_2",
  "WING_ROLE_2",
  "ST_ROLE_2",
];

function cells(positions: string[], roles: string[]): JsonRecord[] {
  return positions.map((position, index) => ({ position, role: roles[index] }));
}

function squad(prefix: string): JsonRecord[] {
  return Array.from({ length: 23 }, (_value, index) => ({
    name: `${prefix}${String(index + 1).padStart(2, "0")}`,
  }));
}

/** 构造符合前端解析要求的双阶段场景，默认当前格式，不使用旧版 phase_plans。 */
export function buildScenario(overrides: JsonRecord = {}): JsonRecord {
  return {
    schema: 3,
    teams: [
      {
        name: "主队",
        players: squad("主"),
        roster_size: 23,
        lineup: Array.from({ length: 11 }, (_value, index) => index),
        captains: [0],
        takers: [10],
        setpieces: {},
        mentality: 4,
        instructions: { "1": 1, "4": 2, "9": 0 },
        phases: [cells(HOME_POSITIONS, IN_POSSESSION_ROLES), cells(HOME_POSITIONS, OUT_OF_POSSESSION_ROLES)],
      },
      {
        name: "客队",
        players: squad("客"),
        roster_size: 23,
        lineup: Array.from({ length: 11 }, (_value, index) => index),
        captains: [0],
        takers: [10],
        setpieces: {},
        mentality: 5,
        instructions: { "1": 0, "4": 1, "9": 1 },
        phases: [cells(AWAY_POSITIONS, IN_POSSESSION_ROLES), cells(AWAY_POSITIONS, OUT_OF_POSSESSION_ROLES)],
      },
    ],
    ...overrides,
  };
}

export const CATALOG: JsonRecord = {
  positions: HOME_POSITIONS.map((id, index) => ({ id, x: 50, y: index * 8 })),
  roles: [
    { id: "GK_ROLE_1", label: "门将组织", possession_phase: 0 },
    { id: "CB_ROLE_1", label: "中卫出球", possession_phase: 0 },
    { id: "FB_ROLE_1", label: "边卫前插", possession_phase: 0 },
    { id: "DM_ROLE_1", label: "后腰接应", possession_phase: 0 },
    { id: "CM_ROLE_1", label: "中场推进", possession_phase: 0 },
    { id: "WING_ROLE_1", label: "边锋内切", possession_phase: 0 },
    { id: "ST_ROLE_1", label: "中锋支点", possession_phase: 0 },
    { id: "GK_ROLE_2", label: "门将防守", possession_phase: 1 },
    { id: "CB_ROLE_2", label: "中卫盯人", possession_phase: 1 },
    { id: "FB_ROLE_2", label: "边卫回收", possession_phase: 1 },
    { id: "DM_ROLE_2", label: "后腰保护", possession_phase: 1 },
    { id: "CM_ROLE_2", label: "中场压迫", possession_phase: 1 },
    { id: "WING_ROLE_2", label: "边锋回防", possession_phase: 1 },
    { id: "ST_ROLE_2", label: "中锋反抢", possession_phase: 1 },
  ],
  team_instructions: [
    {
      id: "1",
      name: "传球方式",
      possession_phase: 0,
      options: [
        { id: 0, label: "短传" },
        { id: 1, label: "混合" },
        { id: 2, label: "长传" },
      ],
    },
    {
      id: "4",
      name: "进攻宽度",
      possession_phase: 0,
      options: [
        { id: 0, label: "收缩" },
        { id: 1, label: "均衡" },
        { id: 2, label: "拉开" },
      ],
    },
    {
      id: "9",
      name: "防线高度",
      possession_phase: 1,
      options: [
        { id: 0, label: "回收" },
        { id: 1, label: "标准" },
        { id: 2, label: "前压" },
      ],
    },
  ],
  mentalities: [
    { id: 1, label: "极度防守" },
    { id: 2, label: "防守" },
    { id: 3, label: "谨慎" },
    { id: 4, label: "均衡" },
    { id: 5, label: "积极" },
    { id: 6, label: "进攻" },
    { id: 7, label: "全力进攻" },
  ],
};

export const TIMESTAMP = "2026-01-01T10:00:00Z";

export function buildDraft(overrides: JsonRecord = {}): JsonRecord {
  return {
    id: "draft-1",
    name: "主队 4-3-3",
    source: { kind: "manual" },
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    scenario: buildScenario(),
    ...overrides,
  };
}

export function buildJob(overrides: JsonRecord = {}): JsonRecord {
  return {
    id: "job-1001",
    kind: "experiment",
    status: "completed",
    name: "测试实验",
    config: { seeds: [11, 23, 42] },
    summary: {},
    workers: 4,
    total: 100,
    completed: 100,
    created_at: TIMESTAMP,
    started_at: TIMESTAMP,
    finished_at: TIMESTAMP,
    ...overrides,
  };
}

export const JOBS: JsonRecord[] = [
  buildJob(),
  buildJob({ id: "job-1002", name: "对照实验", workers: 2 }),
  buildJob({
    id: "job-1003",
    name: "进行中的实验",
    status: "running",
    completed: 40,
    started_at: TIMESTAMP,
    finished_at: null,
  }),
  buildJob({
    id: "job-1004",
    name: "失败实验",
    status: "error",
    completed: 12,
    finished_at: TIMESTAMP,
  }),
];

export const METRICS: JsonRecord = {
  n: 6,
  wins: 3,
  draws: 1,
  losses: 2,
  win_rate: 0.5,
  win_interval: [0.2, 0.8],
  goals_for: 1.5,
  goals_against: 1.2,
  points: 1.66,
  xg: 1.8,
  xga: 1.1,
  possession: 52.4,
  shots: 9.5,
  pass_completion: 0.84,
};

export function buildSummary(job: JsonRecord, metrics: JsonRecord | null = METRICS): JsonRecord {
  return {
    job,
    metrics,
    paired: { n: 6, goal_difference_delta: 0.5 },
  };
}

export const RUNS: JsonRecord[] = [
  {
    job_id: "job-1001",
    sequence: 1,
    variant: "A",
    seed: 11,
    score: [2, 1],
    verified: true,
    stats: {},
    events: null,
    log_path: null,
    created_at: TIMESTAMP,
  },
  {
    job_id: "job-1001",
    sequence: 2,
    variant: "B",
    seed: 11,
    score: [1, 1],
    verified: false,
    stats: {},
    events: null,
    log_path: null,
    created_at: TIMESTAMP,
  },
];

export const POOL_SUMMARY: JsonRecord = {
  enabled: true,
  entry_count: 2,
  mode: "random",
  rounds: 1,
  players: "uniform",
  uniform: { enabled: false, attribute_value: 0 },
  entries: [
    { index: 0, name: "高位压迫 4-2-3-1", weight: 1, probability: 0.5, roster: true },
    { index: 1, name: "低位防守 5-3-2", weight: 1, probability: 0.5, roster: false },
  ],
  draws: { "0": 1, "1": 1 },
};

export const HOST_RESOURCES: JsonRecord = {
  cpu_count: 8,
  available_memory_bytes: 8 * 1024 ** 3,
  free_disk_bytes: 100 * 1024 ** 3,
  recommended_workers: 6,
};

export const CONCURRENCY_CHECK: JsonRecord = {
  allowed: true,
  code: null,
  recommended_workers: 6,
  warnings: [],
  memory_required_bytes: 1024 ** 3,
  disk_required_bytes: 20 * 1024 ** 3,
};

export const ENGINE_STATUS: JsonRecord = {
  engine_root: "/opt/FM27",
  game_root: "/opt/FM27/game",
  engine: { available: true, missing: [] },
  game: { available: true, missing: [] },
};

export const SETTINGS: JsonRecord[] = [
  { key: "worker.threads", value: 6, note: "并行线程数", updated_at: TIMESTAMP },
];

export const COMPARE_METRICS: JsonRecord = {
  ...METRICS,
  n: 6,
  win_rate: 0.6,
};

export const COMPARE_PAIRED: JsonRecord = {
  seeds: 6,
  win_rate_delta: 0.1,
  win_rate_delta_ci: [0.02, 0.18],
  points_delta: 0.2,
  points_delta_ci: null,
  goal_difference_delta: 0.3,
  goal_difference_delta_ci: null,
  xgd_delta: 0.1,
  xgd_delta_ci: null,
};

export const COMPARE_PAIRING: JsonRecord = {
  common_seeds: 6,
  draw_mismatches: null,
  mismatched_seeds: [],
  missing_seeds: [],
};

export function buildCompareResult(input: JsonRecord): JsonRecord {
  const baselineId = String(input["baseline_job_id"] ?? "");
  const rawCandidates = input["candidate_job_ids"];
  const candidateIds = Array.isArray(rawCandidates) ? rawCandidates.map(String) : [];
  const variant = typeof input["variant"] === "string" ? input["variant"] : "A";
  const side = typeof input["side"] === "number" ? input["side"] : 0;
  return {
    baseline: { job_id: baselineId, name: "测试实验", metrics: METRICS, tactic_pool: null },
    variant,
    side,
    candidates: candidateIds.map((id) => ({
      job_id: id,
      name: JOBS.find((job) => job.id === id)?.name ?? id,
      metrics: COMPARE_METRICS,
      tactic_pool: null,
      comparable: true,
      reason: null,
      pairing: COMPARE_PAIRING,
      paired: COMPARE_PAIRED,
    })),
  };
}
