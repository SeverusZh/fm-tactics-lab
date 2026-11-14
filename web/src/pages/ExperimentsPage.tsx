import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Flask } from "@phosphor-icons/react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { useAppContext } from "../app-context";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";
import {
  checkConcurrency,
  getHostResources,
  listDrafts,
  startExperiment,
  submitExperiment,
  type ExperimentSubmitInput,
  type Job,
  type JobStatus,
} from "../lib/api";
import { useAppEvents } from "../lib/useAppEvents";
import { useEventRefresh } from "../lib/useEventRefresh";

const GIB = 1024 ** 3;
const NAME_LIMIT = 100;
const SEED_LIMIT = 10000;
const MATCH_LIMIT = 10000;
const MAX_SEED = 4294967295;
const WORKERS_MIN = 1;
const WORKERS_MAX = 256;

const STATUS_LABELS: Record<JobStatus, string> = {
  queued: "排队中",
  running: "运行中",
  interrupted: "已中断",
  completed: "已完成",
  error: "失败",
  cancelled: "已取消",
};

const STATUS_TONES: Partial<Record<JobStatus, "ok" | "warn" | "error">> = {
  queued: "warn",
  interrupted: "warn",
  completed: "ok",
  error: "error",
};

const PRECHECK_CODE_LABELS: Record<string, string> = {
  insufficient_memory: "内存不足",
  insufficient_disk: "磁盘不足",
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatGib(bytes: number): string {
  return `${(bytes / GIB).toFixed(1)} GiB`;
}

function integerBetween(value: string, minimum: number, maximum: number): boolean {
  if (value.trim() === "") return false;
  const number = Number(value);
  return Number.isInteger(number) && number >= minimum && number <= maximum;
}

function parseSeeds(text: string): { seeds: number[]; problem: string | null } {
  const tokens = text.split(/[\s,，]+/).filter((token) => token !== "");
  if (tokens.length === 0) return { seeds: [], problem: "请填写至少一个种子" };
  if (tokens.length > SEED_LIMIT) {
    return { seeds: [], problem: `种子数量不能超过 ${SEED_LIMIT}` };
  }
  const seeds: number[] = [];
  const seen = new Set<number>();
  for (const token of tokens) {
    if (!/^\d+$/.test(token)) {
      return { seeds: [], problem: `种子 ${token} 必须为 0 到 ${MAX_SEED} 的整数` };
    }
    const seed = Number(token);
    if (seed > MAX_SEED) {
      return { seeds: [], problem: `种子 ${token} 必须为 0 到 ${MAX_SEED} 的整数` };
    }
    if (seen.has(seed)) return { seeds: [], problem: `种子 ${token} 重复` };
    seen.add(seed);
    seeds.push(seed);
  }
  return { seeds, problem: null };
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
  const [seedsText, setSeedsText] = useState("");
  const [workers, setWorkers] = useState("");
  const [allowOversubscription, setAllowOversubscription] = useState(false);
  const [workersTouched, setWorkersTouched] = useState(false);
  const [seedsTouched, setSeedsTouched] = useState(false);
  const [submitAttempted, setSubmitAttempted] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [submittedJob, setSubmittedJob] = useState<Job | null>(null);
  const [startedJob, setStartedJob] = useState<Job | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [startNotice, setStartNotice] = useState<string | null>(null);

  const draftsQuery = useQuery({
    queryKey: ["drafts", connection?.url],
    queryFn: () => listDrafts(connection!),
    enabled: connection !== null,
  });
  const resourcesQuery = useQuery({
    queryKey: ["experiments-resources", connection?.url],
    queryFn: () => getHostResources(connection!),
    enabled: connection !== null,
  });

  const recommendedWorkers = resourcesQuery.data?.recommended_workers;
  useEffect(() => {
    if (recommendedWorkers === undefined || workersTouched) return;
    setWorkers(String(recommendedWorkers));
  }, [recommendedWorkers, workersTouched]);

  const workersValid = integerBetween(workers, WORKERS_MIN, WORKERS_MAX);
  const resources = resourcesQuery.data;
  const seedParse = useMemo(() => parseSeeds(seedsText), [seedsText]);
  const baselineSelected = baselineDraftId !== "";
  const totalMatches = seedParse.seeds.length * (baselineSelected ? 2 : 1);
  const totalProblem =
    seedParse.problem === null && totalMatches > MATCH_LIMIT
      ? `总场数 ${totalMatches} 超过上限 ${MATCH_LIMIT}`
      : null;
  const nameProblem =
    name.trim().length > NAME_LIMIT ? `实验名称最多 ${NAME_LIMIT} 个字符` : null;
  const drafts = draftsQuery.data?.items ?? [];
  const draftsAvailable = drafts.length > 0;
  const baselineDrafts = drafts.filter((draft) => draft.id !== draftId);

  const precheckQuery = useQuery({
    queryKey: [
      "concurrency",
      connection?.url,
      workers,
      allowOversubscription,
      resources?.cpu_count,
      resources?.available_memory_bytes,
      resources?.free_disk_bytes,
    ],
    queryFn: () =>
      checkConcurrency(connection!, {
        workers: Number(workers),
        cpu_count: Number(resources!.cpu_count),
        available_memory_bytes: Number(resources!.available_memory_bytes),
        free_disk_bytes: Number(resources!.free_disk_bytes),
        allow_oversubscription: allowOversubscription,
      }),
    enabled: connection !== null && resources !== undefined && workersValid,
  });
  const precheck = precheckQuery.data;
  const precheckAllowed = precheck?.allowed === true;

  const submit = useMutation({
    mutationFn: (input: ExperimentSubmitInput) => submitExperiment(connection!, input),
    onSuccess: (job) => {
      setSubmitError(null);
      setNotice("实验已提交");
      setStartError(null);
      setStartNotice(null);
      setStartedJob(null);
      setSubmittedJob(job);
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (error) => {
      setNotice(null);
      setSubmitError(errorMessage(error));
    },
  });

  const start = useMutation({
    mutationFn: () => startExperiment(connection!),
    onSuccess: (job) => {
      setStartError(null);
      if (job === null) {
        setStartedJob(null);
        setStartNotice("没有待运行任务");
        return;
      }
      setStartNotice(null);
      setStartedJob(job);
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (error) => {
      setStartNotice(null);
      setStartError(errorMessage(error));
    },
  });

  const showSeedProblem = seedParse.problem !== null && (seedsTouched || submitAttempted);
  const showDraftProblem = submitAttempted && draftsAvailable && draftId === "";
  const showWorkersProblem = workersTouched && !workersValid;
  const formBlocked =
    connection === null ||
    resources === undefined ||
    !draftsAvailable ||
    !workersValid ||
    totalProblem !== null ||
    nameProblem !== null ||
    !precheckAllowed ||
    submit.isPending;

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitAttempted(true);
    if (connection === null || resources === undefined) return;
    if (
      seedParse.problem !== null ||
      totalProblem !== null ||
      nameProblem !== null ||
      draftId === "" ||
      !workersValid
    ) {
      return;
    }
    const input: ExperimentSubmitInput = {
      name: name.trim() === "" ? null : name.trim(),
      seeds: seedParse.seeds,
      draft_id: draftId,
      baseline_draft_id: baselineDraftId === "" ? null : baselineDraftId,
      workers: Number(workers),
      cpu_count: Number(resources.cpu_count),
      available_memory_bytes: Number(resources.available_memory_bytes),
      free_disk_bytes: Number(resources.free_disk_bytes),
      allow_oversubscription: allowOversubscription,
    };
    submit.mutate(input);
  };

  const seedsDescribedBy = [
    seedParse.problem === null ? "experiment-seeds-hint" : "",
    showSeedProblem ? "experiment-seeds-error" : "",
    totalProblem !== null ? "experiment-total-error" : "",
  ]
    .filter((id) => id !== "")
    .join(" ");

  return (
    <div className="page-grid">
      <Panel title="实验" className="span-12">
        {connection === null ? (
          <EmptyState
            icon={Flask}
            title="sidecar 未连接"
            description="连接 sidecar 后可以提交实验。"
          />
        ) : (
          <>
            {draftsQuery.isPending ? (
              <p className="jobs-loading" role="status">
                正在加载草案…
              </p>
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
            {draftsQuery.isSuccess && !draftsAvailable ? (
              <EmptyState
                icon={Flask}
                title="尚无草案"
                description="先到战术板保存草案，再提交实验。"
              />
            ) : null}
            <form className="experiments-form" aria-label="实验提交" onSubmit={handleSubmit}>
              <div className="field">
                <label htmlFor="experiment-name">实验名称</label>
                <input
                  id="experiment-name"
                  value={name}
                  placeholder="可选，最多 100 个字符"
                  aria-invalid={nameProblem !== null}
                  aria-describedby={nameProblem !== null ? "experiment-name-error" : undefined}
                  onChange={(event) => setName(event.target.value)}
                />
                {nameProblem !== null ? (
                  <span className="field-error" id="experiment-name-error" role="alert">
                    {nameProblem}
                  </span>
                ) : null}
              </div>

              <div className="field">
                <label htmlFor="experiment-draft">草案</label>
                <select
                  id="experiment-draft"
                  value={draftId}
                  disabled={!draftsAvailable}
                  aria-invalid={showDraftProblem}
                  aria-describedby={showDraftProblem ? "experiment-draft-error" : undefined}
                  onChange={(event) => {
                    const value = event.target.value;
                    setDraftId(value);
                    if (baselineDraftId === value) setBaselineDraftId("");
                  }}
                >
                  <option value="">请选择草案</option>
                  {drafts.map((draft) => (
                    <option key={draft.id} value={draft.id}>
                      {draft.name.trim() === "" ? draft.id : `${draft.name} · ${draft.id}`}
                    </option>
                  ))}
                </select>
                {showDraftProblem ? (
                  <span className="field-error" id="experiment-draft-error" role="alert">
                    请选择草案
                  </span>
                ) : null}
              </div>

              <div className="field">
                <label htmlFor="experiment-baseline">基线草案</label>
                <select
                  id="experiment-baseline"
                  value={baselineDraftId}
                  onChange={(event) => setBaselineDraftId(event.target.value)}
                >
                  <option value="">不设基线</option>
                  {baselineDrafts.map((draft) => (
                    <option key={draft.id} value={draft.id}>
                      {draft.name.trim() === "" ? draft.id : `${draft.name} · ${draft.id}`}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field experiments-form-wide">
                <label htmlFor="experiment-seeds">种子</label>
                <textarea
                  id="experiment-seeds"
                  value={seedsText}
                  placeholder="每行一个，或用空格、逗号分隔"
                  aria-invalid={showSeedProblem || totalProblem !== null}
                  aria-describedby={seedsDescribedBy === "" ? undefined : seedsDescribedBy}
                  onChange={(event) => {
                    setSeedsText(event.target.value);
                    setSeedsTouched(true);
                  }}
                />
                {seedParse.problem === null ? (
                  <span className="field-hint" id="experiment-seeds-hint">
                    共 {totalMatches} 场
                  </span>
                ) : null}
                {showSeedProblem ? (
                  <span className="field-error" id="experiment-seeds-error" role="alert">
                    {seedParse.problem}
                  </span>
                ) : null}
                {totalProblem !== null ? (
                  <span className="field-error" id="experiment-total-error" role="alert">
                    {totalProblem}
                  </span>
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
                  aria-invalid={showWorkersProblem}
                  aria-describedby={showWorkersProblem ? "experiment-workers-error" : undefined}
                  onChange={(event) => {
                    setWorkers(event.target.value);
                    setWorkersTouched(true);
                  }}
                />
                {showWorkersProblem ? (
                  <span className="field-error" id="experiment-workers-error" role="alert">
                    并行数需为 1 到 256 的整数
                  </span>
                ) : null}
              </div>

              <label
                className="field-inline experiments-oversubscription"
                htmlFor="experiment-oversubscription"
              >
                <input
                  id="experiment-oversubscription"
                  type="checkbox"
                  checked={allowOversubscription}
                  onChange={(event) => setAllowOversubscription(event.target.checked)}
                />
                允许超分配
              </label>

              <section
                className="experiments-resources experiments-form-wide"
                role="region"
                aria-label="主机资源"
              >
                {resourcesQuery.isPending ? (
                  <p className="jobs-loading" role="status">
                    正在探测主机资源…
                  </p>
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
                  <dl className="experiments-resource-list">
                    <div>
                      <dt>CPU 核数</dt>
                      <dd>{resources.cpu_count}</dd>
                    </div>
                    <div>
                      <dt>可用内存</dt>
                      <dd>{formatGib(resources.available_memory_bytes)}</dd>
                    </div>
                    <div>
                      <dt>空闲磁盘</dt>
                      <dd>{formatGib(resources.free_disk_bytes)}</dd>
                    </div>
                  </dl>
                ) : null}
              </section>

              {resources !== undefined && workersValid ? (
                <section
                  className="experiments-precheck experiments-form-wide"
                  role="region"
                  aria-label="资源预检"
                  aria-live="polite"
                >
                  {precheckQuery.isPending ? (
                    <p className="jobs-loading" role="status">
                      正在检查资源…
                    </p>
                  ) : null}
                  {precheckQuery.isError ? (
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
                  {precheck !== undefined ? (
                    <div className="experiments-precheck-headline">
                      <span
                        className="badge"
                        data-tone={precheck.allowed ? "ok" : "error"}
                      >
                        {precheck.allowed ? "通过" : "阻止提交"}
                      </span>
                      {precheck.allowed ? (
                        <span className="experiments-precheck-reason">
                          推荐并行数 <strong>{precheck.recommended_workers}</strong>
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                  {precheck !== undefined
                    ? precheck.warnings.map((warning) => (
                        <p className="experiments-precheck-warning" key={warning}>
                          {warning}
                        </p>
                      ))
                    : null}
                  {precheck !== undefined && !precheck.allowed && precheck.warnings.length === 0 ? (
                    <p className="experiments-precheck-reason">
                      {PRECHECK_CODE_LABELS[precheck.code ?? ""] ?? precheck.code ?? "资源不足"}
                    </p>
                  ) : null}
                </section>
              ) : null}

              <div className="experiments-form-actions">
                <button
                  type="submit"
                  className="button primary"
                  disabled={formBlocked}
                  aria-busy={submit.isPending ? true : undefined}
                >
                  提交实验
                </button>
              </div>
            </form>

            {submitError !== null ? (
              <div className="inline-alert" role="alert">
                <span>{submitError}</span>
              </div>
            ) : null}
            {notice !== null ? (
              <p className="jobs-notice" role="status">
                {notice}
              </p>
            ) : null}
            {submittedJob !== null ? (
              <section className="experiments-result" aria-label="实验任务">
                <div className="experiments-result-head">
                  <span className="badge" data-tone={STATUS_TONES[submittedJob.status]}>
                    {STATUS_LABELS[submittedJob.status]}
                  </span>
                  <span className="experiments-result-total">
                    总场数 {submittedJob.total}
                  </span>
                </div>
                <p className="experiments-result-name">
                  {submittedJob.name === null ? submittedJob.id : submittedJob.name}
                </p>
                <p className="experiments-result-id data-path">{submittedJob.id}</p>
                <div className="experiments-result-actions">
                  <button
                    type="button"
                    className="button primary"
                    disabled={start.isPending}
                    aria-busy={start.isPending ? true : undefined}
                    onClick={() => start.mutate()}
                  >
                    启动实验
                  </button>
                  <Link className="button" to="/jobs">
                    查看任务
                  </Link>
                </div>
                {startError !== null ? (
                  <div className="inline-alert" role="alert">
                    <span>{startError}</span>
                  </div>
                ) : null}
                {startNotice !== null ? (
                  <p className="jobs-notice" role="status">
                    {startNotice}
                  </p>
                ) : null}
              </section>
            ) : null}
            {startedJob !== null ? (
              <section className="experiments-result" aria-label="启动结果">
                <div className="experiments-result-head">
                  <h3 className="experiments-start-title">已启动任务</h3>
                  <span className="badge" data-tone={STATUS_TONES[startedJob.status]}>
                    {STATUS_LABELS[startedJob.status]}
                  </span>
                  <span className="experiments-result-total">总场数 {startedJob.total}</span>
                </div>
                <p className="experiments-result-name">
                  {startedJob.name === null ? startedJob.id : startedJob.name}
                </p>
                <p className="experiments-result-id data-path">{startedJob.id}</p>
                {submittedJob !== null && startedJob.id !== submittedJob.id ? (
                  <p className="experiments-start-note">
                    已启动队列中更早的任务，而不是本次提交的任务
                  </p>
                ) : null}
                <div className="experiments-result-actions">
                  <Link className="button" to="/results">
                    查看结果
                  </Link>
                </div>
              </section>
            ) : null}
          </>
        )}
      </Panel>
    </div>
  );
}
