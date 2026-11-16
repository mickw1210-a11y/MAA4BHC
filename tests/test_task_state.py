import unittest

from app.task_state import InvalidTaskTransition, TaskPhase, transition_task


class TaskPhaseTransitionTests(unittest.TestCase):
    def test_verified_happy_path(self):
        phase = transition_task(TaskPhase.IDLE, TaskPhase.PREPARING)
        phase = transition_task(phase, TaskPhase.RUNNING)
        phase = transition_task(phase, TaskPhase.COMPLETED, postcondition_verified=True)
        self.assertIs(phase, TaskPhase.COMPLETED)

    def test_completion_requires_verified_postcondition(self):
        with self.assertRaisesRegex(InvalidTaskTransition, "后置条件"):
            transition_task(TaskPhase.RUNNING, TaskPhase.COMPLETED)

    def test_failure_cannot_become_success(self):
        with self.assertRaises(InvalidTaskTransition):
            transition_task(TaskPhase.NEEDS_ATTENTION, TaskPhase.COMPLETED,
                            postcondition_verified=True)

    def test_energy_wake_returns_to_preparation_before_running(self):
        with self.assertRaises(InvalidTaskTransition):
            transition_task(TaskPhase.WAITING_ENERGY, TaskPhase.RUNNING)
        phase = transition_task(TaskPhase.WAITING_ENERGY, TaskPhase.PREPARING)
        self.assertIs(transition_task(phase, TaskPhase.RUNNING), TaskPhase.RUNNING)

    def test_stop_uses_stopping_state(self):
        with self.assertRaises(InvalidTaskTransition):
            transition_task(TaskPhase.RUNNING, TaskPhase.STOPPED)
        phase = transition_task(TaskPhase.RUNNING, TaskPhase.STOPPING)
        self.assertIs(transition_task(phase, TaskPhase.STOPPED), TaskPhase.STOPPED)

    def test_recovery_after_stop_or_attention_requires_user_action(self):
        for phase in (TaskPhase.STOPPED, TaskPhase.NEEDS_ATTENTION):
            with self.subTest(phase=phase):
                with self.assertRaisesRegex(InvalidTaskTransition, "显式发起"):
                    transition_task(phase, TaskPhase.PREPARING)
                self.assertIs(
                    transition_task(phase, TaskPhase.PREPARING, user_initiated=True),
                    TaskPhase.PREPARING,
                )

    def test_completed_is_terminal(self):
        with self.assertRaises(InvalidTaskTransition):
            transition_task(TaskPhase.COMPLETED, TaskPhase.PREPARING, user_initiated=True)

    def test_unknown_phase_is_rejected(self):
        with self.assertRaisesRegex(InvalidTaskTransition, "未知"):
            transition_task("not-a-phase", TaskPhase.RUNNING)


if __name__ == "__main__":
    unittest.main()
