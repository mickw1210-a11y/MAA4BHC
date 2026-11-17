# 任务依赖图契约（W02-06）

代码：`app/task_dependencies.py`。调用方提供`task_id -> dependency_ids`映射；每个任务的依赖必须是列表或元组。验证器复制为不可变元组并返回依赖在前的稳定执行顺序，不保留调用方可修改的列表。

发现以下问题会抛出`TaskDependencyError`，并提供稳定的`code`及相关ID：

- `self_dependency`：任务依赖自身，记录任务ID。
- `missing_task`：依赖的任务没有出现在映射中，同时记录依赖方和缺失ID。
- `cycle`：存在循环，附带可重放的闭合路径，例如`scan -> play -> identity -> scan`。
- `duplicate_dependency`、`invalid_dependencies`、`invalid_task_id`：输入结构或标识无效，并指出具体任务。

任务依赖不是执行结果；图有效只表示计划无自依赖、缺失节点或循环。运行调度器仍需检查依赖任务已完成且结果核实，不能仅按拓扑顺序就运行游戏动作。当前代码是纯校验，不连接UI或设备；W02-10会在离线任务样例中验证错误原因和状态边界。

离线验证：`tests/test_task_dependencies.py`覆盖有效排序、自依赖、缺失任务、循环闭合路径、重复依赖、错误输入类型、无效ID、输入变更隔离和空图。
