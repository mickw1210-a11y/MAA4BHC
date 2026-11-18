# W11-04：合法动作枚举安全契约

日期：2026-11-16。范围：要求规则适配器对候选动作显式分类，构造绑定当前状态的合法动作集合；不定义五款游戏的具体动作，不创建空规则适配器。

## 分类与拒绝条件

`ActionCandidate`由`LogicalAction`、动作分类和规则证据引用组成。只有带非空规则证据引用的`gameplay`动作可进入`LegalActionSet`。辅助道具、购买、重开及unknown分类都会拒绝整个集合；重复逻辑动作也拒绝。不会静默过滤有问题的候选，避免把未核实动作藏在动作集生成过程中。

合法动作集绑定一份`SimulationState`及其SHA-256指纹；已验证的逻辑动作可提供给现有策略接口。空集合只表示当前枚举结果为空，不自动代表死局或正常终止，这些状态由后续任务单独定义。

## 验证与限制

定向测试覆盖允许的逻辑动作、所有禁止类别、缺失来源引用、重复动作、空集合和绕过工厂的直接构造。测试使用合成规则引用，不证明真实规则，也不验证适配器不会错误地把不安全动作伪标为普通游戏动作。当前无任何一款游戏动作适配器；五款仍保持关闭。

定向测试7项、完整Python回归372项、纯导入烟测及`git -c core.whitespace=cr-at-eol diff --check`均通过。修改前副本与SHA-256清单：`.local/history/v04-w11-04-legal-actions-20261116-before/manifest.json`。

代码：[simulation_actions.py](../../../app/minigames/simulation_actions.py)；规则接口：[simulation_contract.py](../../../app/simulation_contract.py)；测试：[test_simulation_actions.py](../../../tests/test_simulation_actions.py)。
