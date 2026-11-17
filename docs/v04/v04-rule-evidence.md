# W11-01：规则版本与证据字段

日期：2026-11-16。范围：为五款小游戏建立只读证据目录，逐项区分来源直接记载、模拟假设和未知；不建立规则转移、不创建空适配器，也不连接设备。

## 数据契约

`app.minigames.rule_evidence`为五款获批游戏提供不可变的`RuleEvidenceProfile`：

- `rule_version`显式表示当前版本、渠道／区服和活动轮次；当前五款均为`unknown`，没有推测值。
- `source_reported`保存来源原话所支持的有限线索、来源类型和限制。它不等于当前官服画面已核实，也不自动成为模拟规则。
- `assumption`必须写出假设内容及依据说明，并与来源事实分开；当前没有已启用模拟，因此生产目录的假设列表为空。
- `unknown`必须带具体原因，不能存入猜测值。
- `build_simulation_assumption_report()`为五款分别返回规则版本和已用假设，结果可序列化为JSON。未知游戏ID与重复游戏ID都会拒绝。

目录中的来源ID沿用`docs/v04/minigame-rules/README.md`：O2为官方烤串大师宣传类别；C1、C2、C3为三篇玩家经验。玩家经验保留为`source_reported`，没有提升为已核实游戏机制。糖果派对目前没有可用的规则线索。

## 当前未知字段

五款分别登记活动身份、棋盘／容器、可见信息、输入方式、合法动作、成本、补入、结算、计分目标、终止条件、辅助道具、重开后果和体力行为。来源线索不会覆盖这些未知项，除非证据明确支持该字段本身。

## 验证边界

定向测试验证五款白名单、版本unknown、来源字段限制、假设报告序列化与未知／重复ID拒绝。该目录不改变`app.game_capability`中的规则未核实状态，不满足模拟或无辅助道具死局验收，不开放任何真实执行。

代码：[rule_evidence.py](../../app/minigames/rule_evidence.py)；测试：[test_rule_evidence.py](../../tests/test_rule_evidence.py)；研究来源：[五款规则研究索引](minigame-rules/README.md)。
