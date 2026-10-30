"""E-001 analysis, frozen at pre-registration. Reads the colony's records read-only.

    python experiments/e001_analyze.py --verdicts /srv/grid/colony-one/verdicts \
        --history /srv/grid/colony-one/state/history.sqlite3 --since 2026-10-28T00:00:00Z

Prints, per genome arm over settled verdicts with outcome == proposed and tier outside the
exclusions: n, positive rate, mean fitness, validity, unborn rate. Then the two
pre-registered tests (10,000 label permutations each, seed 0): the omnibus spread of positive
rates across arms, and best arm vs the pooled rest. Then the blind baseline for the same
epochs: P(births >= 2) among children with no proposal-log row. Then arm counts per day with
a chi-square against uniform, the interleaving check.
"""
from __future__ import annotations

import argparse
import calendar
import json
import math
import random
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

POSITIVE = {"reproduced", "growing", "enduring", "established"}
EXCLUDED = {"preexisting", "unknown", "rejected"}
PERMS = 10_000
REGISTERED_ARMS_DIR = Path(__file__).resolve().parent.parent / "genomes" / "e001"


def read_jsonl(p: Path):
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def iso_ms(s: str) -> int:
    # calendar.timegm, not mktime - time.timezone: the latter is off by an hour on a host in
    # daylight-saving time (amendment 3; debain1 runs Central time).
    return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ")) * 1000


def registered_arms(d: Path) -> set[str]:
    """Individuals named by the registered arm files, or empty when the directory is absent."""
    if not d.is_dir():
        return set()
    out = set()
    for f in sorted(d.glob("*.json")):
        try:
            out.add(json.loads(f.read_text(encoding="utf-8"))["individual"])
        except (ValueError, KeyError, OSError):
            continue
    return out


def perm_test(groups: dict, stat, rng: random.Random, n=PERMS) -> tuple[float, float]:
    """Observed statistic and permutation p-value (share of shuffles with stat >= observed)."""
    labels, values = [], []
    for g, vs in groups.items():
        labels += [g] * len(vs)
        values += vs
    observed = stat(groups)
    at_least = 0
    for _ in range(n):
        rng.shuffle(values)
        shuffled = defaultdict(list)
        for lab, v in zip(labels, values):
            shuffled[lab].append(v)
        if stat(shuffled) >= observed - 1e-12:
            at_least += 1
    return observed, (at_least + 1) / (n + 1)


def spread(groups):
    rates = [sum(v) / len(v) for v in groups.values() if v]
    return max(rates) - min(rates)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", required=True)
    ap.add_argument("--history", required=True)
    ap.add_argument("--since", required=True, help="ISO UTC, the moment the arms went live")
    ap.add_argument("--until", default=None)
    ap.add_argument("--arms", default=str(REGISTERED_ARMS_DIR),
                    help="directory of the registered arm genomes; rows labelled with any other "
                         "individual are reported and excluded (amendment 3)")
    a = ap.parse_args()
    since_ms = iso_ms(a.since)
    until_ms = iso_ms(a.until) if a.until else None
    vd = Path(a.verdicts)
    arms_set = registered_arms(Path(a.arms))

    in_window = [e for e in read_jsonl(vd / "proposals.jsonl")
                 if e.get("genome") and since_ms <= e.get("ts", 0) <= (until_ms or 1 << 62)]
    strays = Counter(e["genome"] for e in in_window if arms_set and e["genome"] not in arms_set)
    props = {e["request_id"]: e for e in in_window if not strays or e["genome"] not in strays}
    verdicts = [r for r in read_jsonl(vd / "verdicts.jsonl") if r.get("request_id") in props]
    print(f"arms' proposal-log rows: {len(props)}; settled verdicts among them: {len(verdicts)}")
    if arms_set:
        print(f"registered arms: {len(arms_set)} from {a.arms}")
    for g, n in sorted(strays.items()):
        print(f"excluded: {n} row(s) labelled {g}, not a registered arm")

    per = defaultdict(lambda: Counter())
    scorable = defaultdict(list)
    fitness = defaultdict(list)
    for r in verdicts:
        g = r.get("genome") or props[r["request_id"]].get("genome")
        per[g][r["tier"]] += 1
        per[g]["_rows"] += 1
        if r.get("outcome") == "proposed" and r["tier"] not in EXCLUDED:
            scorable[g].append(1 if r["tier"] in POSITIVE else 0)
            fitness[g].append(r.get("fitness", 0))
    for e in props.values():
        per[e["genome"]]["_" + e.get("outcome", "?")] += 1

    print("\n| arm | scorable | positive rate | mean fitness | validity | unborn |")
    print("|---|---|---|---|---|---|")
    for g in sorted(per):
        n = len(scorable[g])
        pos = sum(scorable[g]) / n if n else float("nan")
        fit = sum(fitness[g]) / n if n else float("nan")
        prop, rej = per[g]["_proposed"], per[g]["_rejected"]
        validity = prop / (prop + rej) if prop + rej else float("nan")
        unborn = per[g]["unborn"] / n if n else float("nan")
        print(f"| {g} | {n} | {pos:.3f} | {fit:.2f} | {validity:.3f} | {unborn:.3f} |")

    groups = {g: v for g, v in scorable.items() if v}
    if len(groups) >= 2 and all(len(v) >= 20 for v in groups.values()):
        rng = random.Random(0)
        obs, p = perm_test(groups, spread, rng)
        print(f"\nomnibus: spread of positive rates {obs:.3f}, permutation p = {p:.4f} "
              f"({'H0 rejected at 0.01' if p < 0.01 else 'H0 not rejected'})")
        best = max(groups, key=lambda g: sum(groups[g]) / len(groups[g]))
        two = {"best": groups[best], "rest": [v for g, vs in groups.items() if g != best for v in vs]}
        obs2, p2 = perm_test(two, lambda G: sum(G["best"]) / len(G["best"]) - sum(G["rest"]) / len(G["rest"]),
                             random.Random(0))
        print(f"best arm {best}: +{obs2:.3f} over pooled rest, permutation p = {p2:.4f}")
    else:
        print("\ntests skipped: fewer than 2 arms with >= 20 scorable rows")

    # blind baseline over the same epochs
    epochs = sorted({int(r["epoch"]) for r in verdicts if r.get("epoch")})
    if epochs:
        logged = {e.get("proposal_genome_id") for e in read_jsonl(vd / "proposals.jsonl") if e.get("proposal_genome_id")}
        c = sqlite3.connect(f"file:{a.history}?mode=ro", uri=True)
        lo, hi = epochs[0], epochs[-1]
        rows = c.execute("SELECT t.epoch, t.child_genome_id, s.births FROM transitions t "
                         "JOIN genome_stats s ON s.epoch=t.epoch AND s.genome_id=t.child_genome_id "
                         "WHERE t.epoch BETWEEN ? AND ? AND t.parent_genome_id != t.child_genome_id", (lo, hi)).fetchall()
        blind = [(b or 0) >= 2 for _, gid, b in rows if gid not in logged]
        print(f"\nblind baseline, epochs {lo}-{hi}: {len(blind)} children, P(births>=2) = "
              f"{sum(blind) / len(blind):.3f}" if blind else "\nblind baseline: no rows")

    # interleaving check
    byday = defaultdict(Counter)
    for e in props.values():
        byday[time.strftime("%m-%d", time.gmtime(e["ts"] / 1000))][e["genome"]] += 1
    arms = sorted({g for d in byday.values() for g in d})
    chi, dof = 0.0, 0
    for d, cnt in sorted(byday.items()):
        tot = sum(cnt.values())
        exp = tot / len(arms)
        chi += sum((cnt[g] - exp) ** 2 / exp for g in arms)
        dof += len(arms) - 1
        print(f"{d}: " + " ".join(f"{g.split('-')[-1]}={cnt[g]}" for g in arms))
    if dof:
        # Wilson-Hilferty normal approximation to the chi-square tail
        z = ((chi / dof) ** (1 / 3) - (1 - 2 / (9 * dof))) / math.sqrt(2 / (9 * dof))
        p = 0.5 * math.erfc(z / math.sqrt(2))
        print(f"interleaving: chi2 {chi:.1f} on {dof} dof, p ~ {p:.3f} ({'OK' if p >= 0.01 else 'NOT interleaved'})")


if __name__ == "__main__":
    main()
