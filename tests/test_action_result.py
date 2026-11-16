import unittest

from app.action_result import ActionOutcome, ActionResult


class ActionResultContractTests(unittest.TestCase):
    def test_four_outcomes_are_distinct(self):
        self.assertEqual(
            {item.value for item in ActionOutcome},
            {
                "not_submitted",
                "submitted_unknown",
                "verified_success",
                "verified_failure",
            },
        )

    def test_not_submitted_is_distinct_from_any_submitted_result(self):
        result = ActionResult("action-1", ActionOutcome.NOT_SUBMITTED, reason="cancelled_before_send")
        self.assertFalse(result.was_submitted)
        self.assertFalse(result.is_verified)

    def test_submitted_unknown_is_submitted_but_not_verified(self):
        result = ActionResult(
            "action-1", ActionOutcome.SUBMITTED_UNKNOWN, reason="device_timeout_after_send"
        )
        self.assertTrue(result.was_submitted)
        self.assertFalse(result.is_verified)

    def test_verified_success_requires_postcondition_observation(self):
        with self.assertRaisesRegex(ValueError, "后置观察"):
            ActionResult("action-1", ActionOutcome.VERIFIED_SUCCESS)
        result = ActionResult(
            "action-1",
            ActionOutcome.VERIFIED_SUCCESS,
            verification_observation_id="frame-after-1",
        )
        self.assertTrue(result.was_submitted)
        self.assertTrue(result.is_verified)

    def test_verified_failure_requires_observation_and_reason(self):
        with self.assertRaisesRegex(ValueError, "后置观察"):
            ActionResult("action-1", ActionOutcome.VERIFIED_FAILURE, reason="postcondition_not_met")
        with self.assertRaisesRegex(ValueError, "说明原因"):
            ActionResult(
                "action-1",
                ActionOutcome.VERIFIED_FAILURE,
                verification_observation_id="frame-after-1",
            )
        result = ActionResult(
            "action-1",
            ActionOutcome.VERIFIED_FAILURE,
            reason="postcondition_not_met",
            verification_observation_id="frame-after-1",
        )
        self.assertTrue(result.was_submitted)
        self.assertTrue(result.is_verified)

    def test_unverified_results_cannot_claim_verification_evidence(self):
        for outcome in (ActionOutcome.NOT_SUBMITTED, ActionOutcome.SUBMITTED_UNKNOWN):
            with self.subTest(outcome=outcome):
                with self.assertRaisesRegex(ValueError, "不能附带"):
                    ActionResult(
                        "action-1",
                        outcome,
                        reason="result_pending",
                        verification_observation_id="frame-after-1",
                    )

    def test_non_success_outcomes_require_a_reason(self):
        for outcome in (
            ActionOutcome.NOT_SUBMITTED,
            ActionOutcome.SUBMITTED_UNKNOWN,
            ActionOutcome.VERIFIED_FAILURE,
        ):
            with self.subTest(outcome=outcome):
                with self.assertRaisesRegex(ValueError, "说明原因"):
                    ActionResult(
                        "action-1",
                        outcome,
                        verification_observation_id=(
                            "frame-after-1" if outcome is ActionOutcome.VERIFIED_FAILURE else None
                        ),
                    )

    def test_unknown_outcome_is_rejected_and_string_value_is_normalized(self):
        with self.assertRaisesRegex(ValueError, "状态无效"):
            ActionResult("action-1", "maybe_done")
        result = ActionResult("action-1", "not_submitted", reason="stale_frame")
        self.assertIs(result.outcome, ActionOutcome.NOT_SUBMITTED)


if __name__ == "__main__":
    unittest.main()
