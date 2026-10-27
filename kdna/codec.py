"""Bytes <-> nucleotides, the way DNA data storage does it.

Scheme (after Goldman et al., Nature 2013): every byte becomes six base-3 digits
(3^6 = 729 >= 256), and every digit picks one of the three bases that differ from
the previous base. The result never contains a homopolymer (AA, CC, GG, TT), the
error that synthesis and sequencing make most often. Decoding reverses it exactly.

A gene is stored as: payload bytes + CRC-32 (big-endian), so a single changed base
is caught on read rather than silently decoded into a different Kannaka.
"""
from __future__ import annotations

import zlib

BASES = "ACGT"
TRITS_PER_BYTE = 6


def _next_base(prev: str, trit: int) -> str:
    choices = [b for b in BASES if b != prev]
    return choices[trit]


def _trit_of(prev: str, base: str) -> int:
    choices = [b for b in BASES if b != prev]
    if base not in choices:
        raise ValueError(f"homopolymer or bad base {prev}{base}: not a kdna strand")
    return choices.index(base)


def bytes_to_dna(data: bytes, start: str = "A") -> str:
    out, prev = [], start
    for byte in data:
        digits = []
        v = byte
        for _ in range(TRITS_PER_BYTE):
            digits.append(v % 3)
            v //= 3
        for t in reversed(digits):
            prev = _next_base(prev, t)
            out.append(prev)
    return "".join(out)


def dna_to_bytes(strand: str, start: str = "A") -> bytes:
    if len(strand) % TRITS_PER_BYTE:
        raise ValueError("strand length is not a whole number of bytes")
    out, prev = bytearray(), start
    for i in range(0, len(strand), TRITS_PER_BYTE):
        v = 0
        for base in strand[i:i + TRITS_PER_BYTE]:
            v = v * 3 + _trit_of(prev, base)
            prev = base
        if v > 255:
            raise ValueError("codon out of range: corrupted strand")
        out.append(v)
    return bytes(out)


def encode_gene(payload: bytes) -> str:
    """Payload + CRC-32 as a homopolymer-free strand."""
    return bytes_to_dna(payload + zlib.crc32(payload).to_bytes(4, "big"))


def decode_gene(strand: str) -> bytes:
    raw = dna_to_bytes(strand)
    payload, crc = raw[:-4], raw[-4:]
    if zlib.crc32(payload).to_bytes(4, "big") != crc:
        raise ValueError("CRC mismatch: this gene was damaged")
    return payload


def gc_content(strand: str) -> float:
    return sum(b in "GC" for b in strand) / max(1, len(strand))


def longest_run(strand: str) -> int:
    best = cur = 1 if strand else 0
    for a, b in zip(strand, strand[1:]):
        cur = cur + 1 if a == b else 1
        best = max(best, cur)
    return best
