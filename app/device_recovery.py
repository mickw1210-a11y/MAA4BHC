"""Project-local persistent recovery records for device actions.

This is an offline-proven protocol prototype. It neither acquires a device
lease nor dispatches device commands. Callers must hold the current OS device
lease before beginning a lease record or changing this journal.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from .action_result import ActionOutcome, ActionResult
from .device_identity import DeviceInstanceIdentity
from .device_lease import LeaseOwnerInfo, ProcessLiveness, owner_process_liveness


class RecoveryError(RuntimeError):
    """The configured recovery authority is missing, mismatched, or unsafe."""


class RecoveryDisposition(str, Enum):
    FIRST_USE = "first_use"
    READY = "ready"
    REPLAN_REQUIRED = "replan_required"
    VERIFY_REQUIRED = "verify_required"
    OWNER_ACTIVE = "owner_active"
    OWNER_UNKNOWN = "owner_unknown"


@dataclass(frozen=True, slots=True)
class RecoveryAuthorityConfig:
    """Per-copy trusted pointer to one explicitly provisioned authority."""

    authority_project_root: str
    authority_root: str
    authority_id: str

    def __post_init__(self):
        _require_text(self.authority_project_root, "authority_project_root")
        _require_text(self.authority_root, "authority_root")
        if not isinstance(self.authority_id, str) or not re.fullmatch(r"[0-9a-f]{32}", self.authority_id):
            raise ValueError("authority_id格式无效")

    def to_dict(self):
        return {
            "authority_project_root": self.authority_project_root,
            "authority_root": self.authority_root,
            "authority_id": self.authority_id,
        }

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {
            "authority_project_root", "authority_root", "authority_id"
        }:
            raise ValueError("恢复权威配置格式无效")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class RecoveryObservation:
    """Fresh, identity-bound evidence supplied by a later observer."""

    action_id: str
    identity_digest: str
    observation_id: str
    observed_at: str
    outcome: ActionOutcome
    evidence_ref: str

    def __post_init__(self):
        for field_name in ("action_id", "observation_id", "evidence_ref"):
            _require_text(getattr(self, field_name), field_name)
        _require_digest(self.identity_digest, "identity_digest")
        try:
            outcome = ActionOutcome(self.outcome)
        except (TypeError, ValueError):
            raise ValueError("观察结果状态无效") from None
        if outcome not in (ActionOutcome.VERIFIED_SUCCESS, ActionOutcome.VERIFIED_FAILURE):
            raise ValueError("观察只能核实成功或失败")
        object.__setattr__(self, "outcome", outcome)
        _parse_timestamp(self.observed_at, "observed_at")

    def to_dict(self):
        return {
            "action_id": self.action_id,
            "identity_digest": self.identity_digest,
            "observation_id": self.observation_id,
            "observed_at": self.observed_at,
            "outcome": self.outcome.value,
            "evidence_ref": self.evidence_ref,
        }

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {
            "action_id", "identity_digest", "observation_id",
            "observed_at", "outcome", "evidence_ref",
        }:
            raise RecoveryError("核实观察记录格式无效")
        try:
            return cls(**value)
        except (TypeError, ValueError) as error:
            raise RecoveryError("核实观察记录无效") from error


@dataclass(frozen=True, slots=True)
class RecoveryAssessment:
    disposition: RecoveryDisposition
    previous_owner_liveness: ProcessLiveness | None = None
    action_result: ActionResult | None = None
    evidence_ref: str | None = None
    reason: str = ""

    @property
    def read_only_recovery_required(self):
        return self.disposition in {
            RecoveryDisposition.VERIFY_REQUIRED,
            RecoveryDisposition.OWNER_ACTIVE,
            RecoveryDisposition.OWNER_UNKNOWN,
        }


@dataclass(slots=True)
class _History:
    current_owner: LeaseOwnerInfo | None
    owner_released: bool
    pending_action: dict | None
    latest_result: ActionResult | None
    latest_evidence_ref: str | None
    first_use: bool


_ZERO_HASH = "0" * 64
_AUTHORITY_SCHEMA = 1
_EVENT_NAMES = {
    "lease_started",
    "lease_released",
    "action_prepared",
    "submission_possible",
    "action_result",
}


def _require_text(value, field_name):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name}必须是非空且无首尾空格的文本")


def _require_digest(value, field_name):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{field_name}必须是小写SHA-256")


def _parse_timestamp(value, field_name):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name}必须是带时区的ISO-8601时间")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field_name}时间格式无效") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name}必须包含时区")
    return parsed.astimezone(timezone.utc)


def _timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON包含重复字段")
        result[key] = value
    return result


def _resolve_project_paths(project_root, authority_root):
    try:
        project = Path(project_root).resolve(strict=True)
        authority = Path(authority_root)
        if not authority.is_absolute():
            authority = project / authority
        authority = authority.resolve(strict=False)
    except OSError as error:
        raise RecoveryError("恢复权威路径无法解析") from error
    if not project.is_dir():
        raise RecoveryError("恢复权威所属项目目录不可用")
    if not authority.is_relative_to(project):
        raise RecoveryError("恢复权威目录必须位于明确指定的项目目录内")
    return project, authority


def _owner_from_data(value):
    owner = LeaseOwnerInfo.from_dict(value)
    if owner is None:
        raise RecoveryError("租约持有者记录无效")
    return owner


class RecoveryStore:
    """Read and update one explicitly provisioned, project-contained journal."""

    def __init__(self, config: RecoveryAuthorityConfig, identity: DeviceInstanceIdentity):
        if not isinstance(config, RecoveryAuthorityConfig):
            raise TypeError("config必须是RecoveryAuthorityConfig")
        if not isinstance(identity, DeviceInstanceIdentity):
            raise TypeError("identity必须是DeviceInstanceIdentity")
        self.config = config
        self.identity = identity
        self.project_root, self.authority_root = _resolve_project_paths(
            config.authority_project_root, config.authority_root
        )
        self.directory = (self.authority_root / identity.lease_key).resolve(strict=False)
        if not self.directory.is_relative_to(self.project_root):
            raise RecoveryError("恢复记录目录越出指定项目目录")
        self.state_path = self.directory / "state.json"
        self._load_state()

    @classmethod
    def provision(cls, authority_project_root, authority_root, identity):
        """Explicitly create the first-use marker; never called by open()."""
        if not isinstance(identity, DeviceInstanceIdentity):
            raise TypeError("identity必须是DeviceInstanceIdentity")
        project, authority = _resolve_project_paths(authority_project_root, authority_root)
        directory = (authority / identity.lease_key).resolve(strict=False)
        if not directory.is_relative_to(project):
            raise RecoveryError("恢复记录目录越出指定项目目录")
        if directory.exists():
            raise RecoveryError("恢复权威已存在；不得覆盖或重新初始化")
        authority_id = uuid.uuid4().hex
        config = RecoveryAuthorityConfig(str(project), str(authority), authority_id)
        initial = {
            "schema_version": _AUTHORITY_SCHEMA,
            "authority_id": authority_id,
            "identity_digest": identity.lease_key,
            "events": [],
            "head_hash": _ZERO_HASH,
        }
        try:
            directory.mkdir(parents=True, exist_ok=False)
            _write_new_file(directory / "state.json", _canonical_bytes(initial))
        except OSError as error:
            raise RecoveryError("首次建立恢复权威失败；检查残留后由明确初始化流程处理") from error
        return config, cls(config, identity)

    @classmethod
    def open(cls, config: RecoveryAuthorityConfig, identity: DeviceInstanceIdentity):
        """Open only an already provisioned authority matching trusted config."""
        return cls(config, identity)

    def begin_lease(self, owner: LeaseOwnerInfo, *, liveness_check=None):
        """Record a new holder after the caller has acquired the OS device lease.

        An exited or PID-reused prior owner is accepted only after checking both
        its PID and process-creation marker. An unknown or live owner blocks.
        Unresolved actions put the new holder into a read-only recovery state.
        """
        self._validate_owner(owner)
        if liveness_check is None:
            liveness_check = owner_process_liveness
        if not callable(liveness_check):
            raise TypeError("liveness_check必须可调用")

        _, history = self._load_state()
        if history.current_owner is None:
            predecessor_status = "first_use"
            predecessor_owner = None
            previous_liveness = None
            first_use = True
        elif history.owner_released:
            predecessor_status = "released"
            predecessor_owner = history.current_owner
            previous_liveness = None
            first_use = False
        else:
            predecessor_owner = history.current_owner
            try:
                previous_liveness = ProcessLiveness(liveness_check(predecessor_owner))
            except Exception:
                previous_liveness = ProcessLiveness.UNKNOWN
            if previous_liveness is ProcessLiveness.ALIVE:
                return RecoveryAssessment(
                    RecoveryDisposition.OWNER_ACTIVE,
                    previous_liveness,
                    reason="上一持有者仍存活；保留停止状态",
                )
            if previous_liveness not in (ProcessLiveness.EXITED, ProcessLiveness.PID_REUSED):
                return RecoveryAssessment(
                    RecoveryDisposition.OWNER_UNKNOWN,
                    ProcessLiveness.UNKNOWN,
                    reason="无法确认上一持有者已退出；保留停止状态",
                )
            predecessor_status = previous_liveness.value
            first_use = False

        self._append({
            "kind": "lease_started",
            "data": {
                "owner": owner.to_dict(),
                "predecessor_status": predecessor_status,
                "predecessor_owner": predecessor_owner.to_dict() if predecessor_owner else None,
            },
        })
        history = self._load_state()[1]
        if history.pending_action is not None:
            pending = history.pending_action
            if pending["status"] == "prepared":
                self.record_result(
                    owner,
                    ActionResult(
                        pending["action_id"],
                        ActionOutcome.NOT_SUBMITTED,
                        reason="恢复时只有已持久意图而无提交标记；按协议未派发，须重新规划",
                    ),
                )
            elif pending["status"] == "submission_possible":
                self.record_result(
                    owner,
                    ActionResult(
                        pending["action_id"],
                        ActionOutcome.SUBMITTED_UNKNOWN,
                        reason="提交标记已持久化，但缺少后置观察；禁止重放原动作",
                    ),
                )

        assessment = self.assess_current(owner)
        if first_use and assessment.disposition is RecoveryDisposition.READY:
            return RecoveryAssessment(
                RecoveryDisposition.FIRST_USE,
                previous_liveness,
                reason="首次使用已由显式初始化标记确认；仍须重新读取身份、画面与计划",
            )
        if previous_liveness in (ProcessLiveness.EXITED, ProcessLiveness.PID_REUSED):
            return RecoveryAssessment(
                assessment.disposition,
                previous_liveness,
                assessment.action_result,
                assessment.evidence_ref,
                assessment.reason or "上一持有者已确认退出；按当前恢复状态处理",
            )
        return assessment

    def assess_current(self, owner: LeaseOwnerInfo):
        """Reassess without sending, appending, or repeating any action."""
        self._validate_owner(owner)
        _, history = self._load_state()
        self._require_current_owner(history, owner)
        if history.pending_action is not None:
            pending = history.pending_action
            if pending["status"] == "prepared":
                return RecoveryAssessment(
                    RecoveryDisposition.REPLAN_REQUIRED,
                    action_result=ActionResult(
                        pending["action_id"],
                        ActionOutcome.NOT_SUBMITTED,
                        reason="意图尚无提交标记；原动作不自动重放",
                    ),
                    reason="原动作未提交；必须重新规划并使用新的动作ID",
                )
            result = history.latest_result
            if result is None or result.outcome is not ActionOutcome.SUBMITTED_UNKNOWN:
                result = ActionResult(
                    pending["action_id"],
                    ActionOutcome.SUBMITTED_UNKNOWN,
                    reason="动作可能已提交，尚无匹配的新观察",
                )
            return RecoveryAssessment(
                RecoveryDisposition.VERIFY_REQUIRED,
                action_result=result,
                evidence_ref=history.latest_evidence_ref,
                reason="先取得匹配实例的新观察并核实结果；禁止重放原动作",
            )
        if history.latest_result is not None and history.latest_result.outcome is ActionOutcome.NOT_SUBMITTED:
            return RecoveryAssessment(
                RecoveryDisposition.REPLAN_REQUIRED,
                action_result=history.latest_result,
                reason="原动作未提交；下一次执行必须使用新计划和新动作ID",
            )
        return RecoveryAssessment(
            RecoveryDisposition.READY,
            action_result=history.latest_result,
            evidence_ref=history.latest_evidence_ref,
            reason="恢复记录无未决动作；下一动作仍须重新读取身份、画面与计划",
        )

    def prepare_action(
        self,
        owner: LeaseOwnerInfo,
        *,
        action_id,
        plan_id,
        precondition_observation_id,
        payload_sha256,
    ):
        """Durably save the minimum intent before any dispatcher is called."""
        self._validate_owner(owner)
        _require_text(action_id, "action_id")
        _require_text(plan_id, "plan_id")
        _require_text(precondition_observation_id, "precondition_observation_id")
        _require_digest(payload_sha256, "payload_sha256")
        state, history = self._load_state()
        self._require_current_owner(history, owner)
        if history.pending_action is not None:
            raise RecoveryError("已有未决动作；核实前不能准备新动作")
        for event in state["events"]:
            if event["kind"] == "action_prepared":
                if event["data"]["action_id"] == action_id:
                    raise RecoveryError("action_id已使用；原动作不得重放")
                if event["data"]["plan_id"] == plan_id:
                    raise RecoveryError("plan_id已使用；必须重新规划")
        self._append({
            "kind": "action_prepared",
            "data": {
                "owner": owner.to_dict(),
                "action_id": action_id,
                "plan_id": plan_id,
                "precondition_observation_id": precondition_observation_id,
                "payload_sha256": payload_sha256,
            },
        })

    def mark_submission_possible(self, owner: LeaseOwnerInfo, action_id):
        """Persist the conservative submission boundary before device dispatch."""
        self._validate_owner(owner)
        _require_text(action_id, "action_id")
        _, history = self._load_state()
        self._require_current_owner(history, owner)
        pending = history.pending_action
        if pending is None or pending["action_id"] != action_id or pending["status"] != "prepared":
            raise RecoveryError("动作意图不存在或状态不允许提交")
        self._append({
            "kind": "submission_possible",
            "data": {"owner": owner.to_dict(), "action_id": action_id},
        })

    def record_result(
        self,
        owner: LeaseOwnerInfo,
        result: ActionResult,
        *,
        observation: RecoveryObservation | None = None,
    ):
        """Persist a result; verified results require fresh matching evidence."""
        self._validate_owner(owner)
        if not isinstance(result, ActionResult):
            raise TypeError("result必须是ActionResult")
        _, history = self._load_state()
        self._require_current_owner(history, owner)
        pending = history.pending_action
        if pending is None or pending["action_id"] != result.action_id:
            raise RecoveryError("动作结果与当前未决动作不匹配")

        if result.outcome is ActionOutcome.NOT_SUBMITTED:
            if pending["status"] != "prepared":
                raise RecoveryError("已有可能提交边界；没有新观察时不能改记为未提交")
            if observation is not None:
                raise RecoveryError("未提交结果不能附带后置观察")
            observation_data = None
            evidence_ref = None
        elif result.outcome is ActionOutcome.SUBMITTED_UNKNOWN:
            if pending["status"] != "submission_possible" or observation is not None:
                raise RecoveryError("提交未知结果缺少提交标记或错误附带观察")
            observation_data = None
            evidence_ref = None
        else:
            if pending["status"] not in ("submission_possible", "submitted_unknown"):
                raise RecoveryError("核实结果必须对应可能已提交的动作")
            if not isinstance(observation, RecoveryObservation):
                raise RecoveryError("核实结果必须引用新的匹配实例观察")
            if (observation.action_id != result.action_id
                    or observation.identity_digest != self.identity.lease_key
                    or observation.observation_id != result.verification_observation_id
                    or observation.outcome is not result.outcome):
                raise RecoveryError("核实观察与设备、动作或结果不匹配")
            submitted_at = _parse_timestamp(pending["submission_at"], "submission_at")
            observed_at = _parse_timestamp(observation.observed_at, "observed_at")
            if observed_at <= submitted_at:
                raise RecoveryError("核实观察必须晚于可能提交时间")
            if observed_at > datetime.now(timezone.utc):
                raise RecoveryError("核实观察时间在未来；已停止")
            observation_data = observation.to_dict()
            evidence_ref = observation.evidence_ref

        self._append({
            "kind": "action_result",
            "data": {
                "owner": owner.to_dict(),
                "action_id": result.action_id,
                "outcome": result.outcome.value,
                "reason": result.reason,
                "verification_observation_id": result.verification_observation_id,
                "evidence_ref": evidence_ref,
                "observation": observation_data,
            },
        })

    def release_lease(self, owner: LeaseOwnerInfo):
        """Record normal close only when every action has a terminal result."""
        self._validate_owner(owner)
        _, history = self._load_state()
        self._require_current_owner(history, owner)
        if history.pending_action is not None:
            raise RecoveryError("存在未决动作；核实前不能记录正常释放")
        self._append({
            "kind": "lease_released",
            "data": {"owner": owner.to_dict()},
        })

    def read_events(self):
        """Return a detached snapshot for diagnostics and offline assertions."""
        state, _ = self._load_state()
        return tuple(json.loads(json.dumps(event)) for event in state["events"])

    def _validate_owner(self, owner):
        if not isinstance(owner, LeaseOwnerInfo):
            raise TypeError("owner必须是LeaseOwnerInfo")
        if LeaseOwnerInfo.from_dict(owner.to_dict()) is None:
            raise RecoveryError("租约持有者字段无效")
        if owner.identity_digest != self.identity.lease_key:
            raise RecoveryError("租约持有者与当前设备身份不匹配")

    def _require_current_owner(self, history, owner):
        if history.current_owner != owner or history.owner_released:
            raise RecoveryError("当前进程不是恢复日志记录的活动持有者")

    def _append(self, event):
        state, _ = self._load_state()
        record = {
            "seq": len(state["events"]) + 1,
            "kind": event["kind"],
            "at": _timestamp(),
            "identity_digest": self.identity.lease_key,
            "data": event["data"],
            "previous_hash": state["head_hash"],
        }
        record["record_hash"] = hashlib.sha256(_canonical_bytes(record)).hexdigest()
        updated = {
            **state,
            "events": [*state["events"], record],
            "head_hash": record["record_hash"],
        }
        try:
            self._write_state(updated)
        except OSError as error:
            raise RecoveryError("恢复记录未能持久保存；禁止发送设备动作") from error

    def _write_state(self, state):
        payload = _canonical_bytes(state)
        temporary = self.directory / f".state-{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _load_state(self):
        if not self.directory.is_dir() or self.state_path.is_symlink():
            raise RecoveryError("恢复权威目录或状态文件缺失／不安全；已停止")
        try:
            raw = self.state_path.read_bytes()
        except FileNotFoundError as error:
            raise RecoveryError("已配置的恢复权威记录缺失；不能按首次使用重新初始化") from error
        except OSError as error:
            raise RecoveryError("已配置的恢复权威不可读；已停止") from error
        try:
            state = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise RecoveryError("恢复权威记录损坏；已停止") from error
        try:
            history = self._validate_state(state)
        except RecoveryError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise RecoveryError("恢复权威内容无效；已停止") from error
        return state, history

    def _validate_state(self, state):
        if not isinstance(state, dict) or set(state) != {
            "schema_version", "authority_id", "identity_digest", "events", "head_hash",
        }:
            raise RecoveryError("恢复权威状态格式无效")
        if (type(state["schema_version"]) is not int
                or state["schema_version"] != _AUTHORITY_SCHEMA
                or state["authority_id"] != self.config.authority_id
                or state["identity_digest"] != self.identity.lease_key):
            raise RecoveryError("恢复权威或设备身份不匹配；已停止")
        events = state["events"]
        if not isinstance(events, list):
            raise RecoveryError("恢复事件列表格式无效")
        _require_digest(state["head_hash"], "head_hash")
        history = _History(None, False, None, None, None, not events)
        prior_hash = _ZERO_HASH
        action_ids = set()
        plan_ids = set()
        for index, event in enumerate(events, start=1):
            if not isinstance(event, dict) or set(event) != {
                "seq", "kind", "at", "identity_digest", "data",
                "previous_hash", "record_hash",
            }:
                raise RecoveryError("恢复事件格式无效")
            if (type(event["seq"]) is not int or event["seq"] != index
                    or not isinstance(event["kind"], str) or event["kind"] not in _EVENT_NAMES):
                raise RecoveryError("恢复事件顺序或类型无效")
            if event["identity_digest"] != self.identity.lease_key:
                raise RecoveryError("恢复事件设备身份不匹配")
            _parse_timestamp(event["at"], "event.at")
            _require_digest(event["previous_hash"], "previous_hash")
            _require_digest(event["record_hash"], "record_hash")
            if event["previous_hash"] != prior_hash:
                raise RecoveryError("恢复事件链断裂")
            unsigned = {key: value for key, value in event.items() if key != "record_hash"}
            expected_hash = hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()
            if event["record_hash"] != expected_hash:
                raise RecoveryError("恢复事件校验失败")
            self._apply_event(event, history, action_ids, plan_ids)
            prior_hash = event["record_hash"]
        if state["head_hash"] != prior_hash:
            raise RecoveryError("恢复权威头记录与事件链不一致")
        return history

    def _apply_event(self, event, history, action_ids, plan_ids):
        data = event["data"]
        kind = event["kind"]
        if not isinstance(data, dict):
            raise RecoveryError("恢复事件内容无效")

        if kind == "lease_started":
            if set(data) != {"owner", "predecessor_status", "predecessor_owner"}:
                raise RecoveryError("租约开始记录格式无效")
            owner = _owner_from_data(data["owner"])
            if owner.identity_digest != self.identity.lease_key:
                raise RecoveryError("租约开始设备身份不匹配")
            previous = _owner_from_data(data["predecessor_owner"]) if data["predecessor_owner"] else None
            status = data["predecessor_status"]
            if history.current_owner is None:
                if status != "first_use" or previous is not None:
                    raise RecoveryError("首次租约前置状态无效")
            elif history.owner_released:
                if status != "released" or previous != history.current_owner:
                    raise RecoveryError("正常释放后的租约链不匹配")
            elif (status not in (ProcessLiveness.EXITED.value, ProcessLiveness.PID_REUSED.value)
                    or previous != history.current_owner):
                raise RecoveryError("异常租约接续缺少上一持有者退出证据")
            history.current_owner = owner
            history.owner_released = False
            history.first_use = status == "first_use"
            return

        if kind == "lease_released":
            if set(data) != {"owner"}:
                raise RecoveryError("租约释放记录格式无效")
            owner = _owner_from_data(data["owner"])
            self._require_current_owner(history, owner)
            if history.pending_action is not None:
                raise RecoveryError("存在未决动作却记录了正常租约释放")
            history.owner_released = True
            return

        if kind == "action_prepared":
            expected = {
                "owner", "action_id", "plan_id", "precondition_observation_id", "payload_sha256",
            }
            if set(data) != expected:
                raise RecoveryError("动作意图记录格式无效")
            owner = _owner_from_data(data["owner"])
            self._require_current_owner(history, owner)
            if history.pending_action is not None:
                raise RecoveryError("存在未决动作却开始了新动作")
            for field in ("action_id", "plan_id", "precondition_observation_id"):
                try:
                    _require_text(data[field], field)
                except ValueError as error:
                    raise RecoveryError("动作意图字段无效") from error
            _require_digest(data["payload_sha256"], "payload_sha256")
            if data["action_id"] in action_ids or data["plan_id"] in plan_ids:
                raise RecoveryError("动作ID或计划ID重复")
            action_ids.add(data["action_id"])
            plan_ids.add(data["plan_id"])
            history.pending_action = {
                **data, "status": "prepared",
                "prepared_at": event["at"], "submission_at": None,
            }
            history.latest_result = None
            history.latest_evidence_ref = None
            return

        if kind == "submission_possible":
            if set(data) != {"owner", "action_id"}:
                raise RecoveryError("动作提交记录格式无效")
            owner = _owner_from_data(data["owner"])
            self._require_current_owner(history, owner)
            pending = history.pending_action
            if pending is None or pending["action_id"] != data["action_id"] or pending["status"] != "prepared":
                raise RecoveryError("动作提交记录没有对应意图")
            pending["status"] = "submission_possible"
            pending["submission_at"] = event["at"]
            return

        if kind == "action_result":
            expected = {
                "owner", "action_id", "outcome", "reason",
                "verification_observation_id", "evidence_ref", "observation",
            }
            if set(data) != expected:
                raise RecoveryError("动作结果记录格式无效")
            owner = _owner_from_data(data["owner"])
            self._require_current_owner(history, owner)
            pending = history.pending_action
            if pending is None or pending["action_id"] != data["action_id"]:
                raise RecoveryError("动作结果没有对应未决动作")
            try:
                outcome = ActionOutcome(data["outcome"])
                result = ActionResult(
                    data["action_id"],
                    outcome,
                    reason=data["reason"],
                    verification_observation_id=data["verification_observation_id"],
                )
            except (TypeError, ValueError) as error:
                raise RecoveryError("动作结果契约无效") from error
            if outcome is ActionOutcome.NOT_SUBMITTED:
                if (pending["status"] != "prepared"
                        or data["observation"] is not None or data["evidence_ref"] is not None):
                    raise RecoveryError("未提交结果包含不允许的观察证据")
            elif outcome is ActionOutcome.SUBMITTED_UNKNOWN:
                if (pending["status"] != "submission_possible"
                        or data["observation"] is not None or data["evidence_ref"] is not None):
                    raise RecoveryError("提交未知记录状态无效")
                pending["status"] = "submitted_unknown"
            else:
                if pending["status"] not in ("submission_possible", "submitted_unknown"):
                    raise RecoveryError("核实结果缺少可能提交标记")
                observation = RecoveryObservation.from_dict(data["observation"])
                if (observation.action_id != result.action_id
                        or observation.identity_digest != self.identity.lease_key
                        or observation.observation_id != result.verification_observation_id
                        or observation.outcome is not outcome
                        or data["evidence_ref"] != observation.evidence_ref):
                    raise RecoveryError("核实结果与观察证据不匹配")
                observed_at = _parse_timestamp(observation.observed_at, "observed_at")
                if observed_at <= _parse_timestamp(pending["submission_at"], "submission_at"):
                    raise RecoveryError("核实观察早于动作提交")
                if observed_at > _parse_timestamp(event["at"], "event.at"):
                    raise RecoveryError("恢复结果记录早于其核实观察")
            history.latest_result = result
            history.latest_evidence_ref = data["evidence_ref"]
            if outcome is not ActionOutcome.SUBMITTED_UNKNOWN:
                history.pending_action = None
            return

        raise RecoveryError("未知恢复事件")


def _write_new_file(path, payload):
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
