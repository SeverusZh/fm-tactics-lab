import { useQuery } from "@tanstack/react-query";
import { ChartBar } from "@phosphor-icons/react";
import { useState, type ReactNode } from "react";

import { useAppContext } from "../app-context";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";
import {
  downloadJobCsv,
  getJobPoolSummary,
  getJobSummary,
  listJobRuns,
  listJobs,
  type JobMetrics,
  type JobStatus,
  type JobSummary,
  type PoolSummary,
} from "../lib/api";

const PAGE_SIZE = 20;
const JOB_PAGE_SIZE = 50;

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

function triggerTextDownload(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

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

export function ResultsPage() {
  const { connection } = useAppContext();
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [side, setSide] = useState<0 | 1>(0);
  const [runsOffset, setRunsOffset] = useState(0);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [poolExpandedJobs, setPoolExpandedJobs] = useState<Record<string, boolean>>({});

  const jobs = useQuery({
    queryKey: ["results-jobs", connection?.url],
    queryFn: () => listJobs(connection!, { limit: JOB_PAGE_SIZE, offset: 0 }),
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

  const changeJob = (jobId: string) => {
    setSelectedJobId(jobId);
    setRunsOffset(0);
    setDownloadError(null);
  };

  const changeSide = (next: 0 | 1) => {
    setSide(next);
    setDownloadError(null);
  };

  const togglePool = () => {
    if (activeJobId === null) return;
    setPoolExpandedJobs((previous) => ({
      ...previous,
      [activeJobId]: !(previous[activeJobId] ?? false),
    }));
  };

  const refresh = () => {
    setDownloadError(null);
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

  let body: ReactNode;
  if (connection === null) {
    body = (
      <EmptyState
        icon={ChartBar}
        title="sidecar 未连接"
        description="连接 sidecar 后可以查看实验结果、切换视角并导出 CSV。"
      />
    );
  } else if (jobs.isPending) {
    body = (
      <p className="jobs-loading" role="status">
        正在加载实验任务…
      </p>
    );
  } else if (jobs.isError) {
    body = (
      <div className="inline-alert" role="alert">
        <span>{errorMessage(jobs.error)}</span>
        <button className="button small" type="button" onClick={() => void jobs.refetch()}>
          重试
        </button>
      </div>
    );
  } else if (jobItems.length === 0) {
    body = (
      <EmptyState
        icon={ChartBar}
        title="尚无实验结果"
        description="提交实验后，这里会显示批次摘要、A/B 指标、配对差值与逐场记录。"
      />
    );
  } else {
    body = (
      <>
        <div className="results-toolbar">
          <label className="field results-select">
            实验任务
            <select
              value={activeJobId ?? ""}
              onChange={(event) => changeJob(event.target.value)}
            >
              {jobItems.map((job) => (
                <option key={job.id} value={job.id}>
                  {job.name ?? job.id}
                </option>
              ))}
            </select>
          </label>
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
        {summaryContent}
      </>
    );
  }

  return <Panel title="实验结果">{body}</Panel>;
}
