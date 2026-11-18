# 任务状态与转换契约（W02-02）

代码：`app/task_state.py`。纯状态机尚未接入 Bridge 或首页；W02-10 会用离线样例验证并接入。当前 Bridge 的连接状态仍是独立旧字段，不把它冒充为完整任务状态。

| 状态 | 含义 | 可进入的后续状态 |
| --- | --- | --- |
| `idle` | 尚未开始任务 | `preparing` |
| `preparing` | 核对设备、页面、身份、规则、预算和上次未决结果 | `running`、`waiting_energy`、`needs_attention`、`stopping` |
| `running` | 执行已批准的一项任务 | `waiting_energy`、`needs_attention`、`stopping`、核实后`completed` |
| `waiting_energy` | 当前体力不足或达到用户保留阈值 | `preparing`、`needs_attention`、`stopping` |
| `needs_attention` | 识别、动作结果、配置或保存需要处理 | 用户显式发起后`preparing`，或`stopping` |
| `stopping` | 已请求停止，正在取消排队并核对在途操作 | `stopped` |
| `stopped` | 本轮已停止，不会自动恢复 | 用户显式发起后`preparing` |
| `completed` | 任务预期结果已核实；终态 | 无 |

实现规则：

- 非法转换抛出 `InvalidTaskTransition`，调用方必须保留当前状态并报告具体原因。
- 只有从 `running` 才能进入 `completed`，且调用方必须提供 `postcondition_verified=True`。失败／结果不明走 `needs_attention`，不能直达成功。
- 体力等待唤醒先返回 `preparing`，重新读取实际页面、体力、活动及预算，再决定是否运行。
- 从 `stopped` 或 `needs_attention` 恢复到 `preparing` 必须由用户显式发起；打开程序、计时器、恢复线程不得自动续跑。
- `stopping` 统一过渡到 `stopped`，避免状态提前显示完全停止；在途动作仍须单独核查结果。
- `postcondition_verified` 是调用方的断言入口，不是证据生成器。必须由后续执行层附上实际前后状态证据，不能仅凭点击／ADB返回成功传入真值。

离线验证：`tests/test_task_state.py` 覆盖正常完成、无验证禁止成功、失败无法直达成功、等待唤醒重检、停止阶段、显式恢复和终态不可复用。此状态机测试不证明设备状态读取、用户界面或实机动作已接通。
