# 2026-11-17 ASUS移交验证

本次验证在ASUS Windows运行，基于52092b5及移交时已有首页、分辨率与设备基础源码。用户已明确授权验证全部成果并完成Git推送和Mac交接。

## 验证记录

| 命令或检查 | 预期 | 实际 | 退出码 | ASUS证据路径 |
| --- | --- | --- | --- | --- |
| .venv/Scripts/python.exe -W error::DeprecationWarning -m unittest discover -s tests | 当前完整离线回归通过 | 426项通过，18.629秒 | 0 | .local/logs/v04-transfer-python.log |
| node --test ui/src/inventorySelection.test.js ui/src/inventoryReview.test.js | 前端选择与校对回归通过 | 11项通过 | 0 | .local/logs/v04-transfer-frontend.log |
| npm --prefix ui run build | 静态前端编译成功 | Vite 8.3.5构建成功 | 0 | .local/logs/v04-transfer-build.log |
| powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/run.ps1 -Offline -SmokeTest -TaskHome | 首页、校对与停止桥接可用 | ok、首页往返、内部滚动、框选多选、紧凑布局通过，maa_controller_imported=false | 0 | .local/logs/v04-transfer-smoke.log及v04-transfer-validation.json |
| 同上增加-ReadOnly | 只读入口安全性与首页可用 | 冒烟通过 | 0 | .local/logs/v04-transfer-smoke-readonly.log |

环境为Python 3.12.10、Node 22.21.0和npm 10.9.4。使用项目锁定依赖，测试缓存及日志留在项目内。负向测试打印的预期错误以测试断言结果判定。

## 范围复核

W00、W02和W11通用契约已有的可复用成果完成当前离线复验。旧首页、450×800适配与Windows设备基础经过本轮审阅，来源与本机历史交接相符，按当前用户明确要求整理提交。

W03-04的跨副本持久诊断与未决动作恢复仍有实现缺口。五款完整规则、具体模拟、策略无死局目标、W04—W10自动化与生产库存、W17实机以及W19最终m4b.exe验收仍待对应前置。CP-A—CP-E维持待验收。

本次Git移交为可公开的开发阶段成果，源码、测试及施工文档都纳入审核范围。真实账号、截图、库存、连接配置和OCR模型按各自本机保存状态处理。

## Git审核与同步

远端为GitHub的mickw1210-a11y/MAA4BHC，分支main。移交开始时本地领先origin/main共13个提交，远端基线8b25892。14个既有跟踪修改和12个未跟踪源码或测试已逐项检查。

已fetch确认远端基线。Git直连github.com超时后，通过本机已有系统HTTPS代理成功fetch，代理仅在本次子进程参数中使用。

原13个待推提交共涉及61个路径，路径与凭据特征初检通过。本次后续提交的文件清单、全部待推历史、Markdown链接及共同规则继续在推送前复核。最终同步结果在完成实际push及远端HEAD核对后补记。

本轮已形成两个源码提交。17fd375保存首页、准备检查、分辨率适配及相关测试，共19文件。f67c392保存Windows设备身份、租约、外部ADB探针及对应测试，共6文件。

仓库作者身份未配置，首次commit命令因此失败。核对HEAD与origin/main中的作者名称及GitHub noreply邮箱一致后，沿用其Mick身份，以单次命令参数完成两个提交。

35份共享Markdown的相对链接检查通过，AGENTS与Workspace_Handoff的共同要求检查退出码0。后续文档及暂存审核通过后形成独立移交提交。

移交文档提交前，暂存清单精确核对为35份Markdown加.gitignore、AGENTS.md和Workspace_Handoff.md，共38文件。UTF-8、代码围栏、相对链接、共同规则和暂存空白检查均通过。6份局部恢复副本SHA-256核对通过，42个新路径有此前不存在记录。暂存内容的凭据特征与个人绝对路径检查无发现。

## 证据与恢复

ASUS本机验证汇总位于.local/logs/v04-transfer-validation.json，真实截图和历史故障证据按原位置保留。本报告供另一设备获取审核后的结果与复验命令。

移交修改前的局部恢复清单位于.local/history/v04-mac-transfer-20261117-before/manifest.json，记录6份既有文件真实副本与42个新文件的此前不存在状态。源码既有改动在本次提交前保持其原内容。
