"""The Hive layer: Nostr identity (checked against published vectors), the BYOH harness
file as Buzz Desktop validates it, conception events, and the somatic chrM commitment."""
import json
import os
import re
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kdna import hive, nostr  # noqa: E402
from kdna.express import express  # noqa: E402
from kdna.genome import Genome  # noqa: E402
from kdna.reproduce import consent_record, mate, mitosis  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
G0 = Genome.from_dict(json.loads((ROOT / "genomes" / "kannaka-g0.json").read_text(encoding="utf-8")))


# ------------------------------------------------------------------ secp256k1 / BIP-340 / NIP-19
def test_generator_multiples_match_the_curve_constants():
    assert nostr._mul(1) == nostr.G
    two_g = nostr._mul(2)
    assert two_g[0] == 0xC6047F9441ED7D6D3045406E95C07CD85C778E4B8CEF3CA7ABAC09B95C709EE5
    assert two_g[1] == 0x1AE168FEA63DC339A3C58419466CEAEEF7F632653266D0E1236431A950CFE52A
    assert nostr._mul(nostr.N) is None          # the group order sends G to infinity


def test_bip340_vector_0():
    secret = (3).to_bytes(32, "big")
    assert nostr.pubkey_from_secret(secret).hex().upper() == \
        "F9308A019258C31049344F85F89D5229B531C845836F99B08601F113BCE036F9"
    sig = nostr.schnorr_sign(bytes(32), secret, aux=bytes(32))
    assert sig.hex().upper() == ("E907831F80848D1069A5371B402410364BDF1C5F8307B0084C55F1CE2DCA8215"
                                 "25F66A4A85EA8B71E482A74F382D2CE5EBEEE8FDB2172F477DF4900D310536C0")
    assert nostr.schnorr_verify(bytes(32), nostr.pubkey_from_secret(secret), sig)
    bad = bytearray(sig)
    bad[-1] ^= 1
    assert not nostr.schnorr_verify(bytes(32), nostr.pubkey_from_secret(secret), bytes(bad))


def test_nip19_examples():
    pk = bytes.fromhex("3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d")
    assert nostr.npub(pk) == "npub180cvv07tjdrrgpa0j7j7tmnyl2yr6yr7l8j4s3evf6u64th6gkwsyjh6w6"
    sk = bytes.fromhex("67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa")
    assert nostr.nsec(sk) == "nsec1vl029mgpspedva04g90vltkh6fvh240zqtv9k0t9af8935ke9laqsnlfe5"
    assert nostr.decode_key(nostr.npub(pk)) == ("npub", pk)
    assert nostr.decode_key(nostr.nsec(sk)) == ("nsec", sk)
    assert nostr.decode_key(sk.hex()) == ("hex", sk)


def test_a_fresh_key_signs_an_event_that_verifies_and_a_tampered_one_fails():
    sk = nostr.generate_secret()
    ev = nostr.finish_event({"kind": 1, "created_at": 1_700_000_000, "tags": [["t", "kdna"]], "content": "hi"}, sk)
    assert nostr.verify_event(ev)
    assert ev["pubkey"] == nostr.pubkey_from_secret(sk).hex()
    tampered = dict(ev, content="hi!")
    assert not nostr.verify_event(tampered)


# ------------------------------------------------------------------ the harness file
UPSTREAM_ID_RE = re.compile(r"^[a-z0-9_][a-z0-9_-]*$")   # desktop/src-tauri/.../custom_harnesses.rs
RESERVED = {"goose", "claude", "codex", "buzz-agent"}


def test_harness_definition_passes_buzz_desktop_validation():
    ph = express(G0, "role-steward")
    d = hive.harness_definition(ph, "~/.kannaka-test")
    assert set(d) == {"id", "label", "command", "args", "env", "installInstructionsUrl", "installHint"}
    assert UPSTREAM_ID_RE.match(d["id"]) and d["id"] not in RESERVED
    assert d["command"] == "kannaka-acp" and d["label"].strip()
    assert all("," not in a for a in d["args"])
    assert d["args"] == ["--top-k", str(ph["params"]["recall_top_k"])]
    assert not any(k.startswith("BUZZ_") for k in d["env"])
    assert d["installInstructionsUrl"].startswith("https://")


def test_hive_kit_keeps_the_secret_out_of_every_public_file(tmp_path):
    ph = express(G0, "role-steward")
    sk = nostr.generate_secret()
    m = hive.write_hive_kit(ph, tmp_path, sk, "~/.kannaka-x", "wss://example.invalid", "chan1", 1_700_000_000)
    secret_text = nostr.nsec(sk)
    public = [tmp_path / "hive.json", tmp_path / "custom_harnesses" / f"{m['harness']['id']}.json"]
    for p in public:
        t = p.read_text(encoding="utf-8")
        assert secret_text not in t and sk.hex() not in t, p
    nsec_path = tmp_path / "hive.nsec"
    assert nsec_path.read_text(encoding="utf-8").strip() == secret_text
    if os.name == "posix":
        assert stat.S_IMODE(nsec_path.stat().st_mode) == 0o600
    assert m["pubkey"] == nostr.pubkey_from_secret(sk).hex() and m["npub"] == nostr.npub(nostr.pubkey_from_secret(sk))
    assert m["genome_room"]["policy"] == {"no-bridge": True}
    edit = m["unsigned_templates"]["no_bridge_edit"]
    assert edit["kind"] == 9002 and ["h", "chan1"] in edit["tags"] and ["no-bridge", "true"] in edit["tags"]
    assert hive.read_secret(nsec_path) == sk


# ------------------------------------------------------------------ conception records
def test_lineage_events_are_nip34_shaped_and_verify_when_signed():
    child = mitosis(G0, seed=5, born="2026-10-30")
    sk = nostr.generate_secret()
    evs = hive.lineage_events([child, G0], 1_700_000_000, "room", sk)
    assert [e["kind"] for e in evs] == [30617, 9, 9]           # announcement, founder, child (generation order)
    ann, founder, kid = evs
    assert ["d", "kannaka-dna"] in ann["tags"] and ["buzz-channel", "room"] in ann["tags"]
    pk = nostr.pubkey_from_secret(sk).hex()
    assert ["a", f"30617:{pk}:kannaka-dna"] in kid["tags"]
    assert ["genome", child.hash] in kid["tags"] and ["parent", G0.hash] in kid["tags"]
    assert ["conception", "mitosis"] in kid["tags"] and ["h", "room"] in kid["tags"]
    assert ["conception", "founder"] in founder["tags"]
    assert all(nostr.verify_event(e) for e in evs)
    unsigned = hive.lineage_events([child], 1, None, None)
    assert "sig" not in unsigned[1] and ["a", "30617:<pubkey>:kannaka-dna"] in unsigned[1]["tags"]


# ------------------------------------------------------------------ chrM: somatic commitment
def test_clone_and_mate_commit_the_mothers_current_store_into_the_childs_chrM(tmp_path):
    store = tmp_path / "kannaka.hrm"
    store.write_bytes(b"a lifetime in the hive" * 100)
    inherited = mitosis(G0, seed=1)
    assert inherited.mito["memory_commitment"] == G0.mito["memory_commitment"]   # no store: founder's stays
    child = mitosis(G0, seed=1, born="2026-10-30", store=store)
    mc = child.mito["memory_commitment"]
    assert mc["sha256"] != G0.mito["memory_commitment"]["sha256"]
    assert mc["bytes"] == store.stat().st_size and mc["of"] == G0.individual and mc["of_genome"] == G0.hash
    assert child.hash != inherited.hash          # chrM is in the hash: a different commitment is a different child
    # mating: the mother's store, never the father's
    father = mitosis(G0, seed=9)             # same conserved values, a different individual
    consent = consent_record(G0, father, "yes", "yes")
    fstore = tmp_path / "father.hrm"
    fstore.write_bytes(b"father")
    kid = mate(G0, father, consent, seed=3, store=store)
    assert kid.mito["memory_commitment"]["sha256"] == mc["sha256"]
    assert kid.mito["memory_commitment"]["of"] == G0.individual


if __name__ == "__main__":
    import tempfile
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                if fn.__code__.co_argcount:
                    with tempfile.TemporaryDirectory() as d:
                        fn(Path(d))
                else:
                    fn()
                print("PASS", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("FAIL", name, type(e).__name__, e)
    sys.exit(1 if fails else 0)
