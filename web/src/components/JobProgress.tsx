import type { Job } from "../lib/api";
import { formatDuration, isActiveJob, jobPercent, jobRemainingMs } from "../lib/job-progress";
import "../styles/job-progress.css";

export function JobProgress({
  job,
  now,
  showFraction = false,
}: {
  job: Job;
  now: number;
  showFraction?: boolean;
}) {
  const fraction = String(job.completed) + " / " + String(job.total);
  if (!isActiveJob(job.status)) {
    return <span className="job-progress-done">{fraction}</span>;
  }
  const percent = jobPercent(job.completed, job.total);
  const remainingMs = jobRemainingMs(job, now);
  const max = job.total > 0 ? job.total : 1;
  return (
    <div className="job-progress">
      <div
        className="job-progress-bar"
        role="progressbar"
        aria-label={job.name === null ? "任务 " + job.id + " 进度" : "任务 " + job.name + " 进度"}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={Math.min(Math.max(job.completed, 0), max)}
        aria-valuetext={"已完成 " + fraction}
        title={"已完成 " + fraction}
      >
        <span
          className="job-progress-fill"
          data-status={job.status}
          style={{ width: String(percent) + "%" }}
        />
      </div>
      <span className="job-progress-text">{String(percent) + "%"}</span>
      {job.status === "queued" ? (
        <span className="job-progress-note">等待开始</span>
      ) : remainingMs === null ? null : (
        <span className="job-progress-note">预计剩余 {formatDuration(remainingMs)}</span>
      )}
      {showFraction ? <span className="job-progress-done">{fraction}</span> : null}
    </div>
  );
}
