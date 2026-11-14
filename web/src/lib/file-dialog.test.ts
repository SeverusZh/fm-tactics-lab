import { afterEach, describe, expect, it, vi } from "vitest";

const { openMock } = vi.hoisted(() => ({ openMock: vi.fn() }));

vi.mock("@tauri-apps/plugin-dialog", () => ({ open: openMock }));

import { chooseLocalDirectory, chooseLocalFile, isDesktopShell } from "./file-dialog";

const FILTERS = [{ name: "FM 存档", extensions: ["fm"] }];

function stubDesktopShell(): void {
  Object.defineProperty(window, "__TAURI_INTERNALS__", { value: {}, configurable: true });
}

afterEach(() => {
  Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
  openMock.mockReset();
});

describe("isDesktopShell", () => {
  it("jsdom 环境下返回 false", () => {
    expect(isDesktopShell()).toBe(false);
  });

  it("window 上存在 __TAURI_INTERNALS__ 时返回 true", () => {
    stubDesktopShell();

    expect(isDesktopShell()).toBe(true);
  });
});

describe("chooseLocalFile", () => {
  it("非桌面环境直接返回 null 且不调用系统对话框", async () => {
    const selected = await chooseLocalFile({ title: "选择存档文件", filters: FILTERS });

    expect(selected).toBeNull();
    expect(openMock).not.toHaveBeenCalled();
  });

  it("桌面环境以单文件模式打开并透传标题与过滤器", async () => {
    stubDesktopShell();
    openMock.mockResolvedValue("/saves/season-1.fm");

    const selected = await chooseLocalFile({ title: "选择存档文件", filters: FILTERS });

    expect(selected).toBe("/saves/season-1.fm");
    expect(openMock).toHaveBeenCalledTimes(1);
    expect(openMock).toHaveBeenCalledWith({
      multiple: false,
      directory: false,
      title: "选择存档文件",
      filters: FILTERS,
    });
  });

  it("用户取消选择时返回 null", async () => {
    stubDesktopShell();
    openMock.mockResolvedValue(null);

    await expect(chooseLocalFile({ title: "选择存档文件", filters: FILTERS })).resolves.toBeNull();
  });

  it("对话框返回数组时返回 null", async () => {
    stubDesktopShell();
    openMock.mockResolvedValue(["/saves/a.fm", "/saves/b.fm"]);

    await expect(chooseLocalFile({ title: "选择存档文件", filters: FILTERS })).resolves.toBeNull();
  });

  it("对话框异常向上抛出", async () => {
    stubDesktopShell();
    openMock.mockRejectedValue(new Error("dialog unavailable"));

    await expect(chooseLocalFile({ title: "选择存档文件", filters: FILTERS })).rejects.toThrow(
      "dialog unavailable",
    );
  });
});

describe("chooseLocalDirectory", () => {
  it("非桌面环境直接返回 null 且不调用系统对话框", async () => {
    const selected = await chooseLocalDirectory({ title: "选择引擎目录" });

    expect(selected).toBeNull();
    expect(openMock).not.toHaveBeenCalled();
  });

  it("桌面环境以目录模式打开并透传标题与初始路径", async () => {
    stubDesktopShell();
    openMock.mockResolvedValue("D:\\FM26");

    const selected = await chooseLocalDirectory({ title: "选择引擎目录", defaultPath: "D:\\FM26" });

    expect(selected).toBe("D:\\FM26");
    expect(openMock).toHaveBeenCalledTimes(1);
    expect(openMock).toHaveBeenCalledWith({
      directory: true,
      multiple: false,
      title: "选择引擎目录",
      defaultPath: "D:\\FM26",
    });
  });

  it("桌面环境未提供选项时只传目录模式", async () => {
    stubDesktopShell();
    openMock.mockResolvedValue("/opt/fm26");

    const selected = await chooseLocalDirectory();

    expect(selected).toBe("/opt/fm26");
    expect(openMock).toHaveBeenCalledWith({ directory: true, multiple: false });
  });

  it("用户取消选择时返回 null", async () => {
    stubDesktopShell();
    openMock.mockResolvedValue(null);

    await expect(chooseLocalDirectory({ title: "选择游戏目录" })).resolves.toBeNull();
  });

  it("对话框返回数组时返回 null", async () => {
    stubDesktopShell();
    openMock.mockResolvedValue(["/opt/a", "/opt/b"]);

    await expect(chooseLocalDirectory()).resolves.toBeNull();
  });

  it("对话框异常向上抛出", async () => {
    stubDesktopShell();
    openMock.mockRejectedValue(new Error("dialog unavailable"));

    await expect(chooseLocalDirectory({ title: "选择引擎目录" })).rejects.toThrow(
      "dialog unavailable",
    );
  });
});
