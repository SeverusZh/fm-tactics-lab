# Changelog

## 未发布

- 新增存档战术页面：识别存档后按当前联赛浏览除玩家以外的教练偏好预设战术，可导出到本机文件夹或一键导入客队战术池。
- 客队战术池改为侧边栏独立页面，支持导入本机 FMF 或从存档页面导入联赛对手预设；底栏快速模式旁新增随机模式开关，按权重逐场抽取客队战术。
- 统一客队球员属性只统一能力属性，首发按抽中战术的对应位置获得最高位置熟练度，避免此前整队位置熟练度统一为 15 后明显变弱。
- 修复赛季结束后读取存档时无法识别当前联赛、导致存档战术页面提示教练偏好读取失败的问题。

## v1108.5 — 2026-11-08

- Import career saves, edit match squads and run home and away matches against selectable same-league opponents.
- Preview both tactical phases using presets matched to the head coach's saved preferences.
- Preserve position settings when swapping players, correct Chinese transition labels and add experiment management.
- Add optional manual tactical effectiveness settings for both sides.

## v1106 — 2026-11-06

- Add actual interface screenshots to both player guides.
- Serve `engine-settings.js` from the static route allowlist so engine diagnostics and manual path selection initialize correctly. The v1103.2 release is retained. New desktop builds display v1106 and self-test the engine settings endpoint.

## v1103.2 — Public release

- Publish FM Tactics Lab under MIT with Chinese and English player documentation.
- Release the original `FM27战术推演_v1103.2.exe`, unchanged.
- Publish the corresponding desktop application payload and native adapter sources.
- Include double-phase tactics, player input editing, set pieces, batch comparison, original match statistics and full/quick collection modes.
- Include graded engine compatibility and manual game-path selection.
- Keep career-save versus modules in later development versions.
- Add standalone source preparation, build and export scripts. Local initial inputs can be read from the verified release EXE.
