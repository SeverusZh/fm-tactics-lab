// 本文件由 scripts/generate_web_types.py 自动生成，请勿手动修改。
// 重新生成：.venv/bin/python scripts/generate_web_types.py
// 校验一致：.venv/bin/python scripts/generate_web_types.py --check

export interface ArtifactListOutput {
  items: ArtifactOutput[];
  total: number;
  next_offset: number | null;
}

export interface ArtifactOutput {
  id: string;
  job_id: string | null;
  kind: string;
  path: string;
  sha256: string;
  bytes: number;
  created_at: string;
}

export interface ArtifactRegisterInput {
  kind: string;
  filename: string;
  content_base64: string;
  job_id?: string | null;
}

export interface CatalogSnapshotOutput {
  available: boolean;
  catalog: { [key: string]: unknown } | null;
}

export interface CompareCandidateOutput {
  job_id: string;
  name: string | null;
  metrics: JobMetricsOutput | null;
  tactic_pool: PoolSummaryOutput;
  comparable: boolean;
  reason: string | null;
  pairing: ComparePairingOutput | null;
  paired: ComparePairedOutput | null;
}

export interface CompareInput {
  baseline_job_id: string;
  candidate_job_ids: string[];
  variant?: string;
  side?: number;
  reps?: number;
}

export interface CompareJobOutput {
  job_id: string;
  name: string | null;
  metrics: JobMetricsOutput | null;
  tactic_pool: PoolSummaryOutput;
}

export interface CompareOutput {
  baseline: CompareJobOutput;
  variant: string;
  side: number;
  candidates: CompareCandidateOutput[];
}

export interface ComparePairedOutput {
  seeds: number;
  win_rate_delta: number | null;
  win_rate_delta_ci: number[] | null;
  points_delta: number | null;
  points_delta_ci: number[] | null;
  goal_difference_delta: number | null;
  goal_difference_delta_ci: number[] | null;
  xgd_delta: number | null;
  xgd_delta_ci: number[] | null;
}

export interface ComparePairingOutput {
  common_seeds: number;
  draw_mismatches: number | null;
  mismatched_seeds: number[];
  missing_seeds: number[];
}

export interface ConcurrencyCheckOutput {
  allowed: boolean;
  code: string | null;
  recommended_workers: number;
  warnings: string[];
  memory_required_bytes: number;
  disk_required_bytes: number;
}

export interface DraftAttributeInput {
  side: string;
  scope: string;
  player_index?: number | null;
  operation: string;
  params: { [key: string]: unknown };
}

export interface DraftAttributeOutput {
  draft: DraftSummary;
  snapshot: { [key: string]: unknown } | null;
  changed_players: number;
}

export interface DraftCreateInput {
  name: string;
  scenario: { [key: string]: unknown };
  source?: { [key: string]: unknown } | null;
}

export interface DraftListOutput {
  items: DraftSummary[];
  total: number;
  next_offset: number | null;
}

export interface DraftOutput {
  id: string;
  name: string;
  source: { [key: string]: unknown };
  created_at: string;
  updated_at: string;
  scenario: { [key: string]: unknown };
}

export interface DraftSummary {
  id: string;
  name: string;
  source: { [key: string]: unknown };
  created_at: string;
  updated_at: string;
}

export interface DraftUpdateInput {
  name?: string | null;
  scenario?: { [key: string]: unknown } | null;
  source?: { [key: string]: unknown } | null;
}

export interface ErrorBody {
  code: string;
  message: string;
  details: unknown;
  retriable: boolean;
  retry_after_seconds: number | null;
}

export interface ErrorEnvelope {
  error: ErrorBody;
}

export interface ExperimentStartOutput {
  job: JobOutput;
}

export interface ExperimentSubmitInput {
  name?: string | null;
  seeds: number[];
  draft_id: string;
  baseline_draft_id?: string | null;
  workers: number;
  cpu_count: number;
  available_memory_bytes: number;
  free_disk_bytes: number;
  allow_oversubscription?: boolean;
}

export interface FmfImportInput {
  name: string;
  content_base64: string;
  source?: { [key: string]: unknown } | null;
}

export interface HTTPValidationError {
  detail?: ValidationError[];
}

export interface ImportedClubOutput {
  club_uid: number;
  club_name: string | null;
  players: number;
}

export interface JobBatchActionInput {
  action: "cancel" | "delete";
  ids: string[];
}

export interface JobBatchActionOutput {
  succeeded: string[];
  failed: JobBatchFailureOutput[];
}

export interface JobBatchDeleteFailureOutput {
  id: string;
  error: string;
}

export interface JobBatchDeleteInput {
  ids: string[];
}

export interface JobBatchDeleteOutput {
  deleted: string[];
  failed: JobBatchDeleteFailureOutput[];
}

export interface JobBatchFailureOutput {
  id: string;
  code: string;
  message: string;
}

export interface JobCreateInput {
  kind: string;
  name?: string | null;
  config?: { [key: string]: unknown };
  workers?: number;
  total?: number;
}

export interface JobListOutput {
  items: JobOutput[];
  total: number;
  next_offset: number | null;
}

export interface JobMetricsOutput {
  n: number;
  wins: number;
  draws: number;
  losses: number;
  win_rate: number;
  win_interval: number[];
  goals_for: number;
  goals_against: number;
  points: number;
  xg: number | null;
  xga: number | null;
  possession: number | null;
  shots: number | null;
  pass_completion: number | null;
}

export interface JobOutput {
  id: string;
  kind: string;
  status: "queued" | "running" | "interrupted" | "completed" | "error" | "cancelled";
  name: string | null;
  config: { [key: string]: unknown };
  summary: { [key: string]: unknown };
  workers: number;
  total: number;
  completed: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface JobRunListOutput {
  items: JobRunOutput[];
  total: number;
  next_offset: number | null;
}

export interface JobRunOutput {
  job_id: string;
  sequence: number;
  variant: string;
  seed: number;
  score: number[] | null;
  verified: boolean;
  stats: { [key: string]: unknown };
  events: { [key: string]: unknown } | null;
  log_path: string | null;
  created_at: string;
}

export interface JobUpdateInput {
  status?: string | null;
  completed?: number | null;
  summary?: { [key: string]: unknown } | null;
  name?: string | null;
}

export interface PairedOutput {
  n: number;
  goal_difference_delta: number | null;
}

export interface PoolEntryInput {
  name: string;
  weight?: number;
  tactic: { [key: string]: unknown };
  roster?: { [key: string]: unknown } | null;
  id?: string | null;
}

export interface PoolEntryOutput {
  id: string;
  name: string;
  weight: number;
  tactic: { [key: string]: unknown };
  roster: { [key: string]: unknown } | null;
  created_at: string;
}

export interface PoolListOutput {
  items: PoolEntryOutput[];
  total: number;
  next_offset: number | null;
}

export interface PoolSummaryEntryOutput {
  index: number;
  name: string;
  weight: number;
  probability: number | null;
  roster: boolean;
}

export interface PoolSummaryOutput {
  enabled: boolean;
  entry_count: number;
  mode?: string | null;
  rounds?: number | null;
  players?: string | null;
  uniform?: PoolSummaryUniformOutput | null;
  entries?: PoolSummaryEntryOutput[] | null;
  draws?: { [key: string]: number };
}

export interface PoolSummaryUniformOutput {
  enabled: boolean;
  attribute_value: number;
}

export interface ResultsSummaryOutput {
  job: JobOutput;
  metrics: JobMetricsOutput | null;
  paired: PairedOutput;
}

export interface RosterAppliedOutput {
  starters: number;
  substitutes: number;
}

export interface RosterApplyInput {
  save_id: string;
  club_uid: number;
  side: string;
  scope: string;
}

export interface RosterApplyOutput {
  draft: DraftSummary;
  applied: RosterAppliedOutput;
}

export interface RosterUndoOutput {
  draft: DraftSummary;
}

export interface SaveCreateInput {
  source_path: string;
  source_sha256: string;
  status?: string;
  stage?: string | null;
  metadata?: { [key: string]: unknown } | null;
}

export interface SaveFileImportInput {
  source_path: string;
  replace?: boolean;
}

export interface SaveFileImportOutput {
  save_id: string;
  status: string;
  managed_clubs: ImportedClubOutput[];
  clubs: number;
}

export interface SaveImportInput {
  leagues: { [key: string]: { [key: string]: unknown } };
  clubs: { [key: string]: { [key: string]: unknown } };
  stage?: string | null;
}

export interface SaveListOutput {
  items: SaveOutput[];
  total: number;
  next_offset: number | null;
}

export interface SaveOutput {
  id: string;
  source_path: string;
  source_sha256: string;
  status: "pending" | "reading" | "ready" | "error" | "cancelled";
  stage: string | null;
  metadata: { [key: string]: unknown };
  created_at: string;
  updated_at: string;
}

export interface SaveUpdateInput {
  status?: string | null;
  stage?: string | null;
  metadata?: { [key: string]: unknown } | null;
}

export interface SettingListOutput {
  items: SettingOutput[];
  total: number;
}

export interface SettingOutput {
  key: string;
  value: unknown;
  note: string | null;
  updated_at: string;
}

export interface SettingPutInput {
  value: unknown;
  note?: string | null;
}

export interface SquadOutput {
  save_id: string;
  club_uid: number;
  club_name: string | null;
  players: { [key: string]: unknown }[];
  selection: { [key: string]: unknown } | null;
}

export interface SystemResourcesOutput {
  cpu_count: number;
  available_memory_bytes: number;
  free_disk_bytes: number;
  recommended_workers: number;
}

export interface ValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
}
