export type JobProgressInput = {
  status: string;
  total: number;
  completed: number;
  started_at: string | null;
};

export type JobProgress = {
  active: boolean;
  percent: number;
  elapsedMs: number | null;
  remainingMs: number | null;
};

export function isActiveJob(status: string): boolean {
  return status === "queued" || status === "running";
}

export function jobPercent(completed: number, total: number): number {
  if (!Number.isFinite(completed) || !Number.isFinite(total)) return 0;
  if (total <= 0 || completed <= 0) return 0;
  return Math.min(100, Math.floor((completed / total) * 100));
}

export function jobElapsedMs(job: JobProgressInput, nowMs: number): number | null {
  if (job.started_at === null) return null;
  const started = Date.parse(job.started_at);
  if (Number.isNaN(started) || !Number.isFinite(nowMs)) return null;
  return Math.max(0, nowMs - started);
}

export function jobRemainingMs(job: JobProgressInput, nowMs: number): number | null {
  if (job.status !== "running") return null;
  if (job.completed < 2) return null;
  if (!(job.total > job.completed)) return null;
  const elapsedMs = jobElapsedMs(job, nowMs);
  if (elapsedMs === null || elapsedMs <= 0) return null;
  const perMs = job.completed / elapsedMs;
  if (!(perMs > 0) || !Number.isFinite(perMs)) return null;
  return Math.ceil((job.total - job.completed) / perMs);
}

export function jobProgress(job: JobProgressInput, nowMs: number): JobProgress {
  return {
    active: isActiveJob(job.status),
    percent: jobPercent(job.completed, job.total),
    elapsedMs: jobElapsedMs(job, nowMs),
    remainingMs: jobRemainingMs(job, nowMs),
  };
}

export function formatDuration(ms: number): string {
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  if (totalSeconds < 60) return String(totalSeconds) + " 秒";
  const minutes = Math.floor(totalSeconds / 60);
  if (minutes < 60) {
    const seconds = totalSeconds % 60;
    return seconds === 0 ? String(minutes) + " 分" : String(minutes) + " 分 " + String(seconds) + " 秒";
  }
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return restMinutes === 0
    ? String(hours) + " 小时"
    : String(hours) + " 小时 " + String(restMinutes) + " 分";
}
