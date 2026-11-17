# 动作意图与画面前置契约（W02-04）

代码：`app/action_contract.py`。`ActionIntent`只表示一个待评估的逻辑动作，携带动作／任务标识、动作类型、逻辑目标、显式成本状态、预期后置条件和`FrameFingerprint`。目标保留为逻辑文本，不在策略契约中存屏幕坐标。

`FrameFingerprint`包含`device_id`、`frame_id`和`page_id`。创建指纹时三项都必须是已知且非空的观察值。`frame_id`必须代表一次确切截图；采集新画面时生成新ID，不得只用“背包页”等页面类别重复充当画面ID。

调用方在任何动作派发前将待执行动作与最新的`Observation`传给`assert_action_precondition`：

- 任一当前身份字段unknown或缺少有效观察，立即拒绝。
- 设备实例变化时以`device_id_changed`拒绝。
- 截图变化时以`frame_id_changed`拒绝，即使页面类别未变，旧画面计划也失效。
- 页面身份变化时以`page_id_changed`拒绝。
- 只有设备、确切画面和页面三项完全匹配才通过。

该函数只做纯数据比较，不连接设备、不点击、不声明动作已提交，也不代替W03要求的租约、取消、统一派发和外部冲突检查。调用方必须提供刚取得并核验的当前观察。`expected_cost`仍显式使用`ObservedValue`；unknown不等于零，预算与成本是否满足由后续任务门禁处理，不能因指纹匹配就执行成本未知的动作。

离线验证：`tests/test_action_contract.py`覆盖匹配接受、新截图失效、页面变化、实例变化、三项unknown拒绝、无效观察、字段完整性及空指纹拒绝。通过仅表示此数据契约可拒绝旧画面动作；尚未接入任何设备控制器。
