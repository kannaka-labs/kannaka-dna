"""E-001: make the eight genome arms from the founder, with quantum-drawn seeds.

    python experiments/e001_make_arms.py --seeds seeds.json --served kannaka-brain-v1,kannaka-brain-v2,kannaka-brain-v3,kannaka-brain-7b-v1

`seeds.json` is the raw output of `kannaka-quantum qrng-draw --bits 1024` (or more): its
bits are cut into 32-bit seeds, used in order, and the whole provenance block (QPU job id,
device, harvest time) is written into every arm's `conception.seed_source`. If the draw ran
out of bits before eight distinct arms were found, the script stops and says so rather than
topping up from a PRNG.

Each arm is `kdna clone` of genomes/kannaka-g0.json at rate 1.0 (every mutable gene mutates),
kept only if its brain allele is a served alias and its (model_alias, temperature,
recall_top_k) phenotype is new. Output: genomes/e001/<individual>.json, phenotypes in
genomes/e001/phenotypes/<individual>.json (what the relay reads), and the Registered arms
table appended to the pre-registration.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kdna.express import express, mind_params  # noqa: E402
from kdna.genome import Genome  # noqa: E402
from kdna.reproduce import mitosis  # noqa: E402

PREREG = ROOT / "docs" / "experiments" / "E-001-swarm-mind-selection.md"


def seeds_from_draw(draw: dict) -> tuple[list[int], dict]:
    """32-bit seeds from a qrng-draw result, plus its provenance (anything that is not the bits)."""
    bits = draw.get("bits") or draw.get("bitstring")
    if isinstance(bits, int):
        bits = None
    if not bits and "hex" in draw:
        bits = bin(int(draw["hex"], 16))[2:].zfill(len(draw["hex"]) * 4)
    if not bits or not set(bits) <= {"0", "1"}:
        raise SystemExit(f"no bitstring in the draw; keys were {sorted(draw)}")
    seeds = [int(bits[i:i + 32], 2) for i in range(0, len(bits) - 31, 32)]
    prov = {k: v for k, v in draw.items() if k not in ("bits", "bitstring", "hex", "integer", "float")}
    return seeds, prov


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", required=True, help="qrng-draw JSON output")
    ap.add_argument("--served", required=True, help="comma-separated gateway aliases")
    ap.add_argument("--arms", type=int, default=8)
    ap.add_argument("--born", default="")
    a = ap.parse_args()

    served = set(a.served.split(","))
    draw = json.loads(Path(a.seeds).read_text(encoding="utf-8"))
    seeds, prov = seeds_from_draw(draw)
    founder = Genome.from_dict(json.loads((ROOT / "genomes" / "kannaka-g0.json").read_text(encoding="utf-8")))
    out = ROOT / "genomes" / "e001"
    (out / "phenotypes").mkdir(parents=True, exist_ok=True)

    arms, seen, tried = [], set(), 0
    for seed in seeds:
        if len(arms) >= a.arms:
            break
        tried += 1
        child = mitosis(founder, seed, rate=1.0, born=a.born)
        p = mind_params(child)
        key = (p["model_alias"], p["temperature"], p["recall_top_k"])
        if p["model_alias"] not in served or key in seen:
            continue
        seen.add(key)
        child.conception["seed_source"] = prov
        child.conception["experiment"] = "E-001"
        child.individual = f"{child.species}-g1-{child.hash[:6]}"   # re-derive the name after the edit
        arms.append((child, p))
    if len(arms) < a.arms:
        raise SystemExit(f"only {len(arms)} distinct served arms from {tried} seeds; draw more bits, "
                         "do not top up from a PRNG")

    rows = []
    for child, p in arms:
        (out / f"{child.individual}.json").write_text(json.dumps(child.to_dict(), indent=1, ensure_ascii=False) + "\n",
                                                      encoding="utf-8")
        ph = express(child, "role-swarm-mind")
        (out / "phenotypes" / f"{child.individual}.json").write_text(json.dumps(ph, indent=1, ensure_ascii=False) + "\n",
                                                                     encoding="utf-8")
        muts = "; ".join(f"{m['gene']}{'.' + m['key'] if m.get('key') else ''}" for m in child.conception["mutations"])
        rows.append(f"| `{child.individual}` | `{child.hash[:16]}` | {p['model_alias']} | {p['temperature']} | "
                    f"{p['recall_top_k']} | {muts} |")
    table = ["", f"Generated {a.born or 'now'} from `kannaka-g0` ({founder.hash[:16]}), {tried} seeds tried, "
             f"seed source: `{json.dumps(prov, sort_keys=True)}`", "",
             "| individual | genome | model_alias | temperature | recall_top_k | mutated genes |",
             "|---|---|---|---|---|---|", *rows, ""]
    with open(PREREG, "a", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(table))
    print("\n".join(rows))
    print(f"{len(arms)} arms -> {out}")


if __name__ == "__main__":
    main()
