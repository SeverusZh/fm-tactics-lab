import { invoke } from "@tauri-apps/api/core";

import { isDesktopShell } from "./file-dialog";

const EXTERNAL_PROTOCOLS = new Set(["http:", "https:"]);

export function normalizeExternalUrl(raw: string): string | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return null;
  }
  if (!EXTERNAL_PROTOCOLS.has(parsed.protocol)) return null;
  if (parsed.username !== "" || parsed.password !== "") return null;
  return parsed.toString();
}

export async function openExternalUrl(raw: string): Promise<boolean> {
  const target = normalizeExternalUrl(raw);
  if (target === null) return false;
  if (isDesktopShell()) {
    await invoke("open_external_url", { url: target });
    return true;
  }
  if (typeof window === "undefined" || typeof window.open !== "function") return false;
  const opened = window.open(target, "_blank", "noopener,noreferrer");
  return opened !== null;
}

export async function openDataDirectory(): Promise<string | null> {
  if (!isDesktopShell()) return null;
  const path = await invoke<string>("open_data_dir");
  return typeof path === "string" ? path : null;
}
