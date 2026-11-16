import unittest

from app.minigames.simulation_search import (
    CancellationToken,
    SearchConclusion,
    SearchStopReason,
    SimulationSearchBudget,
    SimulationSearchSession,
)
from app.strategy_contract import LogicalAction


class FakeClock:
    def __init__(self, *values):
        self._values = iter(values)
        self._last = values[-1] if values else 0.0

    def __call__(self):
        return next(self._values, self._last)


class SimulationSearchTests(unittest.TestCase):
    def budget(self, *, nodes=3, depth=3, seconds=10):
        return SimulationSearchBudget(nodes, depth, seconds)

    def test_node_budget_exhaustion_returns_unknown_without_solution(self):
        session = SimulationSearchSession(self.budget(nodes=2), clock=FakeClock(0.0))
        self.assertTrue(session.try_visit(0))
        self.assertTrue(session.try_visit(1))
        self.assertFalse(session.try_visit(2))
        result = session.finish_exhaustive()
        self.assertIs(result.conclusion, SearchConclusion.UNKNOWN)
        self.assertIs(result.stop_reason, SearchStopReason.NODE_BUDGET_EXHAUSTED)
        self.assertIsNone(result.solution_path)
        self.assertEqual(result.visited_nodes, 2)

    def test_depth_limit_returns_unknown_not_proven_no_solution(self):
        session = SimulationSearchSession(
            self.budget(depth=1), clock=FakeClock(0.0),
        )
        self.assertFalse(session.try_visit(2))
        result = session.finish_exhaustive()
        self.assertIs(result.conclusion, SearchConclusion.UNKNOWN)
        self.assertIs(result.stop_reason, SearchStopReason.DEPTH_LIMIT_REACHED)

    def test_timeout_during_search_returns_unknown(self):
        clock = FakeClock(0.0, 1.0)
        session = SimulationSearchSession(
            self.budget(seconds=1), clock=clock,
        )
        self.assertFalse(session.try_visit(0))
        result = session.finish_exhaustive()
        self.assertIs(result.conclusion, SearchConclusion.UNKNOWN)
        self.assertIs(result.stop_reason, SearchStopReason.TIMEOUT)

    def test_timeout_is_checked_before_claiming_exhaustive_proof(self):
        session = SimulationSearchSession(
            self.budget(seconds=1), clock=FakeClock(0.0, 0.5, 1.0),
        )
        self.assertTrue(session.try_visit(0))
        result = session.finish_exhaustive()
        self.assertIs(result.conclusion, SearchConclusion.UNKNOWN)
        self.assertIs(result.stop_reason, SearchStopReason.TIMEOUT)

    def test_cancellation_returns_unknown_and_discards_candidate_path(self):
        token = CancellationToken()
        session = SimulationSearchSession(
            self.budget(), cancellation=token, clock=FakeClock(0.0),
        )
        self.assertTrue(session.try_visit(0))
        token.cancel()
        result = session.finish_solution((LogicalAction("match", "slot:1"),))
        self.assertTrue(token.is_cancelled)
        self.assertIs(result.conclusion, SearchConclusion.UNKNOWN)
        self.assertIs(result.stop_reason, SearchStopReason.CANCELLED)
        self.assertIsNone(result.solution_path)

    def test_solution_and_exhaustive_no_solution_remain_distinct(self):
        found = SimulationSearchSession(
            self.budget(), clock=FakeClock(0.0),
        )
        self.assertTrue(found.try_visit(0))
        path = (LogicalAction("match", "slot:1"),)
        found_result = found.finish_solution(path)
        self.assertIs(found_result.conclusion, SearchConclusion.SOLUTION_FOUND)
        self.assertEqual(found_result.solution_path, path)

        exhausted = SimulationSearchSession(
            self.budget(), clock=FakeClock(0.0),
        )
        self.assertTrue(exhausted.try_visit(0))
        no_solution = exhausted.finish_exhaustive()
        self.assertIs(no_solution.conclusion, SearchConclusion.PROVEN_NO_SOLUTION)
        self.assertIsNone(no_solution.stop_reason)

    def test_exhaustive_no_solution_requires_visiting_root(self):
        session = SimulationSearchSession(self.budget(), clock=FakeClock(0.0))
        with self.assertRaisesRegex(ValueError, "访问根局面"):
            session.finish_exhaustive()
        self.assertTrue(session.try_visit(0))
        self.assertIs(
            session.finish_exhaustive().conclusion,
            SearchConclusion.PROVEN_NO_SOLUTION,
        )

    def test_search_budget_rejects_invalid_limits(self):
        for args in ((0, 1, 1), (True, 1, 1), (1, -1, 1), (1, 1, 0),
                     (1, 1, float("inf")), (1, 1, float("nan"))):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    SimulationSearchBudget(*args)

    def test_session_rejects_invalid_depth_clock_and_budget_types(self):
        with self.assertRaisesRegex(TypeError, "SimulationSearchBudget"):
            SimulationSearchSession({}, clock=FakeClock(0.0))
        with self.assertRaisesRegex(ValueError, "depth"):
            SimulationSearchSession(self.budget(), clock=FakeClock(0.0)).try_visit(True)
        with self.assertRaisesRegex(ValueError, "clock"):
            SimulationSearchSession(self.budget(), clock=lambda: float("nan"))

    def test_clock_must_not_move_backwards(self):
        session = SimulationSearchSession(
            self.budget(), clock=FakeClock(1.0, 0.5),
        )
        with self.assertRaisesRegex(ValueError, "不能倒退"):
            session.try_visit(0)

    def test_session_cannot_continue_after_a_result_is_finalized(self):
        session = SimulationSearchSession(self.budget(), clock=FakeClock(0.0))
        self.assertTrue(session.try_visit(0))
        session.finish_solution(())
        with self.assertRaisesRegex(RuntimeError, "已结束"):
            session.try_visit(1)


if __name__ == "__main__":
    unittest.main()
