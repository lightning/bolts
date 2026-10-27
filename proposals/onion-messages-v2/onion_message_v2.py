"""Reference implementation of Onion Messages Version 2 (Extension BOLT XX).

Not constant time, not for production use. Intended to document the
construction and to generate test vectors.

Dependencies: coincurve (libsecp256k1), cryptography (ChaCha20, ChaCha20-Poly1305).
"""
from __future__ import annotations

import hashlib
import hmac
import struct
from dataclasses import dataclass, field
from typing import Optional

from coincurve import PrivateKey, PublicKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

CURVE_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

SLOT_LEN = 114            # 82 byte encrypted_hop_data + 32 byte next_hmac
NUM_SLOTS = 8
HEADER_LEN = NUM_SLOTS * SLOT_LEN   # 912
ENC_HOP_DATA_LEN = 82     # 66 byte plaintext + 16 byte Poly1305 tag
HOP_DATA_LEN = 66
HMAC_LEN = 32
PACKET_OVERHEAD = 1 + 33 + 33 + HEADER_LEN + HMAC_LEN   # 1011: version, path_key, public_key, header, hmac
MSG_TYPE_ONION_MESSAGE_V2 = 515
MAX_E2E_PAYLOAD_LEN = 65535 - 2 - 2 - PACKET_OVERHEAD   # 64520: type, len
ALLOWED_PAYLOAD_LENS = [1 << k for k in range(8, 16)] + [MAX_E2E_PAYLOAD_LEN]

ZERO_HMAC = bytes(HMAC_LEN)

assert HEADER_LEN == 912
assert MAX_E2E_PAYLOAD_LEN == 64520


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------

def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def hmac256(key: bytes, msg: bytes) -> bytes:
    """HMAC-SHA256 where `key` is the key-type (e.g. b"rho")."""
    return hmac.new(key, msg, hashlib.sha256).digest()


def chacha20_stream(key: bytes, length: int) -> bytes:
    """ChaCha20 keystream with a 96-bit all-zero nonce and counter 0."""
    enc = Cipher(algorithms.ChaCha20(key, bytes(16)), mode=None).encryptor()
    return enc.update(bytes(length))


def xor(a: bytes, b: bytes) -> bytes:
    assert len(a) == len(b)
    return bytes(x ^ y for x, y in zip(a, b))


def to_scalar(b: bytes) -> int:
    return int.from_bytes(b, "big") % CURVE_ORDER


def priv_to_pub(priv: int) -> bytes:
    return PrivateKey(priv.to_bytes(32, "big")).public_key.format(compressed=True)


def point_mul(point: bytes, scalar: int) -> bytes:
    return PublicKey(point).multiply(scalar.to_bytes(32, "big")).format(compressed=True)


def ecdh(priv: int, point: bytes) -> bytes:
    """BOLT 4 shared secret: SHA256 of the compressed ECDH point."""
    return sha256(point_mul(point, priv))


def is_valid_point(b: bytes) -> bool:
    try:
        PublicKey(b)
        return len(b) == 33
    except Exception:
        return False


# Key-types
def key_rho(secret: bytes) -> bytes:
    return hmac256(b"rho", secret)


def key_mu(secret: bytes) -> bytes:
    return hmac256(b"mu", secret)


def key_pad(secret: bytes) -> bytes:
    return hmac256(b"pad", secret)


def key_delta(secret: bytes) -> bytes:
    return hmac256(b"delta", secret)


def blinding_factor(secret: bytes) -> bytes:
    return hmac256(b"blinded_node_id", secret)


# --------------------------------------------------------------------------
# Serialization helpers
# --------------------------------------------------------------------------

def encode_bigsize(n: int) -> bytes:
    if n < 0xFD:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\xfd" + n.to_bytes(2, "big")
    if n <= 0xFFFFFFFF:
        return b"\xfe" + n.to_bytes(4, "big")
    return b"\xff" + n.to_bytes(8, "big")


def decode_bigsize(b: bytes, off: int) -> tuple[int, int]:
    first = b[off]
    if first < 0xFD:
        return first, off + 1
    size = {0xFD: 2, 0xFE: 4, 0xFF: 8}[first]
    if off + 1 + size > len(b):
        raise ValueError("truncated bigsize")
    val = int.from_bytes(b[off + 1:off + 1 + size], "big")
    minimum = {2: 0xFD, 4: 0x10000, 8: 0x100000000}[size]
    if val < minimum:
        raise ValueError("non-canonical bigsize")
    return val, off + 1 + size


def encode_tlv_stream(records: dict[int, bytes]) -> bytes:
    out = b""
    for t in sorted(records):
        v = records[t]
        out += encode_bigsize(t) + encode_bigsize(len(v)) + v
    return out


def decode_tlv_stream(b: bytes) -> dict[int, bytes]:
    records: dict[int, bytes] = {}
    off, last = 0, -1
    while off < len(b):
        t, off = decode_bigsize(b, off)
        ln, off = decode_bigsize(b, off)
        if t <= last:
            raise ValueError("TLV types not strictly increasing")
        if off + ln > len(b):
            raise ValueError("truncated TLV value")
        records[t] = b[off:off + ln]
        off += ln
        last = t
    return records


# --------------------------------------------------------------------------
# Blinded paths
# --------------------------------------------------------------------------

@dataclass
class BlindedHop:
    blinded_node_id: bytes
    encrypted_hop_data: bytes


@dataclass
class BlindedPathV2:
    first_node_id: bytes
    first_path_key: bytes
    hops: list[BlindedHop]

    def serialize(self) -> bytes:
        out = self.first_node_id + self.first_path_key + bytes([len(self.hops)])
        for h in self.hops:
            out += h.blinded_node_id + h.encrypted_hop_data
        return out

    @classmethod
    def parse(cls, b: bytes) -> "BlindedPathV2":
        first_node_id, first_path_key, n = b[:33], b[33:66], b[66]
        hops, off = [], 67
        for _ in range(n):
            hops.append(BlindedHop(b[off:off + 33], b[off + 33:off + 33 + ENC_HOP_DATA_LEN]))
            off += 33 + ENC_HOP_DATA_LEN
        if off != len(b):
            raise ValueError("trailing bytes in blinded_path_v2")
        return cls(first_node_id, first_path_key, hops)


@dataclass
class BlindingTrace:
    """Intermediate values for one hop, for test vectors."""
    node_id: bytes
    path_key_secret: int
    E: bytes
    ss: bytes
    blinding_factor: bytes
    blinded_node_id: bytes
    rho_path: bytes
    hop_data: bytes
    encrypted_hop_data: bytes


def check_no_bounce_or_self_loop(route: list[bytes]) -> None:
    """`route` includes the origin (or path creator's predecessor) where known."""
    for i in range(1, len(route)):
        if route[i] == route[i - 1]:
            raise ValueError(f"self loop at position {i}")
        if i >= 2 and route[i] == route[i - 2]:
            raise ValueError(f"route bounces back to sending peer at position {i}")


def blind_hops(node_ids: list[bytes], e0: int, *,
               path_id: Optional[bytes] = None,
               next_node_id: Optional[bytes] = None,
               next_path_key: Optional[bytes] = None,
               ) -> tuple[bytes, list[BlindedHop], list[BlindingTrace]]:
    """Blind a sequence of hops using the BOLT 4 route blinding derivation.

    The last hop either is the final node (`path_id` given), or forwards to
    `next_node_id` with `next_path_key` (the origin node's own segment, joining
    a recipient's blinded path).

    Returns (first_path_key, hops, traces).
    """
    final = path_id is not None
    if final == (next_node_id is not None):
        raise ValueError("specify exactly one of path_id or next_node_id")
    if final and len(path_id) != 32:
        raise ValueError("path_id must be 32 bytes")

    e = e0
    hops, traces = [], []
    E0 = priv_to_pub(e0)
    for i, node_id in enumerate(node_ids):
        E = priv_to_pub(e)
        ss = ecdh(e, node_id)
        bf = blinding_factor(ss)
        blinded = point_mul(node_id, to_scalar(bf))
        rho = key_rho(ss)
        e_next = e * to_scalar(sha256(E + ss)) % CURVE_ORDER
        E_next = priv_to_pub(e_next)

        last = i == len(node_ids) - 1
        if not last:
            hop_data = node_ids[i + 1] + E_next
        elif final:
            hop_data = path_id + bytes(HOP_DATA_LEN - 32)
        else:
            hop_data = next_node_id + next_path_key
        assert len(hop_data) == HOP_DATA_LEN

        enc = ChaCha20Poly1305(rho).encrypt(bytes(12), hop_data, None)
        assert len(enc) == ENC_HOP_DATA_LEN

        hops.append(BlindedHop(blinded, enc))
        traces.append(BlindingTrace(node_id, e, E, ss, bf, blinded, rho, hop_data, enc))
        e = e_next
    return E0, hops, traces


def create_blinded_path(node_ids: list[bytes], e0: int, path_id: bytes = bytes(32)
                        ) -> tuple[BlindedPathV2, list[BlindingTrace]]:
    """Writer of a `blinded_path_v2` (the recipient)."""
    if not 1 <= len(node_ids) <= NUM_SLOTS:
        raise ValueError("invalid blinded path length")
    check_no_bounce_or_self_loop(node_ids)
    E0, hops, traces = blind_hops(node_ids, e0, path_id=path_id)
    return BlindedPathV2(node_ids[0], E0, hops), traces


# --------------------------------------------------------------------------
# e2e payload
# --------------------------------------------------------------------------

def encode_e2e_payload(records: dict[int, bytes], length: Optional[int] = None,
                       padding_byte: int = 0) -> bytes:
    tlv = encode_tlv_stream(records)
    body = struct.pack(">H", len(tlv)) + tlv
    if length is None:
        length = next((l for l in ALLOWED_PAYLOAD_LENS if l >= len(body)), None)
        if length is None:
            raise ValueError("payload too large")
    if length not in ALLOWED_PAYLOAD_LENS or len(body) > length:
        raise ValueError("invalid e2e_payload length")
    return body + bytes([padding_byte]) * (length - len(body))


def decode_e2e_payload(payload: bytes) -> dict[int, bytes]:
    tlv_len = struct.unpack(">H", payload[:2])[0]
    if 2 + tlv_len > len(payload):
        raise ValueError("tlv_len exceeds payload")
    records = decode_tlv_stream(payload[2:2 + tlv_len])
    for t in records:
        if t % 2 == 0 and t not in (2, 64, 66, 68):
            raise ValueError(f"unknown even type {t}")
    if sum(1 for t in records if t >= 64) > 1:
        raise ValueError("more than one payload field")
    return records


# --------------------------------------------------------------------------
# Packet construction
# --------------------------------------------------------------------------

@dataclass
class HopTrace:
    """Origin-side intermediate values for one hop, for test vectors."""
    blinded_node_id: bytes
    session_secret: int
    X: bytes
    sk: bytes
    rho: bytes
    mu: bytes
    delta: bytes
    e2e_payload: bytes = b""       # C_i, as received by this hop
    routing_header: bytes = b""    # as received by this hop
    hmac: bytes = b""              # as received by this hop


@dataclass
class ConstructedPacket:
    public_key: bytes
    routing_header: bytes
    e2e_payload: bytes
    hmac: bytes
    traces: list[HopTrace]
    filler: bytes


def generate_filler(sks: list[bytes]) -> bytes:
    """Filler for hops 1..r-1 (all shared secrets except the final one)."""
    filler = b""
    for sk in sks[:-1]:
        filler += bytes(SLOT_LEN)
        stream = chacha20_stream(key_rho(sk), HEADER_LEN + SLOT_LEN)
        filler = xor(filler, stream[HEADER_LEN + SLOT_LEN - len(filler):])
    return filler


def construct_packet(session_key: int, hops: list[BlindedHop], e2e_payload: bytes
                     ) -> ConstructedPacket:
    r = len(hops)
    if not 1 <= r <= NUM_SLOTS:
        raise ValueError(f"route must have 1..{NUM_SLOTS} hops")
    L = len(e2e_payload)
    if L not in ALLOWED_PAYLOAD_LENS:
        raise ValueError("invalid e2e_payload length")

    # 1. Onion ephemeral keys and shared secrets.
    traces: list[HopTrace] = []
    x = session_key
    for h in hops:
        X = priv_to_pub(x)
        sk = ecdh(x, h.blinded_node_id)
        traces.append(HopTrace(h.blinded_node_id, x, X, sk,
                               key_rho(sk), key_mu(sk), key_delta(sk)))
        x = x * to_scalar(sha256(X + sk)) % CURVE_ORDER

    # 2. Layered e2e_payload, from the final node backwards.
    c = xor(e2e_payload, chacha20_stream(traces[-1].delta, L))
    traces[-1].e2e_payload = c
    for i in range(r - 2, -1, -1):
        c = xor(c, chacha20_stream(traces[i].delta, L))
        traces[i].e2e_payload = c

    # 3. Filler.
    filler = generate_filler([t.sk for t in traces])

    # 4./5. Routing header, from the final node backwards.
    header = chacha20_stream(key_pad(session_key.to_bytes(32, "big")), HEADER_LEN)
    next_hmac = ZERO_HMAC
    for i in range(r - 1, -1, -1):
        slot = hops[i].encrypted_hop_data + next_hmac
        header = slot + header[:HEADER_LEN - SLOT_LEN]
        header = xor(header, chacha20_stream(traces[i].rho, HEADER_LEN))
        if i == r - 1 and filler:
            header = header[:HEADER_LEN - len(filler)] + filler
        next_hmac = hmac256(traces[i].mu, header + traces[i].e2e_payload)
        traces[i].routing_header = header
        traces[i].hmac = next_hmac

    return ConstructedPacket(traces[0].X, header, traces[0].e2e_payload, next_hmac,
                             traces, filler)


def construct_onion_message(session_key: int, origin_e0: int,
                            origin_hops: list[bytes],
                            blinded_path: Optional[BlindedPathV2],
                            e2e_payload: bytes,
                            final_node_id: Optional[bytes] = None,
                            origin_node_id: Optional[bytes] = None,
                            *, validate: bool = True):
    """Origin node: build a complete onion_message_v2.

    `origin_hops` are the hops the origin chooses itself. If `blinded_path` is
    given, they lead to its `first_node_id` (and may be empty if the origin is
    directly connected to it). Otherwise, the last origin hop is the final node
    and `final_node_id` must be None (it's origin_hops[-1]).

    Returns (message, path_key, ConstructedPacket, origin blinding traces).
    """
    origin_traces: list[BlindingTrace] = []
    all_hops: list[BlindedHop] = []
    route_ids = list(origin_hops)

    if blinded_path is None:
        if not origin_hops:
            raise ValueError("no route")
        E1, hops, origin_traces = blind_hops(origin_hops, origin_e0, path_id=bytes(32))
        all_hops = hops
    else:
        route_ids.append(blinded_path.first_node_id)
        if origin_hops:
            E1, hops, origin_traces = blind_hops(
                origin_hops, origin_e0,
                next_node_id=blinded_path.first_node_id,
                next_path_key=blinded_path.first_path_key)
            all_hops = hops
        else:
            E1 = blinded_path.first_path_key
        all_hops = all_hops + blinded_path.hops

    if validate:
        if len(all_hops) > NUM_SLOTS:
            raise ValueError("route too long")
        if origin_node_id is not None:
            check_no_bounce_or_self_loop([origin_node_id] + route_ids)

    cp = construct_packet(session_key, all_hops, e2e_payload)
    msg = encode_message(E1, cp.public_key, cp.routing_header, cp.e2e_payload, cp.hmac)
    return msg, E1, cp, origin_traces


def encode_message(path_key: bytes, public_key: bytes, routing_header: bytes,
                   e2e_payload: bytes, hmac_: bytes) -> bytes:
    """onion_message_v2 = type || len || packet, where
    packet = version || path_key || public_key || routing_header || e2e_payload || hmac."""
    packet = b"\x00" + path_key + public_key + routing_header + e2e_payload + hmac_
    return struct.pack(">HH", MSG_TYPE_ONION_MESSAGE_V2, len(packet)) + packet


@dataclass
class DecodedMessage:
    version: int
    path_key: bytes
    public_key: bytes
    routing_header: bytes
    e2e_payload: bytes
    hmac: bytes


def decode_message(msg: bytes) -> DecodedMessage:
    if len(msg) < 4 or struct.unpack(">H", msg[:2])[0] != MSG_TYPE_ONION_MESSAGE_V2:
        raise ValueError("not an onion_message_v2")
    ln = struct.unpack(">H", msg[2:4])[0]
    packet = msg[4:]
    if len(packet) != ln:
        raise ValueError("bad length")
    L = ln - PACKET_OVERHEAD
    if L not in ALLOWED_PAYLOAD_LENS:
        raise ValueError("invalid packet length")
    off = 67 + HEADER_LEN
    return DecodedMessage(packet[0], packet[1:34], packet[34:67], packet[67:off],
                          packet[off:off + L], packet[off + L:])


# --------------------------------------------------------------------------
# Packet processing
# --------------------------------------------------------------------------

class Ignore(Exception):
    """The message MUST be ignored."""


@dataclass
class Forward:
    next_node_id: bytes
    next_path_key: bytes
    message: bytes
    trace: dict = field(default_factory=dict)


@dataclass
class Deliver:
    path_id: bytes
    e2e_payload: bytes
    records: dict[int, bytes]
    trace: dict = field(default_factory=dict)


def process_message(node_privkey: int, message: bytes,
                    sending_peer: Optional[bytes] = None):
    """Processing node: returns Forward or Deliver, raises Ignore."""
    try:
        m = decode_message(message)
    except ValueError as e:
        raise Ignore(str(e))
    if m.version != 0:
        raise Ignore("unknown version")
    path_key, X, header, payload, mac = m.path_key, m.public_key, m.routing_header, m.e2e_payload, m.hmac
    L = len(payload)
    if not (is_valid_point(X) and is_valid_point(path_key)):
        raise Ignore("invalid point")

    k = node_privkey
    own_id = priv_to_pub(k)
    ss = ecdh(k, path_key)
    b = k * to_scalar(blinding_factor(ss)) % CURVE_ORDER
    sk = ecdh(b, X)
    trace = {"ss": ss, "blinded_privkey": b, "sk": sk,
             "rho": key_rho(sk), "mu": key_mu(sk), "delta": key_delta(sk)}

    if not hmac.compare_digest(mac, hmac256(key_mu(sk), header + payload)):
        raise Ignore("hmac mismatch")

    dec = xor(header + bytes(SLOT_LEN), chacha20_stream(key_rho(sk), HEADER_LEN + SLOT_LEN))
    enc_hop_data, next_hmac = dec[:ENC_HOP_DATA_LEN], dec[ENC_HOP_DATA_LEN:SLOT_LEN]
    next_header = dec[SLOT_LEN:]

    try:
        hop_data = ChaCha20Poly1305(key_rho(ss)).decrypt(bytes(12), enc_hop_data, None)
    except Exception:
        raise Ignore("encrypted_hop_data decryption failed")
    trace["hop_data"] = hop_data

    next_payload = xor(payload, chacha20_stream(key_delta(sk), L))

    if next_hmac == ZERO_HMAC:
        try:
            records = decode_e2e_payload(next_payload)
        except Exception as e:
            raise Ignore(f"invalid e2e_payload: {e}")
        return Deliver(hop_data[:32], next_payload, records, trace)

    next_node_id, next_path_key = hop_data[:33], hop_data[33:]
    if sending_peer is not None and next_node_id == sending_peer:
        raise Ignore("next_node_id is the sending peer")
    if next_node_id == own_id:
        raise Ignore("next_node_id is own node id")
    if not (is_valid_point(next_node_id) and is_valid_point(next_path_key)):
        raise Ignore("invalid next_node_id or next_path_key")

    X_next = point_mul(X, to_scalar(sha256(X + sk)))
    return Forward(next_node_id, next_path_key,
                   encode_message(next_path_key, X_next, next_header, next_payload, next_hmac),
                   trace)
