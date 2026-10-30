"""Nostr identity for a cell, in the standard library only.

A Hive (kannaka-buzz) member is a Nostr key pair: the x-only secp256k1 public key is the
member id, NIP-19 gives it a readable spelling (`npub1…` / `nsec1…`), and BIP-340 Schnorr
signs its events. kdna mints and signs here so a birth kit never needs a second tool to be
a member; it does not talk to a relay (that is the harness's job).

Everything is checked against published vectors in tests/test_hive.py: the secp256k1
generator multiples, the NIP-19 examples, and the BIP-340 test vector 0. Keys come from
`secrets.token_bytes`; `nsec` strings are written only where `hive.write_hive_kit` says.
"""
from __future__ import annotations

import hashlib
import secrets

# --------------------------------------------------------------- secp256k1 (affine, pure Python)
P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
     0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def _add(a, b):
    if a is None:
        return b
    if b is None:
        return a
    if a[0] == b[0] and (a[1] + b[1]) % P == 0:
        return None
    if a == b:
        lam = 3 * a[0] * a[0] * pow(2 * a[1], -1, P)
    else:
        lam = (b[1] - a[1]) * pow(b[0] - a[0], -1, P)
    x = (lam * lam - a[0] - b[0]) % P
    return (x, (lam * (a[0] - x) - a[1]) % P)


def _mul(k: int, pt=G):
    r = None
    while k:
        if k & 1:
            r = _add(r, pt)
        pt = _add(pt, pt)
        k >>= 1
    return r


def _lift_x(x: int):
    """The even-y point with this x (BIP-340), or None if x is not on the curve."""
    if x >= P:
        return None
    y2 = (pow(x, 3, P) + 7) % P
    y = pow(y2, (P + 1) // 4, P)
    if pow(y, 2, P) != y2:
        return None
    return (x, y if y % 2 == 0 else P - y)


def _tagged(tag: str, *parts: bytes) -> bytes:
    t = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(t + t + b"".join(parts)).digest()


def pubkey_from_secret(secret: bytes) -> bytes:
    """x-only public key (32 bytes) for a 32-byte secret in 1..N-1."""
    d = int.from_bytes(secret, "big")
    if not 1 <= d < N:
        raise ValueError("secret key out of range")
    return _mul(d)[0].to_bytes(32, "big")


def generate_secret() -> bytes:
    while True:
        s = secrets.token_bytes(32)
        if 1 <= int.from_bytes(s, "big") < N:
            return s


def schnorr_sign(msg32: bytes, secret: bytes, aux: bytes | None = None) -> bytes:
    """BIP-340 signature of a 32-byte message."""
    if len(msg32) != 32:
        raise ValueError("message must be 32 bytes")
    d = int.from_bytes(secret, "big")
    if not 1 <= d < N:
        raise ValueError("secret key out of range")
    pt = _mul(d)
    if pt[1] % 2:
        d = N - d
    aux = secrets.token_bytes(32) if aux is None else aux
    t = (d ^ int.from_bytes(_tagged("BIP0340/aux", aux), "big")).to_bytes(32, "big")
    px = pt[0].to_bytes(32, "big")
    k0 = int.from_bytes(_tagged("BIP0340/nonce", t, px, msg32), "big") % N
    if k0 == 0:
        raise ValueError("nonce is zero (astronomically unlikely); retry")
    r = _mul(k0)
    k = N - k0 if r[1] % 2 else k0
    rx = r[0].to_bytes(32, "big")
    e = int.from_bytes(_tagged("BIP0340/challenge", rx, px, msg32), "big") % N
    return rx + ((k + e * d) % N).to_bytes(32, "big")


def schnorr_verify(msg32: bytes, pubkey32: bytes, sig64: bytes) -> bool:
    if len(msg32) != 32 or len(pubkey32) != 32 or len(sig64) != 64:
        return False
    pt = _lift_x(int.from_bytes(pubkey32, "big"))
    r = int.from_bytes(sig64[:32], "big")
    s = int.from_bytes(sig64[32:], "big")
    if pt is None or r >= P or s >= N:
        return False
    e = int.from_bytes(_tagged("BIP0340/challenge", sig64[:32], pubkey32, msg32), "big") % N
    rp = _add(_mul(s), _mul(N - e, pt))
    return rp is not None and rp[1] % 2 == 0 and rp[0] == r


# --------------------------------------------------------------- bech32 (BIP-173) for NIP-19
_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_GEN = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)


def _polymod(values):
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            chk ^= _GEN[i] if (b >> i) & 1 else 0
    return chk


def _hrp_expand(hrp):
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _to5(data: bytes):
    acc = bits = 0
    out = []
    for b in data:
        acc = (acc << 8) | b
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append((acc >> bits) & 31)
    if bits:
        out.append((acc << (5 - bits)) & 31)
    return out


def _from5(words):
    acc = bits = 0
    out = bytearray()
    for w in words:
        acc = (acc << 5) | w
        bits += 5
        while bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 255)
    if bits >= 5 or (acc & ((1 << bits) - 1)):
        raise ValueError("bad bech32 padding")
    return bytes(out)


def bech32_encode(hrp: str, data: bytes) -> str:
    words = _to5(data)
    chk = _polymod(_hrp_expand(hrp) + words + [0] * 6) ^ 1
    return hrp + "1" + "".join(_CHARSET[w] for w in words + [(chk >> 5 * (5 - i)) & 31 for i in range(6)])


def bech32_decode(text: str) -> tuple[str, bytes]:
    text = text.lower()
    hrp, _, body = text.rpartition("1")
    if not hrp or len(body) < 6 or any(c not in _CHARSET for c in body):
        raise ValueError("not bech32")
    words = [_CHARSET.index(c) for c in body]
    if _polymod(_hrp_expand(hrp) + words) != 1:
        raise ValueError("bech32 checksum failed")
    return hrp, _from5(words[:-6])


def npub(pubkey32: bytes) -> str:
    return bech32_encode("npub", pubkey32)


def nsec(secret32: bytes) -> str:
    return bech32_encode("nsec", secret32)


def decode_key(text: str) -> tuple[str, bytes]:
    """('npub'|'nsec', 32 bytes) from a NIP-19 string, or ('hex', 32 bytes) from 64 hex chars."""
    if len(text) == 64 and all(c in "0123456789abcdefABCDEF" for c in text):
        return "hex", bytes.fromhex(text)
    hrp, data = bech32_decode(text)
    if hrp not in ("npub", "nsec") or len(data) != 32:
        raise ValueError(f"not a Nostr key: {hrp} with {len(data)} bytes")
    return hrp, data


# --------------------------------------------------------------- NIP-01 events
def event_id(pubkey_hex: str, created_at: int, kind: int, tags: list, content: str) -> str:
    import json
    ser = json.dumps([0, pubkey_hex, created_at, kind, tags, content],
                     separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(ser.encode("utf-8")).hexdigest()


def finish_event(template: dict, secret: bytes, aux: bytes | None = None) -> dict:
    """Fill pubkey, id and sig on an unsigned {created_at, kind, tags, content} template."""
    pk = pubkey_from_secret(secret).hex()
    ev = {"pubkey": pk, "created_at": int(template["created_at"]), "kind": int(template["kind"]),
          "tags": template.get("tags", []), "content": template.get("content", "")}
    ev["id"] = event_id(pk, ev["created_at"], ev["kind"], ev["tags"], ev["content"])
    ev["sig"] = schnorr_sign(bytes.fromhex(ev["id"]), secret, aux).hex()
    return ev


def verify_event(ev: dict) -> bool:
    try:
        ok_id = event_id(ev["pubkey"], ev["created_at"], ev["kind"], ev["tags"], ev["content"]) == ev["id"]
        return ok_id and schnorr_verify(bytes.fromhex(ev["id"]), bytes.fromhex(ev["pubkey"]), bytes.fromhex(ev["sig"]))
    except (KeyError, ValueError, TypeError):
        return False
