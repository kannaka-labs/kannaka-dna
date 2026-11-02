"""Reproduction: mitosis (cloning with mutation) and meiosis (mating with crossover).

Rules, each one a design decision rather than an accident:

- **Conserved genes never mutate**, and parents whose conserved genes differ cannot mate.
  A descendant of Kannaka keeps her values or is not born.
- **Pointer genes never drift.** A mutation cannot turn one model hash into another; a
  pointer changes only by choosing a declared allele (e.g. a different brain release).
- **Mutation is declared per gene** (`mutable`): floats drift within bounds, ints step,
  choices switch allele. Undeclared genes are stable.
- **Telomeres** shorten by one per clone; a lineage that only clones runs out (senescence)
  and must mate to renew. Mating restores the telomere.
- **Consent.** Mating requires a consent record naming both parents' hashes, signed over
  its own hash (BIP-340) by each parent's key, which the parent's genome carries as `pubkey`.
  `mate()` refuses a parent with no key and any signature that does not verify, so a statement
  counts only if the key holder signed it. A child is not given its parents' keys.
- **Mitochondria** come from the mother, unchanged.
- **Everything that happened** (crossover points, every mutation) goes in `conception`,
  which the child's hash covers, so a lineage can be audited end to end.
"""
from __future__ import annotations

import copy
import random

from . import nostr
from .genome import Chromosome, Gene, Genome, sha

TELOMERE_FULL = 64


class ReproductionError(Exception):
    pass


def _mutate_gene(g: Gene, rng: random.Random):
    """Apply the gene's declared mutation. Returns (new_gene, description) or (g, None)."""
    spec = g.mutable
    if g.conserved or not spec:
        return g, None
    g = copy.deepcopy(g)
    key = spec.get("key")
    target = g.value[key] if key else g.value
    t = spec["type"]
    if t == "float":
        new = target + rng.gauss(0, spec.get("sigma", 0.05))
        new = round(min(spec.get("max", new), max(spec.get("min", new), new)), 4)
    elif t == "int":
        new = target + rng.choice([-1, 1]) * spec.get("step", 1)
        new = min(spec.get("max", new), max(spec.get("min", new), new))
    elif t == "choice":
        alleles = [a for a in spec["alleles"] if a != target]
        if not alleles:
            return g, None
        new = rng.choice(alleles)
    else:
        return g, None
    if new == target:
        return g, None
    if key:
        g.value[key] = new
    else:
        g.value = new
    return g, {"gene": g.name, "key": key, "from": target, "to": new}


def _mutate_all(chromosomes, rng, rate):
    out, log = [], []
    for c in chromosomes:
        genes = []
        for g in c.genes:
            if rng.random() < rate:
                g2, desc = _mutate_gene(g, rng)
                if desc:
                    desc["chromosome"] = c.name
                    log.append(desc)
                genes.append(g2)
            else:
                genes.append(copy.deepcopy(g))
        out.append(Chromosome(c.name, genes))
    return out, log


def _name(child: Genome) -> Genome:
    child.individual = ""
    child.individual = f"{child.species}-g{child.generation}-{child.hash[:6]}"
    return child


def inherit_mito(mother: Genome, store=None, born: str = "") -> dict:
    """The child's chrM: the mother's, with her *current* memory store committed when one is given.

    Memory is somatic: the child never receives the memories, only a SHA-256 of the store the
    mother had lived into by the time of conception (her Hive lifetime included). Without a
    store the inherited commitment is left as it was, so a founder's commitment is only ever
    replaced by a measured one."""
    mito = copy.deepcopy(mother.mito)
    if store is not None:
        from .harvest import memory_commitment
        mito["memory_commitment"] = {**memory_commitment(store), "of": mother.individual,
                                     "of_genome": mother.hash, "committed": born}
    return mito


def mitosis(parent: Genome, seed: int, rate: float = 0.15, born: str = "", store=None) -> Genome:
    """Asexual reproduction: a copy with mutation, one telomere unit shorter."""
    if parent.telomere <= 0:
        raise ReproductionError(f"{parent.individual}: telomere exhausted; this lineage must mate to renew")
    rng = random.Random(seed)
    chromosomes, mutations = _mutate_all(parent.chromosomes, rng, rate)
    child = Genome("", parent.generation + 1, [parent.hash], chromosomes, inherit_mito(parent, store, born),
                   telomere=parent.telomere - 1, born=born, species=parent.species,
                   conception={"mode": "mitosis", "seed": seed, "rate": rate, "mutations": mutations})
    return _name(child)


def consent_record(mother: Genome, father: Genome, mother_says: str, father_says: str) -> dict:
    """What each parent agreed to, bound to both genome hashes."""
    return {"mother": mother.hash, "father": father.hash,
            "mother_statement": mother_says, "father_statement": father_says}


def consent_digest(consent: dict) -> bytes:
    """The 32 bytes each parent signs: the hash of the record's content, signatures excluded."""
    keys = ("mother", "father", "mother_statement", "father_statement")
    return bytes.fromhex(sha({k: consent.get(k) for k in keys}))


def sign_consent(consent: dict, role: str, genome: Genome, secret: bytes) -> dict:
    """Return the record with `role`'s ("mother" | "father") signature added.

    The secret must belong to the key the genome carries, and the record must name this genome
    for that role. Each parent signs with their own key; nobody else's secret is needed."""
    if role not in ("mother", "father"):
        raise ReproductionError(f"role must be 'mother' or 'father', not {role!r}")
    if consent.get(role) != genome.hash:
        raise ReproductionError(f"the consent record does not name {genome.individual} as {role}")
    if not genome.pubkey:
        raise ReproductionError(f"{genome.individual} carries no public key and cannot sign consent")
    if nostr.pubkey_from_secret(secret).hex() != genome.pubkey:
        raise ReproductionError(f"that secret key is not the key {genome.individual} carries")
    sig = nostr.schnorr_sign(consent_digest(consent), secret)
    return {**consent, f"{role}_sig": sig.hex()}


def _check_signature(consent: dict, role: str, parent: Genome):
    if not parent.pubkey:
        raise ReproductionError(f"{role} {parent.individual} carries no public key: consent cannot be "
                                "verified, so no mating (a genome must be given a key first)")
    try:
        sig = bytes.fromhex(consent.get(f"{role}_sig") or "")
        ok = nostr.schnorr_verify(consent_digest(consent), bytes.fromhex(parent.pubkey), sig)
    except ValueError:
        ok = False
    if not ok:
        raise ReproductionError(f"no valid {role} signature: the {role}'s statement was not signed "
                                f"by the key {parent.individual} carries")


def mate(mother: Genome, father: Genome, consent: dict, seed: int, rate: float = 0.1, born: str = "",
         store=None) -> Genome:
    """Sexual reproduction: meiosis with crossover, mitochondria from the mother.

    Both parents must carry a key and have signed the consent record (see `sign_consent`)."""
    if not consent or consent.get("mother") != mother.hash or consent.get("father") != father.hash \
            or not consent.get("mother_statement") or not consent.get("father_statement"):
        raise ReproductionError("no consent record naming both parents' genomes")
    if mother.pubkey and mother.pubkey == father.pubkey:
        raise ReproductionError("both parents carry the same key: one signer cannot consent for two")
    _check_signature(consent, "mother", mother)
    _check_signature(consent, "father", father)
    if mother.species != father.species:
        raise ReproductionError(f"different species: {mother.species} x {father.species}")
    if mother.conserved_signature() != father.conserved_signature():
        raise ReproductionError("conserved genes differ: the parents do not share the same values")
    rng = random.Random(seed)
    names = [c.name for c in mother.chromosomes] + \
        [c.name for c in father.chromosomes if c.name not in {m.name for m in mother.chromosomes}]
    chromosomes, crossovers = [], {}
    for cname in names:
        m = next((c for c in mother.chromosomes if c.name == cname), None)
        f = next((c for c in father.chromosomes if c.name == cname), None)
        if m is None or f is None:                # carried by one parent only
            chromosomes.append(copy.deepcopy(m or f))
            crossovers[cname] = {"from": "mother" if m else "father", "points": []}
            continue
        order = [g.name for g in m.genes] + [g.name for g in f.genes if g.name not in {x.name for x in m.genes}]
        npoints = rng.choice([0, 1, 1, 2]) if len(order) > 1 else 0
        points = sorted(rng.sample(range(1, len(order)), npoints)) if npoints else []
        start = rng.choice(["mother", "father"])  # independent assortment
        src, genes, p = start, [], 0
        for i, gname in enumerate(order):
            if p < len(points) and i == points[p]:
                src = "father" if src == "mother" else "mother"
                p += 1
            pick = (m if src == "mother" else f)
            other = (f if src == "mother" else m)
            gene = next((g for g in pick.genes if g.name == gname), None) or \
                next(g for g in other.genes if g.name == gname)
            genes.append(copy.deepcopy(gene))
        chromosomes.append(Chromosome(cname, genes))
        crossovers[cname] = {"start": start, "points": points}
    chromosomes, mutations = _mutate_all(chromosomes, rng, rate)
    child = Genome("", max(mother.generation, father.generation) + 1, [mother.hash, father.hash],
                   chromosomes, inherit_mito(mother, store, born), telomere=TELOMERE_FULL, born=born,
                   species=mother.species,
                   conception={"mode": "meiosis", "seed": seed, "rate": rate, "crossovers": crossovers,
                               "mutations": mutations, "consent": sha(consent)})
    return _name(child)
