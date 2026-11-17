# 动作结果契约（W02-05）

代码：`app/action_result.py`。一个动作尝试只使用以下四种结果；它们表达动作是否已提交，以及后置结果是否已核实：

| 状态 | 含义 | 必需字段 | 后续处理边界 |
| --- | --- | --- | --- |
| `not_submitted` | 可确认设备动作尚未提交 | `reason` | 可在重新核对计划和画面后重新评估；不能伪装为动作失败 |
| `submitted_unknown` | 动作已提交，但无法确认游戏实际结果 | `reason` | 先重新读取游戏状态核对结果，禁止盲目重放 |
| `verified_success` | 后置条件已由动作后观察确认 | `verification_observation_id` | 可以进入依赖该结果的任务 |
| `verified_failure` | 动作后观察确认预期结果未发生 | `reason`与`verification_observation_id` | 转入错误处理；不能标记任务完成 |

所有结果都绑定非空`action_id`。未提交或结果未知必须说明原因；只有成功／失败核实状态可以引用核实观察，且必须提供观察标识。`ActionResult`本身只校验记录形状，不会读取或验证引用目标；W03-09负责产出真实后置观察，W03-08负责保存动作提交前的意图记录。

设备工具的返回码不能直接变成`verified_success`。发送前因停止、过期画面或租约失败而拒绝时用`not_submitted`；已发出但超时、断线或尚未读取实际状态时用`submitted_unknown`。只有观察证实预期后置条件才可写`verified_success`；观察证实未满足则为`verified_failure`。若无法确认动作是否已生效，按未知结果处理，先核对，不重发。

离线验证：`tests/test_action_result.py`覆盖四种状态区分、提交属性、必需原因、核实证据及未知状态拒绝。该契约未持久化，也没有连接设备；不表示W03动作日志已经实现。
