// API 类型映射：生成别名 47 项；保留手写类型 25 项；字段派生 2 项；ApiError 类保留；明细见 api-types.test.ts。

import type { Connection } from "./connection";
import type {
  CompareInput as GeneratedCompareInput,
  CompareJobOutput,
  ComparePairingOutput,
  ConcurrencyCheckOutput,
  DraftAttributeInput,
  DraftAttributeOutput,
  DraftCreateInput,
  DraftListOutput,
  DraftOutput,
  DraftSummary as GeneratedDraftSummary,
  DraftUpdateInput,
  EngineDiagnosisOutput,
  EngineImportOutput,
  EngineSelectInput,
  EngineStatusOutput,
  ExperimentSubmitInput as GeneratedExperimentSubmitInput,
  FmfFileImportInput as GeneratedFmfFileImportInput,
  ImportedClubOutput,
  JobBatchDeleteFailureOutput,
  JobBatchDeleteOutput,
  JobCreateInput,
  JobListOutput,
  JobMetricsOutput,
  JobOutput,
  JobRunListOutput,
  JobRunOutput,
  JobUpdateInput,
  PairedOutput,
  PoolSummaryEntryOutput,
  ResultsSummaryOutput,
  RosterAppliedOutput,
  RosterApplyInput as GeneratedRosterApplyInput,
  RosterApplyOutput,
  RosterUndoOutput,
  SaveCreateInput,
  SaveFileImportInput as GeneratedSaveFileImportInput,
  SaveFileImportOutput,
  SaveImportInput,
  SaveListOutput,
  SaveOutput,
  SaveTacticOutput,
  SaveUpdateInput,
  SettingListOutput,
  SettingOutput,
  SettingPutInput,
  SystemResourcesOutput,
  TacticsTemplateOutput,
} from "./api-schema";

// 健康检查响应未纳入 OpenAPI 组件模型，保留手写。
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
    readonly retriable: boolean = true,
  ) {
    super(message);
  }
}

export const API_TIMEOUT_MS = 30_000;

type ApiRequestInit = RequestInit & { timeoutMs?: number };

export async function apiFetch(
  connection: Connection,
  path: string,
  init: ApiRequestInit = {},
): Promise<Response> {
  const { timeoutMs = API_TIMEOUT_MS, ...fetchInit } = init;
  const headers = new Headers(fetchInit.headers);
  headers.set("Authorization", `Bearer ${connection.token}`);
  if (fetchInit.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const externalSignal = fetchInit.signal;
  const abortFromExternal = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort();
    else externalSignal.addEventListener("abort", abortFromExternal);
  }
  try {
    const response = await fetch(`${connection.url}${path}`, {
      ...fetchInit,
      headers,
      signal: controller.signal,
    });
    if (!response.ok) {
      let message = `请求失败：${response.status}`;
      let code = "http_error";
      let retriable = response.status >= 500 || response.status === 409;
      try {
        const body = (await response.json()) as {
          error?: { message?: string; code?: string; retriable?: boolean };
        };
        message = body.error?.message ?? message;
        code = body.error?.code ?? code;
        if (typeof body.error?.retriable === "boolean") retriable = body.error.retriable;
      } catch {
        // Keep the status-based fallback when the body is not JSON.
      }
      throw new ApiError(message, response.status, code, retriable);
    }
    return response;
  } catch (error) {
    if (timedOut) throw new ApiError("请求超时，请重试", 0, "timeout", true);
    throw error;
  } finally {
    clearTimeout(timer);
    externalSignal?.removeEventListener("abort", abortFromExternal);
  }
}

export async function apiJson<T>(
  connection: Connection,
  path: string,
  init: ApiRequestInit = {},
): Promise<T> {
  const response = await apiFetch(connection, path, init);
  return (await response.json()) as T;
}

export type JobStatus = Job["status"];

export type Job = JobOutput;

export type JobRun = JobRunOutput;

export type JobList = JobListOutput;

export type JobRunList = JobRunListOutput;

export type JobCreate = JobCreateInput;

export type JobUpdate = JobUpdateInput;

// 任务查询参数未在 OpenAPI 中单独建模，保留手写。
export type JobQuery = {
  status?: JobStatus;
  limit?: number;
  offset?: number;
};

// 运行查询参数未在 OpenAPI 中单独建模，保留手写。
export type JobRunQuery = {
  limit?: number;
  offset?: number;
};

export type JobMetrics = JobMetricsOutput;

export type JobPaired = PairedOutput;

export type JobSummary = ResultsSummaryOutput;

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

export type JobBatchDeleteFailure = JobBatchDeleteFailureOutput;

export type JobBatchDeleteResult = JobBatchDeleteOutput;

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

export type PoolSummaryEntry = PoolSummaryEntryOutput;

// 生成接口把 draws、mode、players 设为可选，页面依赖必填的 draws 索引，保留手写。
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

export type CompareInput = GeneratedCompareInput;

export type ComparePairing = ComparePairingOutput;

// 生成接口的置信区间是 number[]，页面按固定二元组使用，保留手写。
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

export type CompareJob = CompareJobOutput;

// 引用保留手写的 ComparePaired，避免置信区间退化为 number[]。
export type CompareCandidate = CompareJob & {
  comparable: boolean;
  reason: string | null;
  pairing: ComparePairing | null;
  paired: ComparePaired | null;
};

// 生成接口的 candidates 会把置信区间退化为 number[]，保留手写。
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

export type SaveStatus = Save["status"];

export type Save = SaveOutput;

export type SaveList = SaveListOutput;

export type SaveCreate = SaveCreateInput;

export type SaveUpdate = SaveUpdateInput;

export type SaveImport = SaveImportInput;

export type SaveTactic = SaveTacticOutput;

// 存档查询参数未在 OpenAPI 中单独建模，保留手写。
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

export async function listSaveTactics(
  connection: Connection,
  saveId: string,
): Promise<SaveTactic[]> {
  const body = await apiJson<{ items: SaveTactic[] }>(
    connection,
    `/api/saves/${encodeURIComponent(saveId)}/tactics`,
  );
  return body.items;
}

export async function importSaveTactic(
  connection: Connection,
  saveId: string,
  tacticIndex: number,
): Promise<Draft> {
  const body = await apiJson<{ draft: Draft }>(
    connection,
    `/api/saves/${encodeURIComponent(saveId)}/tactics/${tacticIndex}/import`,
    { method: "POST" },
  );
  return body.draft;
}

export type Draft = DraftOutput;

export type DraftSummary = GeneratedDraftSummary;

export type DraftList = DraftListOutput;

export type DraftCreate = DraftCreateInput;

export type DraftUpdate = DraftUpdateInput;

export type FmfFileImportInput = GeneratedFmfFileImportInput;

// 草案查询参数未在 OpenAPI 中单独建模，保留手写。
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

export function importFmfFile(
  connection: Connection,
  input: FmfFileImportInput,
): Promise<Draft> {
  return apiJson<Draft>(connection, "/api/drafts/import-fmf-file", {
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

export async function exportDraftFmf(connection: Connection, draftId: string): Promise<Blob> {
  const response = await apiFetch(
    connection,
    `/api/drafts/${encodeURIComponent(draftId)}/export.fmf`,
  );
  return response.blob();
}

// 属性编辑输入模型仍是 str，页面以字面量联合类型约束，保留手写。
export type DraftAttributeSide = "home" | "away";

// 属性编辑输入模型仍是 str，页面以字面量联合类型约束，保留手写。
export type DraftAttributeScope = "all" | "starters" | "player" | "squad";

// 属性编辑输入模型仍是 str，页面以字面量联合类型约束，保留手写。
export type DraftAttributeOperation = "bulk" | "position" | "copy" | "pair_feet" | "cells" | "undo";

// cells 操作的 params.values 形如 {属性索引十进制字符串: 显示值}。
export type DraftAttributePayload = DraftAttributeInput;

export type DraftAttributeResult = DraftAttributeOutput;

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

// catalog 负载在 OpenAPI 中是不透明对象，保留手写结构。
export type CatalogOption = {
  id: number | string;
  label: string;
};

// catalog 负载在 OpenAPI 中是不透明对象，保留手写结构。
export type CatalogPosition = {
  id: string;
  x?: number;
  y?: number;
};

// catalog 负载在 OpenAPI 中是不透明对象，保留手写结构。
export type CatalogRole = {
  id: string;
  label?: string | null;
  name?: string | null;
};

// catalog 负载在 OpenAPI 中是不透明对象，保留手写结构。
export type CatalogTeamInstruction = {
  id: number | string;
  name?: string | null;
  label?: string | null;
  possession_phase?: number | null;
  phase?: number | null;
  options?: CatalogOption[] | null;
};

// catalog 负载在 OpenAPI 中是不透明对象，保留手写结构。
export type CatalogMentality = {
  id: number | string;
  label?: string | null;
  name?: string | null;
};

// catalog 负载在 OpenAPI 中是不透明对象，保留手写结构。
export type Catalog = {
  positions: CatalogPosition[];
  roles: CatalogRole[];
  team_instructions: CatalogTeamInstruction[];
  mentalities: CatalogMentality[];
};

// catalog 负载在 OpenAPI 中是不透明对象，保留手写结构。
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

export type TacticsTemplate = TacticsTemplateOutput;

export async function getTacticsTemplate(
  connection: Connection,
): Promise<TacticsTemplate["scenario"]> {
  const body = await apiJson<TacticsTemplate>(connection, "/api/tactics/template");
  return body.scenario;
}

export type Setting = SettingOutput;

export type SettingList = SettingListOutput;

export type SettingInput = SettingPutInput;

// 并发检查参数未在 OpenAPI 中单独建模，保留手写。
export type ConcurrencyCheckQuery = {
  workers: number;
  cpu_count: number;
  available_memory_bytes: number;
  free_disk_bytes: number;
  allow_oversubscription: boolean;
};

export type ConcurrencyCheck = ConcurrencyCheckOutput;

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

export type HostResources = SystemResourcesOutput;

export type EngineStatus = EngineStatusOutput;

export type EngineDiagnosis = EngineDiagnosisOutput;

export type EngineSelect = EngineSelectInput;

export type EngineImportResult = EngineImportOutput;

export function importEngineResources(
  connection: Connection,
  sourcePath: string,
): Promise<EngineImportResult> {
  return apiJson<EngineImportResult>(connection, "/api/engine/import", {
    method: "POST",
    body: JSON.stringify({ source_path: sourcePath }),
  });
}

export function getEngineStatus(connection: Connection): Promise<EngineStatus> {
  return apiJson<EngineStatus>(connection, "/api/engine");
}

export function selectEngine(connection: Connection, input: EngineSelect): Promise<EngineStatus> {
  return apiJson<EngineStatus>(connection, "/api/engine/select", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function diagnoseEngine(connection: Connection): Promise<EngineDiagnosis> {
  return apiJson<EngineDiagnosis>(connection, "/api/engine/diagnose", { method: "POST" });
}

export async function restartSidecar(connection: Connection): Promise<void> {
  await apiFetch(connection, "/api/system/restart", { method: "POST" });
}

export type ExperimentSubmitInput = GeneratedExperimentSubmitInput;

export function getHostResources(connection: Connection): Promise<HostResources> {
  return apiJson<HostResources>(connection, "/api/system/resources");
}

export function submitExperiment(
  connection: Connection,
  input: ExperimentSubmitInput,
): Promise<Job> {
  return apiJson<Job>(connection, "/api/experiments", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function startExperiment(connection: Connection): Promise<Job | null> {
  const response = await apiFetch(connection, "/api/experiments/start", { method: "POST" });
  if (response.status === 204) return null;
  const body = (await response.json()) as { job: Job };
  return body.job;
}

export type SaveFileImportInput = GeneratedSaveFileImportInput;

export type ImportedClub = ImportedClubOutput;

export type SaveFileImportResult = SaveFileImportOutput;

// squad 负载在 OpenAPI 中是不透明对象，保留手写结构。
export type SquadPlayer = {
  source_uid: number | string;
  name: string;
  position: string;
  ability: number | null;
};

// squad 负载在 OpenAPI 中是不透明对象，保留手写结构。
export type SquadSelection = {
  club_uid?: number;
  team_id?: number | null;
  team_slot?: number | null;
  lineup: (number | string)[];
  substitutes: (number | string)[];
};

// squad 负载在 OpenAPI 中是不透明对象，保留手写结构。
export type SaveSquad = {
  save_id: string;
  club_uid: number;
  club_name: string | null;
  players: SquadPlayer[];
  selection: SquadSelection | null;
};

// 阵容套用输入模型仍是 str，页面以字面量联合类型约束，保留手写。
export type RosterSide = "home" | "away";

// 阵容套用输入模型仍是 str，页面以字面量联合类型约束，保留手写。
export type RosterScope = "starters" | "bench" | "both";

export type RosterApplyInput = GeneratedRosterApplyInput;

export type RosterApplied = RosterAppliedOutput;

export type RosterApplyResult = RosterApplyOutput;

export type RosterUndoResult = RosterUndoOutput;

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

