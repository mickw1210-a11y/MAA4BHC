"""Immutable task dependency graphs with deterministic cycle diagnostics."""

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass


class TaskDependencyError(ValueError):
    """Raised for malformed or cyclic task dependency declarations."""

    def __init__(self, code, message, *, task_id=None, dependency_id=None, cycle=()):
        self.code = code
        self.task_id = task_id
        self.dependency_id = dependency_id
        self.cycle = tuple(cycle)
        super().__init__(message)


@dataclass(frozen=True)
class TaskDependencyGraph:
    """Validated dependencies and their dependency-first execution order."""

    dependencies: tuple
    execution_order: tuple

    def dependencies_for(self, task_id):
        for current_id, dependency_ids in self.dependencies:
            if current_id == task_id:
                return dependency_ids
        raise KeyError(task_id)


def _require_task_id(value, field_name):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise TaskDependencyError("invalid_task_id", f"{field_name}必须是非空且无首尾空格的文本")


def _find_cycle(dependencies):
    state = {}
    for start in dependencies:
        if state.get(start, 0) != 0:
            continue
        path = [start]
        positions = {start: 0}
        state[start] = 1
        stack = [(start, iter(dependencies[start]))]
        while stack:
            task_id, dependency_iter = stack[-1]
            try:
                dependency_id = next(dependency_iter)
            except StopIteration:
                stack.pop()
                state[task_id] = 2
                path.pop()
                positions.pop(task_id)
                continue
            if dependency_id in positions:
                return tuple(path[positions[dependency_id]:] + [dependency_id])
            if state.get(dependency_id, 0) == 0:
                state[dependency_id] = 1
                positions[dependency_id] = len(path)
                path.append(dependency_id)
                stack.append((dependency_id, iter(dependencies[dependency_id])))
    return ()


def validate_task_dependencies(task_dependencies):
    """Return an immutable DAG or raise a specific error with the cause."""
    if not isinstance(task_dependencies, Mapping):
        raise TaskDependencyError("invalid_graph", "任务依赖必须是任务ID到依赖列表的映射")

    normalized = {}
    for task_id, dependency_ids in task_dependencies.items():
        _require_task_id(task_id, "task_id")
        if task_id in normalized:
            raise TaskDependencyError("duplicate_task", f"任务ID重复：{task_id}", task_id=task_id)
        if not isinstance(dependency_ids, (list, tuple)):
            raise TaskDependencyError(
                "invalid_dependencies",
                f"任务{task_id}的依赖必须是列表或元组",
                task_id=task_id,
            )
        seen = set()
        normalized_dependencies = []
        for dependency_id in dependency_ids:
            _require_task_id(dependency_id, f"任务{task_id}的dependency_id")
            if dependency_id in seen:
                raise TaskDependencyError(
                    "duplicate_dependency",
                    f"任务{task_id}重复声明依赖{dependency_id}",
                    task_id=task_id,
                    dependency_id=dependency_id,
                )
            seen.add(dependency_id)
            if dependency_id == task_id:
                raise TaskDependencyError(
                    "self_dependency",
                    f"任务{task_id}不能依赖自身",
                    task_id=task_id,
                    dependency_id=dependency_id,
                )
            normalized_dependencies.append(dependency_id)
        normalized[task_id] = tuple(normalized_dependencies)

    for task_id, dependency_ids in normalized.items():
        for dependency_id in dependency_ids:
            if dependency_id not in normalized:
                raise TaskDependencyError(
                    "missing_task",
                    f"任务{task_id}依赖不存在的任务{dependency_id}",
                    task_id=task_id,
                    dependency_id=dependency_id,
                )

    cycle = _find_cycle(normalized)
    if cycle:
        display = " -> ".join(cycle)
        raise TaskDependencyError("cycle", f"任务依赖存在循环：{display}", cycle=cycle)

    indegree = {task_id: len(dependency_ids) for task_id, dependency_ids in normalized.items()}
    dependents = {task_id: [] for task_id in normalized}
    for task_id, dependency_ids in normalized.items():
        for dependency_id in dependency_ids:
            dependents[dependency_id].append(task_id)

    ready = deque(task_id for task_id in normalized if indegree[task_id] == 0)
    execution_order = []
    while ready:
        completed_id = ready.popleft()
        execution_order.append(completed_id)
        for dependent_id in dependents[completed_id]:
            indegree[dependent_id] -= 1
            if indegree[dependent_id] == 0:
                ready.append(dependent_id)

    return TaskDependencyGraph(
        dependencies=tuple(normalized.items()),
        execution_order=tuple(execution_order),
    )
