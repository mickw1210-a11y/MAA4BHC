import unittest
from datetime import datetime, timezone

from app.action_contract import (
    ActionIntent,
    ActionPreconditionError,
    FrameFingerprint,
    assert_action_precondition,
)
from app.action_result import ActionOutcome, ActionResult
from app.game_capability import CapabilityState, initial_game_capabilities
from app.observation import Observation, ObservedValue
from app.storage_contract import (
    RetryableStorageError,
    StorageCommitRequest,
    StorageReceipt,
    retry_storage_commit,
)
from app.strategy_contract import LogicalAction, StrategyDecision
from app.task_dependencies import validate_task_dependencies
from app.task_state import InvalidTaskTransition, TaskPhase, transition_task
from app.task_status import describe_task_status


def make_observation(frame_id="frame-1"):
    return Observation(
        observed_at=datetime(2026, 11, 16, tzinfo=timezone.utc),
        device_id=ObservedValue.observed("synthetic-device"),
        character_id=ObservedValue.unknown("identity_not_read"),
        activity_id=ObservedValue.unknown("activity_not_open"),
        rules_version=ObservedValue.unknown("rules_not_verified"),
        frame_id=ObservedValue.observed(frame_id),
        page_id=ObservedValue.observed("synthetic-page"),
        board=ObservedValue.unknown("synthetic_state_not_read"),
        energy=ObservedValue.unknown("energy_not_read"),
    )


def make_action(observation):
    logical = LogicalAction("select", "slot:1")
    return ActionIntent(
        action_id="action-1",
        task_id="task-1",
        kind=logical.kind,
        target=logical.target,
        expected_cost=ObservedValue.observed(1),
        expected_postcondition="slot-1-selected",
        precondition=FrameFingerprint.from_observation(observation),
    )


class FakeExecutor:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def submit(self, action, current_observation):
        self.calls += 1
        return self.result


class RetryOnceCommitter:
    def __init__(self):
        self.requests = []

    def commit(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            raise RetryableStorageError("synthetic storage busy")
        return StorageReceipt(request.commit_id, request.payload_sha256)


class TaskContractFlowTests(unittest.TestCase):
    def test_success_and_storage_retry_complete_without_resubmitting_action(self):
        graph = validate_task_dependencies({"run": ["preflight"], "preflight": []})
        self.assertEqual(graph.execution_order, ("preflight", "run"))
        self.assertTrue(all(
            item.state is CapabilityState.RULES_UNVERIFIED
            for item in initial_game_capabilities()
        ))

        phase = transition_task(TaskPhase.IDLE, TaskPhase.PREPARING)
        observation = make_observation()
        action = make_action(observation)
        decision = StrategyDecision(action=LogicalAction(action.kind, action.target))
        self.assertEqual(decision.action.target, action.target)
        assert_action_precondition(action, observation)
        phase = transition_task(phase, TaskPhase.RUNNING)

        executor = FakeExecutor(ActionResult(
            action.action_id,
            ActionOutcome.VERIFIED_SUCCESS,
            verification_observation_id="frame-after-1",
        ))
        result = executor.submit(action, observation)
        phase = transition_task(
            phase,
            TaskPhase.COMPLETED,
            postcondition_verified=result.is_verified and result.outcome is ActionOutcome.VERIFIED_SUCCESS,
        )

        request = StorageCommitRequest("commit-1", "observation-1", b"synthetic result")
        receipt = retry_storage_commit(RetryOnceCommitter(), request, max_attempts=2)
        self.assertEqual(receipt.commit_id, request.commit_id)
        self.assertEqual(executor.calls, 1)
        self.assertEqual(describe_task_status(phase).to_dict()["label"], "已完成")

    def test_energy_wait_requires_recheck_before_running(self):
        phase = transition_task(TaskPhase.IDLE, TaskPhase.PREPARING)
        phase = transition_task(phase, TaskPhase.WAITING_ENERGY)
        view = describe_task_status(phase)
        self.assertEqual(view.label, "等待体力")
        self.assertIn("不会操作模拟器", view.message)
        with self.assertRaises(InvalidTaskTransition):
            transition_task(phase, TaskPhase.RUNNING)
        phase = transition_task(phase, TaskPhase.PREPARING)
        self.assertIs(transition_task(phase, TaskPhase.RUNNING), TaskPhase.RUNNING)

    def test_stop_state_does_not_auto_recover(self):
        phase = transition_task(TaskPhase.IDLE, TaskPhase.PREPARING)
        phase = transition_task(phase, TaskPhase.RUNNING)
        phase = transition_task(phase, TaskPhase.STOPPING)
        phase = transition_task(phase, TaskPhase.STOPPED)
        self.assertEqual(describe_task_status(phase).label, "已停止")
        with self.assertRaisesRegex(InvalidTaskTransition, "显式发起"):
            transition_task(phase, TaskPhase.PREPARING)

    def test_verified_failure_requires_attention_not_completion(self):
        result = ActionResult(
            "action-1",
            ActionOutcome.VERIFIED_FAILURE,
            reason="落点未出现预期变化",
            verification_observation_id="frame-after-1",
        )
        phase = transition_task(TaskPhase.IDLE, TaskPhase.PREPARING)
        phase = transition_task(phase, TaskPhase.RUNNING)
        phase = transition_task(phase, TaskPhase.NEEDS_ATTENTION)
        view = describe_task_status(phase, reason=result.reason).to_dict()
        self.assertEqual(view["label"], "需要处理")
        self.assertEqual(view["reason"], "落点未出现预期变化")
        with self.assertRaises(InvalidTaskTransition):
            transition_task(phase, TaskPhase.COMPLETED, postcondition_verified=True)

    def test_submitted_unknown_is_reported_for_reconciliation_not_replay(self):
        executor = FakeExecutor(ActionResult(
            "action-1",
            ActionOutcome.SUBMITTED_UNKNOWN,
            reason="提交后连接超时，尚未核对实际画面",
        ))
        result = executor.submit(make_action(make_observation()), make_observation())
        phase = transition_task(TaskPhase.IDLE, TaskPhase.PREPARING)
        phase = transition_task(phase, TaskPhase.RUNNING)
        phase = transition_task(phase, TaskPhase.NEEDS_ATTENTION)
        view = describe_task_status(phase, reason=result.reason)
        self.assertTrue(result.was_submitted)
        self.assertFalse(result.is_verified)
        self.assertIn("尚未核对", view.reason)
        self.assertEqual(executor.calls, 1)

    def test_stale_frame_is_not_submitted_and_ui_gets_reason(self):
        planned_on = make_observation("frame-1")
        current = make_observation("frame-2")
        action = make_action(planned_on)
        executor = FakeExecutor(ActionResult(
            action.action_id,
            ActionOutcome.NOT_SUBMITTED,
            reason="画面已变化，旧画面生成的动作已失效",
        ))
        with self.assertRaises(ActionPreconditionError):
            assert_action_precondition(action, current)
        phase = transition_task(TaskPhase.IDLE, TaskPhase.PREPARING)
        phase = transition_task(phase, TaskPhase.NEEDS_ATTENTION)
        view = describe_task_status(phase, reason=executor.result.reason).to_dict()
        self.assertEqual(executor.calls, 0)
        self.assertEqual(view["reason"], "画面已变化，旧画面生成的动作已失效")
        self.assertEqual(view["phase"], "needs_attention")

    def test_attention_status_requires_a_human_readable_reason(self):
        with self.assertRaisesRegex(ValueError, "可理解的原因"):
            describe_task_status(TaskPhase.NEEDS_ATTENTION)


if __name__ == "__main__":
    unittest.main()
