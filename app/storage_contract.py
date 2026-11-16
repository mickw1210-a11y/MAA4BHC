"""Storage-only commit requests and bounded idempotent retry semantics."""

import hashlib
import re
from dataclasses import dataclass
from typing import Protocol


class RetryableStorageError(OSError):
    """Storage adapter signals that retrying the same commit is safe."""


class StorageCommitError(ValueError):
    """Storage returned an invalid or mismatched commit receipt."""


def _require_text(value, field_name):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name}必须是非空且无首尾空格的文本")


@dataclass(frozen=True)
class StorageCommitRequest:
    """Immutable bytes and stable identity reused unchanged on storage retry."""

    commit_id: str
    observation_id: str
    payload: bytes

    def __post_init__(self):
        _require_text(self.commit_id, "commit_id")
        _require_text(self.observation_id, "observation_id")
        if not isinstance(self.payload, bytes):
            raise TypeError("payload必须是不可变bytes")

    @property
    def payload_sha256(self):
        return hashlib.sha256(self.payload).hexdigest()


@dataclass(frozen=True)
class StorageReceipt:
    commit_id: str
    payload_sha256: str

    def __post_init__(self):
        _require_text(self.commit_id, "commit_id")
        if not isinstance(self.payload_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.payload_sha256
        ):
            raise ValueError("payload_sha256必须是小写SHA-256")


class StorageCommitter(Protocol):
    """Commit one immutable request idempotently; it has no device methods."""

    def commit(self, request: StorageCommitRequest) -> StorageReceipt:
        ...


def retry_storage_commit(committer, request, *, max_attempts):
    """Retry storage only with the same commit ID and exact same bytes."""
    if not isinstance(request, StorageCommitRequest):
        raise TypeError("request必须是StorageCommitRequest")
    if type(max_attempts) is not int or max_attempts < 1:
        raise ValueError("max_attempts必须是正整数")

    for attempt in range(max_attempts):
        try:
            receipt = committer.commit(request)
        except RetryableStorageError:
            if attempt + 1 == max_attempts:
                raise
            continue
        if not isinstance(receipt, StorageReceipt):
            raise StorageCommitError("存储回执类型无效")
        if (receipt.commit_id != request.commit_id
                or receipt.payload_sha256 != request.payload_sha256):
            raise StorageCommitError("存储回执与本次提交不匹配")
        return receipt

    raise AssertionError("unreachable")
