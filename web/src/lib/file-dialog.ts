import { open } from "@tauri-apps/plugin-dialog";

export type LocalFileFilter = { name: string; extensions: string[] };

export type LocalFileDialogOptions = { title: string; filters: LocalFileFilter[] };

export function isDesktopShell(): boolean {
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
