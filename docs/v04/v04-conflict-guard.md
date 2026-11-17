# W03-06：派发前冲突与画面检查契约

核对日期：2026-11-16。范围：把已知外部ADB信号、设备租约状态和动作所依赖的当前画面合并为可离线验证的前置检查；不接设备派发入口。

## 检查条件

`check_pre_dispatch()`要求：

- 设备租约状态为`ACQUIRED`，动作身份与租约身份一致；
- 外部操作者快照为`CLEAR`、结构一致且不超过1秒；`conflict`、`unknown`和过期快照均停止；
- 当前观察必须在外部扫描之后捕获，且设备身份、frame_id和page_id与动作前置完全一致；过期画面会拒绝。

通过后返回短时`KnownSignalPermit`，最多从快照时刻起有效1秒。它显式声明覆盖范围仅为默认ADB端口5037的快照，`exclusive_control_confirmed`固定为`False`，不能解释成全局设备排他。

## 验证与限制

9项定向测试覆盖租约冲突／异常、ADB conflict／unknown、快照过期／未来时间、截图顺序、设备／页面／画面变化、报文不一致和凭据过期。测试构造合成观察、身份与TCP报告，不连接设备。

当前没有任何入口实际调用此门禁；下游W03-07必须将检查放入统一取消／租约派发边界后才能声称应用内覆盖。即使接线，单次netstat扫描不能排除自定义ADB server、瞬时客户端、其他MuMu控制路径或桌面输入注入。W03-04崩溃恢复缺口也仍阻止安全接入。项目没有声称R12的任意外部软件排他已达标。

代码：[conflict_guard.py](../../app/conflict_guard.py)；离线测试：[test_conflict_guard.py](../../tests/test_conflict_guard.py)。
