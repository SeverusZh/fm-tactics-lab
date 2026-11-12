> 历史发布说明，不适用于 v2。v2 已删除存档对战，存档入口只保留存档战术库。

# FM Tactics Lab v1108.5

## 与 v1103.2 的区别

- **存档对战**。导入 FM27 的 `.fm` 存档，读取己方战术、一线队名单和球员属性。可调整首发和替补，再选择同联赛球队进行主客场原生模拟。
- **对手战术预览**。按对手主帅在存档中的风格和阵型偏好匹配原装预设，在有球和无球战术板上查看角色、个人指令与球员属性。缺少可核实主帅或战术偏好的球队暂不可选。
- **按需加载**。首次导入优先读取己方数据，对手名单按需批量读取。开赛准备在后台运行，可查看进度和取消。
- **换位和战术导入修复**。拖动两名球员换位时，角色、职责和个人指令留在原位置。拖到空位如需调整设置，会先提示确认。修正“保持队形”和“立刻反击”的中文标签，保留导入战术里由角色锁定的指令。
- **实验管理**。支持命名、搜索、重命名和删除历史实验。
- **战术执行力实验**。可为双方分别设置 0–100，默认关闭。存档里的实际执行力尚未接入。

下载 `FM27-Tactics-Lab-v1108.5.exe`，从托盘彻底退出旧版后双击运行。需要兼容的本机 FM27 安装，模拟时可关闭游戏。EXE 自带 Python。可用 `SHA256SUMS.txt` 校验下载文件。

Windows 包启动自检通过。曼联档对热刺的主客场原生模拟均已完成，换位后两个阶段的位置、角色、职责和个人指令均与战术板一致。

## English

Compared with v1103.2, this desktop release adds career-save import, editable match squads, same-league opponents, and tactical previews for both possession phases. Opponent tactics use the coach's saved preferences to select a built-in preset. Preparation runs in the background and can be cancelled.

Swapping two players keeps roles, duties, and instructions attached to their positions. The update also fixes Chinese transition labels, adds experiment management, and provides an optional manual tactical effectiveness setting. The latter is disabled by default and does not read effectiveness values from the save.

Download `FM27-Tactics-Lab-v1108.5.exe`. Exit the previous app from its tray icon before launching. A compatible local FM27 installation is required. Python is bundled. Use `SHA256SUMS.txt` to verify the download.
