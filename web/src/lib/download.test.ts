import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { downloadBlob } from "./download";

const objectUrlMock = vi.fn(() => "blob:fmf");
const revokeObjectUrlMock = vi.fn();
let clickSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.useFakeTimers();
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: objectUrlMock });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectUrlMock });
  clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});

afterEach(() => {
  vi.useRealTimers();
  objectUrlMock.mockClear();
  revokeObjectUrlMock.mockClear();
  clickSpy.mockRestore();
});

describe("downloadBlob", () => {
  it("下载文件并在稍后释放对象地址", () => {
    const blob = new Blob(["fmf"], { type: "application/octet-stream" });
    downloadBlob(blob, "direct.fmf");

    expect(objectUrlMock).toHaveBeenCalledTimes(1);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    const anchor = clickSpy.mock.contexts[0] as HTMLAnchorElement;
    expect(anchor.download).toBe("direct.fmf");
    expect(anchor.href).toContain("blob:fmf");
    expect(revokeObjectUrlMock).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1000);
    expect(revokeObjectUrlMock).toHaveBeenCalledWith("blob:fmf");
  });
});
