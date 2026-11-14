import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Flask } from "@phosphor-icons/react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { useAppContext } from "../app-context";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";
import {
  ApiError,
  checkConcurrency,
  getDraft,
  getHostResources,
  listDrafts,
  startExperiment,
  submitExperiment,
  type ConcurrencyCheck,
  type DraftSummary,
  type ExperimentSubmitInput,
  type Job,
} from "../lib/api";
import { useAppEvents } from "../lib/useAppEvents";
import { useEventRefresh } from "../lib/useEventRefresh";
import "../styles/experiments.css";

const GIB = 1024 ** 3;
const NAME_LIMIT = 100;
const MATCH_LIMIT = 10000;
const SEED_LIMIT = 10000;
const MAX_SEED = 4294967295;
const WORKERS_MIN = 1;
const WORKERS_MAX = 256;
const CPU_MIN = 1;
const DEFAULT_MATCHES = 100;
const QUICK_MATCHES = [50, 100, 200];

const PRECHECK_CODE_LABELS: Record<string, string> = {
  insufficient_memory: "可用内存不足",
  insufficient_disk: "空闲磁盘不足",
};

type FormProblem = { text: string; tone: "info" | "error" };
type SeedParse = { seeds: number[]; problem: string | null; active: boolean };
type LaunchPhase = "submit" | "start";
type FailureMode = "settings" | "resource" | "retry" | "jobs" | "blocked";
type LaunchFailure = { phase: LaunchPhase; message: string; mode: FailureMode };
type Outcome = { kind: "started"; job: Job } | { kind: "empty" } | null;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function formatLocal(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return [
    date.getFullYear(),
    "-",
    pad(date.getMonth() + 1),
    "-",
    pad(date.getDate()),
    " ",
    pad(date.getHours()),
    ":",
    pad(date.getMinutes()),
  ].join("");
}

function draftLabel(draft: DraftSummary): string {
  const name = draft.name.trim() === "" ? draft.id : draft.name;
  return [name, " · 更新于 ", formatLocal(draft.updated_at)].join("");
}

function parseSeedText(text: string): SeedParse {
  if (text.trim() === "") return { seeds: [], problem: null, active: false };
  const tokens = text
    .trim()
    .split(/[\s,，]+/)
    .filter((token) => token !== "");
  if (tokens.length === 0) return { seeds: [], problem: "请填写至少一个种子", active: true };
  if (tokens.length > SEED_LIMIT) {
    return { seeds: [], problem: "固定种子最多 " + String(SEED_LIMIT) + " 个", active: true };
  }
  const seeds: number[] = [];
  const seen = new Set<number>();
  for (const token of tokens) {
    if (!/^\d+$/.test(token)) {
      return {
        seeds: [],
        problem: "种子 " + token + " 必须为 0 到 " + String(MAX_SEED) + " 的整数",
        active: true,
      };
    }
    const seed = Number(token);
    if (seed > MAX_SEED) {
      return {
        seeds: [],
        problem: "种子 " + token + " 必须为 0 到 " + String(MAX_SEED) + " 的整数",
        active: true,
      };
    }
    if (seen.has(seed)) {
      return { seeds: [], problem: "种子 " + String(seed) + " 重复", active: true };
    }
    seen.add(seed);
    seeds.push(seed);
  }
  return { seeds, problem: null, active: true };
}

function generateSeeds(count: number): number[] {
  const buffer = new Uint32Array(count);
  if (typeof globalThis.crypto?.getRandomValues === "function") {
    globalThis.crypto.getRandomValues(buffer);
    return Array.from(buffer);
  }
  return Array.from({ length: count }, () =>
    Math.floor(Math.random() * (MAX_SEED + 1)),
  );
}

function parseAwayTacticPool(scenario: { [key: string]: unknown }): {
  enabled: boolean;
  count: number;
} {
  const pool = scenario["away_tactic_pool"];
  if (!isRecord(pool)) return { enabled: false, count: 0 };
  const entries = Array.isArray(pool["entries"]) ? pool["entries"] : [];
  return { enabled: pool["enabled"] === true, count: entries.length };
}

function integerInRange(value: string, minimum: number, maximum: number): boolean {
  if (!/^\d+$/.test(value.trim())) return false;
  const parsed = Number(value);
  return parsed >= minimum && parsed <= maximum;
}

function integerAtLeast(value: string, minimum: number): boolean {
  if (!/^\d+$/.test(value.trim())) return false;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= minimum;
}

function positiveNumber(value: string): boolean {
  const trimmed = value.trim();
  if (trimmed === "") return false;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) && parsed > 0;
}

function gibToBytes(value: string): number {
  return Math.round(Number(value) * GIB);
}

function bytesToGibText(bytes: number): string {
  return String(Number((bytes / GIB).toFixed(1)));
}

const PRECHECK_FAIL_SUFFIX = /[，,]?资源预检未通过$/;

function formatPrecheckProblem(check: ConcurrencyCheck): string {
  if (check.warnings.length > 0) {
    return check.warnings
      .map((warning) => {
        const stripped = warning.replace(PRECHECK_FAIL_SUFFIX, "");
        return stripped === "" ? warning : stripped;
      })
      .join("；");
  }
  if (check.code !== null) return PRECHECK_CODE_LABELS[check.code] ?? check.code;
  return "资源不足";
}

function jobLabel(job: Job): string {
  return job.name !== null && job.name.trim() !== "" ? job.name : job.id;
}

class LaunchError extends Error {
  readonly phase: LaunchPhase;
  readonly original: unknown;

  constructor(phase: LaunchPhase, original: unknown) {
    super(errorMessage(original));
    this.name = "LaunchError";
    this.phase = phase;
    this.original = original;
  }
}

function failureCode(error: unknown): string | null {
  return error instanceof ApiError ? error.code : null;
}

function failureStatus(error: unknown): number | null {
  return error instanceof ApiError ? error.status : null;
}

function launchFailure(caught: unknown): LaunchFailure {
  const phase: LaunchPhase = caught instanceof LaunchError ? caught.phase : "submit";
  const original = caught instanceof LaunchError ? caught.original : caught;
  const message = errorMessage(original);
  const code = failureCode(original);
  const status = failureStatus(original);
  const retriable = original instanceof ApiError ? original.retriable : true;
  if (phase === "start") {
    if (status === 503 || code === "engine_unavailable") {
      return { phase, message, mode: "settings" };
    }
    if (!retriable || code === "invalid_transition") {
      return { phase, message, mode: "jobs" };
    }
    return { phase, message, mode: "retry" };
  }
  if (code === "validation_failed" && message.includes("引擎")) {
    return { phase, message, mode: "settings" };
  }
  if (status === 409 && (code === "insufficient_memory" || code === "insufficient_disk")) {
    return { phase, message, mode: "resource" };
  }
  return { phase, message, mode: retriable ? "retry" : "blocked" };
}

export function ExperimentsPage() {
  const { connection } = useAppContext();
  const queryClient = useQueryClient();

  const refreshJobs = useEventRefresh([["jobs"]]);

  useAppEvents(connection, (event) => {
    if (event.event.startsWith("experiment.") || event.event.startsWith("job.")) {
      refreshJobs();
    }
  });

  const [name, setName] = useState("");
  const [draftId, setDraftId] = useState("");
  const [baselineDraftId, setBaselineDraftId] = useState("");
  const [matchesText, setMatchesText] = useState(String(DEFAULT_MATCHES));
  const [seedsText, setSeedsText] = useState("");
  const [workers, setWorkers] = useState("");
  const [cpuText, setCpuText] = useState("");
  const [memoryText, setMemoryText] = useState("");
  const [diskText, setDiskText] = useState("");
  const [allowOversubscription, setAllowOversubscription] = useState(false);
  const [workersTouched, setWorkersTouched] = useState(false);
  const [resourcesTouched, setResourcesTouched] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [failure, setFailure] = useState<LaunchFailure | null>(null);

  const draftsQuery = useQuery({
    queryKey: ["drafts", connection?.url],
    queryFn: () => listDrafts(connection!),
    enabled: connection !== null,
  });
  const draftDetailQuery = useQuery({
    queryKey: ["draft", connection?.url, draftId],
    queryFn: () => getDraft(connection!, draftId),
    enabled: connection !== null && draftId !== "",
  });
  const resourcesQuery = useQuery({
    queryKey: ["host-resources", connection?.url],
    queryFn: () => getHostResources(connection!),
    enabled: connection !== null,
  });

  const resources = resourcesQuery.data;
  useEffect(() => {
    if (resources === undefined) return;
    if (!resourcesTouched) {
      setCpuText(String(resources.cpu_count));
      setMemoryText(bytesToGibText(resources.available_memory_bytes));
      setDiskText(bytesToGibText(resources.free_disk_bytes));
    }
    if (!workersTouched) {
      setWorkers(String(resources.recommended_workers));
    }
  }, [resources, resourcesTouched, workersTouched]);

  const workersValid = integerInRange(workers, WORKERS_MIN, WORKERS_MAX);
  const cpuValid = integerAtLeast(cpuText, CPU_MIN);
  const memoryValid = positiveNumber(memoryText);
  const diskValid = positiveNumber(diskText);
  const resourcesValid = workersValid && cpuValid && memoryValid && diskValid;

  const precheckQuery = useQuery({
    queryKey: [
      "concurrency",
      connection?.url,
      workers,
      cpuText,
      memoryText,
      diskText,
      allowOversubscription,
    ],
    queryFn: () =>
      checkConcurrency(connection!, {
        workers: Number(workers),
        cpu_count: Number(cpuText),
        available_memory_bytes: gibToBytes(memoryText),
        free_disk_bytes: gibToBytes(diskText),
        allow_oversubscription: allowOversubscription,
      }),
    enabled: connection !== null && resourcesValid,
  });

  const launch = useMutation({
    mutationFn: async (input: ExperimentSubmitInput): Promise<Job | null> => {
      try {
        await submitExperiment(connection!, input);
      } catch (error) {
        throw new LaunchError("submit", error);
      }
      try {
        return await startExperiment(connection!);
      } catch (error) {
        throw new LaunchError("start", error);
      }
    },
    onSuccess: (job) => {
      setFailure(null);
      setOutcome(job === null ? { kind: "empty" } : { kind: "started", job });
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["drafts"] });
    },
    onError: (error) => {
      setOutcome(null);
      setFailure(launchFailure(error));
    },
  });

  const restart = useMutation({
    mutationFn: () => startExperiment(connection!),
    onSuccess: (job) => {
      setFailure(null);
      setOutcome(job === null ? { kind: "empty" } : { kind: "started", job });
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (error) => {
      setFailure(launchFailure(new LaunchError("start", error)));
    },
  });

  const busy = launch.isPending || restart.isPending;

  const drafts = draftsQuery.data?.items ?? [];
  const draftsAvailable = drafts.length > 0;
  const draftDetail = draftDetailQuery.data;
  const pool = draftDetail === undefined ? null : parseAwayTacticPool(draftDetail.scenario);

  const seedParse = useMemo(() => parseSeedText(seedsText), [seedsText]);
  const seedsActive = seedParse.active;
  const baselineSelected = baselineDraftId !== "";
  const matchesValid = integerInRange(matchesText, 1, MATCH_LIMIT);
  const matchCount = seedsActive
    ? seedParse.problem === null
      ? seedParse.seeds.length
      : null
    : matchesValid
      ? Number(matchesText)
      : null;
  const totalMatches = matchCount === null ? null : matchCount * (baselineSelected ? 2 : 1);
  const totalProblem =
    totalMatches !== null && totalMatches > MATCH_LIMIT
      ? "总场数 " + String(totalMatches) + " 超过上限 " + String(MATCH_LIMIT)
      : null;

  const precheck = precheckQuery.data;
  const precheckPending = connection !== null && resourcesValid && precheckQuery.isPending;
  const precheckError = connection !== null && resourcesValid && precheckQuery.isError;
  const precheckProblem =
    precheck !== undefined && !precheck.allowed
      ? "资源预检未通过：" + formatPrecheckProblem(precheck)
      : null;

  const problems: FormProblem[] = [];
  if (busy) problems.push({ text: "正在提交实验…", tone: "info" });
  if (connection === null) {
    problems.push({ text: "sidecar 未连接，无法开始实验", tone: "error" });
  } else if (draftsQuery.isPending) {
    problems.push({ text: "正在加载草案…", tone: "info" });
  } else if (draftsQuery.isError) {
    problems.push({ text: "草案加载失败，请重试", tone: "error" });
  } else if (!draftsAvailable) {
    problems.push({ text: "还没有草案，请先到战术板新建", tone: "error" });
  } else if (draftId === "") {
    problems.push({ text: "请先选择草案", tone: "error" });
  } else if (draftDetailQuery.isPending) {
    problems.push({ text: "正在读取草案详情…", tone: "info" });
  } else if (draftDetailQuery.isError) {
    problems.push({ text: "草案详情读取失败，请重试", tone: "error" });
  }
  if (seedsActive && seedParse.problem !== null) {
    problems.push({ text: seedParse.problem, tone: "error" });
  }
  if (!seedsActive && !matchesValid) {
    problems.push({
      text: "场数需为 1 到 " + String(MATCH_LIMIT) + " 的整数",
      tone: "error",
    });
  }
  if (totalProblem !== null) problems.push({ text: totalProblem, tone: "error" });
  if (connection !== null) {
    if (resourcesQuery.isPending) {
      problems.push({ text: "正在读取本机资源…", tone: "info" });
    } else if (resourcesQuery.isError) {
      problems.push({ text: "本机资源读取失败，请重试", tone: "error" });
    }
  }
  if (resources !== undefined) {
    if (!workersValid) {
      problems.push({
        text: "并行数需为 " + String(WORKERS_MIN) + " 到 " + String(WORKERS_MAX) + " 的整数",
        tone: "error",
      });
    }
    if (!cpuValid) {
      problems.push({
        text: "CPU 核数需为大于等于 " + String(CPU_MIN) + " 的整数",
        tone: "error",
      });
    }
    if (!memoryValid) problems.push({ text: "可用内存需为大于 0 的数值", tone: "error" });
    if (!diskValid) problems.push({ text: "空闲磁盘需为大于 0 的数值", tone: "error" });
    if (precheckPending) {
      problems.push({ text: "正在检查资源…", tone: "info" });
    } else if (precheckError) {
      problems.push({ text: "资源预检失败，请重试", tone: "error" });
    } else if (precheckProblem !== null) {
      problems.push({ text: precheckProblem, tone: "error" });
    }
  }
  if (name.trim().length > NAME_LIMIT) {
    problems.push({ text: "实验名称最多 " + String(NAME_LIMIT) + " 个字符", tone: "error" });
  }
  const formLocked = outcome !== null || failure?.phase === "start";
  const lockedNotice =
    outcome?.kind === "started"
      ? "实验已启动，等待运行结束后才能再次提交。"
      : outcome?.kind === "empty"
        ? "没有待运行任务，点击「重新填写」后可再次提交。"
        : failure?.phase === "start"
          ? "实验已提交，请先处理下方提示。"
          : null;

  function buildInput(): ExperimentSubmitInput | null {
    if (connection === null || problems.length > 0 || matchCount === null) return null;
    return {
      name: name.trim() === "" ? null : name.trim(),
      seeds: seedsActive ? seedParse.seeds : generateSeeds(matchCount),
      draft_id: draftId,
      baseline_draft_id: baselineSelected ? baselineDraftId : null,
      workers: Number(workers),
      cpu_count: Number(cpuText),
      available_memory_bytes: gibToBytes(memoryText),
      free_disk_bytes: gibToBytes(diskText),
      allow_oversubscription: allowOversubscription,
    };
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (formLocked) return;
    const input = buildInput();
    if (input === null) return;
    setOutcome(null);
    setFailure(null);
    launch.mutate(input);
  }

  function handleDraftChange(value: string) {
    setDraftId(value);
    if (baselineDraftId === value) setBaselineDraftId("");
  }

  function adoptRecommended() {
    if (precheck === undefined) return;
    setWorkers(String(precheck.recommended_workers));
    setWorkersTouched(true);
  }

  function handleRetry() {
    if (failure === null) return;
    if (failure.phase === "start") {
      setFailure(null);
      restart.mutate();
      return;
    }
    const input = buildInput();
    if (input === null) return;
    setFailure(null);
    launch.mutate(input);
  }

  function resetLaunch() {
    setOutcome(null);
    setFailure(null);
  }

  return (
    <div className="page-grid">
      <Panel title="实验" className="experiment-page">
        {connection === null ? (
          <EmptyState
            icon={Flask}
            title="sidecar 未连接"
            description="连接 sidecar 后可以开始实验。"
          />
        ) : (
          <>
            <form className="experiment-form" aria-label="实验提交" onSubmit={handleSubmit}>
              {lockedNotice !== null ? (
                <p className="experiment-locked" role="status">
                  {lockedNotice}
                </p>
              ) : null}
              <section className="experiment-step" aria-labelledby="experiment-step-draft">
                <div className="experiment-step-head">
                  <span className="experiment-step-index" aria-hidden="true">
                    1
                  </span>
                  <h3 id="experiment-step-draft">选择战术</h3>
                </div>
                <p className="experiment-step-hint">选择要评估的草案，系统会用相同种子运行对局。</p>
                <div className="field">
                  <label htmlFor="experiment-draft">草案</label>
                  <select
                    id="experiment-draft"
                    value={draftId}
                    disabled={formLocked}
                    onChange={(event) => handleDraftChange(event.target.value)}
                  >
                    <option value="">请选择草案</option>
                    {drafts.map((draft) => (
                      <option key={draft.id} value={draft.id}>
                        {draftLabel(draft)}
                      </option>
                    ))}
                  </select>
                </div>
                {draftsQuery.isPending ? (
                  <p className="experiment-hint">正在加载草案…</p>
                ) : null}
                {draftsQuery.isError ? (
                  <div className="inline-alert" role="alert">
                    <span>{errorMessage(draftsQuery.error)}</span>
                    <button
                      type="button"
                      className="button small"
                      onClick={() => void draftsQuery.refetch()}
                    >
                      重试
                    </button>
                  </div>
                ) : null}
                {!draftsQuery.isPending && !draftsQuery.isError && !draftsAvailable ? (
                  <p className="experiment-empty">
                    还没有草案。<Link to="/tactics">前往战术板新建</Link>
                  </p>
                ) : null}
                {draftId !== "" ? (
                  draftDetailQuery.isPending ? (
                    <p className="experiment-hint">正在读取草案详情…</p>
                  ) : draftDetailQuery.isError ? (
                    <div className="inline-alert" role="alert">
                      <span>{errorMessage(draftDetailQuery.error)}</span>
                      <button
                        type="button"
                        className="button small"
                        onClick={() => void draftDetailQuery.refetch()}
                      >
                        重试
                      </button>
                    </div>
                  ) : pool !== null ? (
                    <p className="experiment-pool">
                      {pool.enabled
                        ? "客队战术池：" +
                          String(pool.count) +
                          " 套客队战术，每个种子随机抽取（用于检验泛化）"
                        : "固定对手（用于验证对特定打法的稳定性）"}
                    </p>
                  ) : null
                ) : null}
              </section>

              <section className="experiment-step" aria-labelledby="experiment-step-scale">
                <div className="experiment-step-head">
                  <span className="experiment-step-index" aria-hidden="true">
                    2
                  </span>
                  <h3 id="experiment-step-scale">对比与场数</h3>
                </div>
                <p className="experiment-step-hint">
                  场数决定实验规模，设置基线草案后会按相同种子做 A/B 对照。
                </p>
                <div className="field">
                  <label htmlFor="experiment-matches">场数</label>
                  <input
                    id="experiment-matches"
                    type="number"
                    min={1}
                    max={MATCH_LIMIT}
                    step={1}
                    value={matchesText}
                    disabled={seedsActive || formLocked}
                    onChange={(event) => setMatchesText(event.target.value)}
                  />
                  {seedsActive ? (
                    <p className="experiment-hint">已启用固定种子，场数由种子数量决定。</p>
                  ) : null}
                  {!seedsActive && !matchesValid ? (
                    <p className="experiment-error" role="alert">
                      场数需为 1 到 {MATCH_LIMIT} 的整数
                    </p>
                  ) : null}
                </div>
                {seedsActive ? null : (
                  <div className="experiment-quick">
                    {QUICK_MATCHES.map((value) => (
                      <button
                        key={value}
                        type="button"
                        className="button small"
                        disabled={formLocked}
                        onClick={() => setMatchesText(String(value))}
                      >
                        {String(value)} 场
                      </button>
                    ))}
                  </div>
                )}
                <p className="experiment-total">
                  {totalMatches === null
                    ? "总场数 = —"
                    : baselineSelected
                      ? "总场数 = " +
                        String(matchCount) +
                        " × 2 = " +
                        String(totalMatches) +
                        " 场（A/B 对照）"
                      : "总场数 = " + String(totalMatches) + " 场"}
                </p>
                {totalProblem !== null ? (
                  <p className="experiment-error" role="alert">
                    {totalProblem}
                  </p>
                ) : null}
                <div className="field">
                  <label htmlFor="experiment-baseline">对比基线草案</label>
                  <select
                    id="experiment-baseline"
                    value={baselineDraftId}
                    disabled={formLocked}
                    onChange={(event) => setBaselineDraftId(event.target.value)}
                  >
                    <option value="">不设基线</option>
                    {drafts
                      .filter((draft) => draft.id !== draftId)
                      .map((draft) => (
                        <option key={draft.id} value={draft.id}>
                          {draftLabel(draft)}
                        </option>
                      ))}
                  </select>
                  <p className="experiment-hint">
                    与基线草案使用相同种子，结果页展示配对差值。
                  </p>
                </div>
                <details className="experiment-advanced">
                  <summary>固定种子（高级）</summary>
                  <div className="experiment-advanced-body">
                    <div className="field">
                      <label htmlFor="experiment-seeds">固定种子</label>
                      <textarea
                        id="experiment-seeds"
                        rows={3}
                        placeholder="例如：11, 23, 42"
                        value={seedsText}
                        disabled={formLocked}
                        onChange={(event) => setSeedsText(event.target.value)}
                      />
                      <p className="experiment-hint">留空时每次提交自动生成随机种子。</p>
                    </div>
                    {seedsActive && seedParse.problem !== null ? (
                      <p className="experiment-error" role="alert">
                        {seedParse.problem}
                      </p>
                    ) : null}
                    {seedsActive && seedParse.problem === null ? (
                      <p className="experiment-total">
                        按固定种子共 {String(totalMatches)} 场
                        {baselineSelected ? "（A/B 对照）" : ""}
                      </p>
                    ) : null}
                  </div>
                </details>
              </section>

              <section className="experiment-step" aria-labelledby="experiment-step-resources">
                <div className="experiment-step-head">
                  <span className="experiment-step-index" aria-hidden="true">
                    3
                  </span>
                  <h3 id="experiment-step-resources">资源与提交</h3>
                </div>
                <p className="experiment-step-hint">
                  本机资源用于预检，提交后会立即启动实验。
                </p>
                <div className="experiment-resources" role="region" aria-label="主机资源">
                  {resourcesQuery.isPending ? (
                    <p className="experiment-hint">正在读取本机资源…</p>
                  ) : null}
                  {resourcesQuery.isError ? (
                    <div className="inline-alert" role="alert">
                      <span>{errorMessage(resourcesQuery.error)}</span>
                      <button
                        type="button"
                        className="button small"
                        onClick={() => void resourcesQuery.refetch()}
                      >
                        重试
                      </button>
                    </div>
                  ) : null}
                  {resources !== undefined ? (
                    <>
                      <p className="experiment-hint">
                        {resourcesTouched
                          ? "资源数值已手动调整。"
                          : "已自动读取本机资源，可手动修改。"}
                      </p>
                      <div className="experiment-grid">
                        <div className="field">
                          <label htmlFor="experiment-cpu">CPU 核数</label>
                          <input
                            id="experiment-cpu"
                            type="number"
                            min={CPU_MIN}
                            step={1}
                            value={cpuText}
                            disabled={formLocked}
                            onChange={(event) => {
                              setCpuText(event.target.value);
                              setResourcesTouched(true);
                            }}
                          />
                          {!cpuValid ? (
                            <p className="experiment-error" role="alert">
                              CPU 核数需为大于等于 {CPU_MIN} 的整数
                            </p>
                          ) : null}
                        </div>
                        <div className="field">
                          <label htmlFor="experiment-memory">可用内存（GiB）</label>
                          <input
                            id="experiment-memory"
                            type="number"
                            min={0}
                            step={0.1}
                            value={memoryText}
                            disabled={formLocked}
                            onChange={(event) => {
                              setMemoryText(event.target.value);
                              setResourcesTouched(true);
                            }}
                          />
                          {!memoryValid ? (
                            <p className="experiment-error" role="alert">
                              可用内存需为大于 0 的数值
                            </p>
                          ) : null}
                        </div>
                        <div className="field">
                          <label htmlFor="experiment-disk">空闲磁盘（GiB）</label>
                          <input
                            id="experiment-disk"
                            type="number"
                            min={0}
                            step={0.1}
                            value={diskText}
                            disabled={formLocked}
                            onChange={(event) => {
                              setDiskText(event.target.value);
                              setResourcesTouched(true);
                            }}
                          />
                          {!diskValid ? (
                            <p className="experiment-error" role="alert">
                              空闲磁盘需为大于 0 的数值
                            </p>
                          ) : null}
                        </div>
                        <div className="field">
                          <label htmlFor="experiment-workers">并行数</label>
                          <input
                            id="experiment-workers"
                            type="number"
                            min={WORKERS_MIN}
                            max={WORKERS_MAX}
                            step={1}
                            value={workers}
                            disabled={formLocked}
                            onChange={(event) => {
                              setWorkers(event.target.value);
                              setWorkersTouched(true);
                            }}
                          />
                          <p className="experiment-hint">同时运行的对局数，受资源预检推荐值约束。</p>
                          {!workersValid ? (
                            <p className="experiment-error" role="alert">
                              并行数需为 {WORKERS_MIN} 到 {WORKERS_MAX} 的整数
                            </p>
                          ) : null}
                        </div>
                      </div>
                      <label className="field-inline">
                        <input
                          type="checkbox"
                          checked={allowOversubscription}
                          disabled={formLocked}
                          onChange={(event) => setAllowOversubscription(event.target.checked)}
                        />
                        允许超分配
                      </label>
                    </>
                  ) : null}
                </div>
                {resources !== undefined ? (
                  <div className="experiment-precheck" role="region" aria-label="资源预检" aria-live="polite">
                    {precheckPending ? <p className="experiment-hint">正在检查资源…</p> : null}
                    {precheckError ? (
                      <div className="inline-alert" role="alert">
                        <span>{errorMessage(precheckQuery.error)}</span>
                        <button
                          type="button"
                          className="button small"
                          onClick={() => void precheckQuery.refetch()}
                        >
                          重试
                        </button>
                      </div>
                    ) : null}
                    {precheck !== undefined && precheck.allowed ? (
                      <p className="experiment-precheck-pass">
                        <span>资源预检通过，推荐并行数 {String(precheck.recommended_workers)}</span>
                        {precheck.recommended_workers !== Number(workers) ? (
                          <button
                            type="button"
                            className="button small"
                            onClick={adoptRecommended}
                          >
                            采用推荐并行数 {String(precheck.recommended_workers)}
                          </button>
                        ) : null}
                      </p>
                    ) : null}
                    {precheck !== undefined && !precheck.allowed ? (
                      <p className="experiment-precheck-fail">{precheckProblem}</p>
                    ) : null}
                  </div>
                ) : null}
                <div className="field">
                  <label htmlFor="experiment-name">实验名称（可选）</label>
                  <input
                    id="experiment-name"
                    type="text"
                    placeholder="便于在任务列表中识别"
                    value={name}
                    disabled={formLocked}
                    onChange={(event) => setName(event.target.value)}
                  />
                </div>
                <div className="experiment-submit">
                  <button
                    type="submit"
                    className="button primary"
                    disabled={formLocked || problems.length > 0}
                    aria-busy={busy ? true : undefined}
                  >
                    {totalMatches === null ? "开始实验" : "开始实验（" + String(totalMatches) + " 场）"}
                  </button>
                  {problems.length > 0 ? (
                    <ul className="experiment-problems" aria-label="阻塞原因" aria-live="polite">
                      {problems.map((problem, index) => (
                        <li
                          key={String(index) + "-" + problem.text}
                          className="experiment-submit-reason"
                          data-tone={problem.tone}
                        >
                          {problem.text}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              </section>
            </form>

            {outcome !== null ? (
              <section className="experiment-outcome" aria-label="启动结果" role="status">
                {outcome.kind === "started" ? (
                  <>
                    <p className="experiment-outcome-title">
                      实验已启动：{jobLabel(outcome.job)}
                    </p>
                    <div className="experiment-outcome-meta">
                      <span>总场数 {String(outcome.job.total)}</span>
                      <Link className="button small" to="/jobs">
                        查看任务
                      </Link>
                      <button type="button" className="button small" onClick={resetLaunch}>
                        重新填写
                      </button>
                    </div>
                  </>
                ) : (
                  <div className="experiment-outcome-meta">
                    <p className="experiment-outcome-title">没有待运行任务</p>
                    <button type="button" className="button small" onClick={resetLaunch}>
                      重新填写
                    </button>
                  </div>
                )}
              </section>
            ) : null}
            {failure !== null ? (
              <div className="inline-alert" role="alert">
                <span>{failure.message}</span>
                {failure.mode === "settings" ? (
                  <Link to="/settings">前往设置页配置引擎</Link>
                ) : null}
                {failure.mode === "resource" ? (
                  <span>请降低并行数或减少场数后重试。</span>
                ) : null}
                {failure.mode === "jobs" ? (
                  <>
                    <span>已有任务在运行，请等待其结束后再试。</span>
                    <Link to="/jobs">查看任务</Link>
                  </>
                ) : null}
                {failure.mode === "blocked" ? <span>请修正输入后重新提交。</span> : null}
                {failure.mode === "jobs" || failure.mode === "blocked" ? (
                  <button type="button" className="button small" onClick={resetLaunch}>
                    重新填写
                  </button>
                ) : null}
                {failure.phase === "start" &&
                (failure.mode === "retry" || failure.mode === "settings") ? (
                  <button type="button" className="button small" onClick={handleRetry}>
                    重试启动
                  </button>
                ) : null}
                {failure.phase === "submit" && failure.mode === "retry" ? (
                  <button type="button" className="button small" onClick={handleRetry}>
                    重试
                  </button>
                ) : null}
              </div>
            ) : null}
          </>
        )}
      </Panel>
    </div>
  );
}
