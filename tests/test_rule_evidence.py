import json
import unittest
from dataclasses import replace

from app.game_capability import CapabilityState, initial_game_capabilities
from app.minigames.rule_evidence import (
    EvidenceStatus,
    RuleEvidenceProfile,
    RuleFieldEvidence,
    build_simulation_assumption_report,
    get_rule_evidence_profile,
    rule_evidence_profiles,
)


class RuleEvidenceTests(unittest.TestCase):
    def test_registry_covers_only_the_five_approved_games_in_order(self):
        profiles = rule_evidence_profiles()
        self.assertEqual(
            tuple(profile.game_id for profile in profiles),
            ("candy-party", "skewer-master", "burger-day", "starlight-mix", "animal-bath"),
        )
        self.assertEqual(
            tuple(item.state for item in initial_game_capabilities()),
            (CapabilityState.RULES_UNVERIFIED,) * 5,
        )

    def test_every_profile_keeps_current_rule_version_unknown(self):
        for profile in rule_evidence_profiles():
            with self.subTest(game_id=profile.game_id):
                version = profile.field("rule_version")
                self.assertIs(version.status, EvidenceStatus.UNKNOWN)
                self.assertIn("版本", version.reason)
                self.assertIsNone(version.value)

    def test_existing_public_clues_are_source_reported_not_verified_rules(self):
        skewer = get_rule_evidence_profile("skewer-master")
        claim = next(item for item in skewer.source_reported_claims
                     if item.field_id == "official_category_announcement")
        self.assertEqual(claim.source_id, "O2")
        self.assertEqual(claim.source_kind, "official_announcement")
        self.assertIn("不确认具体", claim.limitation)
        self.assertIn("legal_actions", {item.field_id for item in skewer.unknown_fields})

    def test_unknown_and_out_of_scope_games_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "不支持"):
            get_rule_evidence_profile("other-game")
        with self.assertRaisesRegex(ValueError, "不支持"):
            RuleEvidenceProfile("other-game", "其他游戏", ())

    def test_evidence_fields_enforce_distinct_source_assumption_and_unknown_shapes(self):
        supported = RuleFieldEvidence(
            "category", EvidenceStatus.SOURCE_REPORTED, "消除", "O2", "official_announcement",
        )
        assumption = RuleFieldEvidence(
            "test_assumption", EvidenceStatus.ASSUMPTION, "示例假设", reason="仅用于测试报告序列化",
        )
        unknown = RuleFieldEvidence(
            "cost", EvidenceStatus.UNKNOWN, reason="没有成本证据",
        )
        self.assertEqual(supported.to_dict()["status"], "source_reported")
        self.assertEqual(assumption.to_dict()["status"], "assumption")
        self.assertEqual(unknown.to_dict()["status"], "unknown")
        with self.assertRaisesRegex(ValueError, "来源ID"):
            RuleFieldEvidence("category", EvidenceStatus.SOURCE_REPORTED, "消除")
        with self.assertRaisesRegex(ValueError, "unknown只能"):
            RuleFieldEvidence("cost", EvidenceStatus.UNKNOWN, value="0", reason="未知")

    def test_assumption_report_lists_active_assumptions_and_is_json_ready(self):
        profile = get_rule_evidence_profile("candy-party")
        explicit_assumption = RuleFieldEvidence(
            "example_assumption", EvidenceStatus.ASSUMPTION,
            "仅测试报表字段", reason="测试构造，不属于实际游戏规则",
        )
        profile_with_test_assumption = replace(
            profile, fields=profile.fields + (explicit_assumption,),
        )
        report = build_simulation_assumption_report((profile_with_test_assumption,))
        self.assertEqual(report[0]["assumptions"][0]["field_id"], "example_assumption")
        self.assertEqual(report[0]["assumptions"][0]["status"], "assumption")
        json.dumps(report, ensure_ascii=False)

    def test_current_catalog_has_no_simulation_assumptions(self):
        report = build_simulation_assumption_report()
        self.assertEqual(len(report), 5)
        self.assertTrue(all(item["assumptions"] == [] for item in report))

    def test_duplicate_profile_ids_are_rejected_from_report(self):
        profile = get_rule_evidence_profile("animal-bath")
        with self.assertRaisesRegex(ValueError, "不能重复"):
            build_simulation_assumption_report((profile, profile))


if __name__ == "__main__":
    unittest.main()
