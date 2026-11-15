import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";

import { chromium } from "@playwright/test";

const INSTALL_HINT = "请执行 pnpm exec playwright install --with-deps chromium";

let cached: string | null | undefined;

/**
 * 返回浏览器不可用的原因；可用时返回 null。
 * 结果缓存，避免同一进程内重复探测。
 */
export function browserBlocker(): string | null {
  if (cached === undefined) {
    cached = detectBlocker();
  }
  return cached;
}

function detectBlocker(): string | null {
  let executable = "";
  try {
    executable = chromium.executablePath();
  } catch {
    return `无法定位 Playwright 的 chromium：${INSTALL_HINT}`;
  }
  if (executable === "" || !existsSync(executable)) {
    return `未安装 Playwright 的 chromium：${INSTALL_HINT}`;
  }

  const missing = missingLinuxLibraries(executable);
  if (missing !== null && missing.length > 0) {
    return `chromium 缺少系统库：${missing.join("、")}；${INSTALL_HINT}`;
  }
  return null;
}

function missingLinuxLibraries(executable: string): string[] | null {
  if (process.platform !== "linux") {
    return null;
  }
  let output = "";
  try {
    output = execFileSync("ldd", [executable], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
  } catch {
    // ldd 不可用时不做推断，让用例真实执行并从 Playwright 的错误中获得原因
    return null;
  }
  const missing: string[] = [];
  for (const line of output.split("\n")) {
    const match = /^\s*(\S+)\s+=>\s+not found/.exec(line);
    if (match !== null) {
      missing.push(match[1]);
    }
  }
  return missing;
}
