import type { Page, Route } from "@playwright/test";

import {
  buildCompareResult,
  buildDraft,
  buildJob,
  buildScenario,
  buildSummary,
  CATALOG,
  CONCURRENCY_CHECK,
  ENGINE_STATUS,
  HEALTH,
  HOST_RESOURCES,
  JOBS,
  METRICS,
  POOL_SUMMARY,
  RUNS,
  SETTINGS,
  TIMESTAMP,
  type JsonRecord,
} from "./fixtures";

export type RecordedRequest = {
  method: string;
  path: string;
  query: Record<string, string>;
  body: JsonRecord | null;
};

type FailureRule = {
  method: string;
  path: string | RegExp;
  status: number;
  message: string;
  remaining: number;
};

type MockResponse = {
  status: number;
  body: unknown;
  contentType: string;
};

export type MockApiOptions = {
  drafts?: JsonRecord[];
  jobs?: JsonRecord[];
  catalog?: JsonRecord | null;
  health?: JsonRecord;
  templateScenario?: JsonRecord;
  summaryMetrics?: JsonRecord | null;
  runs?: JsonRecord[];
  poolSummary?: JsonRecord;
  resources?: JsonRecord;
  concurrency?: JsonRecord;
  engine?: JsonRecord;
  settings?: JsonRecord[];
  compare?: (input: JsonRecord) => JsonRecord;
};

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function readBody(route: Route): JsonRecord | null {
  try {
    const parsed = route.request().postDataJSON();
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? (parsed as JsonRecord)
      : null;
  } catch {
    return null;
  }
}

/**
 * 拦截 sidecar 的 HTTP 接口并返回固定夹具。
 * 所有请求路径都记录在 requests 中，便于断言前端确实发起了预期的调用。
 */
export class MockApi {
  readonly requests: RecordedRequest[] = [];

  drafts: JsonRecord[];
  jobs: JsonRecord[];
  catalog: JsonRecord | null;
  health: JsonRecord;
  templateScenario: JsonRecord;
  summaryMetrics: JsonRecord | null;
  runs: JsonRecord[];
  poolSummary: JsonRecord;
  resources: JsonRecord;
  concurrency: JsonRecord;
  engine: JsonRecord;
  settings: JsonRecord[];

  private pendingJob: JsonRecord | null = null;
  private draftSeq = 1;
  private readonly failures: FailureRule[] = [];
  private readonly compare: (input: JsonRecord) => JsonRecord;

  constructor(private readonly page: Page, options: MockApiOptions = {}) {
    this.drafts = clone(options.drafts ?? [buildDraft()]);
    this.jobs = clone(options.jobs ?? JOBS);
    this.catalog = options.catalog === undefined ? clone(CATALOG) : clone(options.catalog);
    this.health = clone(options.health ?? HEALTH);
    this.templateScenario = clone(options.templateScenario ?? buildScenario());
    this.summaryMetrics = clone(
      options.summaryMetrics === undefined ? METRICS : options.summaryMetrics,
    );
    this.runs = clone(options.runs ?? RUNS);
    this.poolSummary = clone(options.poolSummary ?? POOL_SUMMARY);
    this.resources = clone(options.resources ?? HOST_RESOURCES);
    this.concurrency = clone(options.concurrency ?? CONCURRENCY_CHECK);
    this.engine = clone(options.engine ?? ENGINE_STATUS);
    this.settings = clone(options.settings ?? SETTINGS);
    this.compare = options.compare ?? buildCompareResult;
  }

  static async install(page: Page, options: MockApiOptions = {}): Promise<MockApi> {
    const api = new MockApi(page, options);
    await api.attach();
    return api;
  }

  async attach(): Promise<void> {
    await this.page.route("**/api/**", (route) => this.handle(route));
  }

  /** 让下一次匹配的请求返回错误。 */
  failNext(method: string, path: string | RegExp, status: number, message: string): void {
    this.failures.push({ method, path, status, message, remaining: 1 });
  }

  /** 让所有匹配的请求持续返回错误，用于失败路径与重试路径。 */
  failAlways(method: string, path: string | RegExp, status: number, message: string): void {
    this.failures.push({ method, path, status, message, remaining: Number.POSITIVE_INFINITY });
  }

  requestsFor(method: string, path: string): RecordedRequest[] {
    return this.requests.filter((entry) => entry.method === method && entry.path === path);
  }

  lastRequest(method: string, path: string): RecordedRequest | undefined {
    const matched = this.requestsFor(method, path);
    return matched[matched.length - 1];
  }

  private async handle(route: Route): Promise<void> {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const path = url.pathname;
    const query: Record<string, string> = {};
    url.searchParams.forEach((value, key) => {
      query[key] = value;
    });
    const body = readBody(route);
    this.requests.push({ method, path, query, body });

    const failure = this.consumeFailure(method, path);
    if (failure !== null) {
      await this.reply(route, {
        status: failure.status,
        body: {
          error: {
            code: "mock_error",
            message: failure.message,
            retriable: failure.status >= 500,
          },
        },
        contentType: "application/json",
      });
      return;
    }

    if (path === "/api/events") {
      // 挂起事件流请求，避免前端每秒重连造成的请求噪声
      await new Promise<void>(() => {});
      return;
    }

    const response = this.respond(method, path, query, body);
    await this.reply(route, response);
  }

  private async reply(route: Route, response: MockResponse): Promise<void> {
    if (response.status === 204) {
      await route.fulfill({ status: 204 });
      return;
    }
    await route.fulfill({
      status: response.status,
      contentType: response.contentType,
      body: typeof response.body === "string" ? response.body : JSON.stringify(response.body),
    });
  }

  private consumeFailure(method: string, path: string): FailureRule | null {
    const index = this.failures.findIndex(
      (rule) =>
        rule.method === method &&
        (typeof rule.path === "string" ? rule.path === path : rule.path.test(path)),
    );
    if (index < 0) return null;
    const rule = this.failures[index];
    if (Number.isFinite(rule.remaining)) {
      rule.remaining -= 1;
      if (rule.remaining <= 0) this.failures.splice(index, 1);
    }
    return rule;
  }

  private json(body: unknown, status = 200): MockResponse {
    return { status, body, contentType: "application/json" };
  }

  private error(status: number, message: string): MockResponse {
    return this.json(
      { error: { code: "mock_error", message, retriable: status >= 500 } },
      status,
    );
  }

  private respond(
    method: string,
    path: string,
    query: Record<string, string>,
    body: JsonRecord | null,
  ): MockResponse {
    if (method === "GET" && path === "/api/health") {
      return this.json(this.health);
    }
    if (method === "GET" && path === "/api/catalog") {
      return this.json({ available: this.catalog !== null, catalog: this.catalog });
    }
    if (method === "GET" && path === "/api/tactics/template") {
      return this.json({ scenario: this.templateScenario });
    }
    if (method === "GET" && path === "/api/system/resources") {
      return this.json(this.resources);
    }
    if (method === "GET" && path === "/api/concurrency/check") {
      return this.json(this.concurrency);
    }
    if (path === "/api/system/restart" && method === "POST") {
      return this.json({ status: "restarting" }, 202);
    }

    const drafts = this.respondDrafts(method, path, body);
    if (drafts !== null) return drafts;

    const experiments = this.respondExperiments(method, path, body);
    if (experiments !== null) return experiments;

    const jobs = this.respondJobs(method, path, query, body);
    if (jobs !== null) return jobs;

    const settings = this.respondSettings(method, path, body);
    if (settings !== null) return settings;

    const engine = this.respondEngine(method, path, body);
    if (engine !== null) return engine;

    if (method === "GET" && path === "/api/saves") {
      return this.json({ items: [], total: 0, next_offset: null });
    }
    if (method === "POST" && path === "/api/results/compare") {
      return this.json(this.compare(body ?? {}));
    }
    return this.error(404, `未模拟的接口：${method} ${path}`);
  }

  private respondDrafts(method: string, path: string, body: JsonRecord | null): MockResponse | null {
    if (path === "/api/drafts") {
      if (method === "GET") {
        const items = this.drafts.map((draft) => ({
          id: draft["id"],
          name: draft["name"],
          source: draft["source"],
          created_at: draft["created_at"],
          updated_at: draft["updated_at"],
        }));
        return this.json({ items, total: items.length, next_offset: null });
      }
      if (method === "POST") {
        return this.json(this.createDraft(body), 201);
      }
    }
    if (!path.startsWith("/api/drafts/")) return null;
    const rest = path.slice("/api/drafts/".length);
    const [rawId, action] = rest.split("/");
    const id = decodeURIComponent(rawId);
    const draft = this.drafts.find((item) => item["id"] === id);

    if (action === "attributes" && method === "POST") {
      return draft === undefined ? this.error(404, "草案不存在") : this.json(draft);
    }
    if (action === "apply-roster" && method === "POST") {
      return draft === undefined ? this.error(404, "草案不存在") : this.json(draft);
    }
    if (action === "undo-roster" && method === "POST") {
      return draft === undefined ? this.error(404, "草案不存在") : this.json(draft);
    }
    if (action === "export.fmf" && method === "GET") {
      return draft === undefined
        ? this.error(404, "草案不存在")
        : { status: 200, body: "FMF", contentType: "application/octet-stream" };
    }
    if (action !== undefined) return null;

    if (draft === undefined) return this.error(404, "草案不存在");
    if (method === "GET") return this.json(draft);
    if (method === "PATCH") {
      if (body !== null) {
        if (typeof body["name"] === "string") draft["name"] = body["name"];
        if (body["scenario"] !== undefined) draft["scenario"] = body["scenario"];
        if (body["source"] !== undefined) draft["source"] = body["source"];
      }
      draft["updated_at"] = TIMESTAMP;
      return this.json(draft);
    }
    if (method === "DELETE") {
      this.drafts = this.drafts.filter((item) => item["id"] !== id);
      return { status: 204, body: null, contentType: "application/json" };
    }
    return null;
  }

  private createDraft(body: JsonRecord | null): JsonRecord {
    this.draftSeq += 1;
    const draft = buildDraft({
      id: `draft-${this.draftSeq}`,
      name: typeof body?.["name"] === "string" ? body["name"] : `草案 ${this.draftSeq}`,
      scenario: body?.["scenario"] ?? buildScenario(),
      source: body?.["source"] ?? { kind: "manual" },
    });
    this.drafts = [...this.drafts, draft];
    return draft;
  }

  private respondExperiments(
    method: string,
    path: string,
    body: JsonRecord | null,
  ): MockResponse | null {
    if (method === "POST" && path === "/api/experiments") {
      const seeds = Array.isArray(body?.["seeds"]) ? (body?.["seeds"] as unknown[]) : [];
      const total = seeds.length > 0 ? seeds.length : 100;
      const job = buildJob({
        id: "job-submitted",
        status: "queued",
        name: typeof body?.["name"] === "string" && body["name"] !== "" ? body["name"] : "新实验",
        total,
        completed: 0,
        started_at: null,
        finished_at: null,
      });
      this.pendingJob = job;
      return this.json(job, 201);
    }
    if (method === "POST" && path === "/api/experiments/start") {
      if (this.pendingJob === null) {
        return { status: 204, body: null, contentType: "application/json" };
      }
      const job = { ...this.pendingJob, status: "running", started_at: TIMESTAMP };
      this.pendingJob = null;
      this.jobs = [job, ...this.jobs];
      return this.json({ job });
    }
    return null;
  }

  private respondJobs(
    method: string,
    path: string,
    query: Record<string, string>,
    body: JsonRecord | null,
  ): MockResponse | null {
    if (path === "/api/jobs") {
      if (method === "GET") {
        const status = query["status"];
        const filtered =
          status === undefined || status === ""
            ? this.jobs
            : this.jobs.filter((job) => job["status"] === status);
        const limit = Number(query["limit"] ?? filtered.length);
        const offset = Number(query["offset"] ?? 0);
        const items = filtered.slice(offset, offset + limit);
        const nextOffset = offset + items.length < filtered.length ? offset + items.length : null;
        return this.json({ items, total: filtered.length, next_offset: nextOffset });
      }
      if (method === "POST") {
        const job = buildJob({
          id: `job-${this.jobs.length + 2000}`,
          status: "queued",
          name: typeof body?.["name"] === "string" ? body["name"] : null,
          total: typeof body?.["total"] === "number" ? body["total"] : 0,
          completed: 0,
          started_at: null,
          finished_at: null,
        });
        this.jobs = [job, ...this.jobs];
        return this.json(job, 201);
      }
      if (method === "DELETE") {
        const ids = Array.isArray(body?.["ids"]) ? (body["ids"] as unknown[]).map(String) : [];
        this.jobs = this.jobs.filter((job) => !ids.includes(String(job["id"])));
        return this.json({ deleted: ids, failed: [] });
      }
    }
    if (!path.startsWith("/api/jobs/")) return null;
    const rest = path.slice("/api/jobs/".length);
    const [rawId, action] = rest.split("/");
    const id = decodeURIComponent(rawId);

    if (action === "cancel" && method === "POST") {
      const job = this.jobs.find((item) => item["id"] === id);
      if (job === undefined) return this.error(404, "任务不存在");
      job["status"] = "cancelled";
      return this.json(job);
    }
    if (action === "runs" && method === "GET") {
      const limit = Number(query["limit"] ?? this.runs.length);
      const offset = Number(query["offset"] ?? 0);
      const items = this.runs.slice(offset, offset + limit).map((run) => ({ ...run, job_id: id }));
      const nextOffset = offset + items.length < this.runs.length ? offset + items.length : null;
      return this.json({ items, total: this.runs.length, next_offset: nextOffset });
    }
    if (action === "summary" && method === "GET") {
      const job = this.jobs.find((item) => item["id"] === id) ?? buildJob({ id });
      return this.json(buildSummary(job, this.summaryMetrics));
    }
    if (action === "pool-summary" && method === "GET") {
      return this.json(this.poolSummary);
    }
    if (action === "export.csv" && method === "GET") {
      return { status: 200, body: "sequence,variant,seed,score\n1,A,11,2-1\n", contentType: "text/csv" };
    }
    if (action !== undefined) return null;

    const job = this.jobs.find((item) => item["id"] === id);
    if (job === undefined) return this.error(404, "任务不存在");
    if (method === "GET") return this.json(job);
    if (method === "PATCH") {
      if (body !== null) Object.assign(job, body);
      return this.json(job);
    }
    if (method === "DELETE") {
      this.jobs = this.jobs.filter((item) => item["id"] !== id);
      return { status: 204, body: null, contentType: "application/json" };
    }
    return null;
  }

  private respondSettings(
    method: string,
    path: string,
    body: JsonRecord | null,
  ): MockResponse | null {
    if (path === "/api/settings") {
      if (method === "GET") {
        return this.json({ items: this.settings, total: this.settings.length });
      }
    }
    if (!path.startsWith("/api/settings/")) return null;
    const key = decodeURIComponent(path.slice("/api/settings/".length));
    const index = this.settings.findIndex((item) => item["key"] === key);
    if (method === "GET") {
      return index < 0 ? this.error(404, "设置不存在") : this.json(this.settings[index]);
    }
    if (method === "PUT") {
      const value = body?.["value"] ?? null;
      const note = typeof body?.["note"] === "string" ? body["note"] : null;
      const setting = { key, value, note, updated_at: TIMESTAMP };
      if (index < 0) this.settings = [...this.settings, setting];
      else this.settings[index] = setting;
      return this.json(setting);
    }
    if (method === "DELETE") {
      this.settings = this.settings.filter((item) => item["key"] !== key);
      return { status: 204, body: null, contentType: "application/json" };
    }
    return null;
  }

  private respondEngine(method: string, path: string, body: JsonRecord | null): MockResponse | null {
    if (method === "GET" && path === "/api/engine") {
      return this.json(this.engine);
    }
    if (method === "POST" && path === "/api/engine/select") {
      if (body !== null) {
        const engineRoot = body["engine_root"];
        const gameRoot = body["game_root"];
        if (typeof engineRoot === "string" && engineRoot !== "") this.engine["engine_root"] = engineRoot;
        if (typeof gameRoot === "string" && gameRoot !== "") this.engine["game_root"] = gameRoot;
      }
      return this.json(this.engine);
    }
    if (method === "POST" && path === "/api/engine/import") {
      return this.json({
        target_root: this.engine["engine_root"],
        available: true,
        missing: [],
        matched: 5,
        adapter_version: "1.0.0",
        catalog_path: "/opt/FM27/catalog.json",
        copied: [],
        total_bytes: 0,
      });
    }
    if (method === "POST" && path === "/api/engine/diagnose") {
      return this.json({
        compatible: true,
        trial_allowed: true,
        reason: "",
        adapter_version: "1.0.0",
        image_sha256: "0".repeat(64),
      });
    }
    return null;
  }
}
