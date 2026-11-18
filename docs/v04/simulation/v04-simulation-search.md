# W11-10：模拟搜索预算与中断控制

日期：2026-11-17。目标是限制纯模拟搜索消耗，并确保未完成搜索不会被报告成已证无解，也不会回退为随机动作。

## 控制边界

- `SimulationSearchBudget`同时要求正节点上限、非负深度上限和有限正时间上限。
- `SimulationSearchSession.try_visit(depth)`在节点数、深度、单调时钟到期或`CancellationToken`取消时停止新增搜索，并保存首个停止原因。
- `finish_solution()`和`finish_exhaustive()`都会再次检查取消／超时；到达预算后的结论返回`UNKNOWN`，`solution_path=None`。
- 只有未中断、至少访问根局面且调用方明确报告完整穷尽时，`finish_exhaustive()`才返回`PROVEN_NO_SOLUTION`。控制器无法独立证明搜索算法真的遍历了全部后继。
- 成功路径只由调用方传入逻辑动作；控制器不规划、不随机生成动作，也不连接设备。

## 验证

测试使用确定性假时钟与合成逻辑动作，覆盖节点／深度限制、超时、取消、在超时边界拒绝假无解、找到路径、完整穷尽结果、非法预算和会话关闭。

| 检查 | 命令／结果 |
| --- | --- |
| 定向测试 | `& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests -p test_simulation_search.py`：退出码0，11项通过。 |
| 完整Python回归 | `& .\.venv\Scripts\python.exe -W error::DeprecationWarning -m unittest discover -s tests`：退出码0，419项通过。既有负向用例打印异常日志，最终测试汇总为`OK`。 |
| 导入烟测 | 全新解释器导入预算和会话后，断言`app.device`和`maa`均未加载：退出码0。 |
| 换行／空白 | `git -c core.whitespace=cr-at-eol diff --check`：退出码0；未全仓改写行尾。 |

代码与测试单独本地提交`bdee172`（`Add bounded simulation search controls`）。修改前恢复点见`.local/history/v04-w11-10-search-limits-20261116-before/manifest.json`。

此模块不包含状态枚举、启发式或实际小游戏规则，因此不构成搜索性能或无解证明。五款规则版本仍unknown。

代码：[simulation_search.py](../../../app/minigames/simulation_search.py)；测试：[test_simulation_search.py](../../../tests/test_simulation_search.py)。
