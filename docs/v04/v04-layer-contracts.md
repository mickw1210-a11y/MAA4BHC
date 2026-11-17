# 策略、模拟与执行接口边界（W02-08）

| 层 | 接口 | 输入与输出 | 设备能力 |
| --- | --- | --- | --- |
| 纯策略 | `Strategy`、`StrategyDecision` | 已观察状态、合法`LogicalAction`、显式预算值；返回一个逻辑动作或明确暂停原因 | 不含截图、坐标、ADB或设备控制器 |
| 规则模拟 | `SimulationRules` | 查询合法逻辑动作；对单个动作和本步显式随机输入计算下一状态 | 不读取设备，不偷看未来随机序列 |
| 设备执行 | `DeviceExecutor` | 收到绑定`FrameFingerprint`的`ActionIntent`及当前观察，返回`ActionResult` | 仅定义协议；本任务没有具体设备适配器 |

模块分别位于`app/strategy_contract.py`、`app/simulation_contract.py`、`app/execution_contract.py`。策略与模拟使用不含设备坐标的`LogicalAction`；待执行动作由后续协调层绑定当前设备／截图／页面指纹后成为`ActionIntent`。工具返回不直接等同成功，结果使用W02-05的`ActionResult`契约。

执行协议本身不提供设备租约、取消令牌或安全派发实现。W03必须将这些强制检查接入所有设备入口后，才可能新增具体执行器。当前没有任何小游戏的模拟器或策略实现；缺规则时保留能力关闭，不用空适配器填充。

离线验证：`tests/test_layer_contracts.py`验证策略结果必须是动作或明确暂停、目标为逻辑值，并在全新解释器依次导入三层接口后确认`app.device`与`maa`控制器包均未加载。通过只证明模块导入边界，不证明任何游戏玩法或设备操作完成。
