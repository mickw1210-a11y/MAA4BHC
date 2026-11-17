# W11-02：可序列化状态与单步随机输入

日期：2026-11-16。范围：定义不假设共同棋盘布局的模拟状态封装，并将单步随机输入接到纯规则协议；不实现任何一款小游戏的状态转移。

## 契约

- `SimulationState`包含获批`game_id`、已核实`rules_version`、游戏专属`state_schema`和不可变JSON对象`state_data`。未知或未核实的规则版本不能构造可模拟状态。
- 状态数据按规范JSON排序序列化，保留有限数值与显式结构，提供SHA-256指纹；构造时复制并冻结嵌套容器，反序列化严格校验schema。
- `SimulationRandomInput`按种子、步骤序号和抽取序号用固定版本的SHA-256计数算法生成本步的32位随机值。随机值以数组随记录保存；访问超出本步数组的抽取会失败，不提供跨步随机游标。
- `SimulationRules.apply()`现在要求接收`SimulationState`和`SimulationRandomInput`，并返回新的`SimulationState`。规则模块仍须自行按已证实机制解释随机值。
- `SimulationState.copy_for_trial()`返回内容相同、对象及嵌套快照分离的不可变副本。策略通过`to_dict()`取得独立可变工作数据，试算修改不会写回原状态或输入观察。

## 验证与限制

定向测试验证状态JSON往返、不可变快照与隔离复制、未知规则版本拒绝、种子与步骤确定性、随机记录篡改拒绝，以及测试夹具在相同状态／动作／随机输入下得到相同输出。完整回归只验证数据和协议；夹具不是任何真实小游戏规则。

五款目前都没有已核实规则版本，因此没有可由本目录构造的正式游戏模拟状态。该随机算法是项目模拟输入的可复现来源，不表示真实游戏使用相同随机生成器，也不说明游戏结果概率。隐藏信息处理、实际规则、成本、终止条件与无辅助道具死局仍未解决。

W11-03定向回归增加至9项；完整Python回归365项通过。修改前副本与SHA-256清单：`.local/history/v04-w11-03-trial-copy-20261116-before/manifest.json`。

代码：[simulation_state.py](../../app/minigames/simulation_state.py)；接口：[simulation_contract.py](../../app/simulation_contract.py)；测试：[test_simulation_state.py](../../tests/test_simulation_state.py)。
