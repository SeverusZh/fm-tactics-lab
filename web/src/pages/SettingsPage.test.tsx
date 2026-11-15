import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppContext } from "../app-context";
import type {
  EngineDiagnosis,
  EngineImportResult,
  EngineStatus,
  Health,
  HostResources,
  Setting,
} from "../lib/api";
import type { Connection } from "../lib/connection";
import { SettingsPage } from "./SettingsPage";

const fileDialogMocks = vi.hoisted(() => ({
  isDesktopShellMock: vi.fn(() => false),
  chooseLocalDirectoryMock: vi.fn(async () => null as string | null),
}));

vi.mock("../lib/file-dialog", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/file-dialog")>();
  return {
    ...actual,
    isDesktopShell: fileDialogMocks.isDesktopShellMock,
    chooseLocalDirectory: fileDialogMocks.chooseLocalDirectoryMock,
  };
});

const GIB = 1024 ** 3;

const CONNECTION: Connection = {
  url: "http://127.0.0.1:43210",
  token: "test-token",
  api: "fm27lab/v2",
};

const HEALTH: Health = {
  status: "ok",
  api: "fm27lab/v2",
  version: "2.0.0.dev0",
  database: "ready",
};

const CONFIGURED_STATUS: EngineStatus = {
  engine_root: "D:/FM27",
  game_root: "D:/FM27/game",
  engine: { available: true, missing: [] },
  game: { available: true, missing: [] },
};

const UNCONFIGURED_STATUS: EngineStatus = {
  engine_root: null,
  game_root: null,
  engine: { available: false, missing: ["fm27_native/FM27Simulator.exe"] },
  game: { available: false, missing: ["fm_Data/Plugins/x86_64/game_plugin.dll"] },
};

const MISSING_STATUS: EngineStatus = {
  engine_root: "D:/FM27",
  game_root: "D:/FM27/game",
  engine: {
    available: false,
    missing: ["fm27_native/FM27Simulator.exe", "fm27_native/catalog.json"],
  },
  game: { available: true, missing: [] },
};

const IMPORT_RESULT: EngineImportResult = {
  target_root: "D:/FM27",
  available: true,
  missing: [],
  matched: true,
  adapter_version: "1.4.0",
  catalog_path: "D:/FM27/fm27_native/catalog.json",
  copied: [
    { path: "fm27_native/FM27Simulator.exe", bytes: 1024 },
    { path: "fixtures/editor.json", bytes: 512 },
  ],
  total_bytes: 1536,
};

const IMPORT_INCOMPLETE: EngineImportResult = {
  target_root: "D:/FM27",
  available: false,
  missing: ["fm27_native/catalog.json", "fm27_research/fixtures.json"],
  matched: false,
  adapter_version: null,
  catalog_path: null,
  copied: [{ path: "fm27_native/FM27Simulator.exe", bytes: 1024 }],
  total_bytes: 1024,
};

const RESOURCES: HostResources = {
  cpu_count: 16,
  available_memory_bytes: 24 * GIB,
  free_disk_bytes: 500 * GIB,
  recommended_workers: 8,
};

const COMPATIBLE_DIAGNOSIS: EngineDiagnosis = {
  compatible: true,
  trial_allowed: true,
  reason: null,
  adapter_version: "1.4.0",
  image_sha256: "0123456789abcdef0123456789abcdef",
};

const INCOMPATIBLE_DIAGNOSIS: EngineDiagnosis = {
  compatible: false,
  trial_allowed: false,
  reason: "image fingerprint mismatch",
  adapter_version: null,
  image_sha256: null,
};

const CONCURRENCY_RESULT = {
  allowed: true,
  code: null,
  recommended_workers: 8,
  warnings: [],
  memory_required_bytes: 8 * GIB,
  disk_required_bytes: 50 * GIB,
};

const EXISTING_SETTING: Setting = {
  key: "demo.flag",
  value: { enabled: true },
  note: "演示",
  updated_at: "2026-02-01T00:00:00Z",
};

type RouteResult = Response | Promise<Response>;

interface ApiRoutes {
  engineStatus: () => RouteResult;
  engineSelect: () => RouteResult;
  engineImport: () => RouteResult;
  diagnose: () => RouteResult;
  resources: () => RouteResult;
  restart: () => RouteResult;
  settings: () => RouteResult;
  putSetting: (key: string) => RouteResult;
  deleteSetting: (key: string) => RouteResult;
  concurrency: (search: URLSearchParams) => RouteResult;
  health: () => RouteResult;
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function emptyResponse(): Response {
  return {
    ok: true,
    status: 204,
    json: async () => null,
  } as unknown as Response;
}

function errorResponse(message: string, code: string, status: number): Response {
  return jsonResponse(
    {
      error: {
        code,
        message,
        details: null,
        retriable: false,
        retry_after_seconds: null,
      },
    },
    status,
  );
}

function stubApi(overrides: Partial<ApiRoutes> = {}) {
  const routes: ApiRoutes = {
    engineStatus: () => jsonResponse(CONFIGURED_STATUS),
    engineSelect: () => jsonResponse(CONFIGURED_STATUS),
    engineImport: () => jsonResponse(IMPORT_RESULT),
    diagnose: () => jsonResponse(COMPATIBLE_DIAGNOSIS),
    resources: () => jsonResponse(RESOURCES),
    restart: () => jsonResponse({ status: "restarting" }, 202),
    settings: () => jsonResponse({ items: [], total: 0 }),
    putSetting: (key) =>
      jsonResponse({
        key,
        value: { enabled: true },
        note: null,
        updated_at: EXISTING_SETTING.updated_at,
      }),
    deleteSetting: () => emptyResponse(),
    concurrency: () => jsonResponse(CONCURRENCY_RESULT),
    health: () => jsonResponse(HEALTH),
    ...overrides,
  };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = new URL(String(input));
    const method = (init?.method ?? "GET").toUpperCase();
    const path = url.pathname;
    if (path === "/api/engine") return routes.engineStatus();
    if (path === "/api/engine/select") return routes.engineSelect();
    if (path === "/api/engine/import") return routes.engineImport();
    if (path === "/api/engine/diagnose") return routes.diagnose();
    if (path === "/api/system/resources") return routes.resources();
    if (path === "/api/system/restart") return routes.restart();
    if (path === "/api/health") return routes.health();
    if (path === "/api/concurrency/check") return routes.concurrency(url.searchParams);
    if (path === "/api/settings" && method === "GET") return routes.settings();
    if (path.startsWith("/api/settings/")) {
      const key = decodeURIComponent(path.slice("/api/settings/".length));
      return method === "PUT" ? routes.putSetting(key) : routes.deleteSetting(key);
    }
    throw new Error("unexpected request: " + method + " " + url.toString());
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

type FetchMock = ReturnType<typeof stubApi>;

interface RecordedCall {
  input: RequestInfo | URL;
  init: RequestInit | undefined;
}

function callsTo(fetchMock: FetchMock, path: string, method = "GET"): RecordedCall[] {
  const calls: RecordedCall[] = [];
  for (const [input, init] of fetchMock.mock.calls) {
    const parsed = new URL(String(input));
    if (parsed.pathname !== path) continue;
    if ((init?.method ?? "GET").toUpperCase() !== method) continue;
    calls.push({ input, init });
  }
  return calls;
}

function bodyOf(call: RecordedCall): unknown {
  const body = call.init?.body;
  return typeof body === "string" ? JSON.parse(body) : null;
}

interface RenderOptions {
  connection?: Connection | null;
  health?: Health | null;
}

function renderSettingsPage(options: RenderOptions = {}) {
  const initialConnection = options.connection !== undefined ? options.connection : CONNECTION;
  const initialHealth = options.health !== undefined ? options.health : HEALTH;
  const refresh = vi.fn();
  let currentRefresh: () => void = refresh;
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  const ui = (connection: Connection | null, health: Health | null) => (
    <QueryClientProvider client={client}>
      <AppContext.Provider
        value={{ connection, health, connectionError: null, refreshing: false, refresh: currentRefresh }}
      >
        <SettingsPage />
      </AppContext.Provider>
    </QueryClientProvider>
  );
  const result = render(ui(initialConnection, initialHealth));
  const rerenderWith = (
    next: { connection: Connection | null; health: Health | null },
    nextRefresh?: () => void,
  ) => {
    if (nextRefresh !== undefined) currentRefresh = nextRefresh;
    result.rerender(ui(next.connection, next.health));
  };
  return { ...result, client, refresh, rerenderWith };
}

let fetchMock: FetchMock;

beforeEach(() => {
  fileDialogMocks.isDesktopShellMock.mockReturnValue(false);
  fileDialogMocks.chooseLocalDirectoryMock.mockReset();
  fileDialogMocks.chooseLocalDirectoryMock.mockResolvedValue(null);
  fetchMock = stubApi();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("引擎与游戏目录", () => {
  it("未配置目录时给出填写指引与禁用原因", async () => {
    fetchMock = stubApi({ engineStatus: () => jsonResponse(UNCONFIGURED_STATUS) });
    renderSettingsPage();
    const save = await screen.findByRole("button", { name: "保存配置" });
    expect(save).toBeDisabled();
    expect(screen.getByText("请至少填写引擎目录或游戏目录")).toBeInTheDocument();
    expect(screen.getAllByText("尚未配置")).toHaveLength(2);
    expect(screen.getByText("fm27_native/FM27Simulator.exe")).toBeInTheDocument();
    expect(screen.getByText("fm_Data/Plugins/x86_64/game_plugin.dll")).toBeInTheDocument();
    expect(screen.getByText("引擎目录不可用")).toBeInTheDocument();
    expect(screen.getByText("游戏目录不可用")).toBeInTheDocument();
    const diagnose = screen.getByRole("button", { name: "诊断引擎兼容性" });
    expect(diagnose).toBeDisabled();
    expect(screen.getByText("引擎目录缺少必需文件，无法诊断")).toBeInTheDocument();
    expect(screen.queryByText("已保存，重启 sidecar 后生效")).toBeNull();
  });

  it("禁用原因通过 aria-describedby 关联到对应按钮", async () => {
    fetchMock = stubApi({ engineStatus: () => jsonResponse(UNCONFIGURED_STATUS) });
    renderSettingsPage();
    const save = await screen.findByRole("button", { name: "保存配置" });
    expect(save).toHaveAttribute("aria-describedby", "engine-save-hint");
    expect(screen.getByText("请至少填写引擎目录或游戏目录")).toHaveAttribute(
      "id",
      "engine-save-hint",
    );
    const diagnose = screen.getByRole("button", { name: "诊断引擎兼容性" });
    expect(diagnose).toHaveAttribute("aria-describedby", "engine-diagnose-hint");
    expect(screen.getByText("引擎目录缺少必需文件，无法诊断")).toHaveAttribute(
      "id",
      "engine-diagnose-hint",
    );
    const importButton = screen.getByRole("button", { name: "导入" });
    expect(importButton).toHaveAttribute("aria-describedby", "engine-import-hint");
    expect(screen.getByText("请填写来源目录")).toHaveAttribute("id", "engine-import-hint");
  });

  it("缺少必需文件时逐条列出并禁用诊断", async () => {
    fetchMock = stubApi({ engineStatus: () => jsonResponse(MISSING_STATUS) });
    renderSettingsPage();
    await screen.findByRole("button", { name: "保存配置" });
    expect(screen.getByText("引擎目录不可用")).toBeInTheDocument();
    expect(screen.getByText("游戏目录可用")).toBeInTheDocument();
    expect(screen.getByText("缺少以下文件：")).toBeInTheDocument();
    expect(screen.getByText("fm27_native/catalog.json")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "诊断引擎兼容性" })).toBeDisabled();
    expect(screen.getByText("引擎目录缺少必需文件，无法诊断")).toBeInTheDocument();
    const engineInput = screen.getByLabelText("引擎目录") as HTMLInputElement;
    await waitFor(() => expect(engineInput.value).toBe("D:/FM27"));
    expect(screen.getByRole("button", { name: "保存配置" })).toBeEnabled();
  });

  it("引擎配置读取失败后可以重试", async () => {
    let attempts = 0;
    fetchMock = stubApi({
      engineStatus: () => {
        attempts += 1;
        if (attempts === 1) return errorResponse("无法连接 sidecar", "connection_error", 503);
        return jsonResponse(CONFIGURED_STATUS);
      },
    });
    renderSettingsPage();
    expect(await screen.findByText("无法连接 sidecar")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("引擎目录可用")).toBeInTheDocument();
    expect(callsTo(fetchMock, "/api/engine")).toHaveLength(2);
  });

  it("刷新状态会重新读取引擎配置", async () => {
    let attempts = 0;
    fetchMock = stubApi({
      engineStatus: () => {
        attempts += 1;
        if (attempts === 1) return jsonResponse(UNCONFIGURED_STATUS);
        return jsonResponse(CONFIGURED_STATUS);
      },
    });
    renderSettingsPage();
    await screen.findByRole("button", { name: "保存配置" });
    expect(screen.getByText("引擎目录不可用")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "刷新状态" }));
    expect(await screen.findByText("引擎目录可用")).toBeInTheDocument();
    expect(callsTo(fetchMock, "/api/engine")).toHaveLength(2);
  });

  it("桌面壳显示浏览按钮并写入所选目录", async () => {
    fileDialogMocks.isDesktopShellMock.mockReturnValue(true);
    fileDialogMocks.chooseLocalDirectoryMock.mockResolvedValue("D:/FM27-next");
    fetchMock = stubApi({ engineStatus: () => jsonResponse(UNCONFIGURED_STATUS) });
    renderSettingsPage();
    const browseButtons = await screen.findAllByRole("button", { name: "浏览…" });
    expect(browseButtons).toHaveLength(2);
    fireEvent.click(browseButtons[0]);
    await waitFor(() =>
      expect(fileDialogMocks.chooseLocalDirectoryMock).toHaveBeenCalledTimes(1),
    );
    expect(fileDialogMocks.chooseLocalDirectoryMock).toHaveBeenCalledWith({
      title: "选择引擎目录",
      defaultPath: undefined,
    });
    expect(await screen.findByDisplayValue("D:/FM27-next")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存配置" })).toBeEnabled();
  });

  it("非桌面壳隐藏浏览按钮并允许手填", async () => {
    fetchMock = stubApi({ engineStatus: () => jsonResponse(UNCONFIGURED_STATUS) });
    renderSettingsPage();
    const engineInput = (await screen.findByLabelText("引擎目录")) as HTMLInputElement;
    expect(screen.queryByRole("button", { name: "浏览…" })).toBeNull();
    fireEvent.change(engineInput, { target: { value: "D:/manual" } });
    expect(engineInput.value).toBe("D:/manual");
    expect(screen.getByRole("button", { name: "保存配置" })).toBeEnabled();
    expect(fileDialogMocks.chooseLocalDirectoryMock).not.toHaveBeenCalled();
  });

  it("保存配置提交目录并提示重启", async () => {
    const updated: EngineStatus = { ...CONFIGURED_STATUS, engine_root: "D:/FM27-next" };
    fetchMock = stubApi({
      engineStatus: () => jsonResponse(updated),
      engineSelect: () => jsonResponse(updated),
    });
    renderSettingsPage();
    const engineInput = (await screen.findByLabelText("引擎目录")) as HTMLInputElement;
    await waitFor(() => expect(engineInput.value).toBe("D:/FM27-next"));
    fireEvent.change(engineInput, { target: { value: "D:/FM27-next" } });
    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));
    expect(await screen.findByText("已保存，重启 sidecar 后生效")).toBeInTheDocument();
    const selectCalls = callsTo(fetchMock, "/api/engine/select", "POST");
    expect(selectCalls).toHaveLength(1);
    expect(bodyOf(selectCalls[0])).toEqual({
      engine_root: "D:/FM27-next",
      game_root: "D:/FM27/game",
    });
    expect(screen.getByRole("button", { name: "诊断引擎兼容性" })).toBeDisabled();
    expect(
      screen.getByText("已保存新配置，请先重启 sidecar 使新配置生效"),
    ).toBeInTheDocument();
    expect(screen.getByText("配置已保存，需要重启 sidecar 才能生效。")).toBeInTheDocument();
  });

  it("只修改游戏目录时保存会同时提交两个当前目录", async () => {
    const updated: EngineStatus = { ...CONFIGURED_STATUS, game_root: "D:/FM27/game2" };
    fetchMock = stubApi({
      engineStatus: () => jsonResponse(CONFIGURED_STATUS),
      engineSelect: () => jsonResponse(updated),
    });
    renderSettingsPage();
    const gameInput = (await screen.findByLabelText("游戏目录")) as HTMLInputElement;
    await waitFor(() => expect(gameInput.value).toBe("D:/FM27/game"));
    fireEvent.change(gameInput, { target: { value: "D:/FM27/game2" } });
    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));
    expect(await screen.findByText("已保存，重启 sidecar 后生效")).toBeInTheDocument();
    const selectCalls = callsTo(fetchMock, "/api/engine/select", "POST");
    expect(selectCalls).toHaveLength(1);
    expect(bodyOf(selectCalls[0])).toEqual({
      engine_root: "D:/FM27",
      game_root: "D:/FM27/game2",
    });
  });

  it("桌面壳选择目录失败时展示错误", async () => {
    fileDialogMocks.isDesktopShellMock.mockReturnValue(true);
    fileDialogMocks.chooseLocalDirectoryMock.mockRejectedValue(new Error("目录选择器不可用"));
    fetchMock = stubApi({ engineStatus: () => jsonResponse(UNCONFIGURED_STATUS) });
    renderSettingsPage();
    const browseButtons = await screen.findAllByRole("button", { name: "浏览…" });
    fireEvent.click(browseButtons[0]);
    expect(await screen.findByText("目录选择器不可用")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存配置" })).toBeDisabled();
  });

  it("保存失败展示后端中文错误并可重试", async () => {
    const failure = "引擎目录缺少：fm27_native/FM27Simulator.exe";
    const updated: EngineStatus = { ...CONFIGURED_STATUS, engine_root: "D:/bad" };
    let attempts = 0;
    fetchMock = stubApi({
      engineStatus: () => jsonResponse(updated),
      engineSelect: () => {
        attempts += 1;
        if (attempts === 1) return errorResponse(failure, "validation_failed", 400);
        return jsonResponse(updated);
      },
    });
    renderSettingsPage();
    const engineInput = (await screen.findByLabelText("引擎目录")) as HTMLInputElement;
    await waitFor(() => expect(engineInput.value).toBe("D:/bad"));
    fireEvent.change(engineInput, { target: { value: "D:/bad" } });
    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));
    expect(await screen.findByText(failure)).toBeInTheDocument();
    expect(screen.queryByText("已保存，重启 sidecar 后生效")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));
    expect(await screen.findByText("已保存，重启 sidecar 后生效")).toBeInTheDocument();
    expect(callsTo(fetchMock, "/api/engine/select", "POST")).toHaveLength(2);
  });

  it("两个目录都清空时禁用保存", async () => {
    renderSettingsPage();
    const engineInput = (await screen.findByLabelText("引擎目录")) as HTMLInputElement;
    await waitFor(() => expect(engineInput.value).toBe("D:/FM27"));
    const gameInput = screen.getByLabelText("游戏目录") as HTMLInputElement;
    fireEvent.change(engineInput, { target: { value: "" } });
    fireEvent.change(gameInput, { target: { value: "" } });
    expect(screen.getByRole("button", { name: "保存配置" })).toBeDisabled();
    expect(screen.getByText("请至少填写引擎目录或游戏目录")).toBeInTheDocument();
  });
});

describe("引擎兼容性诊断", () => {
  it("诊断成功展示兼容徽标、适配器版本与镜像指纹前缀", async () => {
    fetchMock = stubApi({ diagnose: () => jsonResponse(COMPATIBLE_DIAGNOSIS) });
    renderSettingsPage();
    await screen.findByText("引擎目录可用");
    const diagnoseButton = screen.getByRole("button", { name: "诊断引擎兼容性" });
    await waitFor(() => expect(diagnoseButton).toBeEnabled());
    fireEvent.click(diagnoseButton);
    expect(await screen.findByText("兼容")).toBeInTheDocument();
    expect(screen.getByText("允许试用")).toBeInTheDocument();
    expect(screen.getByText("适配器版本")).toBeInTheDocument();
    expect(screen.getByText("1.4.0")).toBeInTheDocument();
    expect(screen.getByText("0123456789ab")).toBeInTheDocument();
    expect(screen.queryByText("0123456789abcdef0123456789abcdef")).toBeNull();
    const diagnosisStatus = screen.getByText("适配器版本").closest('[role="status"]');
    expect(diagnosisStatus).toHaveAttribute("aria-live", "polite");
    expect(callsTo(fetchMock, "/api/engine/diagnose", "POST")).toHaveLength(1);
  });

  it("诊断不兼容时展示中文解释与原始原因", async () => {
    fetchMock = stubApi({ diagnose: () => jsonResponse(INCOMPATIBLE_DIAGNOSIS) });
    renderSettingsPage();
    await screen.findByText("引擎目录可用");
    fireEvent.click(screen.getByRole("button", { name: "诊断引擎兼容性" }));
    expect(await screen.findByText("不兼容")).toBeInTheDocument();
    expect(screen.getByText("不允许试用")).toBeInTheDocument();
    expect(
      screen.getByText("引擎与游戏版本不一致，请重新构建或选择匹配的引擎。"),
    ).toBeInTheDocument();
    expect(screen.getByText("image fingerprint mismatch")).toBeInTheDocument();
    expect(screen.getAllByText("未知")).toHaveLength(2);
  });

  it("诊断失败展示后端错误并允许重试", async () => {
    const failure = "引擎诊断失败：宿主退出码 1";
    fetchMock = stubApi({ diagnose: () => errorResponse(failure, "engine_diagnose_failed", 503) });
    renderSettingsPage();
    await screen.findByText("引擎目录可用");
    fireEvent.click(screen.getByRole("button", { name: "诊断引擎兼容性" }));
    expect(await screen.findByText(failure)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "诊断引擎兼容性" })).toBeEnabled();
    expect(screen.queryByText("兼容")).toBeNull();
  });
});

describe("重启 sidecar", () => {
  it("重启需要二次确认且取消不会发起请求", async () => {
    renderSettingsPage();
    await screen.findByRole("button", { name: "保存配置" });
    fireEvent.click(screen.getByRole("button", { name: "重启 sidecar" }));
    const confirmDialog = screen.getByRole("dialog", {
      name: "重启会中断正在运行的任务，确定重启 sidecar？",
    });
    expect(
      within(confirmDialog).getByText("重启会中断正在运行的任务，确定重启 sidecar？"),
    ).toBeInTheDocument();
    expect(callsTo(fetchMock, "/api/system/restart", "POST")).toHaveLength(0);
    fireEvent.click(within(confirmDialog).getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "重启 sidecar" })).toBeInTheDocument();
    expect(callsTo(fetchMock, "/api/system/restart", "POST")).toHaveLength(0);
  });

  it("重启确认框具备对话框语义、初始焦点与 Esc 关闭后焦点回归", async () => {
    renderSettingsPage();
    await screen.findByRole("button", { name: "保存配置" });
    fireEvent.click(screen.getByRole("button", { name: "重启 sidecar" }));
    const dialog = screen.getByRole("dialog", {
      name: "重启会中断正在运行的任务，确定重启 sidecar？",
    });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("aria-describedby", "restart-mode-hint");
    expect(screen.getByText(/浏览器模式：重启会断开连接/)).toHaveAttribute(
      "id",
      "restart-mode-hint",
    );
    const confirm = within(dialog).getByRole("button", { name: "确认重启" });
    expect(confirm).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "重启 sidecar" })).toHaveFocus();
    expect(callsTo(fetchMock, "/api/system/restart", "POST")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "重启 sidecar" }));
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "重启 sidecar" })).toHaveFocus();
  });

  it("确认重启后等待连接恢复", async () => {
    const view = renderSettingsPage();
    await screen.findByRole("button", { name: "保存配置" });
    fireEvent.click(screen.getByRole("button", { name: "重启 sidecar" }));
    fireEvent.click(screen.getByRole("button", { name: "确认重启" }));
    expect(await screen.findByText("正在重启 sidecar… 等待重新连接")).toBeInTheDocument();
    expect(callsTo(fetchMock, "/api/system/restart", "POST")).toHaveLength(1);
    const restartedConnection: Connection = { ...CONNECTION, token: "test-token-restarted" };
    view.rerenderWith({ connection: restartedConnection, health: HEALTH });
    expect(await screen.findByText("sidecar 已重新连接，新配置已生效。")).toBeInTheDocument();
    expect(view.refresh).toHaveBeenCalled();
  });

  it("重启请求失败时显示错误", async () => {
    const failure = "重启失败：监督进程不可用";
    fetchMock = stubApi({ restart: () => errorResponse(failure, "restart_failed", 503) });
    renderSettingsPage();
    await screen.findByRole("button", { name: "保存配置" });
    fireEvent.click(screen.getByRole("button", { name: "重启 sidecar" }));
    fireEvent.click(screen.getByRole("button", { name: "确认重启" }));
    expect(await screen.findByText(failure)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重启 sidecar" })).toBeInTheDocument();
  });

  it("浏览器模式提示需要手动重启后端进程", () => {
    renderSettingsPage();
    expect(
      screen.getByText("浏览器模式：重启会断开连接且不会自动拉起，需要手动重启后端进程。"),
    ).toBeInTheDocument();
  });

  it("桌面模式提示应用会自动拉起 sidecar", () => {
    fileDialogMocks.isDesktopShellMock.mockReturnValue(true);
    renderSettingsPage();
    expect(
      screen.getByText("桌面模式：重启后应用会自动拉起 sidecar，连接恢复后本页自动刷新。"),
    ).toBeInTheDocument();
  });

  it("重启后 60 秒未恢复时提示手动重启应用", async () => {
    fetchMock = stubApi({
      health: () => errorResponse("连接失败", "connection_error", 503),
    });
    renderSettingsPage();
    await screen.findByRole("button", { name: "保存配置" });
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "重启 sidecar" }));
    fireEvent.click(screen.getByRole("button", { name: "确认重启" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText("正在重启 sidecar… 等待重新连接")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(61_000);
    });
    expect(screen.getByText("已等待 60 秒未自动恢复，请手动重启应用")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试重启" })).toBeInTheDocument();
  });

  it("重启后连接断开且迟迟不恢复时仍会超时并给出出口", async () => {
    fetchMock = stubApi({
      health: () => errorResponse("连接失败", "connection_error", 503),
    });
    const view = renderSettingsPage();
    await screen.findByRole("button", { name: "保存配置" });
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "重启 sidecar" }));
    fireEvent.click(screen.getByRole("button", { name: "确认重启" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    view.rerenderWith({ connection: null, health: null });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(61_000);
    });
    expect(screen.getByText("已等待 60 秒未自动恢复，请手动重启应用")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试重启" })).toBeDisabled();
    expect(screen.getByText("sidecar 未连接，无法再次重启")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "取消等待" }));
    expect(screen.queryByText("已等待 60 秒未自动恢复，请手动重启应用")).toBeNull();
    expect(screen.getByRole("button", { name: "重启 sidecar" })).toBeInTheDocument();
  });

  it("超时后重试重启会再次发起重启并回到等待状态", async () => {
    let restartAttempts = 0;
    fetchMock = stubApi({
      health: () => errorResponse("连接失败", "connection_error", 503),
      restart: () => {
        restartAttempts += 1;
        return jsonResponse({ status: "restarting" }, 202);
      },
    });
    renderSettingsPage();
    await screen.findByRole("button", { name: "保存配置" });
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "重启 sidecar" }));
    fireEvent.click(screen.getByRole("button", { name: "确认重启" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(61_000);
    });
    expect(screen.getByText("已等待 60 秒未自动恢复，请手动重启应用")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试重启" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText("正在重启 sidecar… 等待重新连接")).toBeInTheDocument();
    expect(restartAttempts).toBe(2);
  });

  it("页面重渲染不重置重启等待计时", async () => {
    fetchMock = stubApi({
      health: () => errorResponse("连接失败", "connection_error", 503),
    });
    const view = renderSettingsPage();
    await screen.findByRole("button", { name: "保存配置" });
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "重启 sidecar" }));
    fireEvent.click(screen.getByRole("button", { name: "确认重启" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(screen.queryByText("已等待 60 秒未自动恢复，请手动重启应用")).toBeNull();
    view.rerenderWith({ connection: CONNECTION, health: HEALTH }, vi.fn());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(31_000);
    });
    expect(screen.getByText("已等待 60 秒未自动恢复，请手动重启应用")).toBeInTheDocument();
  });

  it("重启后健康探测先失败后成功时自动恢复", async () => {
    let healthAttempts = 0;
    fetchMock = stubApi({
      health: () => {
        healthAttempts += 1;
        if (healthAttempts <= 2) return errorResponse("连接失败", "connection_error", 503);
        return jsonResponse(HEALTH);
      },
    });
    const view = renderSettingsPage();
    await screen.findByRole("button", { name: "保存配置" });
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "重启 sidecar" }));
    fireEvent.click(screen.getByRole("button", { name: "确认重启" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_500);
    });
    expect(screen.getByText("sidecar 已重新连接，新配置已生效。")).toBeInTheDocument();
    expect(view.refresh).toHaveBeenCalled();
    expect(healthAttempts).toBe(3);
  });
});

describe("运行环境与并发", () => {
  it("读取资源后预填 CPU、内存与磁盘", async () => {
    renderSettingsPage();
    const cpuInput = (await screen.findByLabelText("CPU 数量")) as HTMLInputElement;
    await waitFor(() => expect(cpuInput.value).toBe("16"));
    expect((screen.getByLabelText("可用内存 GiB") as HTMLInputElement).value).toBe("24");
    expect((screen.getByLabelText("空闲磁盘 GiB") as HTMLInputElement).value).toBe("500");
    expect(
      screen.getByText("已根据本机资源预填 CPU、内存与磁盘，可手动修改。"),
    ).toBeInTheDocument();
  });

  it("资源读取失败时保留默认值并提示手填", async () => {
    fetchMock = stubApi({
      resources: () => errorResponse("资源探测失败", "resource_probe_failed", 503),
    });
    renderSettingsPage();
    expect(await screen.findByText("无法读取本机资源，请手动填写。")).toBeInTheDocument();
    expect((screen.getByLabelText("CPU 数量") as HTMLInputElement).value).toBe("8");
    expect((screen.getByLabelText("可用内存 GiB") as HTMLInputElement).value).toBe("32");
    expect((screen.getByLabelText("空闲磁盘 GiB") as HTMLInputElement).value).toBe("100");
  });

  it("运行预检使用预填的资源参数并展示结果", async () => {
    renderSettingsPage();
    await waitFor(
      () => expect((screen.getByLabelText("CPU 数量") as HTMLInputElement).value).toBe("16"),
    );
    fireEvent.change(screen.getByLabelText("并行数"), { target: { value: "6" } });
    fireEvent.click(screen.getByRole("button", { name: "运行预检" }));
    const region = await screen.findByRole("region", { name: "并发预检结果" });
    expect(within(region).getByText("允许提交")).toBeInTheDocument();
    expect(within(region).getByText("8")).toBeInTheDocument();
    const preflightCalls = callsTo(fetchMock, "/api/concurrency/check");
    expect(preflightCalls).toHaveLength(1);
    const requestUrl = new URL(String(preflightCalls[0].input));
    expect(requestUrl.searchParams.get("workers")).toBe("6");
    expect(requestUrl.searchParams.get("cpu_count")).toBe("16");
    expect(requestUrl.searchParams.get("available_memory_bytes")).toBe("25769803776");
    expect(requestUrl.searchParams.get("free_disk_bytes")).toBe("536870912000");
    expect(requestUrl.searchParams.get("allow_oversubscription")).toBe("false");
  });

  it("预检结果在输入变化后失效并需要重新运行", async () => {
    renderSettingsPage();
    await waitFor(
      () => expect((screen.getByLabelText("CPU 数量") as HTMLInputElement).value).toBe("16"),
    );
    fireEvent.click(screen.getByRole("button", { name: "运行预检" }));
    expect(await screen.findByRole("region", { name: "并发预检结果" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("并行数"), { target: { value: "5" } });
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "并发预检结果" })).toBeNull(),
    );
    fireEvent.click(screen.getByRole("button", { name: "运行预检" }));
    expect(await screen.findByRole("region", { name: "并发预检结果" })).toBeInTheDocument();
    const preflightCalls = callsTo(fetchMock, "/api/concurrency/check");
    expect(preflightCalls).toHaveLength(2);
    expect(new URL(String(preflightCalls[1].input)).searchParams.get("workers")).toBe("5");
  });

  it("预检失败只展示后端错误一次", async () => {
    fetchMock = stubApi({
      concurrency: () => errorResponse("预检服务不可用", "preflight_failed", 503),
    });
    renderSettingsPage();
    await waitFor(
      () => expect((screen.getByLabelText("CPU 数量") as HTMLInputElement).value).toBe("16"),
    );
    fireEvent.click(screen.getByRole("button", { name: "运行预检" }));
    expect(await screen.findByText("预检服务不可用")).toBeInTheDocument();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "运行预检" })).toBeEnabled();
  });
});

describe("高级设置", () => {
  it("高级设置默认收起且可以展开", async () => {
    renderSettingsPage();
    const details = await screen.findByTestId("settings-advanced");
    expect(details.tagName).toBe("DETAILS");
    expect((details as HTMLDetailsElement).open).toBe(false);
    const summary = within(details).getByText("高级设置（键值）");
    fireEvent.click(summary);
    expect((details as HTMLDetailsElement).open).toBe(true);
    expect(screen.getByRole("button", { name: "新建设置" })).toBeInTheDocument();
  });

  it("展开后可以新建设置", async () => {
    fetchMock = stubApi({
      putSetting: (key) =>
        jsonResponse({
          key,
          value: { enabled: true },
          note: "演示",
          updated_at: EXISTING_SETTING.updated_at,
        }),
    });
    renderSettingsPage();
    const details = await screen.findByTestId("settings-advanced");
    fireEvent.click(within(details).getByText("高级设置（键值）"));
    fireEvent.click(screen.getByRole("button", { name: "新建设置" }));
    fireEvent.change(screen.getByLabelText("设置键"), { target: { value: "demo.flag" } });
    fireEvent.change(screen.getByLabelText("备注"), { target: { value: "演示" } });
    fireEvent.change(screen.getByLabelText("值 JSON"), {
      target: { value: '{"enabled":true}' },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByText("设置「demo.flag」已保存")).toBeInTheDocument();
    const putCalls = callsTo(fetchMock, "/api/settings/demo.flag", "PUT");
    expect(putCalls).toHaveLength(1);
    expect(bodyOf(putCalls[0])).toEqual({ value: { enabled: true }, note: "演示" });
  });

  it("删除设置需要二次确认", async () => {
    fetchMock = stubApi({
      settings: () => jsonResponse({ items: [EXISTING_SETTING], total: 1 }),
    });
    renderSettingsPage();
    const details = await screen.findByTestId("settings-advanced");
    fireEvent.click(within(details).getByText("高级设置（键值）"));
    const keyCell = await within(details).findByText("demo.flag");
    const row = keyCell.closest("tr");
    expect(row).not.toBeNull();
    if (row === null) throw new Error("设置行未渲染");
    fireEvent.click(within(row).getByRole("button", { name: "删除" }));
    expect(within(row).getByRole("button", { name: "确认删除" })).toBeInTheDocument();
    expect(callsTo(fetchMock, "/api/settings/demo.flag", "DELETE")).toHaveLength(0);
    fireEvent.click(within(row).getByRole("button", { name: "放弃" }));
    fireEvent.click(within(row).getByRole("button", { name: "删除" }));
    fireEvent.click(within(row).getByRole("button", { name: "确认删除" }));
    expect(await screen.findByText("已删除设置「demo.flag」")).toBeInTheDocument();
    expect(callsTo(fetchMock, "/api/settings/demo.flag", "DELETE")).toHaveLength(1);
  });
});

describe("sidecar 信息", () => {
  it("展示连接地址、API、版本与数据库状态", () => {
    renderSettingsPage();
    expect(screen.getByText(CONNECTION.url)).toBeInTheDocument();
    expect(screen.getByText("fm27lab/v2")).toBeInTheDocument();
    expect(screen.getByText("2.0.0.dev0")).toBeInTheDocument();
    expect(screen.getByText("ready")).toBeInTheDocument();
  });

  it("sidecar 未连接时配置操作被禁用并说明原因", () => {
    renderSettingsPage({ connection: null, health: null });
    expect(screen.getAllByText("sidecar 未连接")).toHaveLength(2);
    expect(screen.queryByLabelText("引擎目录")).toBeNull();
    expect(screen.getByRole("button", { name: "诊断引擎兼容性" })).toBeDisabled();
    expect(screen.getByText("sidecar 未连接，无法诊断")).toBeInTheDocument();
    const restartButton = screen.getByRole("button", { name: "重启 sidecar" });
    expect(restartButton).toBeDisabled();
    expect(restartButton).toHaveAttribute("aria-describedby", "engine-restart-hint");
    expect(screen.getByText("sidecar 未连接，无法重启")).toHaveAttribute(
      "id",
      "engine-restart-hint",
    );
    expect(screen.getAllByText("未连接")).toHaveLength(2);
  });
});

describe("导入引擎资源", () => {
  it("导入成功后展示清单、回填引擎目录并刷新状态", async () => {
    fetchMock = stubApi({
      engineStatus: () => jsonResponse(UNCONFIGURED_STATUS),
      engineImport: () => jsonResponse(IMPORT_RESULT),
    });
    renderSettingsPage();
    const sourceInput = (await screen.findByLabelText("来源目录")) as HTMLInputElement;
    fireEvent.change(sourceInput, { target: { value: "D:/old-data" } });
    fireEvent.click(screen.getByRole("button", { name: "导入" }));
    expect(await screen.findByText("导入成功")).toBeInTheDocument();
    expect(screen.getByText("D:/FM27/fm27_native/catalog.json")).toBeInTheDocument();
    expect(screen.getByText("2 个文件")).toBeInTheDocument();
    expect(screen.getByText(/1536 字节/)).toBeInTheDocument();
    expect(screen.getByText(/再重启 sidecar 后生效/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "导入结果" })).toHaveAttribute(
      "aria-live",
      "polite",
    );
    const engineInput = (await screen.findByLabelText("引擎目录")) as HTMLInputElement;
    await waitFor(() => expect(engineInput.value).toBe("D:/FM27"));
    await waitFor(() => expect(callsTo(fetchMock, "/api/engine")).toHaveLength(2));
    const importCalls = callsTo(fetchMock, "/api/engine/import", "POST");
    expect(importCalls).toHaveLength(1);
    expect(bodyOf(importCalls[0])).toEqual({ source_path: "D:/old-data" });
  });

  it("导入完成但缺少文件时逐条列出并提示版本可能不匹配", async () => {
    fetchMock = stubApi({
      engineStatus: () => jsonResponse(UNCONFIGURED_STATUS),
      engineImport: () => jsonResponse(IMPORT_INCOMPLETE),
    });
    renderSettingsPage();
    fireEvent.change(await screen.findByLabelText("来源目录"), {
      target: { value: "D:/partial" },
    });
    fireEvent.click(screen.getByRole("button", { name: "导入" }));
    expect(await screen.findByText("导入完成但引擎不可用")).toBeInTheDocument();
    expect(screen.getByText("fm27_native/catalog.json")).toBeInTheDocument();
    expect(screen.getByText("fm27_research/fixtures.json")).toBeInTheDocument();
    expect(screen.getByText("版本不匹配")).toBeInTheDocument();
    expect(
      screen.getByText("引擎与当前游戏版本可能不匹配，诊断会给出结论。"),
    ).toBeInTheDocument();
    expect(screen.getByText("未发现")).toBeInTheDocument();
    expect(screen.queryByText(/再重启 sidecar 后生效/)).toBeNull();
  });

  it("导入失败展示后端中文错误与检查目录提示并保留输入", async () => {
    const failure = "未从源目录发现可用的引擎工作区：D:/bad；缺少：fm27_native";
    fetchMock = stubApi({
      engineStatus: () => jsonResponse(UNCONFIGURED_STATUS),
      engineImport: () => errorResponse(failure, "engine_import_failed", 400),
    });
    renderSettingsPage();
    const sourceInput = (await screen.findByLabelText("来源目录")) as HTMLInputElement;
    fireEvent.change(sourceInput, { target: { value: "D:/bad" } });
    fireEvent.click(screen.getByRole("button", { name: "导入" }));
    expect(await screen.findByText(failure)).toBeInTheDocument();
    expect(
      screen.getByText("请检查所选目录，确认包含 fm27_native 引擎工作区或旧版应用数据目录。"),
    ).toBeInTheDocument();
    expect(sourceInput.value).toBe("D:/bad");
    expect(screen.queryByRole("region", { name: "导入结果" })).toBeNull();
  });

  it("来源路径校验失败时展示后端消息", async () => {
    fetchMock = stubApi({
      engineStatus: () => jsonResponse(UNCONFIGURED_STATUS),
      engineImport: () => errorResponse("来源路径必须是绝对路径", "validation_failed", 400),
    });
    renderSettingsPage();
    fireEvent.change(await screen.findByLabelText("来源目录"), {
      target: { value: "relative/path" },
    });
    fireEvent.click(screen.getByRole("button", { name: "导入" }));
    expect(await screen.findByText("来源路径必须是绝对路径")).toBeInTheDocument();
    expect(callsTo(fetchMock, "/api/engine/import", "POST")).toHaveLength(1);
  });

  it("导入提交中禁用按钮并只提交一次", async () => {
    let resolveImport: ((response: Response) => void) | null = null;
    const pending = new Promise<Response>((resolve) => {
      resolveImport = resolve;
    });
    fetchMock = stubApi({
      engineStatus: () => jsonResponse(UNCONFIGURED_STATUS),
      engineImport: () => pending,
    });
    renderSettingsPage();
    fireEvent.change(await screen.findByLabelText("来源目录"), {
      target: { value: "D:/old-data" },
    });
    fireEvent.click(screen.getByRole("button", { name: "导入" }));
    const pendingButton = await screen.findByRole("button", { name: "导入中…" });
    expect(pendingButton).toBeDisabled();
    expect(screen.getByText("导入进行中…")).toBeInTheDocument();
    fireEvent.click(pendingButton);
    expect(callsTo(fetchMock, "/api/engine/import", "POST")).toHaveLength(1);
    await act(async () => {
      resolveImport?.(jsonResponse(IMPORT_RESULT));
    });
    expect(await screen.findByText("导入成功")).toBeInTheDocument();
    expect(callsTo(fetchMock, "/api/engine/import", "POST")).toHaveLength(1);
  });

  it("桌面壳可从浏览按钮选择来源目录", async () => {
    fileDialogMocks.isDesktopShellMock.mockReturnValue(true);
    fileDialogMocks.chooseLocalDirectoryMock.mockResolvedValue("D:/old-data");
    renderSettingsPage();
    fireEvent.click(await screen.findByRole("button", { name: "浏览来源目录" }));
    await waitFor(() =>
      expect(fileDialogMocks.chooseLocalDirectoryMock).toHaveBeenCalledWith({
        title: "选择旧版数据或引擎目录",
        defaultPath: undefined,
      }),
    );
    expect(await screen.findByDisplayValue("D:/old-data")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "导入" })).toBeEnabled();
  });

  it("非桌面壳隐藏来源目录浏览按钮", async () => {
    renderSettingsPage();
    await screen.findByLabelText("来源目录");
    expect(screen.queryByRole("button", { name: "浏览来源目录" })).toBeNull();
  });

  it("sidecar 未连接时禁用导入并说明原因", async () => {
    renderSettingsPage({ connection: null, health: null });
    const importButton = await screen.findByRole("button", { name: "导入" });
    expect(importButton).toBeDisabled();
    expect(screen.getByText("连接 sidecar 后才能导入")).toBeInTheDocument();
  });

  it("来源目录为空时禁用导入", async () => {
    renderSettingsPage();
    const importButton = await screen.findByRole("button", { name: "导入" });
    expect(importButton).toBeDisabled();
    expect(screen.getByText("请填写来源目录")).toBeInTheDocument();
  });
});
