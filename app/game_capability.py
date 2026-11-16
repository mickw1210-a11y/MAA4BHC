"""Per-game readiness stages with fail-closed execution evidence gates."""

from dataclasses import dataclass
from enum import Enum


SUPPORTED_GAME_IDS = (
    "candy-party",
    "skewer-master",
    "burger-day",
    "starlight-mix",
    "animal-bath",
)


class CapabilityState(str, Enum):
    RULES_UNVERIFIED = "rules_unverified"
    RULES_VERIFIED = "rules_verified"
    SIMULATION_ONLY = "simulation_only"
    EXECUTION_READY = "execution_ready"


@dataclass(frozen=True)
class CapabilityEvidence:
    """Evidence gates required to advance one game's capability stage."""

    rules_verified: bool = False
    simulation_passed: bool = False
    no_deadlock_passed: bool = False
    real_adapter_verified: bool = False

    def __post_init__(self):
        for name in (
            "rules_verified",
            "simulation_passed",
            "no_deadlock_passed",
            "real_adapter_verified",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name}必须是布尔证据")
        if self.simulation_passed and not self.rules_verified:
            raise ValueError("规则未核实不能标记模拟通过")
        if self.no_deadlock_passed and not self.simulation_passed:
            raise ValueError("模拟未通过不能标记无死局目标通过")
        if self.real_adapter_verified and not self.simulation_passed:
            raise ValueError("模拟未通过不能核实真实动作适配器")

    @property
    def state(self):
        if not self.rules_verified:
            return CapabilityState.RULES_UNVERIFIED
        if not self.simulation_passed:
            return CapabilityState.RULES_VERIFIED
        if not self.no_deadlock_passed or not self.real_adapter_verified:
            return CapabilityState.SIMULATION_ONLY
        return CapabilityState.EXECUTION_READY

    @property
    def blockers(self):
        reasons = []
        if not self.rules_verified:
            reasons.append("rules_not_verified")
        if not self.simulation_passed:
            reasons.append("simulation_not_passed")
        if not self.no_deadlock_passed:
            reasons.append("no_deadlock_not_verified")
        if not self.real_adapter_verified:
            reasons.append("real_adapter_not_verified")
        return tuple(reasons)


@dataclass(frozen=True)
class GameCapability:
    game_id: str
    evidence: CapabilityEvidence = CapabilityEvidence()

    def __post_init__(self):
        if self.game_id not in SUPPORTED_GAME_IDS:
            raise ValueError(f"v0.4不支持此小游戏ID：{self.game_id}")
        if not isinstance(self.evidence, CapabilityEvidence):
            raise TypeError("evidence必须是CapabilityEvidence")

    @property
    def state(self):
        return self.evidence.state

    @property
    def execution_ready(self):
        return self.state is CapabilityState.EXECUTION_READY


def initial_game_capabilities():
    """Return the five in-scope games in fail-closed, rules-unverified state."""
    return tuple(GameCapability(game_id) for game_id in SUPPORTED_GAME_IDS)
