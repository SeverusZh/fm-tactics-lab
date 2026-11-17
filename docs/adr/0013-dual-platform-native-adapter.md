# ADR-0013 双平台原生适配器与公开画像元数据

## 状态

已采纳 · 2026-11-17

## 背景

FM27 同时通过 Steam 与 Epic Games Store 发行，两个发行版的 `game_plugin.dll` 不同：Steam 热修构建为 `27.0.1+2503222`（`8c6971ce…`），Epic 构建为 `27.0.1+epic`（`ebf6fcf5…`）。原生宿主必须与本机 DLL 的代码布局精确匹配才能安全加载比赛；安装包又不能分发宿主二进制或游戏资源。此前仓库只维护一个参考构建画像（`27.0.1+2494687`），玩家只能用与本人游戏版本一致的自备 DLL 重新生成本地画像，Epic 玩家没有可用路径。

## 决策

1. 仓库同时维护两套适配器声明：`native/adapter_version.json`（Steam 27.0.1+2503222）与 `native/epic_adapter_version.json`（Epic 27.0.1+epic）。参考构建随上游 FM27 热修更新为 2503222。
2. 画像元数据以不可逆摘要公开：`native/profile_metadata.json` 与 `native/epic_profile_metadata.json` 的 ranges 只含 `rva`、`size` 与 `sha256`。原始游戏字节只在本机构建时由 `scripts/generate_profile.py` 从玩家自备 DLL 恢复或校验，不写入仓库或安装包；本机诊断日志可能记录定位片段，仅保存在本机数据目录。
3. 构建脚本以 `--platform steam|epic` 区分产物：Steam 写入 `private/engine`，Epic 写入 `private/epic-engine`；Epic 宿主按 `FM27_COMPAT_DIGEST_RANGES` 做摘要校验，激活地址取自画像的 `activation_flag_rva`，缺失时由 `--find-activation` 在本机 DLL 上定位。
4. 兼容门禁仍以运行时镜像指纹协商，不依赖静态版本号；镜像或关键 range 摘要不符时 fail-closed，绝不降级加载。
5. `scripts/rebase_profile.py` 负责从新 DLL 重建画像元数据；发布源码清单只包含摘要形式的画像文件。

## 后果

- 安装包保持不含宿主与游戏字节；玩家用与自身发行版匹配的 DLL 运行构建脚本得到宿主，并通过 engine_root 接入。
- Steam 适配已完成真机单场与并发批次验证；Epic 适配完成代码、静态契约与构建前置校验，运行时验收需具备 Epic 版游戏资产的机器，文档必须如实标注该边界。
- 执行力实验只对 Steam `8c6971ce…` 构建开放：宿主执行回执以该镜像 sha 守卫，Epic 构建提交该实验时以退出码 244 拒绝，界面与预检应按镜像 sha 拒绝而不是宣称对等。
- 摘要校验比逐字节比较更难被偶然差异绕过，但同摘要不同代码的碰撞不在威胁模型内；继续 fail-closed。
- 旧 2494687 参考构建不再维护；使用旧构建的玩家需按本机 DLL 重新生成画像。

## 备选方案

- 只维护 Steam 参考构建并依赖运行时指纹协商：实现最小，但 Epic 玩家无法使用原生能力，也无法验证 Epic 布局。
- 在仓库或安装包内公开完整画像字节：违反游戏资源许可与不分发约束，否决。
- 按静态版本号选择画像：无法覆盖同一版本号的运行时差异，与现有指纹协商方向冲突，否决。

## 相关

- [ADR-0004](0004-native-concurrency.md)：原生 counted-session 与并行调度。
- [ADR-0001](0001-tauri2-shell-python-sidecar.md)：桌面壳与 sidecar 边界。
- 上游参考：`lqf0624/fm-tactics-lab` v1113、v1113.1 与 PR #13。
