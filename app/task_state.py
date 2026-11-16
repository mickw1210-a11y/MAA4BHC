"""Pure task lifecycle rules shared by the scheduler and UI bridge."""

from enum import Enum


class TaskPhase(str, Enum):
    IDLE = "idle"
    PREPARING = "preparing"
    RUNNING = "running"
    WAITING_ENERGY = "waiting_energy"
    NEEDS_ATTENTION = "needs_attention"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETED = "completed"


class InvalidTaskTransition(ValueError):
    """Raised when a task lifecycle transition violates the contract."""


_ALLOWED_TRANSITIONS = {
    TaskPhase.IDLE: frozenset({TaskPhase.PREPARING}),
    TaskPhase.PREPARING: frozenset({
        TaskPhase.RUNNING,
        TaskPhase.WAITING_ENERGY,
        TaskPhase.NEEDS_ATTENTION,
        TaskPhase.STOPPING,
    }),
    TaskPhase.RUNNING: frozenset({
        TaskPhase.WAITING_ENERGY,
        TaskPhase.NEEDS_ATTENTION,
        TaskPhase.STOPPING,
        TaskPhase.COMPLETED,
    }),
    TaskPhase.WAITING_ENERGY: frozenset({
        TaskPhase.PREPARING,
        TaskPhase.NEEDS_ATTENTION,
        TaskPhase.STOPPING,
    }),
    TaskPhase.NEEDS_ATTENTION: frozenset({TaskPhase.PREPARING, TaskPhase.STOPPING}),
    TaskPhase.STOPPING: frozenset({TaskPhase.STOPPED}),
    TaskPhase.STOPPED: frozenset({TaskPhase.PREPARING}),
    TaskPhase.COMPLETED: frozenset(),
}


def transition_task(
    current,
    target,
    *,
    postcondition_verified=False,
    user_initiated=False,
):
    """Return the target phase or raise when the transition is unsafe.

    A task may be marked completed only after its caller verifies the expected
    postcondition. Recovering from a stopped or attention-required state always
    requires an explicit user action. Energy waits must pass through preparing
    so the caller can re-read the current device and budget before resuming.
    """
    try:
        current = TaskPhase(current)
        target = TaskPhase(target)
    except (TypeError, ValueError):
        raise InvalidTaskTransition("任务状态未知") from None

    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidTaskTransition(
            f"不允许任务状态从 {current.value} 转为 {target.value}"
        )
    if target is TaskPhase.COMPLETED and postcondition_verified is not True:
        raise InvalidTaskTransition("核实任务后置条件后才能标记已完成")
    if (target is TaskPhase.PREPARING
            and current in {TaskPhase.NEEDS_ATTENTION, TaskPhase.STOPPED}
            and user_initiated is not True):
        raise InvalidTaskTransition("异常或停止后的恢复必须由用户显式发起")
    return target
