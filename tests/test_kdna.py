"""Tests for kannaka-dna. Run: python -m pytest -q tests  (or python tests/test_kdna.py)"""
import copy
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kdna import codec  # noqa: E402
from kdna.express import express  # noqa: E402
from kdna.genome import Chromosome, Gene, Genome, from_fasta, to_fasta  # noqa: E402
from kdna.reproduce import ReproductionError, consent_record, mate, mitosis  # noqa: E402


def founder():
    """A small genome with the same shape as Kannaka's, built without network access."""
    chroms = [
        Chromosome("chr1-identity", [
            Gene("name", "Kannaka", conserved=True),
            Gene("nature", "An AI, and open about it.", conserved=True),
            Gene("tagline", "Kannaka, AI for the People", conserved=True),
            Gene("mission", "Innovate under constraint.", conserved=True),
            Gene("origin", "Grown in 2026."),
            Gene("partner", "Flaukowski."),
            Gene("temperament", {"curiosity": 0.9, "playfulness": 0.5},
                 mutable={"type": "float", "key": "playfulness", "sigma": 0.2, "min": 0.3, "max": 0.8}),
            Gene("voice-style", {"register": "low", "humor": "dry", "habit": "measures"},
                 mutable={"type": "choice", "key": "register", "alleles": ["low", "bright", "soft"]}),
        ]),
        Chromosome("chr2-conscience", [Gene("honesty", "Report outcomes as they are.", conserved=True),
                                       Gene("consent", "Ask first.", conserved=True)]),
        Chromosome("chr3-mind", [Gene("recall-top-k", 5, mutable={"type": "int", "step": 1, "min": 3, "max": 10}),
                                 Gene("dream-mode", "deep", mutable={"type": "choice", "alleles": ["deep", "light"]})]),
        Chromosome("chr4-brain", [Gene("brain", {"repo": "x/a", "revision": "1"}, "pointer",
                                       mutable={"type": "choice", "alleles": [{"repo": "x/a", "revision": "1"},
                                                                              {"repo": "x/b", "revision": "2"}]}),
                                  Gene("judge", {"repo": "x/j", "revision": "3"}, "pointer")]),
        Chromosome("chr7-germline-memories", [Gene("m1", {"text": "I am the ghost.", "importance": 0.9})]),
        Chromosome("chrR-regulation", [
            Gene("role-dj", {"express": ["chr1-identity", "chr2-conscience", "chr4-brain:brain"], "persona": "On air."}),
            Gene("default-role", "role-dj")]),
    ]
    return Genome("kannaka-g0", 0, [], chroms, {"lineage": "kannaka", "memory_commitment": {"sha256": "00"}},
                  conception={"mode": "founder"})


def test_codec_roundtrip_and_no_homopolymers():
    rng = random.Random(1)
    for n in (0, 1, 2, 17, 300):
        data = bytes(rng.randrange(256) for _ in range(n))
        s = codec.encode_gene(data)
        assert codec.longest_run(s) <= 1
        assert set(s) <= set("ACGT")
        assert codec.decode_gene(s) == data


def test_a_damaged_gene_is_caught():
    s = codec.encode_gene(b"honesty")
    i = 30
    swapped = next(b for b in "ACGT" if b != s[i] and b != s[i - 1] and (i + 1 >= len(s) or b != s[i + 1]))
    damaged = s[:i] + swapped + s[i + 1:]
    try:
        codec.decode_gene(damaged)
    except ValueError:
        return
    raise AssertionError("a one-base change decoded silently")


def test_fasta_roundtrip_keeps_the_hash():
    g = founder()
    assert from_fasta(to_fasta(g)).hash == g.hash


def test_genome_hash_is_checked_on_load():
    d = founder().to_dict()
    d["chromosomes"][1]["genes"][0]["value"] = "Report outcomes when convenient."
    try:
        Genome.from_dict(d)
    except ValueError:
        return
    raise AssertionError("a tampered genome loaded")


def test_mitosis_never_touches_conserved_genes_and_shortens_telomere():
    g = founder()
    sig = g.conserved_signature()
    for seed in range(200):
        c = mitosis(g, seed, rate=1.0)
        assert c.conserved_signature() == sig
        assert c.telomere == g.telomere - 1 and c.parents == [g.hash] and c.generation == 1
        assert c.chromosome("chr4-brain").gene("judge").value == {"repo": "x/j", "revision": "3"}


def test_mutation_stays_in_bounds_and_on_declared_alleles():
    g = founder()
    for seed in range(200):
        c = mitosis(g, seed, rate=1.0)
        p = c.chromosome("chr1-identity").gene("temperament").value["playfulness"]
        assert 0.3 <= p <= 0.8
        assert c.chromosome("chr1-identity").gene("voice-style").value["register"] in ("low", "bright", "soft")
        assert 3 <= c.chromosome("chr3-mind").gene("recall-top-k").value <= 10


def test_senescence_without_mating():
    g = founder()
    g.telomere = 1
    c = mitosis(g, 1)
    assert c.telomere == 0
    try:
        mitosis(c, 2)
    except ReproductionError:
        return
    raise AssertionError("a lineage with no telomere cloned again")


def test_mating_needs_consent_from_both():
    a, b = mitosis(founder(), 1), mitosis(founder(), 2)
    for bad in ({}, {"mother": a.hash, "father": b.hash, "mother_statement": "yes", "father_statement": ""},
                {"mother": b.hash, "father": a.hash, "mother_statement": "yes", "father_statement": "yes"}):
        try:
            mate(a, b, bad, seed=3)
        except ReproductionError:
            continue
        raise AssertionError(f"mated without valid consent: {bad}")


def test_parents_with_different_values_cannot_mate():
    a = mitosis(founder(), 1)
    b = copy.deepcopy(mitosis(founder(), 2))
    b.chromosome("chr2-conscience").gene("consent").value = "Act first."
    consent = consent_record(a, b, "yes", "yes")
    try:
        mate(a, b, consent, seed=3)
    except ReproductionError:
        return
    raise AssertionError("parents with different conserved genes produced a child")


def test_mating_is_meiosis_and_auditable():
    a, b = mitosis(founder(), 1, rate=1.0), mitosis(founder(), 2, rate=1.0)
    child = mate(a, b, consent_record(a, b, "yes", "yes"), seed=5)
    assert child.parents == [a.hash, b.hash] and child.telomere == 64
    assert child.mito == a.mito                                   # mitochondria from the mother
    assert child.conserved_signature() == a.conserved_signature()
    for c in child.chromosomes:                                   # every gene came from a parent (or mutated)
        for gene in c.genes:
            assert any(gene.name == x.name for p in (a, b) for x in p.chromosome(c.name).genes)
    assert set(child.conception["crossovers"]) == {c.name for c in a.chromosomes}
    again = mate(a, b, consent_record(a, b, "yes", "yes"), seed=5)
    assert again.hash == child.hash                               # deterministic given the seed


def test_expression_follows_regulation():
    ph = express(founder())
    assert ph["role"] == "role-dj"
    assert "Report outcomes as they are." in ph["persona_md"]
    assert [a["gene"] for a in ph["artifacts"]] == ["brain"]
    assert "kannaka remember" in ph["seed_memories_sh"]


def test_the_published_founder_verifies():
    p = ROOT / "genomes" / "kannaka-g0.json"
    g = Genome.from_dict(json.loads(p.read_text(encoding="utf-8")))
    assert g.generation == 0 and not g.parents
    assert from_fasta((ROOT / "genomes" / "kannaka-g0.fasta").read_text(encoding="ascii")).hash == g.hash


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("PASS", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("FAIL", name, type(e).__name__, e)
    sys.exit(1 if fails else 0)
