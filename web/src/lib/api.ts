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
