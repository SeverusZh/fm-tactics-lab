import { useState } from "react";

import { useAppContext } from "../app-context";

export function RunBar() {
  const { health } = useAppContext();
  const [seed, setSeed] = useState("42");
  const [count, setCount] = useState("100");
  const [workers, setWorkers] = useState("4");
  const [allowOversubscription, setAllowOversubscription] = useState(false);
  const ready = health?.status === "ok";
  return (
    <footer className="runbar" aria-label="运行设置">
      <div>
        <strong>{ready ? "准备就绪" : "等待 sidecar"}</strong>
        <div className="field" style={{ marginTop: 4 }}>
          开赛前会经过原生回读校验
        </div>
      </div>
      <div className="runbar-fields">
        <label className="field">
          起始种子
          <input
            type="number"
            inputMode="numeric"
            min={0}
            max={4294967295}
            value={seed}
            onChange={(event) => setSeed(event.target.value)}
          />
        </label>
        <label className="field">
          每方案场数
          <input
            type="number"
            inputMode="numeric"
            min={1}
            max={10000}
            value={count}
            onChange={(event) => setCount(event.target.value)}
          />
        </label>
        <label className="field">
          并行数
          <input
            type="number"
            inputMode="numeric"
            min={1}
            max={256}
            value={workers}
            onChange={(event) => setWorkers(event.target.value)}
            title="1–256 路；硬件只决定推荐值"
          />
        </label>
        <label className="field-inline" title="可用内存或磁盘不足时仍提交">
          <input
            type="checkbox"
            checked={allowOversubscription}
            onChange={(event) => setAllowOversubscription(event.target.checked)}
          />
          允许资源覆盖
        </label>
        {Number(workers) > 8 ? (
          <span className="badge" data-tone="warn">
            高于 8 路未实测
          </span>
        ) : null}
        <button className="button primary" type="button" disabled title="实验接口将在后续阶段接入">
          运行比赛
        </button>
      </div>
    </footer>
  );
}
