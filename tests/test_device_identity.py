import unittest

from app.device_identity import (
    DeviceIdentityUnavailable,
    DeviceInstanceIdentity,
    DeviceLocator,
    mumu12_identity_from_info,
)


class MuMuIdentityTests(unittest.TestCase):
    def record(self, **overrides):
        values = {
            "index": "0",
            "created_timestamp": 1721180910349678,
            "adb_host_ip": "127.0.0.1",
            "adb_port": 16384,
            "name": "MuMu模拟器12",
            "pid": 15112,
            "main_wnd": "00840F4E",
        }
        values.update(overrides)
        return values

    def test_project_and_adb_locators_are_not_part_of_instance_identity(self):
        first_locator = DeviceLocator("C:/project-a", "C:/MuMu/shell/adb.exe", "127.0.0.1:16384")
        second_locator = DeviceLocator("D:/project-b", "D:/tools/adb.exe", "127.0.0.1:7555")
        first = mumu12_identity_from_info(self.record())
        second = mumu12_identity_from_info(self.record(
            adb_port=7555, name="renamed", pid=9024, main_wnd="00000001"
        ))

        self.assertNotEqual(first_locator, second_locator)
        self.assertEqual(first, second)
        self.assertNotIn(first_locator.project_root, first.canonical)
        self.assertNotIn(first_locator.adb_path, first.canonical)
        self.assertNotIn(first_locator.adb_address, first.canonical)

    def test_recreated_instance_at_same_index_gets_a_different_identity(self):
        original = mumu12_identity_from_info(self.record())
        recreated = mumu12_identity_from_info(self.record(created_timestamp=1721180910349679))
        self.assertNotEqual(original, recreated)
        self.assertNotEqual(original.lease_key, recreated.lease_key)

    def test_identity_and_lease_key_are_deterministic(self):
        left = mumu12_identity_from_info(self.record())
        right = mumu12_identity_from_info(self.record())
        self.assertEqual(left.canonical, right.canonical)
        self.assertEqual(left.lease_key, right.lease_key)
        self.assertEqual(len(left.lease_key), 64)
        self.assertTrue(all(character in "0123456789abcdef" for character in left.lease_key))

    def test_missing_or_invalid_manager_identity_never_falls_back_to_adb(self):
        invalid = (
            {},
            {"index": "0", "adb_port": 16384},
            {"created_timestamp": 1721180910349678, "adb_port": 16384},
            self.record(created_timestamp=True),
            self.record(created_timestamp=0),
            self.record(index="0;other=1"),
            None,
        )
        for record in invalid:
            with self.subTest(record=record):
                with self.assertRaises(DeviceIdentityUnavailable):
                    mumu12_identity_from_info(record)

    def test_identity_model_rejects_unknown_schema_or_empty_evidence(self):
        with self.assertRaisesRegex(ValueError, "身份版本"):
            DeviceInstanceIdentity("mumu12", "index=0", schema_version=2)
        with self.assertRaisesRegex(ValueError, "不能为空"):
            DeviceInstanceIdentity("mumu12", "")


if __name__ == "__main__":
    unittest.main()
