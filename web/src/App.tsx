import { useQuery, useQueryClient } from "@tanstack/react-query";
import { invoke, isTauri } from "@tauri-apps/api/core";
import type { UnlistenFn } from "@tauri-apps/api/event";
import { listen } from "@tauri-apps/api/event";
import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { AppContext } from "./app-context";
import { Rail } from "./components/Rail";
import { RunBar } from "./components/RunBar";
import { TopBar } from "./components/TopBar";
import { apiJson, type Health } from "./lib/api";
import type { Connection } from "./lib/connection";
import { loadConnection } from "./lib/connection";
import { LibraryPage } from "./pages/LibraryPage";
import { PlayersPage } from "./pages/PlayersPage";
import { ResultsPage } from "./pages/ResultsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TacticsPage } from "./pages/TacticsPage";

const titles: Record<string, string> = {
  "/tactics": "战术板",
  "/players": "球员属性",
  "/library": "存档战术库",
  "/results": "实验结果",
  "/settings": "设置",
};

function titleFor(pathname: string): string {
  return titles[pathname] ?? "战术板";
}

export function App() {
  const location = useLocation();
  const queryClient = useQueryClient();
  const [lifecycleError, setLifecycleError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const connection = useQuery({
    queryKey: ["connection"],
    queryFn: loadConnection,
    staleTime: Infinity,
    retry: 1,
  });
  const health = useQuery({
    queryKey: ["health", connection.data?.url],
    queryFn: () => apiJson<Health>(connection.data!, "/api/health"),
    enabled: connection.data != null,
    retry: 1,
  });

  useEffect(() => {
    if (!isTauri()) return;
    let disposed = false;
    const unlisteners: UnlistenFn[] = [];
    const subscribe = async () => {
      const ready = await listen<Connection>("sidecar-ready", (event) => {
        setLifecycleError(null);
        queryClient.setQueryData(["connection"], event.payload);
        void queryClient.invalidateQueries({ queryKey: ["health"] });
      });
      if (disposed) ready();
      else unlisteners.push(ready);
      const degraded = await listen<string>("sidecar-down", (event) => {
        setLifecycleError(String(event.payload));
        queryClient.setQueryData(["connection"], null);
        queryClient.removeQueries({ queryKey: ["health"] });
      });
      if (disposed) degraded();
      else unlisteners.push(degraded);
      const failed = await listen<string>("sidecar-error", (event) => {
        setLifecycleError(String(event.payload));
        queryClient.setQueryData(["connection"], null);
        queryClient.removeQueries({ queryKey: ["health"] });
      });
      if (disposed) failed();
      else unlisteners.push(failed);
      const stopped = await listen<string>("sidecar-failed", (event) => {
        setLifecycleError(String(event.payload));
        queryClient.setQueryData(["connection"], null);
        queryClient.removeQueries({ queryKey: ["health"] });
      });
      if (disposed) stopped();
      else unlisteners.push(stopped);
    };
    void subscribe();
    return () => {
      disposed = true;
      for (const unlisten of unlisteners) unlisten();
    };
  }, [queryClient]);

  const connectionError =
    lifecycleError ??
    (connection.error instanceof Error
      ? connection.error.message
      : health.error instanceof Error
        ? health.error.message
        : null);
  const refresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    try {
      if (connection.data == null && isTauri()) {
        await invoke("restart_sidecar");
      }
      await queryClient.invalidateQueries({ queryKey: ["connection"] });
      await queryClient.invalidateQueries({ queryKey: ["health"] });
    } catch (error) {
      setLifecycleError(String(error));
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <AppContext.Provider
      value={{
        connection: connection.data ?? null,
        health: health.data ?? null,
        connectionError,
        refreshing,
        refresh: () => {
          void refresh();
        },
      }}
    >
      <div className="app-shell">
        <Rail />
        <div className="app-main">
          <TopBar title={titleFor(location.pathname)} />
          {connectionError ? (
            <div role="alert" className="connection-error">
              {connectionError}
            </div>
          ) : null}
          <main className="workspace">
            <Routes>
              <Route path="/" element={<Navigate to="/tactics" replace />} />
              <Route path="/tactics" element={<TacticsPage />} />
              <Route path="/players" element={<PlayersPage />} />
              <Route path="/library" element={<LibraryPage />} />
              <Route path="/results" element={<ResultsPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="*" element={<Navigate to="/tactics" replace />} />
            </Routes>
          </main>
          <RunBar />
        </div>
      </div>
    </AppContext.Provider>
  );
}
