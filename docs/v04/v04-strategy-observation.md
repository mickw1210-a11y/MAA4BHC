# W11-12：策略观察信息边界

日期：2026-11-17。目标是让策略输入只包含适配器提供的当前可见信息；完整模拟状态、未来轨迹和随机输入留在策略接口之外。

## 契约

- `Strategy.choose_action(state=...)`的类型明确为`StrategyObservation`，不再使用泛型`object`。
- `StrategyObservation`只保存游戏ID、规则版本、观察schema和显式`visible_fields`。没有完整`SimulationState.state_data`、随机输入、seed、未来步骤、回放轨迹或测试答案字段。
- 每个字段使用`ObservedValue`。known值递归复制成不可变JSON；unknown字段继续保存原因，不补零。
- `DeterministicLegalActionBaseline`运行时拒绝完整`SimulationState`，并按观察视图、当前合法动作、已观测预算工作。
- 合法动作由规则层提供，预算来源由调用方提供。观察接口不生成动作、不连接设备。

## 验证与限制

定向测试核对策略协议类型、深层不可变视图、unknown字段往返、错误schema拒绝，并确认完整状态对象不会通过离线基线的运行时输入检查。没有游戏规则适配器或隐藏牌面实证。

| 检查 | 命令／结果 |
| --- | --- |
| 观察投影定向测试 | `& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests -p test_strategy_observation.py`：退出码0，7项通过。 |
| 基线定向回归 | `& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests -p test_baseline_strategy.py`：退出码0，8项通过。 |
| 完整Python回归 | `& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests`：退出码0，426项通过；既有负向用例打印异常日志，最终汇总为`OK`。 |
| 导入烟测 | 全新解释器导入策略接口／观察投影后，断言`app.device`和`maa`均未加载：退出码0。 |
| 换行／空白 | `git -c core.whitespace=cr-at-eol diff --check`：退出码0；未全仓改写行尾。 |

代码与测试单独本地提交`52092b5`（`Add strategy observation boundary`）。修改前恢复点见`.local/history/v04-w11-12-strategy-observation-20261117-before/manifest.json`。

**限制：**类型系统不能判断适配器提供的值在语义上是否真的可见。若适配器把隐藏牌序、未来随机量或答案放入`visible_fields`，当前通用契约无法识别；因此本项只证明接口形状和不可变容器，不代表五款游戏的数据适配已经通过。

代码：[strategy_observation.py](../../app/minigames/strategy_observation.py)；协议：[strategy_contract.py](../../app/strategy_contract.py)；测试：[test_strategy_observation.py](../../tests/test_strategy_observation.py)。
