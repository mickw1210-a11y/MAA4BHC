"""Bounded, cancellable control contract for offline simulation searches."""

import time
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from threading import Event

from app.strategy_contract import LogicalAction


class SearchConclusion(str, Enum):
    SOLUTION_FOUND = "solution_found"
    PROVEN_NO_SOLUTION = "proven_no_solution"
    UNKNOWN = "unknown"


class SearchStopReason(str, Enum):
    NODE_BUDGET_EXHAUSTED = "node_budget_exhausted"
    DEPTH_LIMIT_REACHED = "depth_limit_reached"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class SimulationSearchBudget:
    node_limit: int
    depth_limit: int
    time_limit_seconds: float

    def __post_init__(self):
        if type(self.node_limit) is not int or self.node_limit <= 0:
            raise ValueError("node_limit必须是正整数")
        if type(self.depth_limit) is not int or self.depth_limit < 0:
            raise ValueError("depth_limit必须是非负整数")
        if (type(self.time_limit_seconds) not in (int, float)
                or self.time_limit_seconds <= 0
                or (type(self.time_limit_seconds) is float
                    and not isfinite(self.time_limit_seconds))):
            raise ValueError("time_limit_seconds必须是有限正数")


@dataclass(frozen=True, slots=True)
class SimulationSearchResult:
    conclusion: SearchConclusion
    visited_nodes: int
    solution_path: tuple = None
    stop_reason: SearchStopReason = None

    def __post_init__(self):
        if not isinstance(self.conclusion, SearchConclusion):
            raise TypeError("conclusion必须是SearchConclusion")
        if type(self.visited_nodes) is not int or self.visited_nodes < 0:
            raise ValueError("visited_nodes必须是非负整数")
        if self.solution_path is not None and (
            not isinstance(self.solution_path, tuple)
            or any(not isinstance(action, LogicalAction) for action in self.solution_path)
        ):
            raise TypeError("solution_path必须是LogicalAction元组或None")

        if self.conclusion is SearchConclusion.SOLUTION_FOUND:
            if self.solution_path is None or self.stop_reason is not None:
                raise ValueError("找到解必须有路径且不能带停止原因")
        elif self.conclusion is SearchConclusion.PROVEN_NO_SOLUTION:
            if self.solution_path is not None or self.stop_reason is not None:
                raise ValueError("已证无解不能带路径或中断原因")
        else:
            if self.solution_path is not None:
                raise ValueError("unknown搜索结果不能返回动作路径")
            if not isinstance(self.stop_reason, SearchStopReason):
                raise ValueError("unknown搜索结果必须记录停止原因")


class CancellationToken:
    """Thread-safe cooperative cancellation signal checked at search boundaries."""

    def __init__(self):
        self._event = Event()

    def cancel(self):
        self._event.set()

    @property
    def is_cancelled(self):
        return self._event.is_set()


class SimulationSearchSession:
    """Count node visits and turn every incomplete search into an unknown result."""

    def __init__(self, budget, *, cancellation=None, clock=None):
        if not isinstance(budget, SimulationSearchBudget):
            raise TypeError("budget必须是SimulationSearchBudget")
        if cancellation is not None and not isinstance(cancellation, CancellationToken):
            raise TypeError("cancellation必须是CancellationToken或None")
        if clock is None:
            clock = time.monotonic
        if not callable(clock):
            raise TypeError("clock必须可调用")

        self._budget = budget
        self._cancellation = cancellation or CancellationToken()
        self._clock = clock
        self._started_at = self._read_clock()
        self._last_clock_value = self._started_at
        self._visited_nodes = 0
        self._stop_reason = None
        self._closed = False

    @property
    def visited_nodes(self):
        return self._visited_nodes

    @property
    def stop_reason(self):
        return self._stop_reason

    def try_visit(self, depth):
        self._require_open()
        if type(depth) is not int or depth < 0:
            raise ValueError("depth必须是非负整数")
        if self._poll_interruption() is not None:
            return False
        if depth > self._budget.depth_limit:
            self._stop_reason = SearchStopReason.DEPTH_LIMIT_REACHED
            return False
        if self._visited_nodes >= self._budget.node_limit:
            self._stop_reason = SearchStopReason.NODE_BUDGET_EXHAUSTED
            return False
        self._visited_nodes += 1
        return True

    def finish_solution(self, solution_path):
        self._require_open()
        if (not isinstance(solution_path, tuple)
                or any(not isinstance(action, LogicalAction) for action in solution_path)):
            raise TypeError("solution_path必须是LogicalAction元组")
        stop_reason = self._poll_interruption()
        if stop_reason is not None:
            return self._finish_unknown(stop_reason)
        self._closed = True
        return SimulationSearchResult(
            SearchConclusion.SOLUTION_FOUND,
            self._visited_nodes,
            solution_path=solution_path,
        )

    def finish_exhaustive(self):
        """Record caller-asserted exhaustive coverage, unless an interrupt occurred."""
        self._require_open()
        stop_reason = self._poll_interruption()
        if stop_reason is not None:
            return self._finish_unknown(stop_reason)
        if self._visited_nodes == 0:
            raise ValueError("至少访问根局面后才能记录穷尽搜索")
        self._closed = True
        return SimulationSearchResult(
            SearchConclusion.PROVEN_NO_SOLUTION,
            self._visited_nodes,
        )

    def _poll_interruption(self):
        if self._stop_reason is not None:
            return self._stop_reason
        if self._cancellation.is_cancelled:
            self._stop_reason = SearchStopReason.CANCELLED
            return self._stop_reason
        now = self._read_clock()
        if now < self._last_clock_value:
            raise ValueError("monotonic clock不能倒退")
        self._last_clock_value = now
        if now - self._started_at >= self._budget.time_limit_seconds:
            self._stop_reason = SearchStopReason.TIMEOUT
        return self._stop_reason

    def _read_clock(self):
        value = self._clock()
        if (type(value) not in (int, float)
                or (type(value) is float and not isfinite(value))):
            raise ValueError("clock必须返回有限数字")
        return value

    def _finish_unknown(self, reason):
        self._closed = True
        return SimulationSearchResult(
            SearchConclusion.UNKNOWN,
            self._visited_nodes,
            stop_reason=reason,
        )

    def _require_open(self):
        if self._closed:
            raise RuntimeError("搜索会话已结束")
