"""
PKI and Dragino auth helpers used by MeshDebug.

Meshtastic encrypted packets use Curve25519 + SHA256(shared secret) + AES-256-CCM.
Dragino private configuration now uses Meshtastic native X25519 keys plus
HMAC-SHA256 auth_code values for JoinNetWorkV2 and ChangeAdmin.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

_CURVE25519_P = 2**255 - 19
_CURVE25519_A24 = 121665
_CURVE25519_WEAK_POINTS = {
    bytes.fromhex("00" * 32),
    bytes.fromhex("01" + "00" * 31),
    bytes.fromhex("e0eb7a7c3b41b8ae1656e3faf19fc46ada098deb9c32b1fd866205165f49b800"),
    bytes.fromhex("5f9c95bca3508c24b1d0b1559c83ef5b04445cc4581c8e86d8224eddd09f1157"),
    bytes.fromhex("ec" + "ff" * 30 + "7f"),
}


def _require_len(name: str, value: bytes, size: int) -> bytes:
    if len(value) != size:
        raise ValueError(f"{name} must be {size} bytes, got {len(value)}")
    return value


def _firmware_curve25519_eval(private_key: bytes, public_x: bytes | None = None) -> bytes:
    """Match Arduino-Crypto Curve25519::eval(result, private_key, public_x)."""
    scalar = int.from_bytes(_require_len("device_private_key", private_key, 32), "little")
    scalar &= (1 << 255) - 1
    x1 = 9 if public_x is None else int.from_bytes(_require_len("public_x", public_x, 32), "little") & ((1 << 255) - 1)
    x2, z2 = 1, 0
    x3, z3 = x1, 1
    swap = 0

    for bit_index in range(254, -1, -1):
        bit = (scalar >> bit_index) & 1
        swap ^= bit
        if swap:
            x2, x3 = x3, x2
            z2, z3 = z3, z2
        swap = bit

        a = (x2 + z2) % _CURVE25519_P
        aa = (a * a) % _CURVE25519_P
        b = (x2 - z2) % _CURVE25519_P
        bb = (b * b) % _CURVE25519_P
        e = (aa - bb) % _CURVE25519_P
        c = (x3 + z3) % _CURVE25519_P
        d = (x3 - z3) % _CURVE25519_P
        da = (d * a) % _CURVE25519_P
        cb = (c * b) % _CURVE25519_P
        x3 = ((da + cb) * (da + cb)) % _CURVE25519_P
        z3 = (x1 * ((da - cb) * (da - cb))) % _CURVE25519_P
        x2 = (aa * bb) % _CURVE25519_P
        z2 = (e * (aa + _CURVE25519_A24 * e)) % _CURVE25519_P

    if swap:
        x2, x3 = x3, x2
        z2, z3 = z3, z2

    result = (x2 * pow(z2, _CURVE25519_P - 2, _CURVE25519_P)) % _CURVE25519_P
    return result.to_bytes(32, "little")


def _clamp_curve25519_private_key(private_key: bytes) -> bytes:
    raw = bytearray(_require_len("device_private_key", private_key, 32))
    raw[0] &= 0xF8
    raw[31] = (raw[31] & 0x7F) | 0x40
    return bytes(raw)


def generate_keypair() -> tuple[bytes, bytes]:
    """Generate a Meshtastic/Arduino-Crypto compatible Curve25519 key pair."""
    while True:
        private_key = _clamp_curve25519_private_key(os.urandom(32))
        public_key = _firmware_curve25519_eval(private_key)
        if public_key not in _CURVE25519_WEAK_POINTS:
            return private_key, public_key


def public_key_from_private(private_key: bytes) -> bytes:
    """Derive the Meshtastic firmware public key from a 32-byte private key."""
    public_key = _firmware_curve25519_eval(private_key)
    if public_key in _CURVE25519_WEAK_POINTS:
        raise ValueError("device_private_key derives a weak Curve25519 public key")
    return public_key


def generate_ed25519_keypair() -> tuple[bytes, bytes]:
    """Legacy API kept to fail loudly if old tooling calls it."""
    raise ValueError("Ed25519 was removed from the current Dragino join flow.")


def generate_global_keypair() -> tuple[bytes, bytes]:
    """Generate the Dragino Network key pair using Meshtastic native X25519."""
    return generate_keypair()


def encrypt_admin(
    virtual_priv: bytes,
    target_pub: bytes,
    plaintext: bytes,
    packet_id: int,
    from_node_num: int,
) -> bytes:
    """Encrypt an AdminMessage payload using Meshtastic PKI framing."""
    _require_len("virtual_priv", virtual_priv, 32)
    _require_len("target_pub", target_pub, 32)

    priv_key = X25519PrivateKey.from_private_bytes(virtual_priv)
    pub_key = X25519PublicKey.from_public_bytes(target_pub)
    shared_key = hashlib.sha256(priv_key.exchange(pub_key)).digest()

    extra_nonce = os.urandom(4)
    nonce_13 = (
        struct.pack("<Q", packet_id & 0xFFFF_FFFF_FFFF_FFFF)
        + struct.pack("<I", from_node_num & 0xFFFF_FFFF)
        + extra_nonce[:1]
    )

    aesccm = AESCCM(shared_key, tag_length=8)
    return aesccm.encrypt(nonce_13, plaintext, None) + extra_nonce


def node_num_from_id(node_id_str: str) -> int:
    """Convert '!aabbccdd' or 'aabbccdd' into a uint32 node number."""
    return int(node_id_str.strip().lstrip("!"), 16) & 0xFFFF_FFFF


def make_network_access_sign_data(
    flash_public_id: bytes,
    join_nonce: bytes,
    global_public_key: bytes,
    gateway_public_key: bytes,
    gateway_node_id: int,
    timestamp: int,
) -> bytes:
    """Legacy NetworkAccess was removed; use JoinNetWorkV2 HMAC instead."""
    raise ValueError("NetworkAccess was removed. Use hmac_join_network_v2().")


def sign_network_access(
    flash_private_key: bytes,
    flash_public_id: bytes,
    join_nonce: bytes,
    global_public_key: bytes,
    gateway_public_key: bytes,
    gateway_node_id: int,
    timestamp: int,
) -> bytes:
    """Legacy NetworkAccess was removed; use JoinNetWorkV2 HMAC instead."""
    raise ValueError("NetworkAccess was removed. Use hmac_join_network_v2().")


def _parse_dev_eui_words(dev_eui: str) -> tuple[int, int]:
    text = "".join(ch for ch in (dev_eui or "") if ch in "0123456789abcdefABCDEF")
    if len(text) != 16:
        raise ValueError(f"dev_eui must be 16 hex chars, got {len(text)}")
    return int(text[:8], 16), int(text[8:], 16)


def make_join_network_v2_sign_data(
    sn: str,
    dev_eui: str,
    join_challenge: bytes,
    target_node_id: int,
    gateway_node_id: int,
    gateway_public_key: bytes,
    network_public_key: bytes,
    network_seed: bytes,
    timestamp: int,
) -> bytes:
    """Build the exact byte sequence authenticated by firmware JoinNetWorkV2."""
    if not 16 <= len(network_seed) <= 32:
        raise ValueError(f"network_seed must be 16-32 bytes, got {len(network_seed)}")
    sn_bytes = (sn or "").encode("utf-8")
    if len(sn_bytes) > 19:
        raise ValueError(f"sn must fit firmware 20-byte C string, got {len(sn_bytes)} bytes")
    sn_field = sn_bytes + b"\x00" * (20 - len(sn_bytes))
    dev_eui_hi, dev_eui_lo = _parse_dev_eui_words(dev_eui)
    return (
        b"DraginoJoinV2"
        + sn_field
        + struct.pack("<I", dev_eui_hi & 0xFFFF_FFFF)
        + struct.pack("<I", dev_eui_lo & 0xFFFF_FFFF)
        + _require_len("join_challenge", join_challenge, 16)
        + struct.pack("<I", target_node_id & 0xFFFF_FFFF)
        + struct.pack("<I", gateway_node_id & 0xFFFF_FFFF)
        + _require_len("gateway_public_key", gateway_public_key, 32)
        + _require_len("network_public_key", network_public_key, 32)
        + struct.pack("B", len(network_seed))
        + network_seed
        + struct.pack("<Q", timestamp & 0xFFFF_FFFF_FFFF_FFFF)
    )


def sign_join_network_v2(
    join_authority_private_key: bytes,
    sn: str,
    dev_eui: str,
    *,
    flash_public_id: bytes | None = None,
    join_nonce: bytes | None = None,
    join_challenge: bytes | None = None,
    target_node_id: int = 0,
    gateway_node_id: int,
    gateway_public_key: bytes,
    global_public_key: bytes | None = None,
    network_public_key: bytes | None = None,
    network_seed: bytes,
    timestamp: int,
) -> bytes:
    """Compatibility wrapper: return the current JoinNetWorkV2 HMAC auth_code."""
    key = _require_len("join_authority_private_key", join_authority_private_key, 32)
    challenge = join_challenge if join_challenge is not None else join_nonce
    if challenge is None:
        raise ValueError("join_challenge is required")
    net_pub = network_public_key if network_public_key is not None else global_public_key
    if net_pub is None:
        raise ValueError("network_public_key is required")
    sign_data = make_join_network_v2_sign_data(
        sn=sn,
        dev_eui=dev_eui,
        join_challenge=challenge,
        target_node_id=target_node_id,
        gateway_node_id=gateway_node_id,
        gateway_public_key=gateway_public_key,
        network_public_key=net_pub,
        network_seed=network_seed,
        timestamp=timestamp,
    )
    return hmac.new(key, sign_data, hashlib.sha256).digest()


def hmac_join_network_v2(
    device_private_key: bytes,
    sn: str,
    dev_eui: str,
    join_challenge: bytes,
    target_node_id: int,
    gateway_node_id: int,
    gateway_public_key: bytes,
    network_public_key: bytes,
    network_seed: bytes,
    timestamp: int,
) -> bytes:
    """Generate JoinNetWorkV2.auth_code."""
    return sign_join_network_v2(
        join_authority_private_key=device_private_key,
        sn=sn,
        dev_eui=dev_eui,
        join_challenge=join_challenge,
        target_node_id=target_node_id,
        gateway_node_id=gateway_node_id,
        gateway_public_key=gateway_public_key,
        network_public_key=network_public_key,
        network_seed=network_seed,
        timestamp=timestamp,
    )


def derive_join_network_v2_psk(label: str, network_seed: bytes) -> bytes:
    """Derive the same channel PSK that firmware writes for JoinNetWorkV2."""
    if not 16 <= len(network_seed) <= 32:
        raise ValueError(f"network_seed must be 16-32 bytes, got {len(network_seed)}")
    return hashlib.sha256(label.encode("ascii") + network_seed).digest()


def hmac_gateway_announce(network_seed: bytes, network_public_key: bytes) -> bytes:
    """Build GatewayAnnounce.auth_code exactly as the firmware verifies it."""
    if not 16 <= len(network_seed) <= 32:
        raise ValueError(f"network_seed must be 16-32 bytes, got {len(network_seed)}")
    network_public_key = _require_len("network_public_key", network_public_key, 32)
    return hmac.new(
        network_seed,
        b"DraginoGatewayAnnounceV1" + network_public_key,
        hashlib.sha256,
    ).digest()


def _sign_key_change_or_admin(
    global_priv: bytes,
    new_public_key: bytes,
    timestamp: int,
    device_node_id: int,
) -> bytes:
    raise ValueError("Ed25519 management signatures were removed. Use current auth_code helpers.")


def make_change_admin_auth_data(
    sn: str,
    dev_eui: str,
    target_node_id: int,
    current_network_public_key: bytes,
    new_gateway_node_id: int,
    new_gateway_public_key: bytes,
    timestamp: int,
) -> bytes:
    """Build the exact byte sequence authenticated by firmware ChangeAdmin."""
    sn_bytes = (sn or "").encode("utf-8")
    if len(sn_bytes) > 19:
        raise ValueError(f"sn must fit firmware 20-byte C string, got {len(sn_bytes)} bytes")
    sn_field = sn_bytes + b"\x00" * (20 - len(sn_bytes))
    dev_eui_hi, dev_eui_lo = _parse_dev_eui_words(dev_eui)
    return (
        b"DraginoChangeAdminV1"
        + sn_field
        + struct.pack("<I", dev_eui_hi & 0xFFFF_FFFF)
        + struct.pack("<I", dev_eui_lo & 0xFFFF_FFFF)
        + struct.pack("<I", target_node_id & 0xFFFF_FFFF)
        + _require_len("current_network_public_key", current_network_public_key, 32)
        + struct.pack("<I", new_gateway_node_id & 0xFFFF_FFFF)
        + _require_len("new_gateway_public_key", new_gateway_public_key, 32)
        + struct.pack("<Q", timestamp & 0xFFFF_FFFF_FFFF_FFFF)
    )


def hmac_change_admin(
    device_private_key: bytes,
    sn: str,
    dev_eui: str,
    target_node_id: int,
    current_network_public_key: bytes,
    new_gateway_node_id: int,
    new_gateway_public_key: bytes,
    timestamp: int,
) -> bytes:
    """Generate ChangeAdmin.auth_code."""
    key = _require_len("device_private_key", device_private_key, 32)
    data = make_change_admin_auth_data(
        sn=sn,
        dev_eui=dev_eui,
        target_node_id=target_node_id,
        current_network_public_key=current_network_public_key,
        new_gateway_node_id=new_gateway_node_id,
        new_gateway_public_key=new_gateway_public_key,
        timestamp=timestamp,
    )
    return hmac.new(key, data, hashlib.sha256).digest()


def sign_change_admin(
    company_priv: bytes,
    new_gw_pub: bytes,
    timestamp: int,
    device_node_id: int,
) -> bytes:
    """Legacy Ed25519 ChangeAdmin API."""
    raise ValueError("Use hmac_change_admin() for current ChangeAdmin.auth_code.")


def sign_change_global_key(
    global_priv: bytes,
    new_global_pub: bytes,
    timestamp: int,
    device_node_id: int,
) -> bytes:
    """Legacy Ed25519 ChangeGlobalKey API."""
    raise ValueError("Use ChangeNetworkKey.auth_code in the current protocol.")


def sign_change_company_key(
    company_priv: bytes,
    new_company_pub: bytes,
    timestamp: int,
    device_node_id: int,
) -> bytes:
    """Legacy Ed25519 ChangeGlobalKey API."""
    raise ValueError("Use ChangeNetworkKey.auth_code in the current protocol.")


def sign_reset_network_config(
    global_priv: bytes,
    reset_type: int,
    timestamp: int,
    device_node_id: int,
) -> bytes:
    """Legacy Ed25519 ResetNetworkConfig API."""
    raise ValueError("Use ResetNetworkConfig.auth_code in the current protocol.")


def sign_reset_config(
    company_priv: bytes,
    reset_type: int,
    timestamp: int,
    device_node_id: int,
) -> bytes:
    """Legacy name for ResetNetworkConfig."""
    return sign_reset_network_config(company_priv, reset_type, timestamp, device_node_id)
