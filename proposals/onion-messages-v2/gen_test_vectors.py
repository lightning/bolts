"""Generate test vectors for Onion Messages Version 2 and run self-checks."""
import hashlib
import json

from onion_message_v2 import *

# RFC 8439 sanity check: all-zero key, nonce and counter.
assert chacha20_stream(bytes(32), 16).hex() == "76b8e0ada0f13d90405d6ae55386bd28"

NODES = {name: int(c * 32, 16) for name, c in
         [("Alice", "41"), ("Bob", "42"), ("Carol", "43"),
          ("Dave", "44"), ("Eve", "45"), ("Frank", "46")]}
IDS = {name: priv_to_pub(k) for name, k in NODES.items()}
ALIAS = {v: k for k, v in IDS.items()}


def h(b: bytes) -> str:
    return b.hex()


def digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def blinding_json(traces):
    return [{
        "alias": ALIAS[t.node_id],
        "node_id": h(t.node_id),
        "path_key_secret": f"{t.path_key_secret:064x}",
        "E": h(t.E),
        "ss": h(t.ss),
        "HMAC256('blinded_node_id', ss)": h(t.blinding_factor),
        "blinded_node_id": h(t.blinded_node_id),
        "rho": h(t.rho_path),
        "hop_data": h(t.hop_data),
        "encrypted_hop_data": h(t.encrypted_hop_data),
    } for t in traces]


def packet_json(cp, full: bool):
    out = {"filler": h(cp.filler), "hops": []}
    for t in cp.traces:
        entry = {
            "blinded_node_id": h(t.blinded_node_id),
            "session_secret": f"{t.session_secret:064x}",
            "public_key": h(t.X),
            "shared_secret": h(t.sk),
            "rho": h(t.rho),
            "mu": h(t.mu),
            "delta": h(t.delta),
            "hmac": h(t.hmac),
        }
        if full:
            entry["routing_header"] = h(t.routing_header)
            entry["e2e_payload"] = h(t.e2e_payload)
        else:
            entry["sha256(routing_header)"] = digest(t.routing_header)
            entry["sha256(e2e_payload)"] = digest(t.e2e_payload)
        out["hops"].append(entry)
    return out


def run_route(message, route_names, origin="Alice", full=True):
    """Process the message hop by hop, checking next_node_id against the route."""
    hops_out = []
    prev = IDS[origin]
    msg = message
    for i, name in enumerate(route_names):
        res = process_message(NODES[name], msg, sending_peer=prev)
        entry = {"alias": name, "privkey": f"{NODES[name]:064x}"}
        if full:
            entry["onion_message"] = h(msg)
        else:
            entry["sha256(onion_message)"] = digest(msg)
        entry["ss"] = h(res.trace["ss"])
        entry["shared_secret"] = h(res.trace["sk"])
        entry["hop_data"] = h(res.trace["hop_data"])
        last = i == len(route_names) - 1
        if last:
            assert isinstance(res, Deliver), f"{name} expected to be final"
            entry["path_id"] = h(res.path_id)
            entry["e2e_payload"] = h(res.e2e_payload) if full else None
            if not full:
                entry["sha256(e2e_payload)"] = digest(res.e2e_payload)
                del entry["e2e_payload"]
            entry["tlvs"] = {str(k): h(v) for k, v in res.records.items()}
        else:
            assert isinstance(res, Forward), f"{name} expected to forward"
            assert res.next_node_id == IDS[route_names[i + 1]], \
                f"{name} forwarded to {ALIAS.get(res.next_node_id)}"
            entry["next_node_id"] = h(res.next_node_id)
            entry["next_path_key"] = h(res.next_path_key)
            msg = res.message
        hops_out.append(entry)
        prev = IDS[name]
    return hops_out, res


vectors = {
    "comment": "Test vectors for onion messages v2 (Extension BOLT XX). Node private keys "
               "are 0x41.. (Alice), 0x42.. (Bob), 0x43.. (Carol), 0x44.. (Dave), 0x45.. (Eve).",
    "constants": {
        "SLOT_LEN": SLOT_LEN, "NUM_SLOTS": NUM_SLOTS, "HEADER_LEN": HEADER_LEN,
        "MAX_E2E_PAYLOAD_LEN": MAX_E2E_PAYLOAD_LEN,
        "allowed_e2e_payload_lengths": ALLOWED_PAYLOAD_LENS,
    },
    "vectors": [],
}

# ---------------------------------------------------------------------------
# Vector 1: unblinded destination, Alice -> Bob -> Carol -> Dave, 256 bytes.
# ---------------------------------------------------------------------------
payload1 = encode_e2e_payload({65: b"hello onion messages v2"}, 256)
msg1, pk1, cp1, ot1 = construct_onion_message(
    session_key=int("03" * 32, 16), origin_e0=int("63" * 32, 16),
    origin_hops=[IDS["Bob"], IDS["Carol"], IDS["Dave"]],
    blinded_path=None, e2e_payload=payload1, origin_node_id=IDS["Alice"])
dec1, _ = run_route(msg1, ["Bob", "Carol", "Dave"])
vectors["vectors"].append({
    "comment": "Alice sends to Dave via Bob and Carol without a recipient blinded path. "
               "Alice blinds all hops herself; Dave's path_id is all-zero. "
               "The e2e_payload contains a single odd TLV (type 65) with 'hello onion messages v2'.",
    "generate": {
        "session_key": "03" * 32,
        "origin_path_key_secret": "63" * 32,
        "e2e_payload": h(payload1),
        "origin_blinding": blinding_json(ot1),
        "packet": packet_json(cp1, full=True),
    },
    "onion_message": h(msg1),
    "decrypt": {"hops": dec1},
})

# ---------------------------------------------------------------------------
# Vector 2: Eve's blinded path Carol -> Dave -> Eve, Alice reaches Carol via
# Bob, and includes a reply_path Bob -> Alice.  1024 bytes.
# ---------------------------------------------------------------------------
eve_path_id = hashlib.sha256(b"eve's blinded path").digest()
eve_path, eve_traces = create_blinded_path(
    [IDS["Carol"], IDS["Dave"], IDS["Eve"]], e0=int("01" * 32, 16), path_id=eve_path_id)
alice_reply_path_id = hashlib.sha256(b"alice's reply path").digest()
reply_path, reply_traces = create_blinded_path(
    [IDS["Bob"], IDS["Alice"]], e0=int("02" * 32, 16), path_id=alice_reply_path_id)
payload2 = encode_e2e_payload({2: reply_path.serialize(),
                               65: b"hello Eve, please reply"}, 1024)
msg2, pk2, cp2, ot2 = construct_onion_message(
    session_key=int("04" * 32, 16), origin_e0=int("64" * 32, 16),
    origin_hops=[IDS["Bob"]], blinded_path=eve_path,
    e2e_payload=payload2, origin_node_id=IDS["Alice"])
dec2, res2 = run_route(msg2, ["Bob", "Carol", "Dave", "Eve"])
assert res2.path_id == eve_path_id
assert BlindedPathV2.parse(res2.records[2]).serialize() == reply_path.serialize()

# Eve replies using the reply path: Eve -> Bob -> Alice.
reply_payload = encode_e2e_payload({65: b"hello Alice"}, 256)
rmsg, _, rcp, _ = construct_onion_message(
    session_key=int("05" * 32, 16), origin_e0=int("65" * 32, 16),
    origin_hops=[], blinded_path=BlindedPathV2.parse(res2.records[2]),
    e2e_payload=reply_payload, origin_node_id=IDS["Eve"])
rdec, rres = run_route(rmsg, ["Bob", "Alice"], origin="Eve")
assert rres.path_id == alice_reply_path_id

vectors["vectors"].append({
    "comment": "Eve publishes a blinded path Carol -> Dave -> Eve with a path_id. Alice "
               "reaches the introduction node Carol via Bob: Bob's hop_data carries Eve's "
               "first_path_key as next_path_key. Alice includes a reply_path Bob -> Alice, "
               "which Eve uses to reply (Eve is directly connected to Bob).",
    "generate": {
        "session_key": "04" * 32,
        "origin_path_key_secret": "64" * 32,
        "recipient_blinding": {
            "comment": "Eve's blinded path, path_id = SHA256(\"eve's blinded path\")",
            "path_key_secret": "01" * 32,
            "hops": blinding_json(eve_traces),
        },
        "route": {
            "first_node_id": h(eve_path.first_node_id),
            "first_path_key": h(eve_path.first_path_key),
            "hops": [{"blinded_node_id": h(x.blinded_node_id),
                      "encrypted_hop_data": h(x.encrypted_hop_data)} for x in eve_path.hops],
            "serialized": h(eve_path.serialize()),
        },
        "reply_path": {
            "comment": "Alice's reply path, path_id = SHA256(\"alice's reply path\")",
            "path_key_secret": "02" * 32,
            "hops": blinding_json(reply_traces),
            "serialized": h(reply_path.serialize()),
        },
        "e2e_payload": h(payload2),
        "origin_blinding": blinding_json(ot2),
        "packet": packet_json(cp2, full=True),
    },
    "onion_message": h(msg2),
    "decrypt": {"hops": dec2},
    "reply": {
        "session_key": "05" * 32,
        "e2e_payload": h(reply_payload),
        "onion_message": h(rmsg),
        "decrypt": {"hops": rdec},
    },
})

# ---------------------------------------------------------------------------
# Vector 3: 8 hops with cycles of length 3, maximum e2e_payload (64520 bytes).
# ---------------------------------------------------------------------------
route3 = ["Bob", "Carol", "Dave", "Bob", "Carol", "Dave", "Bob", "Eve"]
payload3 = encode_e2e_payload({65: b"maximum size"}, MAX_E2E_PAYLOAD_LEN, padding_byte=0)
msg3, pk3, cp3, ot3 = construct_onion_message(
    session_key=int("06" * 32, 16), origin_e0=int("66" * 32, 16),
    origin_hops=[IDS[n] for n in route3], blinded_path=None,
    e2e_payload=payload3, origin_node_id=IDS["Alice"])
assert len(msg3) == 65535
dec3, _ = run_route(msg3, route3, full=False)
vectors["vectors"].append({
    "comment": "Alice -> Bob -> Carol -> Dave -> Bob -> Carol -> Dave -> Bob -> Eve: all 8 "
               "slots used, cycles of length 3 (permitted), maximum e2e_payload of 64520 "
               "bytes so the onion_message_v2 is exactly 65535 bytes. Only the initial "
               "message is given in full; intermediate values are given as SHA256 digests.",
    "generate": {
        "session_key": "06" * 32,
        "origin_path_key_secret": "66" * 32,
        "sha256(e2e_payload)": digest(payload3),
        "e2e_payload_tlvs": {"65": h(b"maximum size")},
        "origin_blinding": blinding_json(ot3),
        "packet": packet_json(cp3, full=False),
    },
    "onion_message": h(msg3),
    "decrypt": {"hops": dec3},
})

# ---------------------------------------------------------------------------
# Negative vectors: each MUST be ignored by the named processing node.
# ---------------------------------------------------------------------------
negative = []


def expect_ignore(comment, node, message, sending_peer, reason_substr):
    try:
        process_message(NODES[node], message, sending_peer=IDS[sending_peer])
    except Ignore as e:
        assert reason_substr in str(e), (str(e), reason_substr)
        negative.append({"comment": comment, "processing_node": node,
                         "sending_peer": sending_peer, "onion_message": h(message),
                         "expected": "ignore", "reason": str(e)})
        return
    raise AssertionError(f"{comment}: not ignored")


# (a) Bob tampers with the e2e_payload before forwarding to Carol.
fwd = process_message(NODES["Bob"], msg1, sending_peer=IDS["Alice"])
m = decode_message(fwd.message)
tampered = encode_message(m.path_key, m.public_key, m.routing_header,
                          bytes([m.e2e_payload[0] ^ 0x01]) + m.e2e_payload[1:], m.hmac)
expect_ignore("Vector 1 message forwarded by Bob with the first e2e_payload bit flipped: "
              "Carol detects the modification.",
              "Carol", tampered, "Bob", "hmac mismatch")

# (b) Bounce back to the sending peer: Alice -> Bob -> Alice (constructed without
#     writer validation).
payload_b = encode_e2e_payload({65: b"bounce"}, 256)
msg_b, _, _, _ = construct_onion_message(
    int("07" * 32, 16), int("67" * 32, 16), [IDS["Bob"], IDS["Alice"]], None, payload_b,
    origin_node_id=IDS["Alice"], validate=False)
expect_ignore("Alice -> Bob -> Alice: Bob's next_node_id is its sending peer.",
              "Bob", msg_b, "Alice", "sending peer")

# (c) Self loop: Alice -> Bob -> Bob -> Carol.
payload_c = encode_e2e_payload({65: b"self loop"}, 256)
msg_c, _, _, _ = construct_onion_message(
    int("08" * 32, 16), int("68" * 32, 16), [IDS["Bob"], IDS["Bob"], IDS["Carol"]], None,
    payload_c, origin_node_id=IDS["Alice"], validate=False)
expect_ignore("Alice -> Bob -> Bob -> Carol: Bob's next_node_id is its own node id.",
              "Bob", msg_c, "Alice", "own node id")

# (d) Invalid length: vector 1 truncated by one byte of e2e_payload.
m = decode_message(msg1)
bad = encode_message(m.path_key, m.public_key, m.routing_header, m.e2e_payload[:255], m.hmac)
expect_ignore("Vector 1 with the e2e_payload shortened to 255 bytes.",
              "Bob", bad, "Alice", "invalid packet length")

vectors["negative"] = negative

# Writer-side checks must refuse invalid routes.
for bad_route in (["Bob", "Alice"], ["Bob", "Bob"]):
    try:
        construct_onion_message(1, 2, [IDS[n] for n in bad_route], None, payload_b,
                                origin_node_id=IDS["Alice"])
        raise AssertionError("writer accepted invalid route")
    except ValueError:
        pass
try:
    construct_onion_message(1, 2, [IDS[n] for n in route3 + ["Frank"]], None, payload_b,
                            origin_node_id=IDS["Alice"])
    raise AssertionError("writer accepted 9 hops")
except ValueError:
    pass

with open("onion-message-v2-test.json", "w") as f:
    json.dump(vectors, f, indent=2)
    f.write("\n")

print("vector 1:", len(msg1), "bytes,", len(dec1), "hops")
print("vector 2:", len(msg2), "bytes,", len(dec2), "hops; reply", len(rmsg), "bytes")
print("vector 3:", len(msg3), "bytes,", len(dec3), "hops")
print("negative:", [n["reason"] for n in negative])
print("all self-checks passed")
