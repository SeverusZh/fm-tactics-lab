import { useState } from "react";

import { useAppContext } from "../app-context";

function integerInRange(value: string, minimum: number, maximum: number): boolean {
  const number = Number(value);
  return Number.isInteger(number) && number >= minimum && number <= maximum;
}

export function RunBar() {
  const { health } = useAppContext();
  const [seed, setSeed] = useState("42");
  const [count, setCount] = useState("100");
  const [workers, setWorkers] = useState("4");
  const [allowOversubscription, setAllowOversubscription] = useState(false);
  const ready = health?.status === "ok";
  const seedValid = integerInRange(seed, 0, 4294967295);
  const countValid = integerInRange(count, 1, 10000);
  const workersValid = integerInRange(workers, 1, 256);
  const invalid = !seedValid || !countValid || !workersValid;
  const reason = !ready
    ? "sidecar 尚未就绪"
    : !seedValid
      ? "起始种子需为 0–4294967295 的整数"
      : !countValid
        ? "场数需为 1–10000 的整数"
        : !workersValid
          ? "并行数需为 1–256 的整数"
          : "实验提交尚未接入";
  return (
    <footer className="runbar" aria-label="运行设置">
      <div>
        <strong>{ready ? "准备就绪" : "等待 sidecar"}</strong>
        <div className="field" style={{ marginTop: 4 }}>
          当前壳层尚未接入运行提交
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
            aria-invalid={!seedValid}
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
            aria-invalid={!countValid}
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
            aria-invalid={!workersValid}
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
        {Number(workers) > 8 ? <span className="badge" data-tone="warn">高于 8 路未实测</span> : null}
        <span className="field" role="status" aria-live="polite">
          {invalid ? reason : allowOversubscription ? "资源覆盖已允许" : "资源预检按默认值"}
        </span>
        <button className="button primary" type="button" disabled title={reason}>
          运行比赛
        </button>
      </div>
    </footer>
  );
}
