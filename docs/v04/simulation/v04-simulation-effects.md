# W11-05：模拟成本与效果返回

日期：2026-11-16。范围：定义纯模拟转移的成本与后置状态契约；不确定或未知规则时不生成猜测结果。

## 返回状态

- `SimulationCost.known()`包含带规则引用的资源成本向量；空向量表示有证据支持的零成本。
- `SimulationCost.unknown(reason)`没有数值和来源引用，不会被解释成零。
- `APPLIED`要求成本已知、返回同一游戏／规则版本／状态schema的后置状态，并引用效果规则。
- `INVALID`要求成本为有证据的零成本、状态指纹完全不变，并记录拒绝原因和规则引用。
- `UNKNOWN`保留原因，不声称有后置状态；成本可单独保持已知或unknown。

## 验证与限制

定向测试使用合成状态和规则引用，验证应用效果、unknown成本、已证零成本、非法动作零成本且不变、unknown效果和版本不匹配拒绝。没有实际小游戏成本、转移或道具规则，也没有真实执行。模拟规则协议现返回`SimulationTransition`。

| 检查 | 命令／结果 |
| --- | --- |
| 定向测试 | `& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests -p test_simulation_transition.py`：退出码0，10项通过。 |
| 完整Python回归 | `& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests`：退出码0，382项通过。少数既有负向测试打印错误日志，测试汇总为`OK`。 |
| 导入烟测 | 全新解释器导入`SimulationTransition`与`SimulationRules`后，断言`app.device`和`maa`均未加载：退出码0。 |
| 换行／空白 | `git -c core.whitespace=cr-at-eol diff --check`：退出码0；Git提示文件下次触及时会把LF转换为CRLF，没有因此改写行尾。 |

实现与测试已单独本地提交`1515737`（`Add v0.4 simulation transition outcomes`）。本任务修改前恢复点见`.local/history/v04-w11-05-simulation-effect-20261116-before/manifest.json`。上述检查只证明通用数据契约和隔离导入边界，不证明规则引用对应当前游戏事实；未连接或操作模拟器、未消耗资源、未迁移用户数据。

代码：[simulation_transition.py](../../../app/minigames/simulation_transition.py)；接口：[simulation_contract.py](../../../app/simulation_contract.py)；测试：[test_simulation_transition.py](../../../tests/test_simulation_transition.py)。
