# W11-06：模拟 episode 结果分类

日期：2026-11-16。目标：将正常完成、无合法动作、unknown、超时和阈值停止作为互斥结果记录，并分别统计。它们不互相折算，也不把非正常终止合并成胜利。

## 结果契约

- `SimulationEpisodeOutcome`绑定最后一个已知`SimulationState`，只接受一个`EpisodeEndReason`。
- `NORMAL_COMPLETION`需要规则引用；它表示规则定义的正常终止，不额外推断得分或胜负。
- `NO_LEGAL_ACTIONS`需要带规则引用的空`LegalActionSet`，并验证动作集绑定到同一状态。空动作集自身仍不等于死局结论。
- `UNKNOWN`、`TIMEOUT`和`THRESHOLD_STOP`各自保留原因；它们不声称正常完成，也不附带无合法动作断言。
- `SimulationOutcomeCounts`为五类单独累计，拒绝负数、布尔计数和非结果输入。`total`仅为五类计数之和，没有合并的“胜利”或“成功”字段。

## 验证与限制

定向测试使用合成状态和fixture规则引用，覆盖五类结果、逐类计数、空动作集与状态绑定、缺少证据／原因和非法计数。

| 检查 | 命令／结果 |
| --- | --- |
| 定向测试 | `& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests -p test_simulation_outcome.py`：退出码0，8项通过。 |
| 完整Python回归 | `& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests`：退出码0，390项通过。少数既有负向用例打印异常日志，最终测试汇总为`OK`。 |
| 导入烟测 | 全新解释器导入结果模型和计数后，断言`app.device`与`maa`均未加载：退出码0。 |
| 换行／空白 | `git -c core.whitespace=cr-at-eol diff --check`：退出码0；未全仓改写行尾。 |

首轮定向检查有3项断言正则不匹配字段级错误文案（`evidence_ref`／`detail`）；调整断言后重跑定向与完整回归均通过。代码和测试单独本地提交`348d982`（`Add v0.4 simulation outcome distinctions`）。恢复点见`.local/history/v04-w11-06-simulation-outcomes-20261116-before/manifest.json`。

本契约不定义任何一款游戏的完成规则，也不证明某个规则枚举器穷尽了合法动作。五款规则版本仍unknown，尚无可运行的游戏模拟或实机结果。

代码：[simulation_outcome.py](../../../app/minigames/simulation_outcome.py)；测试：[test_simulation_outcome.py](../../../tests/test_simulation_outcome.py)。
