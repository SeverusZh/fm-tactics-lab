import type { Connection } from "./connection";

export type Health = {
  status: string;
  api: string;
  version: string;
  database: string;
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message);
  }
}

export async function apiFetch(
  connection: Connection,
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${connection.token}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${connection.url}${path}`, { ...init, headers });
  if (!response.ok) {
    let message = `请求失败：${response.status}`;
    let code = "http_error";
    try {
      const body = (await response.json()) as { error?: { message?: string; code?: string } };
      message = body.error?.message ?? message;
      code = body.error?.code ?? code;
    } catch {
      // Keep the status-based fallback when the body is not JSON.
    }
    throw new ApiError(message, response.status, code);
  }
  return response;
}

export async function apiJson<T>(
  connection: Connection,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await apiFetch(connection, path, init);
  return (await response.json()) as T;
}

export type JobStatus =
  | "queued"
  | "running"
  | "interrupted"
  | "completed"
  | "error"
  | "cancelled";

export type Job = {
  id: string;
  kind: string;
  status: JobStatus;
  name: string | null;
  config: Record<string, unknown>;
  summary: Record<string, unknown>;
  workers: number;
  total: number;
  completed: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type JobRun = {
  job_id: string;
  sequence: number;
  variant: string;
  seed: number;
  score: [number, number] | null;
  verified: boolean;
  stats: Record<string, unknown>;
  events: Record<string, unknown> | null;
  log_path: string | null;
  created_at: string;
};

export type JobList = {
  items: Job[];
  total: number;
  next_offset: number | null;
};

export type JobRunList = {
  items: JobRun[];
  total: number;
  next_offset: number | null;
};

export type JobCreate = {
  kind: string;
  name?: string | null;
  config?: Record<string, unknown>;
  workers?: number;
  total?: number;
};

export type JobUpdate = {
  status?: JobStatus;
  completed?: number;
  summary?: Record<string, unknown>;
  name?: string | null;
};

export type JobQuery = {
  status?: JobStatus;
  limit?: number;
  offset?: number;
};

export type JobRunQuery = {
  limit?: number;
  offset?: number;
};

export type JobMetrics = {
  n: number;
  wins: number;
  draws: number;
  losses: number;
  win_rate: number;
  win_interval: [number, number];
  goals_for: number;
  goals_against: number;
  points: number;
  xg: number | null;
  xga: number | null;
  possession: number | null;
  shots: number | null;
  pass_completion: number | null;
};

export type JobPaired = {
  n: number;
  goal_difference_delta: number | null;
};

export type JobSummary = {
  job: Job;
  metrics: JobMetrics | null;
  paired: JobPaired;
};

function queryString(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const serialized = search.toString();
  return serialized === "" ? "" : `?${serialized}`;
}

export function listJobs(connection: Connection, query: JobQuery = {}): Promise<JobList> {
  const search = queryString({ status: query.status, limit: query.limit, offset: query.offset });
  return apiJson<JobList>(connection, `/api/jobs${search}`);
}

export function createJob(connection: Connection, input: JobCreate): Promise<Job> {
  return apiJson<Job>(connection, "/api/jobs", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getJob(connection: Connection, jobId: string): Promise<Job> {
  return apiJson<Job>(connection, `/api/jobs/${encodeURIComponent(jobId)}`);
}

export function updateJob(
  connection: Connection,
  jobId: string,
  changes: JobUpdate,
): Promise<Job> {
  return apiJson<Job>(connection, `/api/jobs/${encodeURIComponent(jobId)}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

export function cancelJob(connection: Connection, jobId: string): Promise<Job> {
  return apiJson<Job>(connection, `/api/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
}

export async function deleteJob(connection: Connection, jobId: string): Promise<void> {
  await apiFetch(connection, `/api/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
}

export type JobBatchDeleteFailure = {
  id: string;
  error: string;
};

export type JobBatchDeleteResult = {
  deleted: string[];
  failed: JobBatchDeleteFailure[];
};

export function deleteJobsBatch(
  connection: Connection,
  ids: string[],
): Promise<JobBatchDeleteResult> {
  return apiJson<JobBatchDeleteResult>(connection, "/api/jobs", {
    method: "DELETE",
    body: JSON.stringify({ ids }),
  });
}

export function listJobRuns(
  connection: Connection,
  jobId: string,
  query: JobRunQuery = {},
): Promise<JobRunList> {
  const search = queryString({ limit: query.limit, offset: query.offset });
  return apiJson<JobRunList>(connection, `/api/jobs/${encodeURIComponent(jobId)}/runs${search}`);
}

export function getJobSummary(
  connection: Connection,
  jobId: string,
  side: 0 | 1 = 0,
): Promise<JobSummary> {
  const search = queryString({ side });
  return apiJson<JobSummary>(
    connection,
    `/api/jobs/${encodeURIComponent(jobId)}/summary${search}`,
  );
}

export type PoolSummaryEntry = {
  index: number;
  name: string;
  weight: number;
  probability: number | null;
  roster: boolean;
};

export type PoolSummary = {
  enabled: boolean;
  entry_count: number;
  mode: string | null;
  rounds?: number | null;
  players: string | null;
  uniform?: { enabled: boolean; attribute_value: number } | null;
  entries?: PoolSummaryEntry[] | null;
  draws: Record<string, number>;
};

export function getJobPoolSummary(
  connection: Connection,
  jobId: string,
): Promise<PoolSummary> {
  return apiJson<PoolSummary>(
    connection,
    `/api/jobs/${encodeURIComponent(jobId)}/pool-summary`,
  );
}

export async function downloadJobCsv(connection: Connection, jobId: string): Promise<string> {
  const response = await apiFetch(
    connection,
    `/api/jobs/${encodeURIComponent(jobId)}/export.csv`,
  );
  return response.text();
}

export type CompareInput = {
  baseline_job_id: string;
  candidate_job_ids: string[];
  variant?: "A" | "B";
  side?: 0 | 1;
  reps?: number;
};

export type ComparePairing = {
  common_seeds: number;
  draw_mismatches: number | null;
  mismatched_seeds: number[];
  missing_seeds: number[];
};

export type ComparePaired = {
  seeds: number;
  win_rate_delta: number | null;
  win_rate_delta_ci: [number, number] | null;
  points_delta: number | null;
  points_delta_ci: [number, number] | null;
  goal_difference_delta: number | null;
  goal_difference_delta_ci: [number, number] | null;
  xgd_delta: number | null;
  xgd_delta_ci: [number, number] | null;
};

export type CompareJob = {
  job_id: string;
  name: string | null;
  metrics: JobMetrics | null;
  tactic_pool: PoolSummary;
};

export type CompareCandidate = CompareJob & {
  comparable: boolean;
  reason: string | null;
  pairing: ComparePairing | null;
  paired: ComparePaired | null;
};

export type CompareResult = {
  baseline: CompareJob;
  variant: "A" | "B";
  side: 0 | 1;
  candidates: CompareCandidate[];
};

export function compareResults(
  connection: Connection,
  input: CompareInput,
): Promise<CompareResult> {
  return apiJson<CompareResult>(connection, "/api/results/compare", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export type SaveStatus = "pending" | "reading" | "ready" | "error" | "cancelled";

export type Save = {
  id: string;
  source_path: string;
  source_sha256: string;
  status: SaveStatus;
  stage: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type SaveList = {
  items: Save[];
  total: number;
  next_offset: number | null;
};

export type SaveCreate = {
  source_path: string;
  source_sha256: string;
  status?: SaveStatus;
  stage?: string | null;
  metadata?: Record<string, unknown> | null;
};

export type SaveUpdate = {
  status?: SaveStatus;
  stage?: string | null;
  metadata?: Record<string, unknown>;
};

export type SaveImport = {
  leagues: Record<string, Record<string, unknown>>;
  clubs: Record<string, Record<string, unknown>>;
  stage?: string | null;
};

export type SaveQuery = {
  status?: SaveStatus;
  limit?: number;
  offset?: number;
};

export function listSaves(connection: Connection, query: SaveQuery = {}): Promise<SaveList> {
  const search = queryString({ status: query.status, limit: query.limit, offset: query.offset });
  return apiJson<SaveList>(connection, `/api/saves${search}`);
}

export function createSave(connection: Connection, input: SaveCreate): Promise<Save> {
  return apiJson<Save>(connection, "/api/saves", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateSave(
  connection: Connection,
  saveId: string,
  changes: SaveUpdate,
): Promise<Save> {
  return apiJson<Save>(connection, `/api/saves/${encodeURIComponent(saveId)}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

export async function deleteSave(connection: Connection, saveId: string): Promise<void> {
  await apiFetch(connection, `/api/saves/${encodeURIComponent(saveId)}`, { method: "DELETE" });
}

export function importSave(
  connection: Connection,
  saveId: string,
  payload: SaveImport,
): Promise<Save> {
  return apiJson<Save>(connection, `/api/saves/${encodeURIComponent(saveId)}/import`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export type Draft = {
  id: string;
  name: string;
  scenario: Record<string, unknown>;
  source: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type DraftSummary = Omit<Draft, "scenario">;

export type DraftList = {
  items: DraftSummary[];
  total: number;
  next_offset: number | null;
};

export type DraftCreate = {
  name: string;
  scenario: Record<string, unknown>;
  source?: Record<string, unknown> | null;
};

export type DraftUpdate = {
  name?: string;
  scenario?: Record<string, unknown>;
  source?: Record<string, unknown>;
};

export type DraftQuery = {
  limit?: number;
  offset?: number;
};

export function listDrafts(connection: Connection, query: DraftQuery = {}): Promise<DraftList> {
  const search = queryString({ limit: query.limit, offset: query.offset });
  return apiJson<DraftList>(connection, `/api/drafts${search}`);
}

export function createDraft(connection: Connection, input: DraftCreate): Promise<Draft> {
  return apiJson<Draft>(connection, "/api/drafts", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getDraft(connection: Connection, draftId: string): Promise<Draft> {
  return apiJson<Draft>(connection, `/api/drafts/${encodeURIComponent(draftId)}`);
}

export function updateDraft(
  connection: Connection,
  draftId: string,
  changes: DraftUpdate,
): Promise<Draft> {
  return apiJson<Draft>(connection, `/api/drafts/${encodeURIComponent(draftId)}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

export async function deleteDraft(connection: Connection, draftId: string): Promise<void> {
  await apiFetch(connection, `/api/drafts/${encodeURIComponent(draftId)}`, { method: "DELETE" });
}

export type DraftAttributeSide = "home" | "away";

export type DraftAttributeScope = "all" | "starters" | "player" | "squad";

export type DraftAttributeOperation = "bulk" | "position" | "copy" | "pair_feet" | "undo";

export type DraftAttributePayload = {
  side: DraftAttributeSide;
  scope: DraftAttributeScope;
  player_index?: number | null;
  operation: DraftAttributeOperation;
  params: Record<string, unknown>;
};

export type DraftAttributeResult = {
  draft: DraftSummary;
  snapshot: Record<string, unknown> | null;
  changed_players: number;
};

export function applyDraftAttributes(
  connection: Connection,
  draftId: string,
  payload: DraftAttributePayload,
): Promise<DraftAttributeResult> {
  return apiJson<DraftAttributeResult>(
    connection,
    `/api/drafts/${encodeURIComponent(draftId)}/attributes`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export type CatalogOption = {
  id: number | string;
  label: string;
};

export type CatalogPosition = {
  id: string;
  x?: number;
  y?: number;
};

export type CatalogRole = {
  id: string;
  label?: string | null;
  name?: string | null;
};

export type CatalogTeamInstruction = {
  id: number | string;
  name?: string | null;
  label?: string | null;
  possession_phase?: number | null;
  phase?: number | null;
  options?: CatalogOption[] | null;
};

export type CatalogMentality = {
  id: number | string;
  label?: string | null;
  name?: string | null;
};

export type Catalog = {
  positions: CatalogPosition[];
  roles: CatalogRole[];
  team_instructions: CatalogTeamInstruction[];
  mentalities: CatalogMentality[];
};

export type CatalogResponse = {
  available: boolean;
  catalog: Catalog | null;
};

export async function getCatalog(connection: Connection): Promise<Catalog | null> {
  try {
    const body = await apiJson<CatalogResponse>(connection, "/api/catalog");
    if (body.available !== true || body.catalog === null || body.catalog === undefined) {
      return null;
    }
    return body.catalog;
  } catch {
    return null;
  }
}

export type Setting = {
  key: string;
  value: unknown;
  note: string | null;
  updated_at: string;
};

export type SettingList = {
  items: Setting[];
  total: number;
};

export type SettingInput = {
  value: unknown;
  note?: string | null;
};

export type ConcurrencyCheckQuery = {
  workers: number;
  cpu_count: number;
  available_memory_bytes: number;
  free_disk_bytes: number;
  allow_oversubscription: boolean;
};

export type ConcurrencyCheck = {
  allowed: boolean;
  code: string | null;
  recommended_workers: number;
  warnings: string[];
  memory_required_bytes: number;
  disk_required_bytes: number;
};

function settingPath(key: string): string {
  return `/api/settings/${encodeURIComponent(key)}`;
}

export function listSettings(connection: Connection): Promise<SettingList> {
  return apiJson<SettingList>(connection, "/api/settings");
}

export function getSetting(connection: Connection, key: string): Promise<Setting> {
  return apiJson<Setting>(connection, settingPath(key));
}

export function putSetting(
  connection: Connection,
  key: string,
  input: SettingInput,
): Promise<Setting> {
  return apiJson<Setting>(connection, settingPath(key), {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export async function deleteSetting(connection: Connection, key: string): Promise<void> {
  await apiFetch(connection, settingPath(key), { method: "DELETE" });
}

export function checkConcurrency(
  connection: Connection,
  query: ConcurrencyCheckQuery,
): Promise<ConcurrencyCheck> {
  const search = queryString({
    workers: query.workers,
    cpu_count: query.cpu_count,
    available_memory_bytes: query.available_memory_bytes,
    free_disk_bytes: query.free_disk_bytes,
    allow_oversubscription: query.allow_oversubscription,
  });
  return apiJson<ConcurrencyCheck>(connection, `/api/concurrency/check${search}`);
}

export type SaveFileImportInput = {
  source_path: string;
  replace?: boolean;
};

export type ImportedClub = {
  club_uid: number;
  club_name: string | null;
  players: number;
};

export type SaveFileImportResult = {
  save_id: string;
  status: string;
  managed_clubs: ImportedClub[];
  clubs: number;
};

export type SquadPlayer = {
  source_uid: number | string;
  name: string;
  position: string;
  ability: number | null;
};

export type SquadSelection = {
  club_uid?: number;
  team_id?: number | null;
  team_slot?: number | null;
  lineup: (number | string)[];
  substitutes: (number | string)[];
};

export type SaveSquad = {
  save_id: string;
  club_uid: number;
  club_name: string | null;
  players: SquadPlayer[];
  selection: SquadSelection | null;
};

export type RosterSide = "home" | "away";

export type RosterScope = "starters" | "bench" | "both";

export type RosterApplyInput = {
  save_id: string;
  club_uid: number;
  side: RosterSide;
  scope: RosterScope;
};

export type RosterApplied = {
  starters: number;
  substitutes: number;
};

export type RosterApplyResult = {
  draft: DraftSummary;
  applied: RosterApplied;
};

export type RosterUndoResult = {
  draft: DraftSummary;
};

export function importSaveFile(
  connection: Connection,
  input: SaveFileImportInput,
): Promise<SaveFileImportResult> {
  return apiJson<SaveFileImportResult>(connection, "/api/saves/import", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getSaveSquad(
  connection: Connection,
  saveId: string,
  clubUid: number,
): Promise<SaveSquad> {
  const search = queryString({ club_uid: clubUid });
  return apiJson<SaveSquad>(
    connection,
    `/api/saves/${encodeURIComponent(saveId)}/squad${search}`,
  );
}

export function applyRoster(
  connection: Connection,
  draftId: string,
  input: RosterApplyInput,
): Promise<RosterApplyResult> {
  return apiJson<RosterApplyResult>(
    connection,
    `/api/drafts/${encodeURIComponent(draftId)}/apply-roster`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

export function undoRoster(
  connection: Connection,
  draftId: string,
): Promise<RosterUndoResult> {
  return apiJson<RosterUndoResult>(
    connection,
    `/api/drafts/${encodeURIComponent(draftId)}/undo-roster`,
    { method: "POST" },
  );
}

