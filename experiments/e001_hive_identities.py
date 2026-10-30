"""E-001: give each arm a Hive (kannaka-buzz) identity.

    python experiments/e001_hive_identities.py [--data-root ~/.kannaka-e001] [--relay wss://…] [--channel ID]

For every genome in genomes/e001/*.json this mints one Nostr key pair and writes:

  genomes/e001/hive/<individual>.json          public: pubkey, npub, harness id, policy  (committed)
  genomes/e001/hive/custom_harnesses/<id>.json the Buzz Desktop BYOH definition          (committed)
  births/e001-hive/<individual>.nsec           the secret, 0600                           (gitignored)

Idempotent: an arm whose .nsec already exists keeps its key, so re-running never rotates an
identity by accident. Nothing here talks to a relay; registering the eight members is the
operator's step (the relay's `pubkey_allowlist`, both communities, like the organs). Until then
the identities are reserved, not live, and the public file says so (`"registered": false`).
Once done, re-run with `--relay wss://… --registered YYYY-MM-DD` to record it in the public files.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kdna import hive, nostr  # noqa: E402
from kdna.express import express  # noqa: E402
from kdna.genome import Genome  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", default="~/.kannaka-e001", help="each arm's KANNAKA_DATA_DIR is <root>/<individual>")
    ap.add_argument("--relay", default=None)
    ap.add_argument("--channel", default=None, help="the E-001 genome room's channel id, if it exists yet")
    ap.add_argument("--registered", default=None, metavar="YYYY-MM-DD",
                    help="the operator has added these pubkeys to the relay's allowlist on this date (requires --relay)")
    a = ap.parse_args(argv)
    if a.registered and not a.relay:
        ap.error("--registered needs --relay (which relay were they registered on?)")

    arms = sorted((ROOT / "genomes" / "e001").glob("kannaka-g1-*.json"))
    pub_dir = ROOT / "genomes" / "e001" / "hive"
    sec_dir = ROOT / "births" / "e001-hive"
    pub_dir.mkdir(parents=True, exist_ok=True)
    (pub_dir / "custom_harnesses").mkdir(exist_ok=True)
    sec_dir.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    rows = []
    for p in arms:
        g = Genome.from_dict(json.loads(p.read_text(encoding="utf-8")))
        ph = express(g, "role-swarm-mind")
        nsec_path = sec_dir / f"{g.individual}.nsec"
        secret = hive.read_secret(nsec_path) if nsec_path.exists() else None
        data_dir = f"{a.data_root}/{g.individual}"
        kit = ROOT / "births" / "e001-hive" / g.individual
        m = hive.write_hive_kit(ph, kit, secret, data_dir, a.relay, a.channel, now)
        if not nsec_path.exists():
            (kit / "hive.nsec").replace(nsec_path)
        else:
            (kit / "hive.nsec").unlink()
        prior_path = pub_dir / f"{g.individual}.json"
        if prior_path.exists():  # re-run: the key was minted when the file first appeared, not now
            prior = json.loads(prior_path.read_text(encoding="utf-8"))
            if prior.get("npub") == m["npub"] and "minted" in prior:
                m["minted"] = prior["minted"]
        m["registered"] = bool(a.registered)
        if a.registered:
            m["registered_at"] = a.registered
            m["registration"] = "relay pubkey_allowlist (NIP-42 gate), both communities; not the NIP-43 member roster"
        m["experiment"] = "E-001"
        (pub_dir / f"{g.individual}.json").write_text(json.dumps(m, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        hd = kit / "custom_harnesses" / f"{m['harness']['id']}.json"
        (pub_dir / "custom_harnesses" / hd.name).write_text(hd.read_text(encoding="utf-8"), encoding="utf-8")
        rows.append((g.individual, m["npub"], m["harness"]["id"]))
    assert len({r[1] for r in rows}) == len(rows), "two arms share a key"
    for ind, npub, hid in rows:
        print(f"{ind:22} {npub}  harness {hid}")
    print(f"{len(rows)} identities; public halves in {pub_dir.relative_to(ROOT)}, secrets in {sec_dir.relative_to(ROOT)} (gitignored)")
    # the secrets never appear in anything under genomes/
    for q in pub_dir.rglob("*.json"):
        t = q.read_text(encoding="utf-8")
        for ind, _, _ in rows:
            s = (sec_dir / f"{ind}.nsec").read_text(encoding="utf-8").strip()
            assert s not in t and nostr.decode_key(s)[1].hex() not in t, q


if __name__ == "__main__":
    main()
