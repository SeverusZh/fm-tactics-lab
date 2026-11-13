import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowClockwise, ListChecks, Plus } from "@phosphor-icons/react";
import { useState, type FormEvent, type ReactNode } from "react";

import { useAppContext } from "../app-context";
import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";
import {
  cancelJob,
  createJob,
  deleteJob,
  listJobs,
  type Job,
  type JobCreate,
  type JobStatus,
} from "../lib/api";

const PAGE_SIZE = 20;

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

const CANCELLABLE: ReadonlySet<JobStatus> = new Set(["queued", "running", "interrupted"]);

const dateFormat = new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" });

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : dateFormat.format(date);
}

function integerBetween(value: string, minimum: number, maximum: number): boolean {
  if (value.trim() === "") return false;
  const number = Number(value);
  return Number.isInteger(number) && number >= minimum && number <= maximum;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function JobStatusFilter({
  value,
  onChange,
}: {
  value: JobStatus | "";
  onChange: (value: JobStatus | "") => void;
}) {
  return (
    <label className="field jobs-filter">
      状态筛选
      <select
        value={value}
        onChange={(event) => onChange(event.target.value as JobStatus | "")}
      >
        <option value="">全部</option>
        {(Object.keys(STATUS_LABELS) as JobStatus[]).map((status) => (
          <option key={status} value={status}>
            {STATUS_LABELS[status]}
          </option>
        ))}
      </select>
    </label>
  );
}

export function JobsPage() {
  const { connection } = useAppContext();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<JobStatus | "">("");
  const [offset, setOffset] = useState(0);
  const [confirmation, setConfirmation] = useState<{ id: string; action: "cancel" | "delete" } | null>(
    null,
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [kind, setKind] = useState("experiment");
  const [name, setName] = useState("");
  const [workers, setWorkers] = useState("4");
  const [total, setTotal] = useState("100");

  const jobs = useQuery({
    queryKey: ["jobs", connection?.url, status, offset],
    queryFn: () =>
      listJobs(connection!, {
        status: status === "" ? undefined : status,
        limit: PAGE_SIZE,
        offset,
      }),
    enabled: connection !== null,
  });

  const invalidateJobs = () => {
    void queryClient.invalidateQueries({ queryKey: ["jobs"] });
  };

  const cancel = useMutation({
    mutationFn: (job: Job) => cancelJob(connection!, job.id),
    onSuccess: (job) => {
      setConfirmation(null);
      setActionError(null);
      setNotice(`已取消任务「${job.name ?? job.id}」`);
      invalidateJobs();
    },
    onError: (error) => {
      setConfirmation(null);
      setNotice(null);
      setActionError(errorMessage(error));
    },
  });

  const remove = useMutation({
    mutationFn: (job: Job) => deleteJob(connection!, job.id),
    onSuccess: (_result, job) => {
      setConfirmation(null);
      setActionError(null);
      setNotice(`已删除任务「${job.name ?? job.id}」`);
      invalidateJobs();
    },
    onError: (error) => {
      setConfirmation(null);
      setNotice(null);
      setActionError(errorMessage(error));
    },
  });

  const kindValid = kind.trim().length >= 1 && kind.trim().length <= 64;
  const nameValid = name.trim().length <= 100;
  const workersValid = integerBetween(workers, 1, 256);
  const totalValid = integerBetween(total, 0, Number.MAX_SAFE_INTEGER);
  const formValid = kindValid && nameValid && workersValid && totalValid;
  const formHint = !kindValid
    ? "任务类型需为 1–64 个字符"
    : !nameValid
      ? "任务名称最多 100 个字符"
      : !workersValid
        ? "并行数需为 1–256 的整数"
        : !totalValid
          ? "总场数需为非负整数"
          : null;

  const create = useMutation({
    mutationFn: (input: JobCreate) => createJob(connection!, input),
    onSuccess: () => {
      setActionError(null);
      setNotice("任务已创建");
      setFormOpen(false);
      setKind("experiment");
      setName("");
      setWorkers("4");
      setTotal("100");
      setStatus("");
      setOffset(0);
      invalidateJobs();
    },
    onError: (error) => {
      setNotice(null);
      setActionError(errorMessage(error));
    },
  });

  const changeStatus = (next: JobStatus | "") => {
    setStatus(next);
    setOffset(0);
    setConfirmation(null);
    setActionError(null);
    setNotice(null);
  };

  const refresh = () => {
    setActionError(null);
    setNotice(null);
    void jobs.refetch();
  };

  const submitCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (connection === null || !formValid || create.isPending) return;
    create.mutate({
      kind: kind.trim(),
      name: name.trim() === "" ? null : name.trim(),
      workers: Number(workers),
      total: Number(total),
    });
  };

  const data = jobs.data;
  const pager =
    data === undefined ? null : (
      <div className="jobs-pager">
        <span className="jobs-meta">共 {data.total} 个任务</span>
        <button
          className="button small"
          type="button"
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          disabled={offset === 0 || jobs.isFetching}
        >
          上一页
        </button>
        <button
          className="button small"
          type="button"
          onClick={() => setOffset(data.next_offset ?? offset)}
          disabled={data.next_offset === null || jobs.isFetching}
        >
          下一页
        </button>
      </div>
    );

  let body: ReactNode;
  if (connection === null) {
    body = (
      <EmptyState
        icon={ListChecks}
        title="sidecar 未连接"
        description="连接 sidecar 后可以创建、筛选与管理任务。"
      />
    );
  } else if (jobs.isPending) {
    body = (
      <p className="jobs-loading" role="status">
        正在加载任务…
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
  } else if (data === undefined || data.items.length === 0) {
    body = (
      <>
        <EmptyState
          icon={ListChecks}
          title={status === "" ? "尚无任务" : "没有符合条件的任务"}
          description={
            status === ""
              ? "创建任务后，这里会显示运行状态、进度与取消入口。"
              : "当前筛选条件下没有任务，切换状态或创建新任务。"
          }
        />
        {data !== undefined && data.total > 0 ? pager : null}
      </>
    );
  } else {
    body = (
      <>
        <div className="jobs-table-wrap">
          <table className="jobs-table">
            <caption className="sr-only">任务列表</caption>
            <thead>
              <tr>
                <th scope="col">任务</th>
                <th scope="col">类型</th>
                <th scope="col">状态</th>
                <th scope="col" className="jobs-number">
                  进度
                </th>
                <th scope="col" className="jobs-number">
                  并行
                </th>
                <th scope="col">创建时间</th>
                <th scope="col">操作</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((job) => {
                const confirming = confirmation?.id === job.id;
                return (
                  <tr key={job.id}>
                    <td>
                      <span className="jobs-name">{job.name ?? "未命名"}</span>
                      <span className="jobs-id">{job.id}</span>
                    </td>
                    <td className="jobs-kind">{job.kind}</td>
                    <td>
                      <span className="badge" data-tone={STATUS_TONES[job.status]}>
                        {STATUS_LABELS[job.status]}
                      </span>
                    </td>
                    <td className="jobs-progress">
                      {job.completed} / {job.total}
                    </td>
                    <td className="jobs-number">{job.workers}</td>
                    <td className="jobs-time">{formatTime(job.created_at)}</td>
                    <td>
                      <div className="jobs-actions">
                        {CANCELLABLE.has(job.status) ? (
                          confirming && confirmation.action === "cancel" ? (
                            <>
                              <button
                                className="button small danger"
                                type="button"
                                disabled={cancel.isPending}
                                onClick={() => cancel.mutate(job)}
                              >
                                确认取消
                              </button>
                              <button
                                className="button small"
                                type="button"
                                onClick={() => setConfirmation(null)}
                              >
                                放弃
                              </button>
                            </>
                          ) : (
                            <button
                              className="button small"
                              type="button"
                              onClick={() => setConfirmation({ id: job.id, action: "cancel" })}
                            >
                              取消
                            </button>
                          )
                        ) : null}
                        {confirming && confirmation.action === "delete" ? (
                          <>
                            <button
                              className="button small danger"
                              type="button"
                              disabled={remove.isPending}
                              onClick={() => remove.mutate(job)}
                            >
                              确认删除
                            </button>
                            <button
                              className="button small"
                              type="button"
                              onClick={() => setConfirmation(null)}
                            >
                              放弃
                            </button>
                          </>
                        ) : (
                          <button
                            className="button small danger"
                            type="button"
                            onClick={() => setConfirmation({ id: job.id, action: "delete" })}
                          >
                            删除
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {pager}
      </>
    );
  }

  return (
    <Panel
      title="任务管理"
      action={
        <div className="jobs-toolbar">
          <JobStatusFilter value={status} onChange={changeStatus} />
          <button
            className="button"
            type="button"
            onClick={refresh}
            disabled={connection === null || jobs.isFetching}
          >
            <ArrowClockwise size={16} aria-hidden="true" />
            刷新
          </button>
          <button
            className="button primary"
            type="button"
            onClick={() => setFormOpen((open) => !open)}
            disabled={connection === null}
          >
            <Plus size={16} aria-hidden="true" />
            新建任务
          </button>
        </div>
      }
    >
      {formOpen ? (
        <form className="jobs-create" aria-label="新建任务" onSubmit={submitCreate}>
          <label className="field">
            任务类型
            <input
              value={kind}
              maxLength={64}
              onChange={(event) => setKind(event.target.value)}
            />
          </label>
          <label className="field">
            任务名称
            <input
              value={name}
              maxLength={100}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label className="field">
            并行数
            <input
              type="number"
              inputMode="numeric"
              min={1}
              max={256}
              value={workers}
              aria-invalid={!workersValid}
              onChange={(event) => setWorkers(event.target.value)}
            />
          </label>
          <label className="field">
            总场数
            <input
              type="number"
              inputMode="numeric"
              min={0}
              value={total}
              aria-invalid={!totalValid}
              onChange={(event) => setTotal(event.target.value)}
            />
          </label>
          {formHint === null ? null : (
            <span className="jobs-hint" role="status">
              {formHint}
            </span>
          )}
          <button
            className="button primary"
            type="submit"
            disabled={connection === null || !formValid || create.isPending}
          >
            创建
          </button>
        </form>
      ) : null}
      {actionError === null ? null : (
        <div className="inline-alert" role="alert">
          {actionError}
        </div>
      )}
      {notice === null ? null : (
        <p className="jobs-notice" role="status">
          {notice}
        </p>
      )}
      {body}
    </Panel>
  );
}
