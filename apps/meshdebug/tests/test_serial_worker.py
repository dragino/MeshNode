import unittest

from meshdebug.serial_worker import FRAME_MAGIC_1, FRAME_MAGIC_2, SerialWorker


class _FakeSerial:
    def __init__(self, data: bytes):
        self._data = bytearray(data)

    def read(self, count: int) -> bytes:
        chunk = bytes(self._data[:count])
        del self._data[:count]
        return chunk


class SerialWorkerTests(unittest.TestCase):
    def test_malformed_from_radio_frame_emits_parse_error_frame(self):
        frame = bytes([FRAME_MAGIC_1, FRAME_MAGIC_2, 0x00, 0x01, 0xFF])
        worker = SerialWorker("COM_TEST")
        worker._ser = _FakeSerial(frame)
        received = []
        worker.frame_received.connect(received.append)

        worker._read_one_frame()

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["variant"], "parse_error")
        self.assertEqual(received[0]["raw_hex"], frame.hex())
        self.assertIn("parse_error", received[0]["data"])


if __name__ == "__main__":
    unittest.main()
