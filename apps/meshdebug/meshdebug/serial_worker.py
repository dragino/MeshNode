"""
meshdebug/serial_worker.py
QThread 后台串口读取工作线程，同时提供线程安全的发送接口。

帧格式（与 mesh_gateway 完全相同）：
    [0x94][0xC3][len_MSB][len_LSB][FromRadio / ToRadio protobuf payload]
"""

import logging
import random
import struct
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

import serial
import serial.tools.list_ports
from PyQt6.QtCore import QThread, pyqtSignal
from meshtastic import mesh_pb2

from meshdebug.proto_parser import parse_from_radio

logger = logging.getLogger(__name__)

FRAME_MAGIC_1   = 0x94
FRAME_MAGIC_2   = 0xC3
MAX_PAYLOAD_LEN = 512 * 1024   # 512 KB 防护上限


def list_serial_ports() -> list[dict]:
    """返回 [{"device": "COM3", "description": "USB Serial"}, ...]"""
    return [
        {"device": p.device, "description": p.description}
        for p in serial.tools.list_ports.comports()
    ]


class SerialWorker(QThread):
    """
    后台串口读取线程，兼具发送能力。

    Signals
    -------
    frame_received(dict)
        每收到并解析完一帧触发。dict 为 parse_from_radio 的返回值。
    status_changed(str)
        连接状态变化，格式：
            "connected:<port>"
            "disconnected"
            "error:<消息>"
    """

    frame_received = pyqtSignal(dict)
    status_changed = pyqtSignal(str)
    text_received  = pyqtSignal(str)   # 设备输出的普通文本行（非 protobuf 帧）

    def __init__(self, port: str, baudrate: int = 115200):
        super().__init__()
        self.port     = port
        self.baudrate = baudrate

        self._running    = False
        self._ser: Optional[serial.Serial] = None
        self._write_lock = threading.Lock()   # 保护串口写操作
        self._text_buffer: bytearray = bytearray()  # 非帧字节缓冲

    # ── 公开接口 ──────────────────────────────────────────────────────────────

    def stop(self):
        """请求停止读取线程（线程安全）。"""
        self._running = False

    def is_running(self) -> bool:
        return self._running and self._ser is not None and self._ser.is_open

    def send_packet(self, mesh_packet: mesh_pb2.MeshPacket) -> tuple[bool, str]:
        """
        线程安全地将 MeshPacket 包裹成 ToRadio 帧并发送。

        Parameters
        ----------
        mesh_packet : 已填充字段的 MeshPacket

        Returns
        -------
        (True,  frame_hex) — 写入串口成功，frame_hex 为完整帧的十六进制字符串
        (False, "")        — 串口未连接或写入失败
        """
        if not self.is_running():
            logger.warning("send_packet: 串口未连接")
            return False, ""

        try:
            to_radio = mesh_pb2.ToRadio()
            to_radio.packet.CopyFrom(mesh_packet)
            payload = to_radio.SerializeToString()
            frame = (
                bytes([FRAME_MAGIC_1, FRAME_MAGIC_2])
                + struct.pack(">H", len(payload))
                + payload
            )
            with self._write_lock:
                self._ser.write(frame)
            logger.debug("已发送 MeshPacket id=%d", mesh_packet.id)
            return True, frame.hex()
        except Exception as exc:
            logger.error("send_packet 失败: %s", exc)
            return False, ""

    def send_heartbeat(self) -> bool:
        """发送 ToRadio.heartbeat 维持串口连接（固件 15 分钟超时前）。"""
        if not self.is_running():
            return False
        try:
            to_radio = mesh_pb2.ToRadio()
            to_radio.heartbeat.CopyFrom(mesh_pb2.Heartbeat())
            payload = to_radio.SerializeToString()
            frame = (
                bytes([FRAME_MAGIC_1, FRAME_MAGIC_2])
                + struct.pack(">H", len(payload))
                + payload
            )
            with self._write_lock:
                self._ser.write(frame)
            logger.debug("Heartbeat sent")
            return True
        except Exception as exc:
            logger.error("send_heartbeat 失败: %s", exc)
            return False

    # ── QThread.run ───────────────────────────────────────────────────────────

    def run(self):
        """线程主体：带自动重连的外层循环 → 打开串口 → 握手 → 帧读取。"""
        delay = 1.0   # 指数退避起始延迟（秒）

        while True:
            # ── 尝试打开串口 ──────────────────────────────────────────────
            try:
                self._ser = serial.Serial(
                    port=self.port,
                    baudrate=self.baudrate,
                    timeout=0.5,
                    write_timeout=0,
                )
            except serial.SerialException as exc:
                logger.error("串口打开失败 [%s]: %s", self.port, exc)
                self.status_changed.emit(f"error:串口打开失败: {exc}")
                break   # 端口不存在等永久错误，直接退出

            logger.info("串口已连接: %s @ %d baud", self.port, self.baudrate)
            self._send_want_config()
            self._running = True
            self.status_changed.emit(f"connected:{self.port}")
            delay = 1.0   # 成功连接后重置退避计时

            # ── 帧读取循环 ────────────────────────────────────────────────
            while self._running:
                try:
                    self._read_one_frame()
                except serial.SerialException as exc:
                    logger.error("串口异常断开: %s", exc)
                    self.status_changed.emit(f"error:串口异常断开: {exc}")
                    break   # 退出内层，进入重连
                except Exception as exc:
                    logger.warning("帧解析异常，跳过: %s", exc)

            if self._ser and self._ser.is_open:
                self._ser.close()
            self._flush_text_buffer()   # 刷出断连前缓冲中的残余文本

            # ── 判断退出还是重连 ──────────────────────────────────────────
            if not self._running:
                break   # 用户主动 stop()，正常退出

            # 串口意外断线 → 指数退避后重连
            logger.info("等待 %.0fs 后重连…", delay)
            self.status_changed.emit(f"reconnecting:{delay:.0f}s")
            time.sleep(delay)
            delay = min(delay * 2, 30.0)

        self.status_changed.emit("disconnected")
        logger.info("串口工作线程退出: %s", self.port)

    # ── 内部实现 ──────────────────────────────────────────────────────────────

    def _send_want_config(self):
        """发送 want_config_id 握手，触发设备推送完整配置。"""
        cfg_id   = random.randint(1, 0xFFFF_FFFF)
        to_radio = mesh_pb2.ToRadio()
        to_radio.want_config_id = cfg_id
        payload = to_radio.SerializeToString()
        frame = (
            bytes([FRAME_MAGIC_1, FRAME_MAGIC_2])
            + struct.pack(">H", len(payload))
            + payload
        )
        with self._write_lock:
            self._ser.write(frame)
        logger.debug("已发送 want_config_id=%d", cfg_id)

    def _read_exact(self, n: int) -> bytes:
        """精确读取 n 字节，超时抛出 TimeoutError。"""
        buf      = b""
        deadline = time.monotonic() + 5.0
        while len(buf) < n:
            if time.monotonic() > deadline:
                raise TimeoutError(f"读取 {n} 字节超时，已读 {len(buf)} 字节")
            chunk = self._ser.read(n - len(buf))
            if chunk:
                buf += chunk
        return buf

    def _flush_text_lines(self):
        """将 _text_buffer 中以 \\n 结尾的完整行逐条 emit text_received 信号。"""
        while b'\n' in self._text_buffer:
            idx = self._text_buffer.index(b'\n')
            line_bytes = bytes(self._text_buffer[:idx])
            self._text_buffer = self._text_buffer[idx + 1:]
            text = line_bytes.decode('utf-8', errors='replace').rstrip('\r')
            if text.strip():
                self.text_received.emit(text)

    def _flush_text_buffer(self):
        """在帧到来或断连前刷出缓冲中剩余的不完整文本行。"""
        if self._text_buffer:
            text = bytes(self._text_buffer).decode('utf-8', errors='replace').rstrip('\r\n')
            self._text_buffer = bytearray()
            if text.strip():
                self.text_received.emit(text)

    def _read_one_frame(self):
        """
        帧读取：
          byte 0   : 0x94 (START1)
          byte 1   : 0xC3 (START2)
          byte 2-3 : payload 长度（大端）
          byte 4+  : FromRadio protobuf bytes

        非帧字节（设备 Serial.println 等文本输出）缓冲后按行 emit text_received 信号。
        """
        b = self._ser.read(1)
        if not b:
            return

        if b[0] != FRAME_MAGIC_1:
            # 非帧起始字节 → 放入文本缓冲，尝试输出完整行
            self._text_buffer.extend(b)
            self._flush_text_lines()
            return

        b2 = self._ser.read(1)
        if not b2 or b2[0] != FRAME_MAGIC_2:
            # 0x94 后不是 0xC3 → 两个字节都视为文本
            self._text_buffer.append(b[0])
            if b2:
                self._text_buffer.extend(b2)
            self._flush_text_lines()
            return

        # 合法帧头 0x94 0xC3 → 先刷出缓冲文本，再解析帧
        self._flush_text_buffer()

        len_bytes   = self._read_exact(2)
        payload_len = struct.unpack(">H", len_bytes)[0]

        if payload_len == 0 or payload_len > MAX_PAYLOAD_LEN:
            logger.warning("非法 payload 长度: %d，跳过", payload_len)
            return

        received_utc = datetime.now(timezone.utc)
        payload      = self._read_exact(payload_len)

        raw_hex = (
            bytes([FRAME_MAGIC_1, FRAME_MAGIC_2]) + len_bytes + payload
        ).hex()

        from_radio = mesh_pb2.FromRadio()
        try:
            from_radio.ParseFromString(payload)
        except Exception as exc:
            ts_str = received_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            self.frame_received.emit({
                "id": None,
                "variant": "parse_error",
                "received_at": ts_str,
                "raw_hex": raw_hex,
                "summary": f"FromRadio parse error: {exc}",
                "data": {
                    "parse_error": str(exc),
                    "payload_len": payload_len,
                },
            })
            return

        if from_radio.WhichOneof("payload_variant") == "rebooted":
            logger.info("设备已重启，重新发送 want_config 握手")
            self._send_want_config()

        frame_dict = parse_from_radio(from_radio, raw_hex, received_utc)
        self.frame_received.emit(frame_dict)
