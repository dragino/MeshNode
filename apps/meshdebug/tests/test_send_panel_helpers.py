import unittest
import time as _time
from unittest.mock import patch

from meshtastic import mesh_pb2
from meshdebug.private_config_pb2 import (
    PrivateConfigPacket,
    encode_change_network_key,
    encode_gateway_announce,
    encode_keep_awake,
    encode_set_sync_wakeup,
    encode_trusted_gateway_config,
)
from meshdebug.pki_crypto import hmac_gateway_announce
from meshdebug.widgets.send_panel import (
    SendPanel,
    _PORTNUM_OPTIONS,
    _is_admin_node_id_field,
    _parse_node_id,
    _parse_required_node_id,
)


class _FakeCheckBox:
    def __init__(self, checked=False):
        self.checked = None
        self._checked = checked

    def setChecked(self, value):
        self.checked = bool(value)
        self._checked = bool(value)

    def isChecked(self):
        return self._checked


class _FakeCombo:
    def __init__(self, current_index=0, current_data=None):
        self._current_index = current_index
        self._current_data = current_data

    def currentIndex(self):
        return self._current_index

    def currentData(self):
        return self._current_data


class _FakeLineEdit:
    def __init__(self, text=""):
        self._text = text

    def text(self):
        return self._text


class _FakeSpin:
    def __init__(self, value=0):
        self._value = value

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = value


class _FakeSignal:
    def __init__(self):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)


def _port_index(portnum):
    return next(i for i, (_, value, _) in enumerate(_PORTNUM_OPTIONS) if value == portnum)


class SendPanelHelperTests(unittest.TestCase):
    def test_parse_node_id_accepts_bang_hex(self):
        self.assertEqual(_parse_node_id("!aabbccdd"), 0xAABBCCDD)

    def test_parse_node_id_accepts_plain_hex(self):
        self.assertEqual(_parse_node_id("aabbccdd"), 0xAABBCCDD)

    def test_parse_node_id_accepts_prefixed_hex(self):
        self.assertEqual(_parse_node_id("0xAABBCCDD"), 0xAABBCCDD)

    def test_parse_node_id_accepts_decimal(self):
        self.assertEqual(_parse_node_id("2864434397"), 0xAABBCCDD)

    def test_admin_node_id_field_detection(self):
        self.assertTrue(_is_admin_node_id_field("remove_by_nodenum"))
        self.assertTrue(_is_admin_node_id_field("set_ignored_node"))
        self.assertFalse(_is_admin_node_id_field("set_time_only"))
        self.assertFalse(_is_admin_node_id_field(None))

    def test_required_node_id_rejects_empty_input(self):
        with self.assertRaisesRegex(ValueError, "node_num"):
            _parse_required_node_id("   ", "node_num")

    def test_required_node_id_rejects_invalid_input(self):
        with self.assertRaisesRegex(ValueError, "remote_nodenum"):
            _parse_required_node_id("xyz-not-id", "remote_nodenum")

    def test_required_node_id_rejects_out_of_range_input(self):
        with self.assertRaisesRegex(ValueError, "uint32"):
            _parse_required_node_id("0x1FFFFFFFF", "node_num")

    def test_want_response_default_clears_for_custom_position(self):
        panel = SendPanel.__new__(SendPanel)
        panel.want_resp_chk = _FakeCheckBox()
        panel.portnum_combo = _FakeCombo(current_index=_port_index(286))
        panel.pc_op_combo = _FakeCombo(current_data="get_join_lock_advertise")

        SendPanel._sync_want_response_default(panel)

        self.assertFalse(panel.want_resp_chk.checked)

    def test_want_response_default_enabled_for_private_config_get_join_lock(self):
        panel = SendPanel.__new__(SendPanel)
        panel.want_resp_chk = _FakeCheckBox()
        panel.portnum_combo = _FakeCombo(current_index=_port_index(287))
        panel.pc_op_combo = _FakeCombo(current_data="get_join_lock_advertise")

        SendPanel._sync_want_response_default(panel)

        self.assertTrue(panel.want_resp_chk.checked)

    def test_custom_position_autofills_zero_time_for_port_286(self):
        panel = SendPanel.__new__(SendPanel)
        panel.time_spin = _FakeSpin(0)

        before = int(_time.time())
        SendPanel._autofill_custom_position_time(panel, 286, 1)
        after = int(_time.time())

        self.assertGreaterEqual(panel.time_spin.value(), before)
        self.assertLessEqual(panel.time_spin.value(), after)

    def test_custom_position_autofill_preserves_explicit_time(self):
        panel = SendPanel.__new__(SendPanel)
        panel.time_spin = _FakeSpin(1234567890)

        SendPanel._autofill_custom_position_time(panel, 286, 1)

        self.assertEqual(panel.time_spin.value(), 1234567890)

    def test_custom_position_autofill_ignores_standard_position_port(self):
        panel = SendPanel.__new__(SendPanel)
        panel.time_spin = _FakeSpin(0)

        SendPanel._autofill_custom_position_time(panel, 3, 1)

        self.assertEqual(panel.time_spin.value(), 0)

    def test_join_v2_send_detected_only_on_private_config_join_v2(self):
        panel = SendPanel.__new__(SendPanel)
        panel.portnum_combo = _FakeCombo(current_index=_port_index(287))
        panel.pc_op_combo = _FakeCombo(current_data="join_network_v2")

        self.assertTrue(SendPanel._is_join_network_v2_send(panel))

        panel.pc_op_combo = _FakeCombo(current_data="get_join_lock_advertise")
        self.assertFalse(SendPanel._is_join_network_v2_send(panel))

        panel.portnum_combo = _FakeCombo(current_index=_port_index(4))
        panel.pc_op_combo = _FakeCombo(current_data="join_network_v2")
        self.assertFalse(SendPanel._is_join_network_v2_send(panel))

    def test_send_click_build_error_warns_user(self):
        panel = SendPanel.__new__(SendPanel)
        panel.send_requested = _FakeSignal()
        logs = []
        panel.log_result = lambda success, msg: logs.append((success, msg))
        panel._build_packet = lambda: (_ for _ in ()).throw(
            ValueError("JoinNetWorkV2 needs target node, network_public_key, network_seed, timestamp and auth_code")
        )

        with patch("PyQt6.QtWidgets.QMessageBox.warning") as warning:
            SendPanel._on_send_clicked(panel)

        self.assertEqual([], panel.send_requested.emitted)
        self.assertTrue(logs)
        warning.assert_called_once()
        self.assertIn("JoinNetWorkV2", warning.call_args.args[2])

    def test_join_v2_nodeinfo_gateway_prefers_form_gateway_id(self):
        panel = SendPanel.__new__(SendPanel)
        panel.pc_na_gwid_edit = _FakeLineEdit("!12345678")
        panel._local_node_id = "!87654321"

        self.assertEqual(SendPanel._join_v2_gateway_node_for_nodeinfo(panel), "!12345678")

    def test_join_v2_nodeinfo_gateway_falls_back_to_local_node(self):
        panel = SendPanel.__new__(SendPanel)
        panel.pc_na_gwid_edit = _FakeLineEdit("")
        panel._local_node_id = "!87654321"

        self.assertEqual(SendPanel._join_v2_gateway_node_for_nodeinfo(panel), "!87654321")

    def test_build_join_v2_nodeinfo_packet_does_not_require_nodeinfo_public_key(self):
        panel = SendPanel.__new__(SendPanel)
        panel.pc_na_gwid_edit = _FakeLineEdit("!11223344")
        panel._local_node_id = "!87654321"
        panel.ni_id_edit = _FakeLineEdit("")
        panel.ni_long_edit = _FakeLineEdit("")
        panel.ni_short_edit = _FakeLineEdit("")
        panel.ni_hw_combo = _FakeCombo(current_data=0)
        panel.ni_lic_chk = _FakeCheckBox(False)
        panel.ni_role_combo = _FakeCombo(current_data=0)
        panel.ni_pubkey_edit = _FakeLineEdit("")
        panel.hop_spin = _FakeSpin(3)
        join_packet = mesh_pb2.MeshPacket()
        join_packet.to = 0xAABBCCDD

        nodeinfo_packet = SendPanel._build_join_v2_nodeinfo_packet(panel, join_packet)

        self.assertEqual(nodeinfo_packet.to, 0x11223344)
        self.assertEqual(getattr(nodeinfo_packet, "from"), 0xAABBCCDD)
        self.assertEqual(nodeinfo_packet.channel, 0)
        self.assertEqual(nodeinfo_packet.decoded.portnum, 4)
        self.assertFalse(nodeinfo_packet.want_ack)
        self.assertEqual(nodeinfo_packet.decoded.payload, b"")

    def test_private_config_encodes_trusted_gateway_add(self):
        payload = encode_trusted_gateway_config(
            is_single_gateway=False,
            add_gateway=0xAABBCCDD,
        )
        pkt = PrivateConfigPacket()
        pkt.ParseFromString(payload)
        cfg = pkt.downlink_packet.set_network_config.trusted_gateway_config

        self.assertFalse(cfg.is_single_gateway)
        self.assertEqual(cfg.WhichOneof("payload"), "add_trusted_gateway")
        self.assertEqual(cfg.add_trusted_gateway, 0xAABBCCDD)

    def test_private_config_encodes_change_network_key_seed_and_label(self):
        new_pub = bytes(range(32))
        new_seed = b"seed-012345678901"
        payload = encode_change_network_key(
            new_network_public_key=new_pub,
            new_network_seed=new_seed,
            timestamp=123456,
            label_id=0x01020304,
        )
        pkt = PrivateConfigPacket()
        pkt.ParseFromString(payload)
        change = pkt.downlink_packet.set_network_config.change_network_key

        self.assertEqual(pkt.label_id, 0x01020304)
        self.assertEqual(bytes(change.new_network_public_key), new_pub)
        self.assertEqual(bytes(change.new_network_seed), new_seed)
        self.assertEqual(bytes(change.auth_code), bytes(32))

    def test_private_config_encodes_gateway_announce_hmac(self):
        network_pub = b"\x11" * 32
        network_seed = b"1234567890abcdef"
        payload = encode_gateway_announce(
            network_public_key=network_pub,
            network_seed=network_seed,
            label_id=7,
        )
        pkt = PrivateConfigPacket()
        pkt.ParseFromString(payload)
        announce = pkt.downlink_packet.set_network_config.gateway_announce

        self.assertEqual(pkt.label_id, 7)
        self.assertEqual(bytes(announce.network_public_key), network_pub)
        self.assertEqual(bytes(announce.auth_code), hmac_gateway_announce(network_seed, network_pub))

    def test_private_config_encodes_keep_awake_label(self):
        payload = encode_keep_awake(duration_sec=300, label_id=0x42)
        pkt = PrivateConfigPacket()
        pkt.ParseFromString(payload)
        keep = pkt.downlink_packet.set_sync_wakeup_config.keep_awake

        self.assertEqual(pkt.label_id, 0x42)
        self.assertEqual(keep.duration_sec, 300)

    def test_private_config_encodes_sync_wakeup_scheduled_and_window(self):
        payload = encode_set_sync_wakeup(
            enabled=True,
            interval_min=30,
            align_minute=5,
            offset_sec=7,
            strategy=1,
            scheduled_slots=[(0, 6, 60, 0), (6, 18, 30, 15)],
            startup_delay_sec=3,
            gateway_wait_sec=20,
            final_wait_sec=5,
        )
        pkt = PrivateConfigPacket()
        pkt.ParseFromString(payload)
        cfg = pkt.downlink_packet.set_sync_wakeup_config.config

        self.assertEqual(cfg.strategy, 1)
        self.assertEqual(cfg.scheduled_wakeup.offset_sec, 7)
        self.assertEqual(len(cfg.scheduled_wakeup.time_slots), 2)
        self.assertEqual(cfg.scheduled_wakeup.time_slots[1].start_hour, 6)
        self.assertEqual(cfg.scheduled_wakeup.time_slots[1].align_minute, 15)
        self.assertEqual(cfg.wakeup_window.startup_delay_sec, 3)
        self.assertEqual(cfg.wakeup_window.gateway_wait_sec, 20)
        self.assertEqual(cfg.wakeup_window.final_wait_sec, 5)


if __name__ == "__main__":
    unittest.main()
