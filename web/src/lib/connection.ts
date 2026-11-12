import { invoke, isTauri } from "@tauri-apps/api/core";

export type Connection = {
  url: string;
  token: string;
  api: string;
};

export async function loadConnection(): Promise<Connection> {
  if (isTauri()) {
    return invoke<Connection>("get_connection");
  }
  return {
    url: import.meta.env.VITE_API_URL ?? "http://127.0.0.1:18765",
    token: import.meta.env.VITE_API_TOKEN ?? "",
    api: "fm27lab/v2",
  };
}
