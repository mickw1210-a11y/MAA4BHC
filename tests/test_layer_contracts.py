import subprocess
import sys
import unittest
from pathlib import Path

from app.strategy_contract import LogicalAction, StrategyDecision


class LayerBoundaryTests(unittest.TestCase):
    def test_strategy_decision_is_action_or_explicit_pause(self):
        action = LogicalAction("select", "slot:2")
        self.assertEqual(StrategyDecision(action=action).action, action)
        self.assertEqual(StrategyDecision(pause_reason="no_safe_action").pause_reason,
                         "no_safe_action")
        with self.assertRaisesRegex(ValueError, "同时返回"):
            StrategyDecision(action=action, pause_reason="pause")
        with self.assertRaisesRegex(ValueError, "pause_reason"):
            StrategyDecision()

    def test_logical_action_uses_nonempty_logical_target(self):
        with self.assertRaisesRegex(ValueError, "target"):
            LogicalAction("select", " ")

    def test_pure_interfaces_import_without_loading_device_controller(self):
        project_root = Path(__file__).resolve().parents[1]
        script = (
            "import sys; "
            "import app.strategy_contract; "
            "import app.simulation_contract; "
            "import app.execution_contract; "
            "assert not any(name == 'app.device' or name.startswith('app.device.') "
            "for name in sys.modules); "
            "assert not any(name == 'maa' or name.startswith('maa.') "
            "for name in sys.modules)"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
