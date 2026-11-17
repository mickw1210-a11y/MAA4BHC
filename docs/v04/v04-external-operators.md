# W03-05：外部操作者与可检测信号

核对日期：2026-11-16。此项盘点已知信号并实现只读快照探针；探针尚未接到设备派发入口。

## 已确认的控制路径

- 当前m4b设备入口包括MuMu `adb.exe`、MaaFramework `AdbController`和`adb shell input touchscreen swipe`。调用链见[W02设备调用链](v04-device-call-chain.md)。这些是本项目的已知路径；W03-07仍需统一租约和取消门禁。
- Android官方说明：ADB客户端通过本机TCP 5037联系ADB server；同一server接受多个客户端，并能让任意客户端或脚本控制已连接设备。[ADB官方说明](https://developer.android.com/tools/adb)
- MuMu官方开发文档说明可从命令行用ADB连接实例，并可在产品中查看ADB端口。[MuMu开发者手册](https://www.mumuplayer.com/help/win/developers-essentials-manual.html)、[MuMu更新说明](https://www.mumuplayer.com/update/)。这证明ADB是公开控制入口，不证明本机运行的任何`adb.exe`一定正在控制目标实例。
- Microsoft文档说明`netstat -o`可以给活动TCP连接列出PID。[netstat官方文档](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/netstat)

## 探针与停止条件

`app/external_operator_probe.py`在Windows上运行`%SystemRoot%\System32\netstat.exe -ano -p tcp`的一次只读快照，查找远端端口为5037且状态为`ESTABLISHED`的客户端PID。调用方必须显式登记本任务拥有的PID；其他PID返回`conflict`，快照无法运行／解析时返回`unknown`。后续派发集成应对两种状态都停止，并仅将`clear`理解为“本次快照没有观察到未登记客户端”。

所有扫描只产生PID和状态，不记录命令行、可执行文件路径或ADB地址。模块没有杀进程、建立ADB连接、发送设备命令或启用后台轮询。

## 覆盖边界与本机观察

- 5037是ADB默认server端口。自定义ADB server端口、短暂到快照之间已结束的命令、直接连接MuMu实例的其他ADB server、MuMu其他控制入口，以及桌面鼠标／键盘注入，不一定出现在此快照中。
- Windows可列出TCP端点及PID，但当前资料和探针无法证明某个PID何时会发送游戏动作；进程列表不等于可靠的输入来源证明。没有发现活动连接不能证明设备独占。W03-06还需结合屏幕／页面变化检查；也不能声称阻止任意非协作软件。
- 本机只读快照：系统相关进程列表中观察到`adb`及多个MuMu组件名；这些名字未映射到目标实例或实际操作。`Get-NetTCPConnection`本次因CIM异常不可用。`netstat -ano -p tcp`的单次快照未观察到远端5037的`ESTABLISHED`客户端；这只代表采样瞬间，没有保留PID／命令行／路径，也不构成无外部控制证明。

代码：[external_operator_probe.py](../../app/external_operator_probe.py)；验证：[test_external_operator_probe.py](../../tests/test_external_operator_probe.py)。
