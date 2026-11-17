# W11-07：可回放模拟轨迹

日期：2026-11-16。目标是保存一次纯模拟 episode 的初始状态、游戏与规则版本、seed、每步随机输入、状态变化、动作成本／效果和终止结果，供以后按相同规则实现重放。

## 数据与校验

- `SimulationTrace`采用版本化JSON，包含初始`SimulationState`、明确规则版本、无符号64位seed、连续步骤列表和`SimulationEpisodeOutcome`。
- 每个`SimulationTraceStep`保存步号、该步的`SimulationRandomInput`和完整`SimulationTransition`；转移包含逻辑动作、规则引用、成本、前置状态和已知后置状态。
- 构造时校验：游戏／规则版本一致；step从0连续递增；每个随机输入的seed和步骤号匹配；每步前置状态指纹接续前一步的已知状态；episode结果状态等于最后一个已知状态。
- unknown转移必须是最后一步，并以unknown结束；不能在unknown后继续拼接猜测状态。
- 反序列化严格检查schema版本、字段集合、重复JSON字段和随机输入内容。保留每步抽样而非仅保存初始seed，避免依赖未来可能变化的抽样实现重建旧输入。

## 验证与限制

测试用合成状态和fixture规则引用，覆盖多步状态链、成本／效果／随机输入JSON往返、无合法动作终止、unknown停止、步号／seed／版本／终态校验及错误JSON拒绝。

| 检查 | 命令／结果 |
| --- | --- |
| 定向测试 | `& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests -p test_simulation_trace.py`：退出码0，10项通过。 |
| 完整Python回归 | `& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests`：退出码0，400项通过。既有负向用例会打印预期错误日志，最终测试汇总为`OK`。 |
| 导入烟测 | 全新解释器导入`SimulationTrace`后，断言`app.device`和`maa`均未加载：退出码0。 |
| 换行／空白 | `git -c core.whitespace=cr-at-eol diff --check`：退出码0；未全仓改写行尾。 |

代码及测试单独本地提交`bbfed68`（`Add replayable simulation trace records`）。修改前恢复点见`.local/history/v04-w11-07-replay-trace-20261116-before/manifest.json`。

此格式具备重放所需的数据，但本轮没有可核实的游戏规则引擎，未执行规则重放。完整episode轨迹仅供离线回放／核查；策略输入仍须限制在当前观察接口，不得因轨迹存档而读取未来步骤或隐藏信息。五款游戏规则版本均unknown。

代码：[simulation_trace.py](../../app/minigames/simulation_trace.py)；测试：[test_simulation_trace.py](../../tests/test_simulation_trace.py)。
