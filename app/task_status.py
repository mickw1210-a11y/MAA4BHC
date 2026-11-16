"""Small user-facing task status view model for UI consumers."""

from dataclasses import dataclass

from app.task_state import TaskPhase


_STATUS_TEXT = {
    TaskPhase.IDLE: ("待开始", "选择一个任务后开始。"),
    TaskPhase.PREPARING: ("准备中", "正在核对设备、页面和任务条件。"),
    TaskPhase.RUNNING: ("运行中", "任务正在执行，可随时停止。"),
    TaskPhase.WAITING_ENERGY: (
        "等待体力",
        "等待期间不会操作模拟器；恢复前会重新核对体力和页面。",
    ),
    TaskPhase.NEEDS_ATTENTION: ("需要处理", "任务已暂停，处理原因如下。"),
    TaskPhase.STOPPING: ("正在停止", "正在取消后续操作并核对已发出的动作。"),
    TaskPhase.STOPPED: ("已停止", "任务已停止，不会自动恢复。"),
    TaskPhase.COMPLETED: ("已完成", "任务结果已经核实。"),
}


@dataclass(frozen=True)
class TaskStatusView:
    phase: TaskPhase
    label: str
    message: str
    reason: str | None = None

    def to_dict(self):
        return {
            "phase": self.phase.value,
            "label": self.label,
            "message": self.message,
            "reason": self.reason,
        }


def describe_task_status(phase, *, reason=None):
    try:
        phase = TaskPhase(phase)
    except (TypeError, ValueError):
        raise ValueError("任务状态未知") from None
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        raise ValueError("reason必须是非空文本")
    if phase is TaskPhase.NEEDS_ATTENTION and reason is None:
        raise ValueError("需要处理状态必须提供用户可理解的原因")
    label, message = _STATUS_TEXT[phase]
    return TaskStatusView(phase=phase, label=label, message=message, reason=reason)
