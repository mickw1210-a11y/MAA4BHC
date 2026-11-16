import hashlib
import subprocess
import sys
import unittest
from pathlib import Path

from app.action_result import ActionOutcome, ActionResult
from app.storage_contract import (
    RetryableStorageError,
    StorageCommitError,
    StorageCommitRequest,
    StorageReceipt,
    retry_storage_commit,
)


class FakeActionExecutor:
    def __init__(self):
        self.calls = 0

    def submit(self):
        self.calls += 1
        return ActionResult("action-1", ActionOutcome.SUBMITTED_UNKNOWN,
                            reason="awaiting_observation")


class RetryOnceCommitter:
    def __init__(self):
        self.requests = []

    def commit(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            raise RetryableStorageError("temporary storage lock")
        return StorageReceipt(request.commit_id, request.payload_sha256)


class StorageContractTests(unittest.TestCase):
    def make_request(self):
        return StorageCommitRequest("commit-1", "observation-1", b"synthetic snapshot")

    def test_retry_reuses_identical_commit_and_does_not_resubmit_action(self):
        executor = FakeActionExecutor()
        action_result = executor.submit()
        self.assertIs(action_result.outcome, ActionOutcome.SUBMITTED_UNKNOWN)

        committer = RetryOnceCommitter()
        request = self.make_request()
        receipt = retry_storage_commit(committer, request, max_attempts=2)

        self.assertEqual(executor.calls, 1)
        self.assertEqual(len(committer.requests), 2)
        self.assertTrue(all(item is request for item in committer.requests))
        self.assertEqual(receipt.commit_id, request.commit_id)
        self.assertEqual(receipt.payload_sha256, hashlib.sha256(request.payload).hexdigest())

    def test_retry_exhaustion_is_bounded(self):
        class AlwaysUnavailable:
            def __init__(self):
                self.calls = 0

            def commit(self, request):
                self.calls += 1
                raise RetryableStorageError("still busy")

        committer = AlwaysUnavailable()
        with self.assertRaisesRegex(RetryableStorageError, "still busy"):
            retry_storage_commit(committer, self.make_request(), max_attempts=3)
        self.assertEqual(committer.calls, 3)

    def test_mismatched_receipt_stops_without_retry(self):
        class WrongReceipt:
            def __init__(self):
                self.calls = 0

            def commit(self, request):
                self.calls += 1
                return StorageReceipt("other-commit", request.payload_sha256)

        committer = WrongReceipt()
        with self.assertRaisesRegex(StorageCommitError, "不匹配"):
            retry_storage_commit(committer, self.make_request(), max_attempts=3)
        self.assertEqual(committer.calls, 1)

    def test_nonretryable_storage_error_is_not_retried(self):
        class BrokenCommitter:
            def __init__(self):
                self.calls = 0

            def commit(self, request):
                self.calls += 1
                raise ValueError("foreign file changed")

        committer = BrokenCommitter()
        with self.assertRaisesRegex(ValueError, "foreign file changed"):
            retry_storage_commit(committer, self.make_request(), max_attempts=3)
        self.assertEqual(committer.calls, 1)

    def test_retry_limit_must_be_positive_integer_not_bool(self):
        for attempts in (0, -1, True, 1.5):
            with self.subTest(attempts=attempts):
                with self.assertRaisesRegex(ValueError, "正整数"):
                    retry_storage_commit(RetryOnceCommitter(), self.make_request(),
                                         max_attempts=attempts)

    def test_request_requires_immutable_bytes_and_ids(self):
        with self.assertRaisesRegex(TypeError, "不可变bytes"):
            StorageCommitRequest("commit-1", "observation-1", bytearray(b"x"))
        with self.assertRaisesRegex(ValueError, "commit_id"):
            StorageCommitRequest(" ", "observation-1", b"x")

    def test_retry_requires_a_commit_request(self):
        with self.assertRaisesRegex(TypeError, "StorageCommitRequest"):
            retry_storage_commit(RetryOnceCommitter(), b"x", max_attempts=1)

    def test_storage_contract_import_has_no_action_executor_or_device_dependency(self):
        project_root = Path(__file__).resolve().parents[1]
        script = (
            "import sys; import app.storage_contract; "
            "assert 'app.execution_contract' not in sys.modules; "
            "assert 'app.device' not in sys.modules; "
            "assert not any(name == 'maa' or name.startswith('maa.') for name in sys.modules)"
        )
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=project_root,
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
