"""Fail-closed composition of lease, known-operator, and frame checks."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .action_contract import ActionIntent, ActionPreconditionError, FrameFingerprint, assert_action_precondition
from .device_identity import DeviceInstanceIdentity
from .device_lease import DeviceLeaseState
from .external_operator_probe import OperatorProbeReport, OperatorProbeState


class DeviceConflictError(ValueError):
    """Raised when known conflict evidence or current state is unsafe."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class KnownSignalPermit:
    """Short-lived proof that configured signals and this exact frame matched.

    The permit does not claim that all possible external controllers are absent.
    """

    fingerprint: FrameFingerprint
    operator_snapshot_at: datetime
    expires_at: datetime
    coverage: str = "adb-server-default-port-snapshot"

    @property
    def exclusive_control_confirmed(self):
        return False

    def assert_fresh(self, *, now=None):
        current_time = _as_aware_utc(now or datetime.now(timezone.utc), "当前时间")
        if current_time > self.expires_at:
            raise DeviceConflictError("permit_expired", "冲突检查凭据已过期，请重新检查页面")
        return None


def _as_aware_utc(value, label):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DeviceConflictError("time_unknown", f"无法确认{label}")
    return value.astimezone(timezone.utc)


def _report_timestamp(report):
    try:
        value = datetime.fromisoformat(report.sampled_at)
    except (TypeError, ValueError):
        raise DeviceConflictError("operator_unknown", "外部操作者快照时间无效") from None
    return _as_aware_utc(value, "外部操作者快照时间")


def _validate_report(report):
    if not isinstance(report, OperatorProbeReport):
        raise DeviceConflictError("operator_unknown", "无法确认外部操作者状态")
    if not isinstance(report.state, OperatorProbeState):
        raise DeviceConflictError("operator_unknown", "外部操作者状态格式未知")
    if (not isinstance(report.observed_adb_client_pids, tuple)
            or not isinstance(report.external_adb_client_pids, tuple)):
        raise DeviceConflictError("operator_unknown", "外部操作者进程记录格式未知")
    for pids in (report.observed_adb_client_pids, report.external_adb_client_pids):
        if any(type(pid) is not int or pid <= 0 for pid in pids):
            raise DeviceConflictError("operator_unknown", "外部操作者进程ID无效")
        if tuple(sorted(set(pids))) != pids:
            raise DeviceConflictError("operator_unknown", "外部操作者进程记录重复或乱序")
    if not set(report.external_adb_client_pids).issubset(report.observed_adb_client_pids):
        raise DeviceConflictError("operator_unknown", "外部操作者记录前后不一致")
    if report.state is OperatorProbeState.CLEAR and report.external_adb_client_pids:
        raise DeviceConflictError("operator_unknown", "外部操作者快照状态不一致")
    if report.state is OperatorProbeState.CONFLICT:
        raise DeviceConflictError("operator_conflict", "发现未登记的ADB客户端，设备动作已停止")
    if report.state is OperatorProbeState.UNKNOWN:
        raise DeviceConflictError("operator_unknown", "无法确认外部操作者状态，设备动作已停止")
    return _report_timestamp(report)


def check_pre_dispatch(
    action: ActionIntent,
    current_observation,
    *,
    lease_state,
    lease_identity: DeviceInstanceIdentity,
    operator_report: OperatorProbeReport,
    now=None,
    max_snapshot_age_seconds=1.0,
):
    """Check known conflict signals and the exact page/frame before dispatch.

    A successful result only covers the configured ADB 5037 snapshot and the
    exact observation supplied. It is not proof against arbitrary software.
    """
    if lease_state is not DeviceLeaseState.ACQUIRED:
        raise DeviceConflictError("lease_not_acquired", "设备租约未确认，设备动作已停止")
    if not isinstance(lease_identity, DeviceInstanceIdentity):
        raise DeviceConflictError("identity_unknown", "无法确认设备实例身份")
    if not isinstance(action, ActionIntent):
        raise DeviceConflictError("action_invalid", "动作意图无效")
    if type(max_snapshot_age_seconds) not in (int, float) or max_snapshot_age_seconds <= 0:
        raise ValueError("外部操作者快照有效期必须大于零")
    if action.precondition.device_id != lease_identity.canonical:
        raise DeviceConflictError("lease_identity_mismatch", "动作实例与当前租约身份不同")

    sampled_at = _validate_report(operator_report)
    if operator_report.state is not OperatorProbeState.CLEAR:
        raise DeviceConflictError("operator_unknown", "无法确认外部操作者状态")
    current_time = _as_aware_utc(now or datetime.now(timezone.utc), "当前时间")
    age = (current_time - sampled_at).total_seconds()
    if age < 0 or age > max_snapshot_age_seconds:
        raise DeviceConflictError("operator_snapshot_stale", "外部操作者快照已过期，请重新检查")

    try:
        current_fingerprint = FrameFingerprint.from_observation(current_observation)
    except ActionPreconditionError as error:
        raise DeviceConflictError(error.code, str(error)) from None
    observed_at = _as_aware_utc(current_observation.observed_at, "当前画面时间")
    if observed_at < sampled_at:
        raise DeviceConflictError("frame_before_probe", "当前画面早于冲突检查，需重新读取页面")
    try:
        assert_action_precondition(action, current_observation)
    except ActionPreconditionError as error:
        raise DeviceConflictError(error.code, str(error)) from None
    return KnownSignalPermit(
        fingerprint=current_fingerprint,
        operator_snapshot_at=sampled_at,
        expires_at=sampled_at + timedelta(seconds=float(max_snapshot_age_seconds)),
    )
