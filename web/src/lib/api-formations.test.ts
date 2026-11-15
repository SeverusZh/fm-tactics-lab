// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { applyFormation, listFormations } from "./api-formations";
import type { Connection } from "./connection";

const CONNECTION: Connection = {
  url: "http://127.0.0.1:43210",
  token: "test-token",
  api: "fm27lab/v2",
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function fetchArgs(): { url: string; init: RequestInit } {
  const mock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
  const [input, init] = mock.mock.calls[0] as [RequestInfo | URL, RequestInit | undefined];
  return { url: String(input), init: init ?? {} };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("阵型模板接口", () => {
  it("列阵型模板读取 /api/formations", async () => {
    const payload = {
      formations: [{ id: "4-4-2", name: "4-4-2", phases: [[], []] }],
      editing: null,
    };
    const fetchMock = vi.fn(async () => jsonResponse(payload));
    vi.stubGlobal("fetch", fetchMock);
    const result = await listFormations(CONNECTION);
    expect(result).toEqual(payload);
    const { url, init } = fetchArgs();
    expect(url).toBe("http://127.0.0.1:43210/api/formations");
    expect(init.method).toBeUndefined();
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer test-token");
  });

  it("应用阵型按草案路径提交模板与场景", async () => {
    const payload = { formation_id: "4-2-3-1", scenario: { teams: [] }, notes: ["主队：球员不足"] };
    const fetchMock = vi.fn(async () => jsonResponse(payload));
    vi.stubGlobal("fetch", fetchMock);
    const scenario = { schema: 3, teams: [] };
    const result = await applyFormation(CONNECTION, "draft/1", {
      formation_id: "4-2-3-1",
      overwrite: false,
      scenario,
    });
    expect(result).toEqual(payload);
    const { url, init } = fetchArgs();
    expect(url).toBe("http://127.0.0.1:43210/api/drafts/draft%2F1/formation");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(init.body))).toEqual({
      formation_id: "4-2-3-1",
      overwrite: false,
      scenario,
    });
  });
});
