# 观察数据契约（W02-03）

代码：`app/observation.py`。`Observation` 是一次带时区时间的不可变观察；实例、角色、活动、规则版本、画面、页面、棋盘和小游戏体力全部必须显式给出已观测值或unknown原因。棋盘对象和数组在构造时深拷贝为不可变容器，调用方后续修改原始输入不会改写这次观察；序列化时再还原为普通JSON对象和数组。构造器没有身份、页面或体力默认值。

`ObservedValue.observed(0)` 表示读到数值零；`ObservedValue.unknown("energy_not_read")` 表示没有可靠读数。两者的 JSON 结构不同，`unknown_fields` 由字段状态生成，反序列化时会校验一致性。观察时间必须带时区，身份文本非空；energy只接受非负整数。

当前契约：

| 字段 | 类型要求 | 未知时的处理 |
| --- | --- | --- |
| `observed_at` | 有时区的 `datetime`，不得默认 | 不允许unknown；缺时间不能伪装成有效观察 |
| `device_id` | 非空文本 | unknown时真实设备动作必须由后续执行门禁拦截 |
| `character_id` | 非空文本 | 保持unknown；不借用上次角色 |
| `activity_id` | 非空文本 | 保持unknown；不借用旧活动 |
| `rules_version` | 非空文本 | 保持unknown；不能假定模拟器或策略版本 |
| `frame_id` | 非空文本 | 保持unknown；旧画面动作失效规则见W02-04 |
| `page_id` | 非空文本 | 保持unknown；页面身份未确定时不允许业务执行 |
| `board` | JSON可序列化的观测值 | unknown时保留原因，不构造空盘 |
| `energy` | 非负整数，0有效 | unknown时没有预算判断依据，不允许消耗 |

序列化包含整数 `schema_version=1`、时区时间、字段状态和 `unknown_fields`；布尔值 `true` 不会因Python将其视作整数子类而被接受为版本1。棋盘只接受有限数字、文本键及JSON值，不会把值自动转字符串来“修复”无效数据。此模型目前尚未接入 Bridge 或正式库存；W02-10会把它接到离线状态样例，W03／W04再补实机身份和页面检查。

验证：`tests/test_observation.py` 覆盖0与unknown区别、JSON往返、必填字段、时区、身份文本、体力类型／范围、unknown索引一致性、嵌套棋盘快照不可变、无效JSON值拒绝及严格版本类型。
