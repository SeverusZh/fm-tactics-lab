import { useMutation, useQuery } from "@tanstack/react-query";
import { ChartBar } from "@phosphor-icons/react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { useAppContext } from "../app-context";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";
import {
  compareResults,
  deleteJobsBatch,
  downloadJobCsv,
  getJobPoolSummary,
  getJobSummary,
  listJobRuns,
  listJobs,
  type CompareResult,
  type Job,
  type JobBatchDeleteResult,
  type JobMetrics,
  type JobStatus,
  type JobSummary,
  type PoolSummary,
} from "../lib/api";
import { useAppEvents } from "../lib/useAppEvents";
import { useEventRefresh } from "../lib/useEventRefresh";

const PAGE_SIZE = 20;
const JOB_PAGE_SIZE = 50;
const COMPARE_MAX_CANDIDATES = 5;
const POOL_EXPANDED_KEY = "fm27lab.results.pool-expanded";

function readPoolExpanded(): Record<string, boolean> {
  try {
    const raw = sessionStorage.getItem(POOL_EXPANDED_KEY);
    if (raw === null) return {};
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return {};
    const expanded: Record<string, boolean> = {};
    for (const [jobId, value] of Object.entries(parsed)) {
      if (typeof value === "boolean") expanded[jobId] = value;
    }
    return expanded;
  } catch {
    return {};
  }
}

function writePoolExpanded(expanded: Record<string, boolean>): void {
  try {
    sessionStorage.setItem(POOL_EXPANDED_KEY, JSON.stringify(expanded));
  } catch {
    return;
  }
}

function jobLabel(job: Job): string {
  return job.name === null ? job.id : `${job.name}（${job.id}）`;
}

function jobCheckboxLabel(job: Job): string {
  return job.name === null ? `选择任务 ${job.id}` : `选择任务 ${job.name}（${job.id}）`;
}

const STATUS_LABELS: Record<JobStatus, string> = {
  queued: "排队中",
  running: "运行中",
  interrupted: "已中断",
  completed: "已完成",
  error: "失败",
  cancelled: "已取消",
};

const STATUS_TONES: Record<JobStatus, "ok" | "warn" | "error" | undefined> = {
  queued: "warn",
  running: undefined,
  interrupted: "warn",
  completed: "ok",
  error: "error",
  cancelled: undefined,
};

const POOL_MODE_LABELS: Record<string, string> = {
  random: "随机抽取",
  rotation: "轮战",
};

const POOL_PLAYERS_LABELS: Record<string, string> = {
  uniform: "统一属性",
  real: "真实名单",
};

function poolModeLabel(mode: PoolSummary["mode"]): string {
  return mode === null ? "—" : (POOL_MODE_LABELS[mode] ?? "—");
}

function poolPlayersLabel(players: PoolSummary["players"]): string {
  return players === null ? "—" : (POOL_PLAYERS_LABELS[players] ?? "—");
}

const dateFormat = new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" });

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : dateFormat.format(date);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatNumber(value: number | null, digits: number): string {
  return value === null ? "—" : value.toFixed(digits);
}

function formatRatioPercent(value: number | null): string {
  return value === null ? "—" : (value * 100).toFixed(1) + "%";
}

function formatPercent(value: number): string {
  return value.toFixed(1) + "%";
}

function formatDelta(value: number | null): string {
  if (value === null) return "—";
  return (value >= 0 ? "+" : "") + value.toFixed(2);
}

function formatSignedPercent(value: number | null): string {
  if (value === null) return "—";
  return (value >= 0 ? "+" : "") + (value * 100).toFixed(1) + "%";
}

function formatPercentInterval(interval: [number, number]): string {
  return "[" + (interval[0] * 100).toFixed(1) + "%, " + (interval[1] * 100).toFixed(1) + "%]";
}

function seedList(seeds: number[]): string {
  return seeds.slice(0, 3).join("、") + (seeds.length > 3 ? "…" : "");
}

function triggerTextDownload(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

type CompareView =
  | { key: string; status: "running" }
  | { key: string; status: "error"; message: string }
  | { key: string; status: "success"; result: CompareResult };

type MetricCard = {
  label: string;
  value: string;
  hint?: string;
};

function metricCards(metrics: JobMetrics, paired: JobSummary["paired"]): MetricCard[] {
  return [
    { label: "场次", value: String(metrics.n) },
    { label: "胜 / 平 / 负", value: `${metrics.wins} / ${metrics.draws} / ${metrics.losses}` },
    {
      label: "胜率",
      value: formatRatioPercent(metrics.win_rate),
      hint: `95% 区间 ${formatRatioPercent(metrics.win_interval[0])}–${formatRatioPercent(metrics.win_interval[1])}`,
    },
    { label: "场均进球", value: formatNumber(metrics.goals_for, 2) },
    { label: "场均失球", value: formatNumber(metrics.goals_against, 2) },
    { label: "场均积分", value: formatNumber(metrics.points, 2) },
    { label: "xG", value: formatNumber(metrics.xg, 2) },
    { label: "xGA", value: formatNumber(metrics.xga, 2) },
    { label: "控球率", value: metrics.possession === null ? "—" : formatPercent(metrics.possession) },
    { label: "场均射门", value: formatNumber(metrics.shots, 1) },
    { label: "传球成功率", value: formatRatioPercent(metrics.pass_completion) },
    { label: "配对场次", value: String(paired.n) },
    { label: "净胜球差", value: formatDelta(paired.goal_difference_delta) },
  ];
}

function eventPayloadField(payload: unknown, key: string): unknown {
  if (typeof payload !== "object" || payload === null) return undefined;
  return Object.getOwnPropertyDescriptor(payload, key)?.value;
}

export function ResultsPage() {
  const { connection } = useAppContext();
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatus | "">("");
  const [side, setSide] = useState<0 | 1>(0);
  const [runsOffset, setRunsOffset] = useState(0);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [poolExpandedJobs, setPoolExpandedJobs] = useState<Record<string, boolean>>(
    readPoolExpanded,
  );
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const [compareVariant, setCompareVariant] = useState<"A" | "B">("B");
  const [compareView, setCompareView] = useState<CompareView | null>(null);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set<string>());
  const [batchConfirmOpen, setBatchConfirmOpen] = useState(false);
  const [batchResult, setBatchResult] = useState<JobBatchDeleteResult | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const compareRequestRef = useRef(0);
  const batchTriggerRef = useRef<HTMLButtonElement>(null);
  const batchCancelRef = useRef<HTMLButtonElement>(null);
  const batchResultRef = useRef<HTMLDivElement>(null);

  const jobs = useQuery({
    queryKey: ["results-jobs", connection?.url, jobStatus],
    queryFn: () =>
      listJobs(connection!, {
        status: jobStatus === "" ? undefined : jobStatus,
        limit: JOB_PAGE_SIZE,
        offset: 0,
      }),
    enabled: connection !== null,
  });

  const jobItems =
    jobs.data !== undefined && Array.isArray(jobs.data.items) ? jobs.data.items : [];
  const activeJobId = jobItems.some((job) => job.id === selectedJobId)
    ? selectedJobId
    : (jobItems[0]?.id ?? null);

  const summary = useQuery({
    queryKey: ["job-summary", connection?.url, activeJobId, side],
    queryFn: () => getJobSummary(connection!, activeJobId!, side),
    enabled: connection !== null && activeJobId !== null,
  });

  const runs = useQuery({
    queryKey: ["job-runs", connection?.url, activeJobId, runsOffset],
    queryFn: () => listJobRuns(connection!, activeJobId!, { limit: PAGE_SIZE, offset: runsOffset }),
    enabled: connection !== null && activeJobId !== null && summary.data?.metrics != null,
  });

  const poolSummary = useQuery({
    queryKey: ["job-pool-summary", connection?.url, activeJobId],
    queryFn: () => getJobPoolSummary(connection!, activeJobId!),
    enabled: connection !== null && activeJobId !== null && summary.data !== undefined,
  });

  const refreshJobList = useEventRefresh([["results-jobs"]]);
  const refreshActiveJob = useEventRefresh([
    ["results-jobs"],
    ["job-summary"],
    ["job-runs"],
    ["job-pool-summary"],
  ]);

  useAppEvents(connection, (event) => {
    if (eventPayloadField(event.data, "deleted") === true) {
      refreshJobList();
      return;
    }
    const eventJobId =
      eventPayloadField(event.data, "id") ?? eventPayloadField(event.data, "job_id");
    if (typeof eventJobId !== "string" || eventJobId !== activeJobId) return;
    refreshActiveJob();
  });

  const candidateJobs = jobItems.filter((job) => job.id !== activeJobId);
  const activeJob = jobItems.find((job) => job.id === activeJobId) ?? null;
  const selectedCandidateJobIds = candidateJobs
    .filter((job) => selectedCandidateIds.has(job.id))
    .map((job) => job.id);
  const atCandidateLimit = selectedCandidateIds.size >= COMPARE_MAX_CANDIDATES;
  const compareKey = JSON.stringify({
    baseline: activeJobId,
    candidates: selectedCandidateJobIds,
    variant: compareVariant,
    side,
  });
  const visibleCompare =
    compareView !== null && compareView.key === compareKey ? compareView : null;
  const comparing = visibleCompare?.status === "running";

  const clearCompare = () => {
    setCompareView(null);
    compareRequestRef.current += 1;
  };

  const selectedJobs = jobItems.filter((job) => selected.has(job.id));
  const selectedCount = selectedJobs.length;
  const allSelected = jobItems.length > 0 && selectedCount === jobItems.length;
  const someSelected = selectedCount > 0 && !allSelected;

  const batchRemove = useMutation({
    mutationFn: (ids: string[]) => deleteJobsBatch(connection!, ids),
    onSuccess: (result) => {
      setBatchConfirmOpen(false);
      setActionError(null);
      setBatchResult(result);
      setSelected(new Set<string>());
      if (activeJobId !== null && result.deleted.includes(activeJobId)) {
        const nextJob = jobItems.find((job) => !result.deleted.includes(job.id));
        setSelectedJobId(nextJob?.id ?? null);
        setRunsOffset(0);
        setDownloadError(null);
        setSelectedCandidateIds(new Set());
        clearCompare();
      }
      void jobs.refetch();
    },
    onError: (error) => {
      setBatchConfirmOpen(false);
      setBatchResult(null);
      setActionError(errorMessage(error));
      batchTriggerRef.current?.focus();
    },
  });

  useEffect(() => {
    if (!batchConfirmOpen) return;
    batchCancelRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setBatchConfirmOpen(false);
      batchTriggerRef.current?.focus();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [batchConfirmOpen]);

  useEffect(() => {
    if (batchResult === null) return;
    batchResultRef.current?.focus();
  }, [batchResult]);

  useEffect(() => {
    setSelected((previous) => {
      if (previous.size === 0) return previous;
      const available = new Set(jobItems.map((job) => job.id));
      const next = new Set([...previous].filter((id) => available.has(id)));
      return next.size === previous.size ? previous : next;
    });
  }, [jobs.data]);

  const toggleJob = (jobId: string, checked: boolean) => {
    setSelected((previous) => {
      const next = new Set(previous);
      if (checked) next.add(jobId);
      else next.delete(jobId);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelected((previous) => {
      const all = jobItems.length > 0 && jobItems.every((job) => previous.has(job.id));
      return all ? new Set<string>() : new Set(jobItems.map((job) => job.id));
    });
  };

  const clearSelection = () => {
    setSelected(new Set<string>());
    setBatchConfirmOpen(false);
  };

  const closeBatchConfirm = () => {
    setBatchConfirmOpen(false);
    batchTriggerRef.current?.focus();
  };

  const openBatchConfirm = () => {
    if (selectedCount === 0 || connection === null || batchRemove.isPending) return;
    setActionError(null);
    setBatchResult(null);
    setBatchConfirmOpen(true);
  };

  const confirmBatchDelete = () => {
    if (connection === null || selectedJobs.length === 0 || batchRemove.isPending) return;
    batchRemove.mutate(selectedJobs.map((job) => job.id));
  };

  const toggleCandidate = (jobId: string) => {
    setSelectedCandidateIds((previous) => {
      const next = new Set(previous);
      if (next.has(jobId)) {
        next.delete(jobId);
      } else if (next.size < COMPARE_MAX_CANDIDATES) {
        next.add(jobId);
      } else {
        return previous;
      }
      return next;
    });
    clearCompare();
  };

  const changeVariant = (next: "A" | "B") => {
    setCompareVariant(next);
    clearCompare();
  };

  const changeJob = (jobId: string) => {
    setSelectedJobId(jobId);
    setRunsOffset(0);
    setDownloadError(null);
    setSelectedCandidateIds(new Set());
    clearCompare();
  };

  const changeJobStatus = (next: JobStatus | "") => {
    setJobStatus(next);
    setSelectedJobId(null);
    setRunsOffset(0);
    setDownloadError(null);
    setActionError(null);
    setBatchResult(null);
    setSelected(new Set<string>());
    setBatchConfirmOpen(false);
    setSelectedCandidateIds(new Set());
    clearCompare();
  };

  const changeSide = (next: 0 | 1) => {
    setSide(next);
    setDownloadError(null);
    clearCompare();
  };

  const runCompare = async () => {
    if (
      connection === null ||
      activeJobId === null ||
      selectedCandidateJobIds.length === 0 ||
      comparing
    ) {
      return;
    }
    const requestId = compareRequestRef.current + 1;
    compareRequestRef.current = requestId;
    const key = compareKey;
    setCompareView({ key, status: "running" });
    try {
      const result = await compareResults(connection, {
        baseline_job_id: activeJobId,
        candidate_job_ids: selectedCandidateJobIds,
        variant: compareVariant,
        side,
      });
      if (compareRequestRef.current !== requestId) return;
      setCompareView({ key, status: "success", result });
    } catch (error) {
      if (compareRequestRef.current !== requestId) return;
      setCompareView({ key, status: "error", message: errorMessage(error) });
    }
  };

  const togglePool = () => {
    if (activeJobId === null) return;
    const next = {
      ...poolExpandedJobs,
      [activeJobId]: !(poolExpandedJobs[activeJobId] ?? false),
    };
    setPoolExpandedJobs(next);
    writePoolExpanded(next);
  };

  const refresh = () => {
    setDownloadError(null);
    setActionError(null);
    setBatchResult(null);
    setBatchConfirmOpen(false);
    setSelected(new Set<string>());
    void jobs.refetch();
    if (activeJobId !== null) {
      void summary.refetch();
      void runs.refetch();
      if (summary.data !== undefined) {
        void poolSummary.refetch();
      }
    }
  };

  const download = async () => {
    if (connection === null || activeJobId === null || downloading) return;
    setDownloading(true);
    setDownloadError(null);
    try {
      const text = await downloadJobCsv(connection, activeJobId);
      triggerTextDownload(`job-${activeJobId}.csv`, text);
    } catch (error) {
      setDownloadError(errorMessage(error));
    } finally {
      setDownloading(false);
    }
  };

  let runsContent: ReactNode;
  if (runs.isPending) {
    runsContent = (
      <p className="jobs-loading" role="status">
        正在加载逐场记录…
      </p>
    );
  } else if (runs.isError) {
    runsContent = (
      <div className="inline-alert" role="alert">
        <span>{errorMessage(runs.error)}</span>
        <button className="button small" type="button" onClick={() => void runs.refetch()}>
          重试
        </button>
      </div>
    );
  } else if (runs.data === undefined || runs.data.items.length === 0) {
    runsContent = <p className="results-note">暂无逐场记录</p>;
  } else {
    const page = runs.data;
    runsContent = (
      <>
        <div className="jobs-table-wrap">
          <table className="jobs-table">
            <caption className="sr-only">逐场记录</caption>
            <thead>
              <tr>
                <th scope="col">序号</th>
                <th scope="col">变体</th>
                <th scope="col">种子</th>
                <th scope="col" className="jobs-number">
                  比分
                </th>
                <th scope="col">校验</th>
                <th scope="col">时间</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((run) => (
                <tr key={`${run.job_id}-${run.sequence}`}>
                  <td className="jobs-number">{run.sequence}</td>
                  <td>{run.variant}</td>
                  <td className="jobs-number">{run.seed}</td>
                  <td className="jobs-number">
                    {run.score === null ? "—" : `${run.score[0]}–${run.score[1]}`}
                  </td>
                  <td>{run.verified ? "已验证" : "未验证"}</td>
                  <td className="jobs-time">{formatTime(run.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="jobs-pager">
          <span className="jobs-meta">共 {page.total} 场</span>
          <button
            className="button small"
            type="button"
            onClick={() => setRunsOffset(Math.max(0, runsOffset - PAGE_SIZE))}
            disabled={runsOffset === 0 || runs.isFetching}
          >
            上一页
          </button>
          <button
            className="button small"
            type="button"
            onClick={() => setRunsOffset(page.next_offset ?? runsOffset)}
            disabled={page.next_offset === null || runs.isFetching}
          >
            下一页
          </button>
        </div>
      </>
    );
  }

  let summaryContent: ReactNode;
  const summaryData = summary.data;
  if (summary.isError) {
    summaryContent = (
      <div className="inline-alert" role="alert">
        <span>{errorMessage(summary.error)}</span>
        <button className="button small" type="button" onClick={() => void summary.refetch()}>
          重试
        </button>
      </div>
    );
  } else if (summaryData === undefined) {
    summaryContent = (
      <p className="jobs-loading" role="status">
        正在加载任务摘要…
      </p>
    );
  } else {
    const data = summaryData;
    const metrics = data.metrics;
    const poolData = poolSummary.data;
    const poolExpanded = activeJobId !== null && (poolExpandedJobs[activeJobId] ?? false);

    let poolContent: ReactNode = null;
    if (poolSummary.isError) {
      poolContent = (
        <div className="inline-alert" role="alert">
          <span>{errorMessage(poolSummary.error)}</span>
          <button
            className="button small"
            type="button"
            onClick={() => void poolSummary.refetch()}
          >
            重试
          </button>
        </div>
      );
    } else if (poolSummary.isPending) {
      poolContent = (
        <p className="jobs-loading" role="status">
          正在加载客队战术池…
        </p>
      );
    } else if (poolData !== undefined && poolData.entry_count > 0) {
      const entries = poolData.entries ?? [];
      poolContent = (
        <section className="pool-card" aria-labelledby="pool-card-title">
          <div className="pool-card-header">
            <h3 className="pool-card-title" id="pool-card-title">
              客队战术池
            </h3>
            <span className="pool-card-meta">共 {poolData.entry_count} 套</span>
            {poolData.enabled ? (
              <>
                <span className="pool-card-meta">{poolModeLabel(poolData.mode)}</span>
                <span className="pool-card-meta">
                  名单：{poolPlayersLabel(poolData.players)}
                </span>
                <button
                  className="button small pool-card-toggle"
                  type="button"
                  aria-expanded={poolExpanded}
                  aria-controls="pool-card-body"
                  onClick={togglePool}
                >
                  {poolExpanded ? "折叠" : "展开"}
                </button>
              </>
            ) : (
              <span className="pool-card-note">未启用客队战术池</span>
            )}
          </div>
          {poolData.enabled && poolExpanded ? (
            <div className="pool-card-body" id="pool-card-body">
              <table className="jobs-table pool-card-table">
                <caption className="sr-only">客队战术池明细</caption>
                <thead>
                  <tr>
                    <th scope="col">名称</th>
                    <th scope="col" className="jobs-number">
                      权重
                    </th>
                    <th scope="col" className="jobs-number">
                      概率
                    </th>
                    <th scope="col">名单</th>
                    <th scope="col" className="jobs-number">
                      抽中次数
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((entry) => (
                    <tr key={entry.index}>
                      <td>{entry.name}</td>
                      <td className="jobs-number">{entry.weight}</td>
                      <td className="jobs-number">
                        {entry.probability === null
                          ? "—"
                          : formatRatioPercent(entry.probability)}
                      </td>
                      <td>
                        <span className="badge">
                          {entry.roster ? "真实名单" : "统一属性"}
                        </span>
                      </td>
                      <td className="jobs-number">
                        {poolData.draws[String(entry.index)] ?? 0}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
      );
    }

    summaryContent = (
      <>
        <div className="results-meta">
          <strong>{data.job.name ?? "未命名任务"}</strong>
          <span className="jobs-id">{data.job.id}</span>
          <span className="badge" data-tone={STATUS_TONES[data.job.status]}>
            {STATUS_LABELS[data.job.status]}
          </span>
          <span>
            完成 {data.job.completed} / {data.job.total}
          </span>
        </div>
        {metrics === null ? (
          <>
            <EmptyState
              icon={ChartBar}
              title="尚无比赛结果"
              description="该任务还没有已完成的比赛，完成后会显示指标与逐场记录。"
            />
            {poolContent}
          </>
        ) : (
          <>
            <div className="metric-grid">
              {metricCards(metrics, data.paired).map((card) => (
                <div className="metric" key={card.label}>
                  <span className="metric-label">{card.label}</span>
                  <strong className="metric-value">{card.value}</strong>
                  {card.hint === undefined ? null : (
                    <span className="metric-hint">{card.hint}</span>
                  )}
                </div>
              ))}
            </div>
            {poolContent}
            <h3 className="results-section-title">逐场记录</h3>
            {runsContent}
          </>
        )}
      </>
    );
  }

  const compareContent =
    activeJobId !== null && candidateJobs.length > 0 ? (
      <section className="compare-panel" aria-labelledby="compare-title" aria-busy={comparing}>
        <h3 className="results-section-title" id="compare-title">
          任务对比
        </h3>
        <div className="results-meta compare-baseline">
          <span>基线</span>
          <strong>{activeJob?.name ?? activeJobId}</strong>
          <span className="jobs-id">{activeJobId}</span>
        </div>
        <div className="compare-controls">
          <fieldset className="compare-candidates">
            <legend>候选任务</legend>
            {candidateJobs.map((job) => {
              const checked = selectedCandidateIds.has(job.id);
              return (
                <label className="compare-candidate" key={job.id}>
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={!checked && atCandidateLimit}
                    aria-label={`候选任务 ${job.name ?? job.id}（${job.id}）`}
                    onChange={() => toggleCandidate(job.id)}
                  />
                  <span>{job.name ?? job.id}</span>
                  <span className="jobs-id">{job.id}</span>
                </label>
              );
            })}
          </fieldset>
          <div className="compare-actions">
            <div className="segmented" role="group" aria-label="对比变体">
              <button
                type="button"
                aria-pressed={compareVariant === "A"}
                onClick={() => changeVariant("A")}
              >
                A
              </button>
              <button
                type="button"
                aria-pressed={compareVariant === "B"}
                onClick={() => changeVariant("B")}
              >
                B
              </button>
            </div>
            <button
              className="button primary"
              type="button"
              onClick={() => void runCompare()}
              disabled={selectedCandidateJobIds.length === 0 || comparing}
            >
              {comparing ? "对比中…" : "开始对比"}
            </button>
          </div>
        </div>
        {visibleCompare !== null && visibleCompare.status === "error" ? (
          <div className="inline-alert" role="alert">
            <span>{visibleCompare.message}</span>
            <button className="button small" type="button" onClick={() => void runCompare()}>
              重试
            </button>
          </div>
        ) : null}
        {visibleCompare !== null && visibleCompare.status === "success" ? (
          <div className="jobs-table-wrap">
            <table className="jobs-table">
              <caption className="sr-only">任务对比结果</caption>
              <thead>
                <tr>
                  <th scope="col">候选任务</th>
                  <th scope="col">可比性</th>
                  <th scope="col" className="jobs-number">
                    场次
                  </th>
                  <th scope="col" className="jobs-number">
                    Δ胜率
                  </th>
                  <th scope="col" className="jobs-number">
                    Δ净胜球
                  </th>
                  <th scope="col" className="jobs-number">
                    Δ积分
                  </th>
                  <th scope="col" className="jobs-number">
                    ΔxGD
                  </th>
                </tr>
              </thead>
              <tbody>
                {visibleCompare.result.candidates.map((candidate) => {
                  const paired = candidate.paired;
                  const pairing = candidate.pairing;
                  return (
                    <tr key={candidate.job_id}>
                      <td>
                        <span className="jobs-name">{candidate.name ?? candidate.job_id}</span>
                        <span className="jobs-id">{candidate.job_id}</span>
                        {pairing === null ? null : (
                          <span className="compare-note">
                            {pairing.draw_mismatches === null
                              ? `同种子 ${pairing.common_seeds} 场`
                              : `同种子 ${pairing.common_seeds} 场，抽签不一致 ${pairing.draw_mismatches} 场`}
                          </span>
                        )}
                      </td>
                      <td>
                        <span className="badge" data-tone={candidate.comparable ? "ok" : "warn"}>
                          {candidate.comparable ? "可比" : "不可比"}
                        </span>
                        {candidate.reason === null ? null : (
                          <span className="compare-note">{candidate.reason}</span>
                        )}
                        {pairing !== null && pairing.mismatched_seeds.length > 0 ? (
                          <span className="compare-note">
                            不一致种子 {seedList(pairing.mismatched_seeds)}
                          </span>
                        ) : null}
                        {pairing !== null && pairing.missing_seeds.length > 0 ? (
                          <span className="compare-note">
                            缺失种子 {seedList(pairing.missing_seeds)}
                          </span>
                        ) : null}
                      </td>
                      <td className="jobs-number">{paired === null ? "—" : paired.seeds}</td>
                      <td className="jobs-number">
                        {paired === null ? "—" : formatSignedPercent(paired.win_rate_delta)}
                        {paired !== null && paired.win_rate_delta_ci !== null ? (
                          <span className="metric-hint compare-ci">
                            95% 区间 {formatPercentInterval(paired.win_rate_delta_ci)}
                          </span>
                        ) : null}
                      </td>
                      <td className="jobs-number">
                        {formatDelta(paired?.goal_difference_delta ?? null)}
                      </td>
                      <td className="jobs-number">{formatDelta(paired?.points_delta ?? null)}</td>
                      <td className="jobs-number">{formatDelta(paired?.xgd_delta ?? null)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    ) : null;

  const jobSelection =
    jobItems.length === 0 && jobStatus === "" ? null : (
      <section className="results-jobs" aria-label="实验任务">
        <div className="results-jobs-head">
          <label className="field results-jobs-filter">
            状态筛选
            <select
              value={jobStatus}
              onChange={(event) => changeJobStatus(event.target.value as JobStatus | "")}
            >
              <option value="">全部</option>
              {(Object.keys(STATUS_LABELS) as JobStatus[]).map((status) => (
                <option key={status} value={status}>
                  {STATUS_LABELS[status]}
                </option>
              ))}
            </select>
          </label>
          <div className="results-jobs-actions" aria-busy={batchRemove.isPending}>
            <label className="results-jobs-select-all">
              <input
                type="checkbox"
                aria-label="全选当前筛选结果"
                aria-checked={allSelected ? "true" : someSelected ? "mixed" : "false"}
                checked={allSelected}
                disabled={jobItems.length === 0}
                ref={(element) => {
                  if (element !== null) element.indeterminate = someSelected;
                }}
                onChange={toggleSelectAll}
              />
              <span>全选</span>
            </label>
            <button
              className="button small"
              type="button"
              onClick={clearSelection}
              disabled={selectedCount === 0}
            >
              清空选择
            </button>
            <span className="jobs-bulk-count" aria-live="polite">
              已选 {selectedCount} 个任务
            </span>
            <button
              ref={batchTriggerRef}
              className="button small danger"
              type="button"
              disabled={selectedCount === 0 || batchRemove.isPending}
              onClick={openBatchConfirm}
            >
              {batchRemove.isPending ? "删除中…" : "删除所选"}
            </button>
          </div>
        </div>
        {jobItems.length === 0 ? (
          jobs.isPending ? null : <p className="results-note">当前筛选条件下没有任务。</p>
        ) : (
          <ul className="results-jobs-list">
            {jobItems.map((job) => {
              const current = job.id === activeJobId;
              return (
                <li className="results-job" key={job.id}>
                  <input
                    type="checkbox"
                    className="results-job-check"
                    aria-label={jobCheckboxLabel(job)}
                    checked={selected.has(job.id)}
                    onChange={(event) => toggleJob(job.id, event.target.checked)}
                  />
                  <button
                    className="results-job-name"
                    type="button"
                    aria-current={current ? "true" : undefined}
                    onClick={() => changeJob(job.id)}
                  >
                    {job.name ?? job.id}
                  </button>
                  <span className="jobs-id">{job.id}</span>
                  <span className="badge" data-tone={STATUS_TONES[job.status]}>
                    {STATUS_LABELS[job.status]}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        {batchConfirmOpen ? (
          <div
            className="jobs-batch-confirm"
            role="alertdialog"
            aria-label="确认批量删除"
            aria-describedby="results-batch-confirm-summary"
          >
            <p id="results-batch-confirm-summary">将删除 {selectedJobs.length} 个任务：</p>
            <ul className="jobs-batch-confirm-list">
              {selectedJobs.map((job) => (
                <li key={job.id}>
                  {jobLabel(job)}（总场数 {job.total}）
                </li>
              ))}
            </ul>
            <p>运行中或排队中的任务会被服务端跳过，失败原因会显示在结果中。</p>
            <div className="jobs-batch-confirm-actions">
              <button
                className="button small danger"
                type="button"
                disabled={batchRemove.isPending || selectedJobs.length === 0}
                onClick={confirmBatchDelete}
              >
                确认删除
              </button>
              <button
                ref={batchCancelRef}
                className="button small"
                type="button"
                onClick={closeBatchConfirm}
              >
                放弃
              </button>
            </div>
          </div>
        ) : null}
      </section>
    );

  const batchFeedback = (
    <>
      {actionError === null ? null : (
        <div className="inline-alert" role="alert">
          {actionError}
        </div>
      )}
      {batchResult === null ? null : (
        <div
          ref={batchResultRef}
          className="jobs-batch-result"
          role="status"
          aria-label="批量删除结果"
          tabIndex={-1}
        >
          <p className="jobs-notice">已删除 {batchResult.deleted.length} 个任务</p>
          {batchResult.deleted.length === 0 ? null : (
            <ul className="jobs-batch-deleted" aria-label="已删除任务 ID">
              {batchResult.deleted.map((jobId) => (
                <li key={jobId}>{jobId}</li>
              ))}
            </ul>
          )}
          {batchResult.failed.length === 0 ? null : (
            <div className="inline-alert" role="alert">
              <div>
                <p>{batchResult.failed.length} 个任务删除失败</p>
                <ul className="jobs-batch-failures">
                  {batchResult.failed.map((failure) => (
                    <li key={failure.id}>
                      {failure.id}：{failure.error}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  );

  let body: ReactNode;
  if (connection === null) {
    body = (
      <EmptyState
        icon={ChartBar}
        title="sidecar 未连接"
        description="连接 sidecar 后可以查看实验结果、切换视角并导出 CSV。"
      />
    );
  } else if (jobs.isError) {
    body = (
      <>
        {batchFeedback}
        <div className="inline-alert" role="alert">
          <span>{errorMessage(jobs.error)}</span>
          <button className="button small" type="button" onClick={() => void jobs.refetch()}>
            重试
          </button>
        </div>
      </>
    );
  } else if (jobs.isPending && jobStatus === "") {
    body = (
      <p className="jobs-loading" role="status">
        正在加载实验任务…
      </p>
    );
  } else if (jobItems.length === 0 && jobStatus === "") {
    body = (
      <>
        {batchFeedback}
        <EmptyState
          icon={ChartBar}
          title="尚无实验结果"
          description="提交实验后，这里会显示批次摘要、A/B 指标、配对差值与逐场记录。"
        />
      </>
    );
  } else {
    body = (
      <>
        {jobSelection}
        {batchFeedback}
        <div className="results-toolbar">
          <div className="segmented" role="group" aria-label="统计视角">
            <button type="button" aria-pressed={side === 0} onClick={() => changeSide(0)}>
              主队
            </button>
            <button type="button" aria-pressed={side === 1} onClick={() => changeSide(1)}>
              客队
            </button>
          </div>
          <div className="results-toolbar-end">
            <button
              className="button"
              type="button"
              onClick={refresh}
              disabled={jobs.isFetching || summary.isFetching}
            >
              刷新
            </button>
            <button
              className="button primary"
              type="button"
              onClick={() => void download()}
              disabled={activeJobId === null || downloading}
            >
              下载 CSV
            </button>
          </div>
        </div>
        {downloadError === null ? null : (
          <div className="inline-alert" role="alert">
            {downloadError}
          </div>
        )}
        {activeJobId === null ? (
          jobs.isPending ? null : (
            <EmptyState
              icon={ChartBar}
              title="没有符合条件的任务"
              description="切换状态筛选，或提交新的实验后再查看结果。"
            />
          )
        ) : (
          <>
            {summaryContent}
            {compareContent}
          </>
        )}
      </>
    );
  }

  return <Panel title="实验结果">{body}</Panel>;
}
