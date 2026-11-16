"""Per-game evidence ledger for future simulators.

Source-reported claims are not treated as verified current-game rules. The
registry deliberately contains no transition implementation or device code.
"""

from dataclasses import dataclass
from enum import Enum

from app.game_capability import SUPPORTED_GAME_IDS


class EvidenceStatus(str, Enum):
    SOURCE_REPORTED = "source_reported"
    ASSUMPTION = "assumption"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RuleFieldEvidence:
    """One rule field with explicit provenance, assumption, or unknown reason."""

    field_id: str
    status: EvidenceStatus
    value: str = None
    source_id: str = None
    source_kind: str = None
    limitation: str = None
    reason: str = None

    def __post_init__(self):
        if not isinstance(self.field_id, str) or not self.field_id.strip():
            raise ValueError("field_id必须是非空文本")
        if not isinstance(self.status, EvidenceStatus):
            raise TypeError("status必须是EvidenceStatus")

        if self.status is EvidenceStatus.SOURCE_REPORTED:
            if not _nonempty(self.value) or not _nonempty(self.source_id) or not _nonempty(self.source_kind):
                raise ValueError("source_reported必须包含值、来源ID和来源类型")
            if self.reason is not None:
                raise ValueError("source_reported不能使用unknown原因")
        elif self.status is EvidenceStatus.ASSUMPTION:
            if not _nonempty(self.value) or not _nonempty(self.reason):
                raise ValueError("assumption必须包含假设内容和依据说明")
            if (self.source_id is None) != (self.source_kind is None):
                raise ValueError("假设来源ID和来源类型必须同时提供")
            if self.source_id is not None and not _nonempty(self.source_id):
                raise ValueError("假设来源ID不能为空")
            if self.source_kind is not None and not _nonempty(self.source_kind):
                raise ValueError("假设来源类型不能为空")
        else:
            if any(value is not None for value in (
                self.value, self.source_id, self.source_kind, self.limitation,
            )) or not _nonempty(self.reason):
                raise ValueError("unknown只能包含非空原因，不能补入值或来源")

        if self.limitation is not None and not _nonempty(self.limitation):
            raise ValueError("limitation提供时必须是非空文本")

    def to_dict(self):
        return {
            "field_id": self.field_id,
            "status": self.status.value,
            "value": self.value,
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "limitation": self.limitation,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class RuleEvidenceProfile:
    """Evidence inventory for one approved v0.4 minigame."""

    game_id: str
    display_name: str
    fields: tuple

    def __post_init__(self):
        if self.game_id not in SUPPORTED_GAME_IDS:
            raise ValueError(f"v0.4不支持此小游戏ID：{self.game_id}")
        if not _nonempty(self.display_name):
            raise ValueError("display_name必须是非空文本")
        if not isinstance(self.fields, tuple) or any(
            not isinstance(field, RuleFieldEvidence) for field in self.fields
        ):
            raise TypeError("fields必须是RuleFieldEvidence元组")
        field_ids = tuple(field.field_id for field in self.fields)
        if len(set(field_ids)) != len(field_ids):
            raise ValueError("规则字段ID不能重复")
        if "rule_version" not in field_ids:
            raise ValueError("每款游戏都必须显式登记rule_version")

    def field(self, field_id):
        for item in self.fields:
            if item.field_id == field_id:
                return item
        raise KeyError(field_id)

    @property
    def source_reported_claims(self):
        return tuple(item for item in self.fields if item.status is EvidenceStatus.SOURCE_REPORTED)

    @property
    def simulation_assumptions(self):
        return tuple(item for item in self.fields if item.status is EvidenceStatus.ASSUMPTION)

    @property
    def unknown_fields(self):
        return tuple(item for item in self.fields if item.status is EvidenceStatus.UNKNOWN)

    def to_dict(self):
        return {
            "game_id": self.game_id,
            "display_name": self.display_name,
            "rule_version": self.field("rule_version").to_dict(),
            "source_reported_claims": [item.to_dict() for item in self.source_reported_claims],
            "simulation_assumptions": [item.to_dict() for item in self.simulation_assumptions],
            "unknown_fields": [item.to_dict() for item in self.unknown_fields],
        }


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _unknown(field_id, reason):
    return RuleFieldEvidence(field_id, EvidenceStatus.UNKNOWN, reason=reason)


def _source_reported(field_id, value, source_id, source_kind, limitation):
    return RuleFieldEvidence(
        field_id=field_id,
        status=EvidenceStatus.SOURCE_REPORTED,
        value=value,
        source_id=source_id,
        source_kind=source_kind,
        limitation=limitation,
    )


_COMMON_UNKNOWN_FIELDS = (
    ("rule_version", "当前客户端版本、渠道／区服和活动轮次未核对。"),
    ("activity_identity", "没有当前游戏画面或已核实的活动身份。"),
    ("board_geometry", "没有足以确认棋盘、托盘或容器结构的本游戏证据。"),
    ("visible_information", "未知格、预览内容和遮挡信息尚未核实。"),
    ("input_mode", "点击、拖动、放置或交换等输入方式尚未核实。"),
    ("legal_actions", "合法动作集合尚未核实。"),
    ("step_cost", "开局与单步成本尚未核实。"),
    ("spawn_or_refill", "补入内容、顺序和随机性尚未核实。"),
    ("resolution_order", "合并、消除及连锁结算顺序尚未核实。"),
    ("scoring_and_goal", "计分与目标尚未核实。"),
    ("terminal_conditions", "正常完成、失败、超时和无合法动作条件尚未核实。"),
    ("assist_items", "辅助道具的作用和成本尚未核实。"),
    ("restart_consequences", "重开、退出及跨局后果尚未核实。"),
    ("energy_behavior", "体力扣除、恢复和活动结束行为尚未核实。"),
)


def _base_unknowns():
    return tuple(_unknown(field_id, reason) for field_id, reason in _COMMON_UNKNOWN_FIELDS)


_PROFILES = (
    RuleEvidenceProfile(
        game_id="candy-party",
        display_name="糖果派对",
        fields=_base_unknowns(),
    ),
    RuleEvidenceProfile(
        game_id="skewer-master",
        display_name="烤串大师",
        fields=_base_unknowns() + (
            _source_reported(
                "official_category_announcement",
                "官方公告将其称为“全新趣味消除”。",
                "O2",
                "official_announcement",
                "只说明宣传类别，不确认具体消除规则、操作、成本或关卡。",
            ),
        ),
    ),
    RuleEvidenceProfile(
        game_id="burger-day",
        display_name="疯狂汉堡日",
        fields=_base_unknowns() + (
            _source_reported(
                "player_layout_advice",
                "玩家攻略建议食材向两侧摆放，小食材放上、大食材放下。",
                "C2",
                "player_guide",
                "页面注明信息来自小程序“时尚城兑换码”；版本／渠道未核，属于布局建议，不是已验证规则。",
            ),
            _source_reported(
                "player_multiplier_mention",
                "玩家攻略称小黄瓜片等食材可开启倍数合成。",
                "C2",
                "player_guide",
                "倍数功能的实际作用、成本、风险及官服可用性均未核实。",
            ),
        ),
    ),
    RuleEvidenceProfile(
        game_id="starlight-mix",
        display_name="星光特调",
        fields=_base_unknowns() + (
            _source_reported(
                "player_layout_advice",
                "玩家攻略建议不同颜色酒斜向错开放置，并将待消除的混合酒置于夹角。",
                "C1",
                "player_guide",
                "来源只提供摆放经验，没有说明移动规则、混合／消除条件或收益。",
            ),
        ),
    ),
    RuleEvidenceProfile(
        game_id="animal-bath",
        display_name="动物沐场",
        fields=_base_unknowns() + (
            _source_reported(
                "player_pair_merge_report",
                "玩家攻略称两个同级动物上下左右相邻时可合成高一级。",
                "C3",
                "player_guide",
                "未核对当前官服画面；合并位置、优先级、连锁和其他邻接规则未知。",
            ),
            _source_reported(
                "player_triple_merge_report",
                "玩家攻略称三个同级动物可合成高两级。",
                "C3",
                "player_guide",
                "未核对当前官服画面；不能推导超过三只时的处理方式。",
            ),
        ),
    ),
)


def rule_evidence_profiles():
    """Return the five immutable evidence profiles in approved scope order."""
    return _PROFILES


def get_rule_evidence_profile(game_id):
    """Return one approved game's profile; reject unknown IDs explicitly."""
    for profile in _PROFILES:
        if profile.game_id == game_id:
            return profile
    raise ValueError(f"v0.4不支持此小游戏ID：{game_id}")


def build_simulation_assumption_report(profiles=None):
    """Return a JSON-ready per-game list of assumptions used by simulation.

    The default registry currently has no active simulations, so its
    assumption lists are empty. Supplying profiles is useful for offline
    validation of report handling before any game model is approved.
    """
    selected = rule_evidence_profiles() if profiles is None else tuple(profiles)
    if any(not isinstance(profile, RuleEvidenceProfile) for profile in selected):
        raise TypeError("profiles必须只包含RuleEvidenceProfile")
    game_ids = tuple(profile.game_id for profile in selected)
    if len(set(game_ids)) != len(game_ids):
        raise ValueError("报告中不能重复登记小游戏")
    return tuple({
        "game_id": profile.game_id,
        "display_name": profile.display_name,
        "rule_version": profile.field("rule_version").to_dict(),
        "assumptions": [item.to_dict() for item in profile.simulation_assumptions],
    } for profile in selected)
