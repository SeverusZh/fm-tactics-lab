import { Fragment } from "react";
import { Link } from "react-router-dom";

import { Panel } from "../components/Panel";

const STEPS = [
  "在存档战术库导入 .fm 存档，查看球队名单并把阵容同步为草案。",
  "在战术板编辑双阶段阵型与球队指令，保存草案；也可以导入 FMF 战术文件。",
  "在实验页选择草案与对手提交批次，启动后在实验结果页查看汇总与逐场记录。",
];

const PAGES = [
  { name: "战术板", purpose: "新建与编辑双阶段阵型、球队指令与球员属性，保存为草案。" },
  { name: "球员属性", purpose: "编辑草案球员的单项属性，或按位置批量调整与撤销。" },
  {
    name: "存档战术库",
    purpose: "导入 FM 存档、查看球队名单、同步阵容与导入 FMF 战术文件。",
  },
  { name: "实验", purpose: "选择草案与固定对手或客队战术池，提交并启动批次。" },
  { name: "实验结果", purpose: "查看批次汇总、指标、配对差值与逐场比分。" },
  { name: "任务管理", purpose: "查看任务状态与进度，取消或删除任务。" },
  { name: "设置", purpose: "配置引擎目录与游戏目录、诊断兼容性，并管理高级设置。" },
  { name: "帮助", purpose: "查看上手步骤、能力边界与常见问题。" },
];

const WITHOUT_ENGINE = [
  "导入 .fm 存档：查看俱乐部、球员名单与球队阵容。",
  "阵容同步：把存档阵容写入草案球队。",
  "战术板草案：编辑阵型、指令与球员属性并保存。",
  "任务与实验结果：查看状态、汇总与逐场记录。",
];

const WITH_ENGINE = [
  "导入真实 FMF 战术文件：由游戏自身的序列化器解析归档内容。",
  "运行模拟比赛与批量实验：需要可用的 FM27 宿主与游戏目录。",
  "引擎诊断：校验宿主与游戏版本是否匹配。",
];

const FAQ = [
  {
    question: "FMF 导入失败",
    answer:
      "确认路径存在且文件可读。真实 FMF 文件需要先在设置页配置引擎目录与游戏目录，并保证宿主与游戏版本匹配。",
  },
  {
    question: "存档导入失败",
    answer:
      "确认选择的是 .fm 文件且 sidecar 已连接；提示存档重复时，在导入表单勾选覆盖已存在的存档后重试。",
  },
  {
    question: "引擎未配置",
    answer:
      "提交带草案的实验会在校验阶段返回“引擎目录未配置，无法生成比赛配置”，启动任务返回引擎不可用。先在设置页配置引擎目录与游戏目录并保存，按提示重启 sidecar 后重试。",
  },
];

export function HelpPage() {
  return (
    <div className="page-grid">
      <Panel title="帮助" className="span-12">
        <section className="help-section" aria-label="三步上手">
          <h3>三步上手</h3>
          <ol>
            {STEPS.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </section>
        <section className="help-section" aria-label="页面用途">
          <h3>页面用途</h3>
          <dl className="settings-list">
            {PAGES.map((page) => (
              <Fragment key={page.name}>
                <dt>{page.name}</dt>
                <dd>{page.purpose}</dd>
              </Fragment>
            ))}
          </dl>
        </section>
        <section className="help-section" aria-label="能力边界">
          <h3>能力边界</h3>
          <h4>无需游戏与引擎</h4>
          <ul data-testid="help-without-engine">
            {WITHOUT_ENGINE.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <h4>需要配置游戏与引擎</h4>
          <ul data-testid="help-with-engine">
            {WITH_ENGINE.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
        <section className="help-section" aria-label="配置游戏与引擎">
          <h3>配置游戏与引擎</h3>
          <p>
            引擎目录是包含 fm27_native 与 fm27_research 的工作区，游戏目录是 FM27
            安装目录。在设置页填写两个路径后保存，按提示重启 sidecar 生效；也可以给
            sidecar 传 --engine-root 与 --game-root。诊断会校验宿主与游戏版本是否匹配。
          </p>
        </section>
        <section className="help-section" aria-label="常见问题">
          <h3>常见问题</h3>
          <dl className="settings-list">
            {FAQ.map((item) => (
              <Fragment key={item.question}>
                <dt>{item.question}</dt>
                <dd>{item.answer}</dd>
              </Fragment>
            ))}
          </dl>
        </section>
        <nav className="help-links" aria-label="页面跳转">
          <Link className="button" to="/tactics">
            前往战术板
          </Link>
          <Link className="button" to="/library">
            前往存档战术库
          </Link>
          <Link className="button" to="/experiments">
            前往实验
          </Link>
          <Link className="button" to="/settings">
            前往设置
          </Link>
        </nav>
      </Panel>
    </div>
  );
}
