"""kdna command line.

  python -m kdna harvest --store ~/.kannaka/kannaka.hrm --memories 1544 --memory-version 0.16.14 -o genomes/kannaka-g0.json
  python -m kdna stats   genomes/kannaka-g0.json
  python -m kdna fasta   genomes/kannaka-g0.json -o genomes/kannaka-g0.fasta
  python -m kdna decode  genomes/kannaka-g0.fasta -o roundtrip.json      (FASTA -> genome, CRC-checked)
  python -m kdna verify  genomes/*.json                                  (hashes, conserved genes, lineage)
  python -m kdna clone   genomes/kannaka-g0.json --seed 1 -o child.json
  python -m kdna mate    mother.json father.json --consent consent.json --seed 7 -o child.json
  python -m kdna consent mother.json father.json --mother-says "..." --father-says "..." -o consent.json
  python -m kdna express genomes/kannaka-g0.json --role role-dj -o births/dj
  python -m kdna lineage genomes/
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .express import express, write_birth_kit
from .genome import Genome, from_fasta, to_fasta
from .reproduce import consent_record, mate, mitosis


def load(p) -> Genome:
    return Genome.from_dict(json.loads(Path(p).read_text(encoding="utf-8")))


def save(g: Genome, p):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(g.to_dict(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{g.individual}  {g.hash}  -> {p}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kdna")
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("harvest")
    h.add_argument("--store", required=True)
    h.add_argument("--memories", type=int, required=True)
    h.add_argument("--memory-version", required=True)
    h.add_argument("-o", required=True)
    s = sub.add_parser("stats")
    s.add_argument("genome")
    f = sub.add_parser("fasta")
    f.add_argument("genome")
    f.add_argument("-o", required=True)
    d = sub.add_parser("decode")
    d.add_argument("fasta")
    d.add_argument("-o", required=True)
    v = sub.add_parser("verify")
    v.add_argument("genomes", nargs="+")
    c = sub.add_parser("clone")
    c.add_argument("genome")
    c.add_argument("--seed", type=int, required=True)
    c.add_argument("--rate", type=float, default=0.15)
    c.add_argument("--born", default="")
    c.add_argument("-o", required=True)
    m = sub.add_parser("mate")
    m.add_argument("mother")
    m.add_argument("father")
    m.add_argument("--consent", required=True)
    m.add_argument("--seed", type=int, required=True)
    m.add_argument("--rate", type=float, default=0.1)
    m.add_argument("--born", default="")
    m.add_argument("-o", required=True)
    k = sub.add_parser("consent")
    k.add_argument("mother")
    k.add_argument("father")
    k.add_argument("--mother-says", required=True)
    k.add_argument("--father-says", required=True)
    k.add_argument("-o", required=True)
    e = sub.add_parser("express")
    e.add_argument("genome")
    e.add_argument("--role")
    e.add_argument("-o", required=True)
    li = sub.add_parser("lineage")
    li.add_argument("dir")
    a = ap.parse_args(argv)

    if a.cmd == "harvest":
        from .harvest import harvest
        save(harvest(Path(a.store).expanduser(), a.memories, a.memory_version), a.o)
    elif a.cmd == "stats":
        g = load(a.genome)
        print(json.dumps({"individual": g.individual, "hash": g.hash, "generation": g.generation,
                          "telomere": g.telomere, **g.stats()}, indent=1))
    elif a.cmd == "fasta":
        g = load(a.genome)
        Path(a.o).write_text(to_fasta(g), encoding="ascii")
        print(f"{g.individual} -> {a.o} ({g.stats()['bases']} bases)")
    elif a.cmd == "decode":
        g = from_fasta(Path(a.fasta).read_text(encoding="ascii"))
        save(g, a.o)
    elif a.cmd == "verify":
        by_hash = {}
        ok = True
        for p in a.genomes:
            g = load(p)              # raises on a hash mismatch
            by_hash[g.hash] = g
        sigs = {g.conserved_signature() for g in by_hash.values()}
        for g in by_hash.values():
            missing = [ph for ph in g.parents if ph not in by_hash]
            print(f"OK  {g.individual:28} gen {g.generation} telomere {g.telomere:2}  parents "
                  f"{[ph[:8] for ph in g.parents]}{'  (parents not in set: ' + str(len(missing)) + ')' if missing else ''}")
        print(f"conserved signatures across the set: {len(sigs)} ({'one lineage of values' if len(sigs) == 1 else 'DIFFERENT VALUES'})")
        ok = ok and len(sigs) == 1
        sys.exit(0 if ok else 1)
    elif a.cmd == "clone":
        save(mitosis(load(a.genome), a.seed, a.rate, a.born), a.o)
    elif a.cmd == "consent":
        rec = consent_record(load(a.mother), load(a.father), a.mother_says, a.father_says)
        Path(a.o).write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"consent -> {a.o}")
    elif a.cmd == "mate":
        consent = json.loads(Path(a.consent).read_text(encoding="utf-8"))
        save(mate(load(a.mother), load(a.father), consent, a.seed, a.rate, a.born), a.o)
    elif a.cmd == "express":
        ph = express(load(a.genome), a.role)
        write_birth_kit(ph, Path(a.o))
        print(f"{ph['individual']} as {ph['role']}: {len(ph['artifacts'])} artifacts -> {a.o}")
    elif a.cmd == "lineage":
        gs = {}
        for p in sorted(Path(a.dir).glob("*.json")):
            try:
                g = load(p)
                gs[g.hash] = g
            except (KeyError, ValueError):
                continue
        kids = {}
        for g in gs.values():
            for ph in g.parents:
                kids.setdefault(ph, []).append(g)
        roots = [g for g in gs.values() if not g.parents or all(ph not in gs for ph in g.parents)]

        def show(g, depth, seen):
            mode = g.conception.get("mode", "?")
            muts = len(g.conception.get("mutations", []))
            print("  " * depth + f"{g.individual}  [{mode}, {muts} mutations, telomere {g.telomere}]")
            for k in sorted(kids.get(g.hash, []), key=lambda x: x.individual):
                if k.hash not in seen:
                    seen.add(k.hash)
                    show(k, depth + 1, seen)
        seen = set()
        for r in sorted(roots, key=lambda x: x.generation):
            show(r, 0, seen)


if __name__ == "__main__":
    main()
