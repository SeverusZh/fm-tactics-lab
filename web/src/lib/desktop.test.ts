import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const coreMocks = vi.hoisted(() => ({ invoke: vi.fn() }));
const fileDialogMocks = vi.hoisted(() => ({ isDesktopShell: vi.fn(() => false) }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: coreMocks.invoke }));
vi.mock("./file-dialog", () => ({ isDesktopShell: fileDialogMocks.isDesktopShell }));

import { normalizeExternalUrl, openDataDirectory, openExternalUrl } from "./desktop";

describe("normalizeExternalUrl", () => {
  it("接受 http 与 https 并去掉首尾空白", () => {
    expect(normalizeExternalUrl("  https://example.com/docs?q=1  ")).toBe(
      "https://example.com/docs?q=1",
    );
    expect(normalizeExternalUrl("http://127.0.0.1:1420/health")).toBe(
      "http://127.0.0.1:1420/health",
    );
  });

  it("拒绝非 http 协议、相对地址与内嵌凭据", () => {
    expect(normalizeExternalUrl("")).toBeNull();
    expect(normalizeExternalUrl("   ")).toBeNull();
    expect(normalizeExternalUrl("ftp://example.com/file")).toBeNull();
    expect(normalizeExternalUrl("javascript:alert(1)")).toBeNull();
    expect(normalizeExternalUrl("file:///etc/passwd")).toBeNull();
    expect(normalizeExternalUrl("/relative/path")).toBeNull();
    expect(normalizeExternalUrl("example.com")).toBeNull();
    expect(normalizeExternalUrl("https://user:secret@example.com/")).toBeNull();
  });
});

describe("openExternalUrl", () => {
  const openSpy = vi.fn();

  beforeEach(() => {
    openSpy.mockReset();
    openSpy.mockReturnValue({});
    vi.stubGlobal("open", openSpy);
    coreMocks.invoke.mockReset();
    fileDialogMocks.isDesktopShell.mockReturnValue(false);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("浏览器环境用新窗口打开合法的外部链接", async () => {
    await expect(openExternalUrl("https://example.com/")).resolves.toBe(true);
    expect(openSpy).toHaveBeenCalledWith("https://example.com/", "_blank", "noopener,noreferrer");
    expect(coreMocks.invoke).not.toHaveBeenCalled();
  });

  it("拒绝非法链接时不打开窗口", async () => {
    await expect(openExternalUrl("javascript:alert(1)")).resolves.toBe(false);
    expect(openSpy).not.toHaveBeenCalled();
    expect(coreMocks.invoke).not.toHaveBeenCalled();
  });

  it("弹窗被浏览器拦截时返回 false", async () => {
    openSpy.mockReturnValue(null);
    await expect(openExternalUrl("https://example.com/")).resolves.toBe(false);
    expect(openSpy).toHaveBeenCalledTimes(1);
  });

  it("桌面壳把链接交给系统浏览器", async () => {
    fileDialogMocks.isDesktopShell.mockReturnValue(true);
    coreMocks.invoke.mockResolvedValue("https://example.com/");

    await expect(openExternalUrl(" https://example.com/ ")).resolves.toBe(true);
    expect(coreMocks.invoke).toHaveBeenCalledWith("open_external_url", {
      url: "https://example.com/",
    });
    expect(openSpy).not.toHaveBeenCalled();
  });
});

describe("openDataDirectory", () => {
  beforeEach(() => {
    coreMocks.invoke.mockReset();
    fileDialogMocks.isDesktopShell.mockReturnValue(false);
  });

  it("浏览器环境返回 null 且不调用桌面命令", async () => {
    await expect(openDataDirectory()).resolves.toBeNull();
    expect(coreMocks.invoke).not.toHaveBeenCalled();
  });

  it("桌面壳返回系统数据目录并交给文件管理器", async () => {
    fileDialogMocks.isDesktopShell.mockReturnValue(true);
    coreMocks.invoke.mockResolvedValue("C:\\AppData\\Local\\com.severuszh.fm27lab");

    await expect(openDataDirectory()).resolves.toBe(
      "C:\\AppData\\Local\\com.severuszh.fm27lab",
    );
    expect(coreMocks.invoke).toHaveBeenCalledWith("open_data_dir");
  });

  it("桌面命令失败时向上抛出", async () => {
    fileDialogMocks.isDesktopShell.mockReturnValue(true);
    coreMocks.invoke.mockRejectedValue(new Error("数据目录不可用"));

    await expect(openDataDirectory()).rejects.toThrow("数据目录不可用");
  });
});
