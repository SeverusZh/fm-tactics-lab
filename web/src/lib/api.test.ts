// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { API_TIMEOUT_MS, ApiError, apiFetch, apiJson } from "./api";
import type { Connection } from "./connection";

const CONNECTION: Connection = {
  url: "http://127.0.0.1:43210",
  token: "test-token",
  api: "fm27lab/v2",
};

function jsonBody(value: unknown): Pick<Response, "json"> {
  return { json: async () => value };
}

function response(status: number, body?: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    ...(body === undefined ? { json: async () => { throw new SyntaxError("Unexpected token <"); } } : jsonBody(body)),
  } as unknown as Response;
}

async function captureError(): Promise<ApiError> {
  try {
    await apiFetch(CONNECTION, "/api/health");
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error("预期 apiFetch 抛出 ApiError");
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiFetch 失败兜底", () => {
  it("响应体不是 JSON 时 500 视为可重试", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response(500)));
    const error = await captureError();
    expect(error.status).toBe(500);
    expect(error.code).toBe("http_error");
    expect(error.message).toBe("请求失败：500");
    expect(error.retriable).toBe(true);
  });

  it("响应体不是 JSON 时 400 视为不可重试", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response(400)));
    expect((await captureError()).retriable).toBe(false);
  });

  it("响应体不是 JSON 时 409 视为可重试", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response(409)));
    expect((await captureError()).retriable).toBe(true);
  });

  it("错误体缺少 retriable 字段时按状态码兜底", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response(400, { error: { message: "参数错误", code: "bad_request" } })));
    const error = await captureError();
    expect(error.message).toBe("参数错误");
    expect(error.code).toBe("bad_request");
    expect(error.retriable).toBe(false);
  });

  it("错误体缺少 retriable 字段时 502 按状态码兜底为可重试", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response(502, { error: { message: "上游不可用" } })));
    const error = await captureError();
    expect(error.message).toBe("上游不可用");
    expect(error.retriable).toBe(true);
  });

  it("错误体显式 retriable 覆盖状态码兜底", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response(400, { error: { message: "冲突", retriable: true } })));
    expect((await captureError()).retriable).toBe(true);

    vi.stubGlobal("fetch", vi.fn(async () => response(502, { error: { message: "致命错误", retriable: false } })));
    expect((await captureError()).retriable).toBe(false);
  });
});

describe("apiFetch 请求封装", () => {
  it("成功时返回原始响应并透传鉴权头", async () => {
    const fetchMock = vi.fn(async () => response(200, { status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);
    const result = await apiFetch(CONNECTION, "/api/health");
    expect(result.status).toBe(200);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://127.0.0.1:43210/api/health");
    expect((init.headers as Headers).get("Authorization")).toBe("Bearer test-token");
    expect((init.headers as Headers).get("Content-Type")).toBeNull();
  });

  it("携带请求体时补充 JSON Content-Type 并由 apiJson 解析响应", async () => {
    const fetchMock = vi.fn(async () => response(200, { saved: true }));
    vi.stubGlobal("fetch", fetchMock);
    const body = await apiJson<{ saved: boolean }>(CONNECTION, "/api/settings/x", {
      method: "PUT",
      body: JSON.stringify({ value: 1 }),
    });
    expect(body).toEqual({ saved: true });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.method).toBe("PUT");
    expect((init.headers as Headers).get("Content-Type")).toBe("application/json");
  });
});

function pendingUntilAbort(init: RequestInit): Promise<Response> {
  return new Promise<Response>((_resolve, reject) => {
    const abort = () => {
      const error = new Error("请求已中止");
      error.name = "AbortError";
      reject(error);
    };
    const signal = init.signal;
    if (signal === undefined || signal === null) return;
    if (signal.aborted) abort();
    else signal.addEventListener("abort", abort);
  });
}

async function settle(request: Promise<Response>): Promise<unknown> {
  return request.then(
    () => "resolved",
    (error: unknown) => error,
  );
}

describe("apiFetch 超时", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("默认 30 秒无响应时中止请求并抛出可重试超时错误", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn((_url: string, init: RequestInit) => pendingUntilAbort(init));
    vi.stubGlobal("fetch", fetchMock);
    const pending = settle(apiFetch(CONNECTION, "/api/health"));
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://127.0.0.1:43210/api/health");
    expect(init.signal).toBeInstanceOf(AbortSignal);
    expect(API_TIMEOUT_MS).toBe(30_000);
    await vi.advanceTimersByTimeAsync(30_000 - 1);
    expect(init.signal?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    const error = await pending;
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe("请求超时，请重试");
    expect((error as ApiError).status).toBe(0);
    expect((error as ApiError).code).toBe("timeout");
    expect((error as ApiError).retriable).toBe(true);
    expect(init.signal?.aborted).toBe(true);
  });

  it("timeoutMs 覆盖默认超时并在边界后中止", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn((_url: string, init: RequestInit) => pendingUntilAbort(init));
    vi.stubGlobal("fetch", fetchMock);
    const pending = settle(apiFetch(CONNECTION, "/api/health", { timeoutMs: 120 }));
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    await vi.advanceTimersByTimeAsync(119);
    expect(init.signal?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    const error = await pending;
    expect((error as ApiError).code).toBe("timeout");
    expect(init.signal?.aborted).toBe(true);
  });

  it("外部 signal 中止时按原子错误抛出而不误判为超时", async () => {
    const fetchMock = vi.fn((_url: string, init: RequestInit) => pendingUntilAbort(init));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    const pending = settle(apiFetch(CONNECTION, "/api/health", { signal: controller.signal }));
    controller.abort();
    const error = await pending;
    expect(error).not.toBeInstanceOf(ApiError);
    expect((error as Error).name).toBe("AbortError");
  });
});
