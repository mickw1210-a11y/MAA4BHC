# W03-01：设备实例身份契约

核对日期：2026-11-16。状态：离线身份契约已实现；当前 MuMu 实例的实际字段读取和生命周期稳定性尚未实测。

## 身份来源

MuMu 官方《命令行开发者使用说明》记载 `MuMuManager.exe info --vmindex ...` 的实例信息包含 `index`、`created_timestamp`，并可能包含启动时才有的 ADB 地址、PID 和窗口句柄。文档没有声称存在全局 UUID，也没有承诺创建时间戳不可变或全局唯一。[官方说明](https://mumu.163.com/help/20240726/35047_1170006.html)

本项目先按同一 Windows 主机上的协作租约定义身份键：`provider=mumu12`、`index`、`created_timestamp`。二者都必须来自 MuMuManager 实例记录；缺失或格式异常时返回“身份未知”，不以项目目录、ADB 地址、可执行文件路径、实例名称、PID 或窗口句柄补位。公开说明核实了字段存在，但未核实其在克隆、迁移、删除后重建等情况下的完整稳定性；这些边界仍待运行环境验证。

## 定位信息与身份的区分

`DeviceLocator` 保存项目根目录、ADB 可执行文件和连接地址，供后续连接流程定位目标。它们不参与 `DeviceInstanceIdentity` 相等比较或 `lease_key` 计算。同一 MuMu 实例即使从不同项目副本、不同 ADB 客户端路径或不同 ADB 端口访问，只要 MuMuManager 返回同一 `index + created_timestamp`，契约会给出同一身份。PID、窗口句柄、名称和端口改变也不会改变身份。

如果两个实例因克隆等操作保留了相同的编号和创建标记，本契约会把它们映射到同一租约键并产生保守冲突；不会放宽为并发操作。实际冲突检测与信息刷新由后续任务实现。

## 验证边界

`app/device_identity.py` 是纯数据转换，不启动 MuMuManager、不读取注册表、不运行 ADB、不连接或操作模拟器。定向测试用合成的官方字段形状验证：跨项目／端口／ADB路径同身份、同编号重建后区分、租约键稳定，以及身份字段缺失时失败关闭。该结果只证明离线契约，不证明本机当前 MuMu 版本实际输出与官方示例一致。

实现入口：[device_identity.py](../../app/device_identity.py)；离线验证：[test_device_identity.py](../../tests/test_device_identity.py)。W03-02 将消费 `lease_key` 建立跨项目进程租约；如接入时发现现场字段或生命周期与契约不一致，需先保持身份未知并阻止派发。
