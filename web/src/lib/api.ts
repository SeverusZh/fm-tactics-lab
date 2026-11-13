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

function queryString(params: Record<string, string | number | undefined | null>): string {
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

export function listJobRuns(
  connection: Connection,
  jobId: string,
  query: JobRunQuery = {},
): Promise<JobRunList> {
  const search = queryString({ limit: query.limit, offset: query.offset });
  return apiJson<JobRunList>(connection, `/api/jobs/${encodeURIComponent(jobId)}/runs${search}`);
}
