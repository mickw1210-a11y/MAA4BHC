import unittest

from app.task_dependencies import (
    TaskDependencyError,
    validate_task_dependencies,
)


class TaskDependencyGraphTests(unittest.TestCase):
    def test_valid_graph_returns_dependency_first_order(self):
        graph = validate_task_dependencies({
            "combined": ["inventory", "activity"],
            "inventory": [],
            "activity": ["identity"],
            "identity": [],
        })
        positions = {task_id: index for index, task_id in enumerate(graph.execution_order)}
        for task_id, dependencies in graph.dependencies:
            for dependency_id in dependencies:
                self.assertLess(positions[dependency_id], positions[task_id])
        self.assertEqual(graph.dependencies_for("combined"), ("inventory", "activity"))

    def test_self_dependency_is_rejected_with_task_id(self):
        with self.assertRaisesRegex(TaskDependencyError, "不能依赖自身") as raised:
            validate_task_dependencies({"scan": ["scan"]})
        self.assertEqual(raised.exception.code, "self_dependency")
        self.assertEqual(raised.exception.task_id, "scan")

    def test_missing_dependency_is_rejected_with_both_ids(self):
        with self.assertRaisesRegex(TaskDependencyError, "依赖不存在") as raised:
            validate_task_dependencies({"play": ["preflight"]})
        self.assertEqual(raised.exception.code, "missing_task")
        self.assertEqual(raised.exception.task_id, "play")
        self.assertEqual(raised.exception.dependency_id, "preflight")

    def test_cycle_is_rejected_with_a_replayable_path(self):
        with self.assertRaisesRegex(TaskDependencyError, "存在循环") as raised:
            validate_task_dependencies({
                "scan": ["play"],
                "play": ["identity"],
                "identity": ["scan"],
            })
        self.assertEqual(raised.exception.code, "cycle")
        self.assertEqual(raised.exception.cycle, ("scan", "play", "identity", "scan"))

    def test_duplicate_dependency_is_rejected(self):
        with self.assertRaisesRegex(TaskDependencyError, "重复声明") as raised:
            validate_task_dependencies({"play": ["identity", "identity"], "identity": []})
        self.assertEqual(raised.exception.code, "duplicate_dependency")

    def test_dependency_input_must_be_a_sequence_not_a_string(self):
        with self.assertRaisesRegex(TaskDependencyError, "列表或元组") as raised:
            validate_task_dependencies({"play": "identity", "identity": []})
        self.assertEqual(raised.exception.code, "invalid_dependencies")

    def test_invalid_task_ids_are_rejected(self):
        for graph_data in ({" ": []}, {"play": [" identity"]}):
            with self.subTest(graph_data=graph_data):
                with self.assertRaisesRegex(TaskDependencyError, "task_id|dependency_id"):
                    validate_task_dependencies(graph_data)

    def test_graph_does_not_retain_mutable_input_lists(self):
        source = {"play": ["identity"], "identity": []}
        graph = validate_task_dependencies(source)
        source["play"].clear()
        self.assertEqual(graph.dependencies_for("play"), ("identity",))

    def test_empty_graph_is_valid(self):
        graph = validate_task_dependencies({})
        self.assertEqual(graph.dependencies, ())
        self.assertEqual(graph.execution_order, ())


if __name__ == "__main__":
    unittest.main()
