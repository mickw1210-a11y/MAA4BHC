# v0.4 施工任务账本

最后更新：2026-11-17（Asia/Shanghai）
主任务清单：[v0.4 construction guidance](v04-construction-guidance.md)
需求追踪：[v0.4 requirements map](v04-requirements-map.md)

## 2026-11-17 Mac 接续入口

- **基线**：Mac 已同步到 `744b34d`。Python 共 426 项，413 通过、9 跳过、4 因 Windows 专用 `msvcrt` 缺失报错。前端 11 项、构建、共同规则检查通过。命令和日志位置见 Mac 的 Workspace_Handoff.md 与本机交接。
- **W03-04 当前状态**：Mac 离线原型与 11 项合成用例已通过；目标 Windows 双进程、双副本复验待执行。清单见[Windows 双副本复验](w03-04-windows-revalidation.md)。在该复验通过前不开放设备派发。
- **独立分支**：W01／W12—W16 的公开取证可继续。优先检查能取得连续动作与状态的线索。五款规则与模拟状态保持各自的证据结论。
- **独立分支**：Windows 环境未在本机，继续按账本推进可独立公开取证的 W01／W12—W16；设备派发及 W04—W10 仍受 W03-04 目标平台验证阻止。

## 2026-11-17 W03-04 Mac 离线恢复原型

- **输入与前置**：读取设备租约、设备调用链、动作结果契约、已有跨副本崩溃复现及 W03-04 验收条件。工作区为 main，接续时干净，Mac 基线提交 dae912d，较 origin/main 领先 1 个已有提交。
- **方案比较**：比较单一、显式配置且位于指定项目副本内的权威目录，与各副本分散记录再按配置互相发现。原型选择单一权威：两个副本读写同一份序列，无需合并；权威缺失、不可读或身份不同即停止。配置缺失不自动初始化，项目外存储和未知目录遍历未使用。
- **实现**：新增 app/device_recovery.py、tests/test_device_recovery.py 和 tests/test_device_recovery_windows.py。状态以同目录临时文件写入、刷新后原子替换，事件带序号与哈希链；配置 authority_id 区分首次 provision 与已初始化权威丢失。持有者记录 PID、进程创建FILETIME和实例摘要；动作记录动作ID、计划ID、前置观察ID及载荷摘要，不记录ADB地址、路径或账号。
- **动作协议**：意图和“可能提交”边界必须分别保存成功后才可调用发送器。写入意图失败或提交边界失败的模拟发送数为0。只有意图的崩溃恢复为 not_submitted，原动作不重放；越过提交边界但无结果则保存 submitted_unknown，重复检查不重发。只有匹配实例、动作ID、时间晚于提交边界的新观察可核实结果，并保留观察ID和证据引用。
- **Mac 验证**：项目 Python 3.12.12；命令 `.local/test-venv/bin/python -W error::DeprecationWarning -m unittest -v tests.test_device_recovery`，11 项通过。扩展命令一并运行 tests.test_device_recovery_windows 与 tests.test_device_lease，合计 19 项，其中 11 通过、8 项 Windows 专属测试按平台条件跳过，退出码 0。完整输出见 .local/logs/w03-04-recovery-offline-20261117.log。系统 python3 是 3.9.6，不能导入项目使用的类型标注；该次启动失败未计入项目验证。
- **目标 Windows 清单**：已新增 docs/v04/w03-04-windows-revalidation.md；要求 19 项通过、0 跳过，涵盖活跃冲突、正常释放、最后句柄关闭、跨副本发现和两个中断边界。Windows 环境不在本机，未执行；不是通过证据。
- **限制与安全边界**：原型未接入设备租约、Bridge、MaaDevice、开发CLI或真实观察器；不验证断电、磁盘损坏或整体回滚到旧的有效权威文件，且哈希链本身不能发现这种整份回滚。故 W03-04 仍是进行中，W03-07及W04—W10保持依赖受阻；没有连接或操作游戏、使用资源、迁移数据或推送。
- **修改前恢复点**：.local/history/w03-04-recovery-prototype-before-20261117/manifest.json 与 .local/history/w03-04-recovery-docs-before-20261117/manifest.json；均只存本轮将改文件的副本／新文件缺失登记与SHA-256。
- **下一项**：先按独立分支继续公开规则取证；目标 Windows 代码可用时运行上述双副本清单。只有退出码0、0跳过且各项行为与预期相符后才解除 W03-04，再由账本选择 W03-07。

## 2026-11-17 换机移交复核

用户已授权审核、提交和推送全部可公开成果。当前状态以[移交概览](README.md)及[验证与同步记录](validation-report.md)为准。下文的提交领先数、未提交标记和本机路径是历次施工快照。

本轮426项Python回归、11项前端测试、构建及两种离线TaskHome冒烟通过。首页与分辨率代码提交17fd375，设备基础提交f67c392，35份共享施工文档及根交接入口提交23ab070。连同原13个本地提交共16个已push，GitHub main与23ab070c305330a787565a70a05b54d8f8f64464一致。后续同步回执的提交状态按最新验证报告和实际Git状态核对。

W00、W02公共契约和W11已列明的通用工具通过离线验证。W03-04保持当前实现缺口，W03-07—12和W04—W10依赖未满足。W11-14—18仍需游戏规则、可重放失败或对应观察器等输入。五款规则取证仍缺关键转移与成本，尚无一款完整模拟。CP-A—CP-E均未验收完成。

设备租约当前接口将诊断根限制在调用方项目树内，尚无跨副本发现和共享持久动作记录。项目内可行替代方案仍可继续研究，项目外存储的必要性尚未证明。

标有`.local/history/`、`runtime/`或私人参考图的历史证据保留在ASUS，本次Git移交包含审核后的文字、源码与测试。

## 移交前接续点（历史快照）

- 当前工作包：W01／W12—W16公开规则取证复查，并核对W03-04崩溃恢复的本机实现边界；本轮未发现新玩法机制，也未修改游戏模拟代码。
- 已完成关口：W00离线通过；W01-01—W01-06、W01-08—W01-12初检通过；W02-01—W02-10离线通过；W03-01—W03-03、W03-05—W03-06离线通过；W11-01—W11-07、W11-09—W11-10、W11-12通用契约离线通过。
- 下一项：本轮追加12组定向公开检索并复开C2／C3／O2页面，未得到新的机制、成本或连续动作证据；当前Edge只显示C5 TapTap静态帖，绑定页面读取超时。W01-07、W12-01、W13-01及W14-01—03、W15-01—03、W16-01—05仍受阻，不建立规则模型。W03-04的项目内日志不能由另一项目副本读取，Windows互斥体也不能在最后句柄关闭后留下可共享的崩溃／未决动作证据；项目外持久化位置未获授权，故不实施。W03-07及W04—W10、W17—W20下游继续关闭。
- 设备授权：本轮授权包括本地阅读、研究、编码和离线检查；不包含未知体力／预算下的真实小游戏消耗。上次本机交接记录游戏停在隐私提示，当前没有可确认的已处理状态；不操作游戏。
- 最新基线：`main` / `52092b5`，领先`origin/main` 13个提交；接管前已有14个跟踪修改、12个未跟踪文件，未暂存；本轮未改代码。项目内未找到`adb.exe`。中文OCR模型文件当前存在且非空，但尚未验证加载成功。

## 2026-11-17 公开来源再查与W03-04恢复边界

- 输入与前置：W01来源取证分支仍可执行；设备派发需W03-04先证明崩溃持有者退出且在途动作状态可核。
- 本次动作：使用公开网页检索查询糖果派对、烤串大师、疯狂汉堡日、星光特调、动物沐场的玩法／操作／视频，并按微博、B站、抖音、小红书检索；复开C2汉堡攻略、C3动物攻略与O2官方B站公告。搜索结果又出现C2／C3／O2和既有C7等内容，没有取得新的状态转移、输入动作、成本或连续操作证据。C3页面文字仍是玩家对两只、三只同级动物合并的描述，未满足当前版本或连续画面验收。
- 浏览器核查：CUA窗口清单显示Edge当前在TapTap C5静态求助帖，in-app browser无标签；绑定Edge现有标签等待30秒超时。没有登录或绕过访问限制，未取得新视频帧。
- W03-04本机边界：`app/device_lease.py`将事件日志限制在各自项目根下；不同项目副本不能读取彼此日志。离线崩溃试验已证明，若最后句柄随持有者退出而关闭，命名互斥体本身不保留可供后续副本读取的未决状态。项目规则要求项目外持久文件先核实必要性并获决定；当前没有共享、持久且获授权的位置，因此W03-04保持受阻，不接入W03-07设备派发。
- 结果：无新规则证据，无代码改动，无设备连接／操作和资源消耗；没有运行代码测试。W12—W16模拟仍未开始；W04—W10及实机任务不越过W03前置。
- 修改前恢复点：`.local/history/v04-evidence-recovery-audit-20261117-before/manifest.json`；本次实际修改的账本、交接、来源索引和本机README均有当前版本副本及SHA-256。
- 当前接续条件：只在取得可公开核验的游戏专属操作／规则证据后推进相应规则卡；W03-04需先具备可由不同项目副本安全读取的持久未决动作证据。其余当前未满足前置的下游任务保持未开始。

## 工作区基线

- 项目根与 Git 根：`<PROJECT_ROOT>`。
- 接管时分支：`main`；当时HEAD：`8168300`（`Add offline inventory persistence experiments and Windows fixes`）；远端基线：`origin/main` / `8b25892`。这是W00历史基线，不代表当前HEAD。
- 接管时已有工作区差异：14 个受跟踪文件修改、6 个未跟踪文件；全部来自本轮接管前的既有工作，保留原样，不计为本轮成果，不暂存、不提交、不推送。完整路径见本文件“既有差异”。
- 生效项目说明：根 `AGENTS.md`。没有活动源码目录中的更深层规则；历史恢复副本目录中的同名文件不适用于当前源码。
- 本机交接中的游戏状态：先前实机授权限于背包无消耗测试；交接记录停在用户需处理的隐私提示。无当前页面新证据，不继续任何设备动作。

## W00 — 现场与基线

| ID | 状态 | 输入／动作 | 结果与证据 |
| --- | --- | --- | --- |
| W00-01 | 离线通过 | 核对工作目录、Git 根与分支 | PowerShell 当前路径与 `git rev-parse --show-toplevel` 均为项目根；当前分支 `main`。 |
| W00-02 | 离线通过 | 搜索有效根／子目录指令 | 根 `AGENTS.md` 适用；源码树中未发现 override 或子目录指令。历史恢复副本下的规则文件不在活动路径内。 |
| W00-03 | 离线通过 | 读取本机交接并恢复授权／停止状态 | 交接确认上次停在隐私提示；本轮不操作游戏，不从旧背包授权推导小游戏消耗许可。 |
| W00-04 | 离线通过 | 记录 Git 状态及接管前差异 | `git status --short --branch` 显示 `main...origin/main [ahead 1]`；14 个 tracked 修改、6 个 untracked 文件。清单见下方。 |
| W00-05 | 离线通过 | 建立本账本并登记真实状态 | 本文件列出 W00 证据、既有差异和首个待办；未开始工作包没有标为完成。 |
| W00-06 | 离线通过 | 核实 Python、Node、依赖、ADB 与 OCR 文件 | Python 3.12.10；`pip check` 退出码 0；Node v22.21.0；npm 10.9.4；`ui/node_modules` 存在且 `npm ls --depth=0` 正常。项目树没有 `adb.exe`、`det.onnx`、`rec.onnx`、`keys.txt`；路径依据 `app/preflight.py` / `app/ocr.py` 为 `assets/ocr/zh_cn/`。不打印本机连接值。 |
| W00-07 | 离线通过 | Python 回归、前端测试、前端构建 | `& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests`：退出码 0，252 项通过；`node --test ui/src/inventorySelection.test.js ui/src/inventoryReview.test.js`：退出码 0，11 项通过；`npm --prefix ui run build`：退出码 0。 |
| W00-08 | 离线通过 | 离线首页及校对窗口冒烟 | `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1 -Offline -SmokeTest -TaskHome`：退出码 0。`runtime/logs/inventory-window-smoke.json` 中 `ok=true`、`taskHomeRoundTrip=true`、`stop_bridge=true`、`maa_controller_imported=false`；固定布局、内部滚动、框选／多选和紧凑窗口检查通过。未连接设备。 |
| W00-09 | 离线通过 | 检查共同规则一致性 | `& .\.venv\Scripts\python.exe scripts/sync_shared_rules.py --check`：退出码 0，规则一致。 |
| W00-10 | 离线通过 | 保存修改前局部恢复点 | `.local/history/v04-w00-w01-baseline-20261116-before/manifest.json`；仅备份修改中的本机说明文件，其 SHA-256 已核对；新账本和映射登记为此前不存在。 |

### 2026-11-17 W00现场复核

以下为同一工作包的最新复核；上表与“既有差异”中的14个 tracked／6个 untracked 是2026-11-16首次接管时的历史快照，不代表当前状态。

| ID | 状态 | 输入／动作 | 结果与证据 |
| --- | --- | --- | --- |
| W00-01 | 离线通过 | 再核对工作目录、Git根与分支 | 当前目录与Git根均为`<PROJECT_ROOT>`；分支`main`，HEAD `52092b5f1cb4f9065c3bb4ce0776a060dee3ed7d`，较`origin/main`领先13个提交。 |
| W00-02 | 离线通过 | 搜索活动AGENTS／override | `rg --files -g AGENTS.md -g AGENTS.override.md`仅发现根`AGENTS.md`；没有活动子目录指令或override。 |
| W00-03 | 离线通过 | 核对授权与设备停止状态 | 最新交接记录的旧游戏页面停在隐私提示；本轮未读取新页面，不操作游戏或模拟器，不将背包旧授权扩大到小游戏。 |
| W00-04 | 离线通过 | 复核Git状态、暂存区和已有差异 | `git status --short --branch`为`main...origin/main [ahead 13]`；14个跟踪文件修改、12个未跟踪文件、无暂存文件，均是本轮开始前已有差异。`git diff --stat`为14个跟踪文件、364 insertions／44 deletions；`git diff --cached --name-only`为空；`git -c core.whitespace=cr-at-eol diff --check`退出码0。 |
| W00-05 | 离线通过 | 更新账本接续点 | 已将当前状态指向W14—W16公开取证；规则缺口和未开始状态未标成完成。 |
| W00-06 | 离线通过 | 复核Python、Node、依赖、ADB及OCR模型 | Python 3.12.10、`pip check`退出码0；Node v22.21.0、npm 10.9.4；`ui/node_modules`及`npm ls --depth=0`正常。项目内搜索未找到`adb.exe`。`assets/ocr/zh_cn/{det.onnx,rec.onnx,keys.txt}`当前存在，大小分别为4,731,945、10,816,419、26,249字节，目录被`.gitignore`忽略；只核对存在及非空，没有宣称模型加载成功。 |
| W00-07 | 离线通过 | Python回归、前端测试、构建 | `& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests`退出码0，426项通过；`node --test ui/src/inventorySelection.test.js ui/src/inventoryReview.test.js`退出码0，11项通过；`npm --prefix ui run build`退出码0，Vite构建成功。 |
| W00-08 | 离线通过 | 离线任务首页／校对窗口冒烟 | `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1 -Offline -SmokeTest -TaskHome`退出码0；`runtime/logs/inventory-window-smoke.json`记录`ok=true`、`taskHomeRoundTrip=true`、`stop_bridge=true`、`maa_controller_imported=false`、`internalScroll=true`、`pageScroll=false`、`batchSelection=true`。没有设备动作。 |
| W00-09 | 离线通过 | 检查共同规则一致性 | `& .\.venv\Scripts\python.exe scripts/sync_shared_rules.py --check`退出码0，规则一致。 |
| W00-10 | 离线通过 | 建立本轮修改前清单 | `.local/history/v04-w00-w14-w16-evidence-20261117-before/manifest.json`；账本、交接、来源索引、汉堡卡及文件映射均已局部备份并核对SHA-256；清单记录manifest此前不存在。 |

### 既有差异（接管前）

受跟踪修改：`AGENTS.md`、`app/bag_alignment.py`、`app/bag_capture.py`、`app/bridge.py`、`app/device.py`、`app/main.py`、`app/ocr.py`、`scripts/run.ps1`、`tests/test_bag_alignment.py`、`tests/test_bag_capture.py`、`tests/test_device.py`、`tests/test_ocr.py`、`ui/src/App.vue`、`ui/src/style.css`。

未跟踪文件：`app/bag_geometry.py`、`app/preflight.py`、`start.cmd`、`tests/test_bag_geometry.py`、`tests/test_preflight.py`、`tests/test_task_entry.py`。

`git diff --check` 在当前 CRLF 文件上会把换行误报为尾随空白；已使用 `git -c core.whitespace=cr-at-eol diff --check` 复核，退出码 0。本轮没有改写这些已有文件。

## W01 — 范围、来源与规则证据

| ID | 状态 | 输入／动作 | 结果与证据 |
| --- | --- | --- | --- |
| W01-01 | 离线通过 | 将 R01—R25 映射到工作包和验收证据 | [v04-requirements-map.md](v04-requirements-map.md) 覆盖 25 项，无缺号；商战、环球差旅及复用小助理不列为 v0.4 任务。 |
| W01-02 | 离线通过 | 建立五款稳定英文 ID | `candy-party`、`skewer-master`、`burger-day`、`starlight-mix`、`animal-bath`与中文名称映射见 requirements map；均来自 guidance 的用户确认名单。 |
| W01-03 | 离线通过 | 核对用户轮换图及边界 | 只读检查 `docs/v04/references/minigame-rotation-reference.jpg`；五个名称与当前名单相符，图上明确提示周期／天数仅供参考，不把周期或时间硬编码。 |
| W01-04 | 离线通过 | 定位并核验官方多平台账号／公告入口 | 来源索引 O1—O3 记录官方 TapTap 多平台公告、B站游戏公告与官网预约入口；官方公告给出平台账号名称，但直接主页 ID 尚未取得。 |
| W01-05 | 离线通过 | 搜索五款全名及玩法词 | 2026-11-16 对五款分别检索；找到星光特调、疯狂汉堡日、动物沐场玩家攻略及烤串大师类别公告；糖果派对未发现可用的本游戏规则。来源与边界见 `docs/v04/minigame-rules/README.md`。 |
| W01-06 | 离线通过 | 分平台尝试定向搜索 | 抖音／小红书／TapTap／B站分别检索；每个平台实际返回内容与无结果边界见来源索引。搜索服务返回的非目标结果未被当规则。 |
| W01-07 | 进行中（V1部分取样） | 有可用玩法视频时核对画面 | V1短链已解析并在微博播放器播放至01:34；抽样00:02、01:02、01:34。后两处可见纵向游戏区域、虚线和食材图块，01:34有汉堡状图块；未捕获动作前后状态，也未确认剪辑或版本。后续浏览器状态采集超时，搜索工具报告robots阻止，直接HTTP访问跳转visitor页面；未登录或绕过。V2／V3未播放。W01-07未通过，见规则索引及burger-day规则卡。 |
| W01-08 | 离线通过 | 分类规则未知项阻塞范围 | 五张卡逐项区分模拟、实机／预算阻塞与策略缺口；当前均未到完整模拟门槛。 |
| W01-09 | 离线通过 | 比较官方信息和玩家经验 | 官方烤串公告只说消除类别；三篇TapTap攻略单独标作玩家经验。没有将官方宣传和玩家机制拼成一份规则。 |
| W01-10 | 离线通过 | 记录成本、失败、正常完成、辅助道具及重开后果 | 五卡均明写未知项；未虚构成本、道具作用或重开后果，相关真实动作保持关闭。 |
| W01-11 | 离线通过 | 判断现有规则是否足以模拟 | 五款均缺少完整状态／合法动作／成本／终止条件；没有一款批准进入模拟实现。 |
| W01-12 | 离线通过 | 列出公共基础与逐款阻碍 | 公共来源与范围台账建立；糖果缺规则，烤串只有玩法类别，另三款只有有限玩家线索。可进入W02公共数据契约；W11／各款模拟仍被规则依赖阻止。 |

## 工作包状态

| 工作包 | 状态 | 说明 |
| --- | --- | --- |
| W00 | 离线通过 | 2026-11-17复核的Python／前端／构建／离线冒烟／共同规则检查均通过；ADB缺失，OCR模型文件存在但未核实加载。 |
| W01 | 进行中 | 需求映射、来源初检和五张未知保持显式的规则卡已建立；没有一款规则卡足以批准模拟。W01-07已有V1部分画面取样但缺动作前后与剪辑判断，尚未通过。 |
| W02 | 离线通过 | W02-01—W02-10公共契约、状态机及虚拟端到端边界均离线通过；任务状态视图尚未接入主窗口，留W06。没有实机或库存生产接入。 |
| W03 | 进行中／派发受阻 | W03-01—03、05—06离线通过；W03-04的Mac恢复原型与合成测试通过，等待目标Windows双副本关口。W03-07不得接入设备派发。未连接或操作模拟器。 |
| W04—W10 | 未开始／依赖受阻 | 需要W03设备派发安全关口及后续依赖，不以离线模拟替代。 |
| W11 | 进行中 | W11-01—W11-07、W11-09—W11-10、W11-12通用模拟基础离线通过；W11-08、W11-11、W11-13受五款规则证据不足阻止，未建立任何游戏转移规则。 |
| W12—W13取证 | 进行中／各自受阻 | W12-01、W13-01定向公开检索未取得足够游戏专属画面／操作规则；没有据此开始模拟。 |
| W14—W16取证 | 进行中／证据不足 | W14静态截图确认单帧画面但未确定动作模型；W15仅有玩家布局建议；W16仅有未经当前版本验证的局部合并说法。详细状态见下方任务行。 |
| W17—W20其余项 | 未开始／依赖受阻 | W17需规则／模拟／策略及W03—W06；W18需W05、W10或至少一款可用任务；W19／W20依赖W18与可运行核心功能。不得用离线证据冒充实机或交付。 |

## Git 与提交

- W02代码与测试已本地提交：`365fa7a`（`Add v0.4 task contracts`），仅含20个新增契约模块／测试文件；`.local`施工记录受忽略规则管理，不在提交中；未推送。
- 接管前14个受跟踪差异和6个未跟踪文件仍在工作区，未暂存／覆盖／夹带。提交后分支`main`本地领先`origin/main`两个提交，HEAD为`365fa7a`。
- W03-06代码与测试单独本地提交：`d538097`（`Add v0.4 conflict guard checks`），只含`app/conflict_guard.py`与`tests/test_conflict_guard.py`；没有混入接管前改动，未推送。
- W11-05代码与测试已单独本地提交：`1515737`（`Add v0.4 simulation transition outcomes`），只含`app/simulation_contract.py`、`app/minigames/simulation_transition.py`和`tests/test_simulation_transition.py`；本机说明留在`.local`，未纳入提交。
- W11-06代码与测试已单独本地提交：`348d982`（`Add v0.4 simulation outcome distinctions`），只含模拟结果模型和定向测试；本机说明留在`.local`，未纳入提交。
- W11-07代码与测试已单独本地提交：`bbfed68`（`Add replayable simulation trace records`），只含轨迹序列化／校验模块和定向测试；本机说明留在`.local`。
- W11-09代码与测试已单独本地提交：`d4d97ad`（`Add deterministic simulation baseline strategy`），只含模拟基线和定向测试；本机说明留在`.local`。
- W11-10代码与测试已单独本地提交：`bdee172`（`Add bounded simulation search controls`），只含搜索预算／取消控制模块和定向测试；本机说明留在`.local`。
- W11-12代码与测试已单独本地提交：`52092b5`（`Add strategy observation boundary`），含观察投影、策略协议收紧、基线更新和对应测试；本机说明留在`.local`。
- 当前分支`main`、HEAD `52092b5`，较`origin/main`领先13个提交。接管前跟踪修改和既有未跟踪文件均保留；W03-01—03、W03-05相关源码仍在工作区，未混入W11-05—12提交。没有达到CP-A，不推送。

## W02 — 核心数据契约与状态机（公共基础）

前置：W01公共部分已完成来源索引、需求映射和逐款未知清单；游戏模拟仍独立受规则门槛阻止。

| ID | 状态 | 输入／动作 | 结果与证据 |
| --- | --- | --- | --- |
| W02-01 | 离线通过 | 追踪UI→Bridge→Worker→Device及所有设备动作入口 | [设备调用链](v04-device-call-chain.md)覆盖 `MaaDevice` 构造、连接、截图、点击、普通滑动和背包受限滑动，也记录CLI路径、每项目根锁的限制和页面身份缺口。 |
| W02-02 | 离线通过 | 定义任务状态和合法转换 | [任务状态契约](v04-task-state.md)与`app/task_state.py`给出显式转换；8项Python单元测试通过。完成必须带后置条件核实；异常／停止恢复要求用户显式发起。尚未接入UI。 |
| W02-03 | 离线通过 | 定义观察数据并显式表示unknown | `app/observation.py` 与 [观察数据契约](v04-observation-contract.md) 明确保存时区时间、设备／角色／活动／规则／画面身份及棋盘／体力；unknown有原因且不补0。棋盘在构造时深拷贝为递归不可变JSON快照，严格拒绝无效JSON值；整数schema版本严格校验。定向测试11项、完整Python回归271项通过。命令：`& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests -p test_observation.py`（0）；`& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests`（0）。证据：`tests/test_observation.py`、`app/observation.py`。观察模型仍未接入Bridge或正式库存，留W02-10及后续工作验证。 |
| W02-04 | 离线通过 | 定义动作及前置画面指纹 | `app/action_contract.py` 中的`ActionIntent`绑定设备、确切截图和页面指纹；`assert_action_precondition`仅在三项已知且完全匹配时通过。新截图、页面或实例变化及unknown均拒绝。定向8项、完整Python回归279项通过；命令：`& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests -p test_action_contract.py`（0）；完整回归命令同上（0）。证据：`tests/test_action_contract.py`、[动作契约](v04-action-contract.md)。纯离线比较，尚未接入W03统一设备派发。 |
| W02-05 | 离线通过 | 定义四种动作结果 | `app/action_result.py`区分`not_submitted`、`submitted_unknown`、`verified_success`、`verified_failure`。未知结果与未提交分开；成功／失败必须引用后置观察，失败／未提交／未知必须给原因。定向8项、完整Python回归287项通过；命令：`& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests -p test_action_result.py`（0）；完整回归命令同上（0）。证据：`tests/test_action_result.py`、[动作结果契约](v04-action-results.md)。仅数据模型，尚无持久化或实机验证。 |
| W02-06 | 离线通过 | 定义任务依赖并进行无环验证 | `app/task_dependencies.py`建立依赖优先顺序；具体拒绝自依赖、缺失任务、循环、重复依赖及无效结构，并返回错误码、任务ID或闭合循环路径。定向9项、完整Python回归296项通过；命令：`& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests -p test_task_dependencies.py`（0）；完整回归命令同上（0）。证据：`tests/test_task_dependencies.py`、[任务依赖契约](v04-task-dependencies.md)。纯校验，未接入实际调度器。 |
| W02-07 | 离线通过 | 定义每款能力状态和开放条件 | `app/game_capability.py`仅列五个获批ID；以规则、模拟、无死局目标、真实适配器证据推导状态，缺少任一门槛即不为`execution_ready`。定向9项、完整Python回归305项通过；命令：`& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests -p test_game_capability.py`（0）；完整回归命令同上（0）。证据：`tests/test_game_capability.py`、[能力契约](v04-game-capabilities.md)。五款当前仍规则未核实；状态契约未接UI／模拟／设备。 |
| W02-08 | 离线通过 | 隔离策略、模拟和设备执行接口 | 新增三个协议模块，策略／模拟仅依赖纯数据；执行接口仅描述边界。全新解释器导入三层后未加载`app.device`或`maa`。定向3项、完整Python回归308项通过；命令：`& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests -p test_layer_contracts.py`（0）；完整回归命令同上（0）。证据：`tests/test_layer_contracts.py`、[分层契约](v04-layer-contracts.md)。没有创建游戏规则适配器或具体设备执行器。 |
| W02-09 | 离线通过 | 区分存储提交与游戏动作记录 | `app/storage_contract.py`用稳定提交ID、来源观察ID和不可变负载建立请求；限定重试只接收存储提交器及原请求，不接收执行器。测试验证同请求有界重试、存储冲突停止及一项已提交动作不会被重发。定向8项、完整Python回归316项通过；命令：`& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests -p test_storage_contract.py`（0）；完整回归命令同上（0）。证据：`tests/test_storage_contract.py`、[存储／动作边界](v04-storage-action-boundary.md)。真实库存仍未接入，旧样例仍受临时目录限制。 |
| W02-10 | 离线通过 | 用虚拟状态验证公共端到端分支 | `app/task_status.py`提供UI可消费的阶段、中文说明和具体原因。7项虚拟流程测试覆盖成功后保存重试仍只提交一次动作、体力等待先重检、停止不自动恢复、已核实失败不得完成、提交未知不重放及旧画面拒绝。完整Python回归323项通过；命令：`& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests -p test_task_contract_flow.py`（0）；完整回归同上（0）。证据：`tests/test_task_contract_flow.py`、[离线流程说明](v04-task-contract-flow.md)。主窗口尚未接入此状态视图（W06）；全程未连接设备／正式库存。 |

## W03 — 排他、取消与动作记录

前置：W02离线通过。W03-01输出身份键契约；后续租约仍须在真实派发前刷新实例信息并确认身份，不得回退到项目路径或ADB地址。

| ID | 状态 | 输入／动作 | 结果与证据 |
| --- | --- | --- | --- |
| W03-01 | 离线通过 | 定义MuMu实例身份，与项目／ADB定位信息分离 | `app/device_identity.py`以MuMuManager记录的`index + created_timestamp`生成确定性身份及SHA-256租约键；项目根、ADB路径／地址、名称、PID和窗口句柄不参与身份。5项定向测试及完整Python回归328项退出码0。证据：[身份契约](v04-device-identity.md)、`tests/test_device_identity.py`。官方说明列出这些字段，但未承诺唯一性或克隆／迁移稳定性；本机实际输出尚未读取。 |
| W03-02 | 离线通过（活跃互斥） | 实现Windows跨进程、跨项目副本租约 | `app/device_lease.py`以W03-01的身份摘要创建`Global\\MAA4BHC.DeviceLease`命名互斥体；专用线程持有并释放。3项定向子进程测试覆盖不同项目根竞争、释放后重获及异常退出注入；完整Python回归331项退出码0。命令：`& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests -p test_device_lease.py`（0）；完整回归同上（0）。证据：[租约说明](v04-device-lease.md)、`tests/test_device_lease.py`。发现限制：持有者崩溃且对象无其他打开句柄时，Windows销毁互斥体，重启后不能据此识别旧动作。尚未接入设备入口；不代表W03整体排他通过。 |
| W03-03 | 离线通过 | 记录租约持有者、进程存活和本机诊断信息 | `app/device_lease.py`在`Local\\`共享映射提供PID、TID、进程创建标记、取得时间和身份摘要；按当前项目根追加本机JSONL诊断，禁止记录项目路径或ADB连接值。5项定向测试、完整Python回归333项退出码0。证据：[租约与诊断说明](v04-device-lease.md)、`tests/test_device_lease.py`。仅同一Windows登录会话能读取映射；同一设备冲突一律停止。 |
| W03-04 | 进行中（Mac离线通过，待Windows复验） | Mac原型与11项合成测试通过；状态记录显式区分首次初始化与权威丢失、先持久意图再发送、结果未知需核实。目标Windows两进程／两副本复验尚未执行；设备派发不得接入。 |
| W03-05 | 离线通过（信号有限） | 盘点已知外部操作者及可检测信号 | `app/external_operator_probe.py`实现只读Windows `netstat -ano -p tcp`快照，识别远端端口5037、ESTABLISHED客户端PID；未登记PID为conflict，命令失败／格式未知／目标PID不可见为unknown。6项定向测试及完整Python回归339项退出码0。证据：[外部操作者盘点](v04-external-operators.md)、`tests/test_external_operator_probe.py`。单次主机快照`clear/0`只表示未观察到客户端；`Get-NetTCPConnection`本次CIM异常；进程名`adb`和多个MuMu组件不能映射到目标设备／实际控制。自定义ADB端口、快照间隙和桌面输入仍不覆盖。探针尚未接入派发。 |
| W03-06 | 离线通过（信号有限） | 增加外部冲突与画面变化检查 | `app/conflict_guard.py`要求租约已取得、默认ADB端口快照为新鲜`CLEAR`、动作实例与当前观察的设备／画面／页面身份一致；conflict、unknown、陈旧快照或页面变化均失败关闭。9项定向测试、完整Python回归348项、`git -c core.whitespace=cr-at-eol diff --check`均退出码0。许可只覆盖已知信号和精确画面，不证明绝对独占；未接入派发。代码说明：[W03-06冲突检查](v04-conflict-guard.md)。 |
| W03-07 | 受阻 | 所有设备指令统一经过取消和租约检查 | 前置W03-04仍未解决；当前不可安全接入设备派发。W03-08—12按依赖顺序待其后推进。 |

当前W03派发仍受W03-04目标Windows复验阻塞。本轮离线原型只验证持久记录与恢复状态机；不代表W03整体排他通过，也未接入设备入口。

## W11 — 公共模拟与策略验证工具

前置：W02离线通过；W01规则来源索引及五款规则卡存在。规则证据不足之处只能登记unknown，不阻止与具体游戏无关的契约工作。

| ID | 状态 | 输入／动作 | 结果与证据 |
| --- | --- | --- | --- |
| W11-01 | 离线通过 | 定义每款规则版本与已证实／假设字段 | 新增`app/minigames/rule_evidence.py`及[规则证据说明](v04-rule-evidence.md)，覆盖五款来源线索、版本unknown、模拟假设与未知字段。来源陈述不冒充当前实机规则；现有游戏能力仍为`rules_unverified`。定向8项、完整Python回归356项、纯导入烟测和`git -c core.whitespace=cr-at-eol diff --check`均退出码0。 |
| W11-02 | 离线通过（通用契约） | 定义可序列化状态与显式随机输入 | `app/minigames/simulation_state.py`保存游戏ID、已核实规则版本、游戏专属schema及不可变JSON快照；拒绝unknown版本。每步有限随机值由固定SHA-256计数算法生成并随记录保存；模拟协议现使用具体状态／输入类型。8项定向测试、完整Python回归364项、纯导入烟测和换行检查均退出码0。虚拟转移只用测试夹具，不代表任何实际游戏模拟。代码说明：[W11-02状态契约](v04-simulation-state.md)。 |
| W11-03 | 离线通过（快照隔离） | 实现只读状态快照及复制 | 新增`SimulationState.copy_for_trial()`生成独立且仍不可变的副本；其序列化数据为试算提供另一个可变工作副本，不回写输入观察。测试用合成`Observation`确认原观测、原状态及试算状态保持一致。定向9项、完整Python回归365项、纯导入烟测和换行检查均退出码0。未连接设备或真实观察器。 |
| W11-04 | 离线通过（动作契约） | 定义合法动作枚举接口 | 新增`ActionCandidate`及状态绑定的`LegalActionSet`；只允许带非空规则证据引用的`gameplay`分类，辅助道具／购买／重开／unknown或重复动作均拒绝。空动作集不自动解释为死局。定向7项、完整Python回归372项、纯导入烟测及换行检查均退出码0；无实际游戏动作适配器。代码说明：[W11-04动作集合](v04-simulation-actions.md)。 |
| W11-05 | 离线通过（通用契约） | 定义动作成本及效果返回 | 新增`SimulationCost`、`SimulationTransition`并更新纯模拟协议。已知成本向量必须带规则引用；unknown成本没有数值；非法动作要求有证据的零成本和不变状态；unknown效果不声称后置状态。定向10项、完整Python回归382项、纯导入烟测及换行检查均退出码0。只用合成状态和fixture引用，不代表任何小游戏规则。说明：[W11-05成本与效果](v04-simulation-effects.md)。 |
| W11-06 | 离线通过（通用契约） | 区分五种模拟 episode 结果并分别计数 | 新增`SimulationEpisodeOutcome`及不可变`SimulationOutcomeCounts`，分别记录正常完成、无合法动作、unknown、timeout和阈值停止。无合法动作要求空且绑定同一状态的`LegalActionSet`和规则引用；单独出现空动作集仍不会自动产生此结论。定向8项、完整Python回归390项、纯导入烟测及换行检查均退出码0。测试用合成状态，不含游戏规则。说明：[W11-06模拟结果](v04-simulation-outcomes.md)。 |
| W11-07 | 离线通过（通用轨迹数据格式） | 建立可序列化、可校验的逐步轨迹 | 新增`SimulationTrace`／`SimulationTraceStep`及严格JSON往返；保存初始状态、游戏规则版本、种子、逐步随机输入、动作成本／效果及终止原因。验证状态连续性、步号／随机输入一致性、unknown必须最终停止和规则版本一致。定向10项、完整Python回归400项、纯导入烟测及换行检查均退出码0。尚无实际游戏规则引擎，因此没有真实规则回放。说明：[W11-07模拟轨迹](v04-simulation-traces.md)。 |
| W11-08 | 受阻 | 编写独立的规则示例作为测试真值 | 五款小游戏的规则版本和关键转移均未取得足够来源／画面证据；禁止拿fixture或模型推断冒充真实真值。待有可核实规则后再为对应游戏建立测试样例。 |
| W11-09 | 离线通过（比较基线） | 建立最小合法策略作为比较基线 | 新增`DeterministicLegalActionBaseline`，从已校验逻辑动作中按`(kind,target)`稳定排序选择首项；缺少／unknown预算或没有候选时暂停。定向8项、完整Python回归408项、纯导入烟测及换行检查均退出码0。该基线不估算单个动作成本，不授予执行权限；模拟器仍须先核成本和阈值。无游戏适配器，也不证明无死局。 |
| W11-10 | 离线通过（搜索控制契约） | 建立搜索节点／深度预算、取消与超时 | `SimulationSearchSession`在节点数、深度、超时或取消边界中断时返回`UNKNOWN`且没有动作路径；只有调用方报告完整穷尽且未中断，才可标`PROVEN_NO_SOLUTION`。定向11项、完整Python回归419项、纯导入烟测及换行检查均退出码0。它不实现游戏搜索算法。 |
| W11-11 | 受阻 | 对可穷举的小状态空间求解并验证解路径 | 当前没有任何游戏专属已核实状态空间和转移规则；不能用合成fixture声称已穷举真实玩法。待取得规则真值后按款推进。 |
| W11-12 | 离线通过（信息边界契约） | 策略只经观察接口取得当前可见信息 | 新增深层不可变`StrategyObservation`，策略协议由泛型`object`改为该类型；离线基线拒绝完整`SimulationState`，未向策略提供轨迹或随机输入。观察字段显式保留unknown。定向7项观察测试及8项基线回归、完整Python回归426项、纯导入烟测和换行检查均退出码0。该类型无法判断适配器是否把隐藏值错误标作visible，因此尚不代表具体游戏实现通过。 |
| W11-13 | 受阻 | 搜索最坏后继和近满局面，保留反例 | 需要游戏专属状态空间和转移规则；五款均未核实，不以合成fixture冒充真实反例。 |

## 独立规则取证分支

| ID | 状态 | 输入／动作 | 结果与证据 |
| --- | --- | --- | --- |
| W12-01 | 受阻 | 找到明确属于百货城糖果派对的规则页或连续操作资料 | 2026-11-17复核精确组合及B站／抖音／小红书／TapTap；没有百货城专属操作资料。TapTap同名应用为Ultrafun的2017独立游戏，其交换匹配规则排除。详情与链接见规则来源索引。 |
| W13-01 | 受阻 | 取得烤串大师操作前后画面和规则说明 | 2026-11-17复核未找到连续操作资料或已观看视频。官方B站公告仍只写“趣味消除”；玩家长攻略只称“完成烤串得盒饭”，无机制细节；TapTap同名独立烧烤游戏排除。来源类型及边界见规则索引。 |

## W14—W16公开规则取证

前置均为W01公共来源工作。以下记录玩家来源、静态配图与汉堡视频V1的部分抽样画面，不代表规则已核实；没有满足验收证据时后续模拟保持关闭。

| ID | 状态 | 输入／动作 | 结果与证据 |
| --- | --- | --- | --- |
| W14-01 | 受阻（部分画面线索） | 核实输入方式、容器边界、食材和预览信息 | C5静帧及V1抽样00:02／01:02／01:34显示纵向游戏区域、横向虚线和食材图块，01:34可见汉堡状图块。V1仅播放至01:34，未捕获动作前后状态；输入方式、虚线语义、预览仍unknown，不能区分点击／拖动／离散放置／物理落点。V2／V3未播放。 |
| W14-02 | 受阻 | 核实食材等级、合成顺序和大汉堡完成／移除规则 | C2只给摆放建议和食材大小用语；C5只是一帧，未展示合成前后。等级映射、合成顺序、完成／移除规则仍unknown。 |
| W14-03 | 受阻 | 查倍数设置的真实成本与副作用 | C2称可开启倍数合成以避免卡位，但未说明费用、体力／步数影响或副作用；不得开启或用于策略。 |
| W15-01 | 受阻（静态视觉线索） | 核实容器、颜色、混合状态及待放物 | C1文字提到不同颜色酒与混合酒，附四张静态配图，可见纵向游戏画面区域和多色饮品图块；没有版本标记或连续动作。准确盘格／容器、单色与混合物视觉判据及待放物预览仍unknown。 |
| W15-02 | 受阻 | 记录可放位置、邻接、混合、消除与连锁次序 | C1仅给斜向摆放建议；不能推出合法位置、邻接规则、混合条件或连锁。 |
| W15-03 | 受阻（非定量体力线索） | 查满盘、结束、计分、预览和体力扣除 | C6 App Store玩家评论定性称体力消耗快，但无每步／每局数值；C1文字与静态配图未能确认满盘、结束、计分或预览规则。预算与终止条件仍unknown。 |
| W16-01 | 受阻（静态视觉线索） | 核实正式名称、棋盘与动物等级 | C3标题与用户确认名单均写“动物沐场”；C3另含四张无版本标记的静态图片及动物图块示意／画面，未能核实当前盘面尺寸、等级图例或版本一致性，不能当作当前实测。 |
| W16-02 | 受阻 | 验证上下左右／对角是否算邻接 | C3玩家文字报告“上下左右相邻”；未核当前版本，也未说明对角规则或给出连续动作画面，不能通过规则验证。 |
| W16-03 | 受阻（部分玩家描述） | 验证两只、三只、更多同级相邻的处理 | C3文字报告两只与三只的等级差异，静态图没有可配对的动作前后状态；合成位置、优先级、多组竞争及更多数量规则仍unknown，来源未达到验收证据。 |
| W16-04 | 受阻 | 核实自动连锁、最高等级、移除和计分 | 未取得足以确认这些机制的来源或画面。 |
| W16-05 | 受阻 | 核实新动物来源、预览、成本及结束条件 | 当前可用来源未说明生成、可见预览、成本或结束条件；未来状态不作推断。 |

来源链接、视频候选与抽样边界见[规则来源索引](minigame-rules/README.md)。W14-04／05互斥分支及W15／W16模拟、策略任务均未开始；不得用相似玩法或合成fixture填补缺口。

## 2026-11-17 Mac 独立公开取证续查

- **W01-07**：按汉堡玩法名及“时尚百货城＋疯狂汉堡／合成汉堡”继续查找公开视频。未获得可读取的连续操作序列；C2仍是玩家布局／倍数建议，不能替代动作前后画面。保持进行中，恢复条件是可访问并能辨认版本与操作前、操作中、操作后状态的素材。
- **W12-01**：定向检索TapTap与B站糖果派对规则／视频。结果仅复现跨游戏讨论C7，没有百货城糖果派对专属动作或规则页；保持受阻。恢复条件是本游戏专属状态、合法动作及完成／失败规则，最好有可配对的连续状态记录。
- **W13-01**：定向检索TapTap与B站烤串大师操作／规则／演示。只复现官方O2“全新趣味消除”公告；无连续操作与成本说明，保持受阻。恢复条件是能核对玩法状态转移与结束条件的专属说明或连续演示，并明确版本／渠道。
- **W15-01—03**：定向搜索复现C1静态摆放建议和C8非定量体力评论；没有新增棋盘、混合转移、消除顺序或单局／单步成本。均保持受阻。恢复条件是可配对动作状态及可核验成本、终止证据。
- **W14-01—03／W16-01—05**：没有新增规则证据；C2／C3既有玩家说法未核当前版本，页面配图链接本轮未能由网页读取呈现，未增加新的图像观察。任务继续保持表内受阻状态。
- **本轮结果**：来源索引已记录查询词范围、重复来源及证据边界；没有改游戏代码或规则模型，不运行代码测试。未连接或操作游戏，未使用资源。
- **恢复点**：`.local/history/v04-public-research-followup-before-20261117/manifest.json`，只包含本轮准备修改的来源索引、任务账本、Mac交接与本机交接文件的修改前副本及SHA-256。
- **下一项**：只在出现满足对应恢复条件的公开证据时推进规则卡与W01／W12—W16验收。W03-04仍等待Windows双进程／双副本复验，W03-07设备派发不开放。

## 2026-11-17 W01-07公开视频访问复核

- 输入与前置：W01公共来源工作已完成；V1已有部分画面，但没有动作前后对照。验收需要可辨认的实际操作、操作前后状态及剪辑边界。
- 本次动作：按汉堡游戏名与“合成汉堡”重新检索；在公开网页工具打开V2／V3新浪转载页及其视频目标；尝试绑定桌面浏览器已有V1标签页读取当前画面。未登录、未绕过限制。
- 结果：V2／V3转载页只有配文和短链，`video.weibo.com`与`t.cn`目标在网页工具中不可访问；桌面浏览器读取V1标签页连续两次超时，没有得到新帧。抖音试玩广告页面由网页工具打开后无可读正文或视频帧，未播放，不包含机制证据。V1仍只抽样至01:34，W01-07未通过，W14-01保持unknown。
- 证据与边界：查询结果及访问状态写入[规则来源索引](minigame-rules/README.md)和[疯狂汉堡日规则卡](minigame-rules/burger-day.md)。搜索索引未命中不能证明内容不存在。没有代码改动，因此本次不运行代码测试。
- 修改前恢复点：`.local/history/v04-w01-video-review-20261117-before/manifest.json`。本轮只更新本机来源记录、账本、交接与文件说明；代码差异、暂存区和提交均未触碰。
- 下一步：仅在取得公开可读取的视频动作序列后推进W01-07／W14-01；若没有可用证据，五款规则研究继续保留unknown。W03-04仍阻止设备派发；不连接或操作模拟器。

## 2026-11-17 W12／W13糖果与烤串定向再检索

- 输入与前置：W01公共来源工作已完成；W12／W13取证分支不要求其他小游戏规则先通过。
- 本次动作：重新查询糖果派对玩法／规则、烤串大师玩法／视频，并定向查询抖音视频与B站；打开新发现的TapTap跨游戏讨论和官方B站公告。
- 结果：抖音糖果派对精确组合未返回可用玩法视频；B站命中官方O2公告，仅称烤串大师为“全新趣味消除”。TapTap新来源C7写在《土豆兄弟》论坛，作者用糖果派对举例说明收入榜与奖励联动，没有给出游戏动作、状态、成本或完成条件。W12-01和W13-01仍受阻；没有启动模拟。
- 证据：来源类别、链接与边界见[规则来源索引](minigame-rules/README.md)。此轮没有代码修改，不运行代码测试；未连接或操作模拟器。
- 修改前恢复点：与本轮W01-07来源记录相同，见`.local/history/v04-w01-video-review-20261117-before/manifest.json`；文档修改前副本的哈希在清单内。

## 2026-11-17 W14—W16机制与成本窄词复查

- 输入与前置：W14—W16公开证据研究均依赖W01；本次继续查具体规则／成本，不进入模拟实现。
- 本次动作：查询汉堡小黄瓜片与倍数合成、食材等级／顺序、星光特调体力／合成规则、动物沐场合并规则。
- 结果：搜索重复C2、C3、C6，没有取得倍数成本、汉堡食材等级表或动物连锁规则。新增C8是TapTap星光特调玩家帖，只定性称体力太少，没有费用数字、规则或版本。W14-01—03、W15-01—03、W16-01—05维持受阻。
- 证据：来源索引已添加C8并记录此次窄词复查。没有代码修改，不运行代码测试；没有触碰模拟器。
- 修改前恢复点：仍见`.local/history/v04-w01-video-review-20261117-before/manifest.json`，本轮修改涉及的来源索引、账本、交接和README都包含在其副本清单中。
