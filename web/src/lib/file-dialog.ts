import { isTauri } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";

export type LocalFileFilter = { name: string; extensions: string[] };

export type LocalFileDialogOptions = { title: string; filters: LocalFileFilter[] };

export type LocalDirectoryDialogOptions = { title?: string; defaultPath?: string };

export function isDesktopShell(): boolean {
  if (isTauri()) return true;
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function chooseLocalFile(options: LocalFileDialogOptions): Promise<string | null> {
  if (!isDesktopShell()) return null;
  const selected: string | string[] | null = await open({
    multiple: false,
    directory: false,
    title: options.title,
    filters: options.filters,
  });
  return typeof selected === "string" ? selected : null;
}

export async function chooseLocalDirectory(
  options: LocalDirectoryDialogOptions = {},
): Promise<string | null> {
  if (!isDesktopShell()) return null;
  const selected: string | string[] | null = await open({
    directory: true,
    multiple: false,
    ...(options.title === undefined ? {} : { title: options.title }),
    ...(options.defaultPath === undefined ? {} : { defaultPath: options.defaultPath }),
  });
  return typeof selected === "string" ? selected : null;
}
