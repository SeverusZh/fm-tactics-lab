import {
  Archive,
  ChartBar,
  Flask,
  GearSix,
  ListChecks,
  SquaresFour,
  UsersThree,
} from "@phosphor-icons/react";
import { NavLink } from "react-router-dom";

import { useAppContext } from "../app-context";

const links = [
  { to: "/tactics", label: "战术板", icon: SquaresFour },
  { to: "/players", label: "球员属性", icon: UsersThree },
  { to: "/library", label: "存档战术库", icon: Archive },
  { to: "/experiments", label: "实验", icon: Flask },
  { to: "/results", label: "实验结果", icon: ChartBar },
  { to: "/jobs", label: "任务管理", icon: ListChecks },
  { to: "/settings", label: "设置", icon: GearSix },
];

export function Rail() {
  const { health, connectionError } = useAppContext();
  const connected = health?.status === "ok";
  return (
    <aside className="rail">
      <div className="brand">
        <strong>
          FM<span>27</span>
        </strong>
        <small>战术实验室</small>
      </div>
      <nav aria-label="主导航">
        {links.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) => `rail-link${isActive ? " active" : ""}`}
            aria-label={label}
          >
            <Icon size={18} weight="regular" aria-hidden="true" />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="rail-footer">
        <span>{connected ? "sidecar 已连接" : connectionError ? "sidecar 未连接" : "正在连接 sidecar"}</span>
        <span>{health ? health.api : "fm27lab/v2"}</span>
      </div>
    </aside>
  );
}
