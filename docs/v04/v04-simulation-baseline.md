# W11-09：确定性合法动作比较基线

日期：2026-11-16。此基线只用于模拟中的比较，不连接设备、不提交动作、不承诺无死局。

## 选择规则

- 输入必须是`StrategyObservation`、通过合法动作校验得到的`LogicalAction`元组，以及资源预算映射。观察视图只保存适配器明确提供的可见字段，不包含完整`SimulationState`、轨迹或随机输入。
- 所有预算字段必须显式已知且为有限非负数；预算缺失或任一项unknown时返回暂停原因。
- 没有候选时返回`no_candidates`。这只是策略无法给出动作，不自动转换为episode的无合法动作结果。
- 候选存在时按`(kind, target)`稳定排序，选择字典序第一项。结果不依赖动作枚举到达的顺序，也不使用随机选择。

## 成本和执行边界

基线目前没有每个候选动作对应的成本输入，因此它只给出比较候选，不能判断候选是否符合剩余预算。模拟器须通过规则转移核实成本，再决定是否可在虚拟状态中应用；unknown成本或超过阈值应保留为unknown／阈值停止。策略结果不构成真实动作授权。

基线不读取轨迹未来状态、随机输入或隐藏信息；输入仍限于当前观察、当前合法动作和已观测预算。适配器仍需证明没有把隐藏信息塞入可见字段。它不体现游戏知识，不是五款小游戏中的可用策略，也不能证明不出现死局。

## 验证

| 检查 | 命令／结果 |
| --- | --- |
| 定向测试 | `& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests -p test_baseline_strategy.py`：退出码0，8项通过。 |
| 完整Python回归 | `& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests`：退出码0，408项通过。既有负向用例打印异常日志，最终测试汇总为`OK`。 |
| 导入烟测 | 全新解释器导入基线后，断言`app.device`和`maa`均未加载：退出码0。 |
| 换行／空白 | `git -c core.whitespace=cr-at-eol diff --check`：退出码0；未全仓改写行尾。 |

代码和测试单独本地提交`d4d97ad`（`Add deterministic simulation baseline strategy`）。修改前恢复点见`.local/history/v04-w11-09-baseline-strategy-20261116-before/manifest.json`。

代码：[baseline_strategy.py](../../app/minigames/baseline_strategy.py)；测试：[test_baseline_strategy.py](../../tests/test_baseline_strategy.py)。
