import { WarningCircle } from "@phosphor-icons/react";

import { useAppContext } from "../app-context";

export function TopBar({ title }: { title: string }) {
  const { connection, health, connectionError, refresh } = useAppContext();
  const tone = health?.status === "ok" ? "ok" : connectionError ? "error" : "warn";
  const label = health?.status === "ok" ? "sidecar 正常" : connectionError ? "sidecar 未连接" : "正在连接";
  return (
    <header className="topbar">
      <h1>{title}</h1>
      <div className="topbar-status">
        <span className="badge" data-tone={tone}>
          {tone === "error" ? <WarningCircle size={14} aria-hidden="true" /> : null}
          {label}
        </span>
        {health ? (
          <>
            <span className="badge">{health.database === "ready" ? "SQLite 就绪" : "SQLite 不可用"}</span>
            <span className="badge">v{health.version}</span>
          </>
        ) : null}
        <button className="button" type="button" onClick={refresh} disabled={!connection}>
          重新检查
        </button>
      </div>
    </header>
  );
}
