# ADR-0015 FM27 27.1.0 运行时布局画像

- 状态：已采纳，真机待验收
- 日期：2026-11-20
- 决策者：仓库维护者

## 背景

FM27 在 2026-11-18 自动更新到 Steam `27.1.0+2505117`（BuildID 26620374）。上游 v1118.1 已为该构建增加静态适配：`native/steam_27_1_rvas.h` 给出 105 个调用点的新 RVA，`native_layout.h` 同时调整 manager 与 player 对象偏移，并新增战术版本 `0x1b010000`、执行采样栈与 FMF 流版本 61。

本仓库的原生宿主编译在 Steam `27.0.1+2503222` 或 Epic `27.0.1+epic` 参考上，通过 ADR-0014 的运行时画像重定位 RVA。该画像只改地址，不改对象偏移；27.1.0 的偏移变化无法由旧画像表达，宿主会在错误偏移上读写。

本 ADR 扩展 ADR-0014，并替代其中“运行时画像只面向 Steam”和“执行实验一律拒绝运行时画像”两条限制。

## 决策

1. 运行时画像增加布局字段：`layout_steam_27_1`、`layout_manager`、`layout_player_input`、`layout_player_runtime`、`layout_player_statistics`、`layout_tactic_version`、`layout_execution_sample_stack`。未激活画像时全部取参考布局的零偏移。
2. 宿主保持单二进制，编译参考仍为 2503222 Steam 或 27.0.1 Epic。27.1.0 Steam 与 Epic 各有一份静态画像，`reference` 分别绑定编译期参考 id，`image` 绑定安装 DLL 的 SHA-256。
3. `known_image` 按安装镜像选择：画像镜像匹配且 reference 匹配时激活；镜像不匹配时记录 `adapter_profile_fallback` 并回退到编译期静态契约，因此同一工作区的 27.1 画像不会破坏 27.0.1 安装；镜像匹配但 reference 不匹配时 fail-closed。
4. 激活顺序：激活画像优先使用画像 `activation` 字；无激活画像时优先使用 `WaitForActivation` 导出，导出缺失才使用编译期 flag；激活画像没有 `activation` 字且无导出时 fail-closed，避免把参考构建的激活字用于 27.1.0。这样 27.1.0 与上游使用同一激活字，2503222 保持既有导出路径。
5. 画像由 `scripts/static_profile.py` 从公开的 `steam_27_1_rvas.h` 与两份元数据 JSON 生成；`scripts/build_native.py` 把对应平台的画像复制为引擎工作区的 `adapter_profile.txt`，`engine_import` 将其作为可选文件保留。画像只含 RVA、布局与哈希，不含游戏字节。
6. 不移植上游 v1118.1 的 match importance 与 Xbox Game Pass 诊断：v2 不发送对应场景记录，也不支持 XGP。
7. Steam 27.1.0 的战术执行力实验沿用上游已验证的 `d12202dd` 镜像守卫；Epic 27.1.0 的完赛尚未由上游确认，宿主以 `epic_27_1_execution_unverified` 拒绝其实验执行。

## 后果

- 27.1.0 无需为每个玩家重编宿主；画像与安装镜像哈希绑定，换 DLL 后旧画像失效。
- 2503222 与 27.0.1 Epic 的行为保持不变；27.1 画像作为可选文件存在时，镜像不匹配会安全回退。
- 27.1.0 的自定义定位球、FMF 流版本 61 与战术版本 `0x1b010000` 已接入宿主；是否覆盖玩家全部 27.1 存档布局仍需真实存档验证。
- 尚未完成的验证：MSVC 编译、`--check-image`/`--probe-engine`、真实单场、A/B、27.1.0 存档导入、Epic 27.1.0 完赛。上游的 Steam 完赛证据来自 v1 宿主，不能替代本仓库 v2 宿主与 sidecar 的端到端验收。
- 上游 v1118.1 的完整匹配与 XGP 功能不在本轮范围；如后续需要，另开切片。

## 备选

- 为 27.1.0 单独构建第二个宿主二进制：实现直接，但引入宿主选择、双份打包与两套发布验收，否决。
- 直接把 `native_layout` 保持为编译期常量并只在 27.1 构建启用：无法在同一工作区保留 2503222 支持，否决。
- 继续使用自适应画像补齐 27.1 锚点：已有试验显示补齐锚点仍会触发保护层单步异常，且布局偏移缺失，否决。

## 修订 2026-11-25 Steam 27.1.1

FM27 于 2026-11-25 更新到 Steam `27.1.1+2511875`。上游 v1125 的适配显示该构建的对象布局与 27.1.0 相同，只有镜像哈希、激活字与 RVA 目标地址不同，因此沿用本 ADR 的运行时画像路线，不新增宿主二进制，也不改编译期参考。

1. 新增 `native/steam_27_1_1_rvas.h` 与 `native/steam_27_1_1_profile.json`，`scripts/static_profile.py` 生成第三份静态画像；`scripts/build_native.py` 通过 `--profile` 选择 steam_27_1、steam_27_1_1 或 epic_27_1，默认行为不变。
2. 画像 reference 仍绑定编译期参考 `fm27_desktop_8c6971ce_adapter_v1`，image 绑定 `4781439443ab…`，activation 取上游 `activation_flag_rva`（`0x17845538`）；布局字段与 27.1.0 相同。
3. 存档侧 27.1.* 共用同一俱乐部财务尾部，27.1.1 只有战术签名第三字节不同，由 fmsave 的未知签名诊断处理；`fm27lab/adapters/save_fmsave/builds.py` 把 27.1.0 的 game_db 条目注册到 `27.1.1+2511875`，不压制 unknown build 警告。
4. 验证边界：本机无 Windows 与真实 27.1.1 镜像，`--check-image`、`--probe-engine`、真实单场与 27.1.1 存档导入仍未执行。
