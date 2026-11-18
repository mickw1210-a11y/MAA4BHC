# ASUS 一次性接续 Prompt

使用方法：在 ASUS 的 Codex 中打开用户指定的既有 MAA4BHC 项目，复制下列内容作为一次性接续指令。本文随 Git 同步，使用后无需反复执行，也不要擅自删除。

---

请接续 MAA for BHC 的 v0.4 开发。当前设备是 ASUS 原生 Windows，目标为 Windows＋MuMu12 x86_64；Mac 的 CrossOver 仅是历史兼容性测试，不需要安装、迁移或继续排障。

**先核对现场**

- 在用户指定的既有项目根目录工作，不凭名称新建副本。先读根目录 `AGENTS.md`、`Workspace_Handoff.md`、`docs/v04/README.md`、`docs/v04/v04-task-ledger.md` 和 `docs/v04/v04-construction-guidance.md`；本机若有 `.local/README.md` 和 `.local/docs/handoff.md` 也按需读取。
- 确认 Git 仓库、分支、远端和全部本机改动。Mac 交接完成时 GitHub `main` 至少有 `39e5750`，本提示可能属于其后的提交；以实际远端为准。有未提交改动、分支分叉或冲突时先保护现状并核对，不覆盖、不强推。
- Mac 上五款小游戏的安装包和配置提供了规则线索；模拟、无死局与实机均未验收。Mac 离线设备恢复用例通过，不等于目标 Windows 通过。项目无已验证的 `m4b.exe` 发行包。

**文件怎么放**

- GitHub 的源码、测试、公开指导和 `Workspace_Handoff.md` 保持仓库正常位置；已跟踪文件不搬进 `.local`。`Workspace_Handoff.md` 是 Mac 工作记录，不往里面代写 ASUS 工作。
- 移动硬盘既有项目目录中的 `maa4bhc_all/asus-transfer-20261118-145856/` 是 Mac 携带包，盘符依 ASUS 实际情况确认；其 `.local/` 是资料来源，`transfer-manifest.json` 是相对 `.local/` 的 SHA-256 清单。该包不通过 Git 同步，可能包含私人资料，不能上传公开仓库。
- 为避免覆盖 ASUS 已有工棚，先将携带包 `.local/` **内部内容**按原相对结构复制到现有项目的 `.local/imports/mac-20261118/`，并将 `transfer-manifest.json` 放在该导入目录中；逐文件校验大小与 SHA-256。导入目标已存在时，先比较内容，冲突项保留双方版本并报告，不覆盖、不删除。复制及校验成功后才使用，不删除硬盘原件。
- 导入后，`imports/mac-20261118/exports/sessions/2026-11-17-18/` 是 11 月 17—18 日项目聊天副本及主题索引；本次 Mac 整理聊天仅有复制时快照。`imports/mac-20261118/data/research/minigames/` 是小游戏安装包、REA 与部分热更证据；`imports/mac-20261118/data/research/inventory-assets-20261118/` 是道具表、图标与研究资料。保留原结构；原素材有缺图和推定关联，详见包内说明。
- `imports/mac-20261118/docs/file-index.md` 和 `README.md` 为 Mac 文件索引，`docs/handoff.md` 为 Mac 详细交接，`history/` 为修改前副本，`logs/` 为 Mac 测试日志。它们只是历史材料，不替换 ASUS 的 `.local/README.md`、本机交接、设备配置或已有历史。Mac 工具环境、CrossOver 和缓存不迁移。
- `.local/` 是设备上的开发工棚，不是正式用户数据目录；ASUS 的角色、库存、截图、连接配置和其他用户数据保持原位置。共享素材和程序功能仍按项目现有目录使用，不直接把研究素材当成已审核发布素材。账号、库存、截图、原始聊天、APK、连接配置和凭据默认本机保存。

**接续工作与边界**

- 安全接收文件后，先核对 ASUS 的 Python、Node、项目依赖及 MuMu 实际状态；需要安装、配置或真实连接时遵循项目规则与当前授权，不擅改模拟器设置。
- 首个关键关口是 `docs/v04/w03-04-windows-revalidation.md`：使用隔离合成数据执行 Windows 双进程、双项目副本与异常退出复验，记录测试、跳过和实际结果。所有对应验收满足之前，不解除 W03-04 或接入 W03-07 设备派发；其他工作按 Guidance 的依赖与授权推进。
- 不自动开始或操作游戏，不消耗资源；不得执行用量重置。真实游戏操作须有当前有效授权、确认设备和页面、资源边界及停止条件。遇到识别不确定或上次结果不明时停止相关操作。
- 按项目规则保留修改前副本、更新实际验证结果。ASUS 需独立记录决策与关键节点，但具体记录文件名及位置仍由用户决定；不要把 Mac 的详细记录当成 ASUS 发生的事实。
- 本提示只用于这次交接，不自动扩大游戏操作、数据迁移或上传权限。接收完成后简要报告文件放置、未解决冲突、Windows 验证结果及下一步。
