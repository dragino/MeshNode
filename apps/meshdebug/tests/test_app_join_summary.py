import unittest

from meshdebug.app import MainWindow


class MainWindowJoinSummaryTests(unittest.TestCase):
    def setUp(self):
        self.window = MainWindow.__new__(MainWindow)

    def test_join_lock_advertise_is_not_joined_evidence(self):
        summary = self.window._node_join_summary(
            {
                "join_lock_advertise": {
                    "sn": "SN001",
                    "dev_eui": "0011223344556677",
                    "join_challenge": "abcd",
                }
            }
        )

        self.assertEqual(summary["state"], "not_joined")
        self.assertEqual(summary["reason"], "join_lock_advertise")

    def test_network_config_is_joined_evidence(self):
        info = {
            "network_config": {
                "network_public_key": "aa" * 32,
                "network_seed": "bb" * 16,
                "trusted_gateway_sources": ["!50070e1b"],
            }
        }

        summary = self.window._node_join_summary(info)
        config = self.window._node_network_config_summary(info)

        self.assertEqual(summary["state"], "joined")
        self.assertEqual(summary["reason"], "network_config captured")
        self.assertTrue(config["captured"])
        self.assertEqual(config["network_public_key_len"], 32)
        self.assertEqual(config["network_seed_len"], 16)
        self.assertEqual(config["trusted_gateway_sources"], ["!50070e1b"])

    def test_join_network_v2_result_overrides_config_shape(self):
        joined = self.window._node_join_summary(
            {"last_operation_result": {"operation": "JOIN_NETWORK_V2", "status": "OK"}}
        )
        failed = self.window._node_join_summary(
            {"last_operation_result": {"operation": "JOIN_NETWORK_V2", "status": "BAD_AUTH_CODE"}}
        )

        self.assertEqual(joined["state"], "joined")
        self.assertEqual(failed["state"], "not_joined")


if __name__ == "__main__":
    unittest.main()
