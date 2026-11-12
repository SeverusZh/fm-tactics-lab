import { useQuery } from "@tanstack/react-query";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { AppContext } from "./app-context";
import { Rail } from "./components/Rail";
import { RunBar } from "./components/RunBar";
import { TopBar } from "./components/TopBar";
import { apiJson, type Health } from "./lib/api";
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
  const connectionError =
    connection.error instanceof Error
      ? connection.error.message
      : health.error instanceof Error
        ? health.error.message
        : null;
  const refresh = () => {
    void connection.refetch();
    void health.refetch();
  };

  return (
    <AppContext.Provider
      value={{
        connection: connection.data ?? null,
        health: health.data ?? null,
        connectionError,
        refresh,
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
