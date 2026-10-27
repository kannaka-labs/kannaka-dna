"""The genome: chromosomes of genes, a mitochondrial genome, and a content hash.

Biology mapping, kept honest about where it is a metaphor:

- **Gene**: one heritable trait, stored as canonical JSON. `inline` genes carry the trait
  itself (a value, a voice setting, a line of character). `pointer` genes carry where a
  heavy part lives (a model on Hugging Face, a repo at a commit) plus its content hash, the
  way a gene encodes a protein rather than containing one.
- **Conserved gene**: never mutated, and two parents whose conserved genes differ cannot
  reproduce (reproductive isolation). Kannaka's values live here, so honesty and consent
  cannot be bred out of a descendant.
- **Chromosome**: a named group of genes inherited together unless crossover splits them.
- **Mitochondrial genome**: inherited from the mother only, never recombined: provenance,
  licence, the lineage's origin.
- **Telomere**: shortens with every clone; mating restores it (germline renewal).
- **Epigenome**: not in here. Experience (the memory store) is somatic: a child inherits how
  to remember and a commitment to its mother's memory, never the memories themselves.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from . import codec

SPECIES = "kannaka"
FORMAT = "kdna/1"


def canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha(obj) -> str:
    return hashlib.sha256(canon(obj)).hexdigest()


@dataclass
class Gene:
    name: str
    value: object
    kind: str = "inline"          # inline | pointer
    conserved: bool = False
    mutable: dict = field(default_factory=dict)   # how mutation may change it (see reproduce.py)

    def to_dict(self):
        d = {"name": self.name, "kind": self.kind, "conserved": self.conserved, "value": self.value}
        if self.mutable:
            d["mutable"] = self.mutable
        return d

    @staticmethod
    def from_dict(d):
        return Gene(d["name"], d["value"], d.get("kind", "inline"), d.get("conserved", False), d.get("mutable", {}))

    def digest(self) -> str:
        return sha(self.to_dict())


@dataclass
class Chromosome:
    name: str
    genes: list

    def to_dict(self):
        return {"name": self.name, "genes": [g.to_dict() for g in self.genes]}

    @staticmethod
    def from_dict(d):
        return Chromosome(d["name"], [Gene.from_dict(g) for g in d["genes"]])

    def gene(self, name):
        for g in self.genes:
            if g.name == name:
                return g
        raise KeyError(name)


@dataclass
class Genome:
    individual: str
    generation: int
    parents: list            # genome hashes; [] for the founder
    chromosomes: list
    mito: dict
    telomere: int = 64
    born: str = ""
    species: str = SPECIES
    notes: str = ""
    conception: dict = field(default_factory=dict)   # how this individual came to be (hashed)

    def body(self):
        """Everything that defines the individual (the hash covers exactly this)."""
        return {
            "format": FORMAT, "species": self.species, "individual": self.individual,
            "generation": self.generation, "parents": self.parents, "telomere": self.telomere,
            "born": self.born, "mito": self.mito, "conception": self.conception,
            "chromosomes": [c.to_dict() for c in self.chromosomes],
        }

    @property
    def hash(self) -> str:
        return sha(self.body())

    def to_dict(self):
        d = self.body()
        d["hash"] = self.hash
        if self.notes:
            d["notes"] = self.notes
        return d

    @staticmethod
    def from_dict(d, verify=True):
        g = Genome(d["individual"], d["generation"], d["parents"],
                   [Chromosome.from_dict(c) for c in d["chromosomes"]], d["mito"],
                   d.get("telomere", 64), d.get("born", ""), d.get("species", SPECIES), d.get("notes", ""),
                   d.get("conception", {}))
        if verify and "hash" in d and d["hash"] != g.hash:
            raise ValueError(f"genome hash mismatch: file says {d['hash'][:12]}, content is {g.hash[:12]}")
        return g

    def chromosome(self, name):
        for c in self.chromosomes:
            if c.name == name:
                return c
        raise KeyError(name)

    def conserved_signature(self) -> str:
        """Hash of every conserved gene: equal signatures = compatible parents."""
        return sha(sorted([c.name, g.name, g.value] for c in self.chromosomes for g in c.genes if g.conserved))

    def stats(self):
        genes = [g for c in self.chromosomes for g in c.genes]
        strands = [codec.encode_gene(canon(g.to_dict())) for g in genes]   # one molecule per gene
        joined = "".join(strands)
        return {"chromosomes": len(self.chromosomes), "genes": len(genes),
                "conserved": sum(g.conserved for g in genes),
                "pointers": sum(g.kind == "pointer" for g in genes),
                "bases": len(joined), "gc": round(codec.gc_content(joined), 4),
                "longest_homopolymer": max(codec.longest_run(s) for s in strands)}


# ---------------------------------------------------------------- FASTA

def to_fasta(genome: Genome, width: int = 80) -> str:
    """One FASTA record per gene, plus the mitochondrial genome and a header record."""
    def rec(header, strand):
        return f">{header}\n" + "\n".join(strand[i:i + width] for i in range(0, len(strand), width)) + "\n"

    meta = {k: v for k, v in genome.body().items() if k not in ("chromosomes", "mito")}
    out = [rec(f"{genome.individual}|header|{genome.hash[:16]}", codec.encode_gene(canon(meta))),
           rec(f"{genome.individual}|chrM|mito", codec.encode_gene(canon(genome.mito)))]
    for c in genome.chromosomes:
        for i, g in enumerate(c.genes):
            flag = "conserved" if g.conserved else g.kind
            out.append(rec(f"{genome.individual}|{c.name}|{i}|{g.name}|{flag}",
                           codec.encode_gene(canon(g.to_dict()))))
    return "".join(out)


def from_fasta(text: str) -> Genome:
    records, cur, seq = [], None, []
    for line in text.splitlines():
        if line.startswith(">"):
            if cur is not None:
                records.append((cur, "".join(seq)))
            cur, seq = line[1:], []
        elif line.strip():
            seq.append(line.strip())
    if cur is not None:
        records.append((cur, "".join(seq)))
    meta, mito, chroms = None, None, {}
    for header, strand in records:
        parts = header.split("|")
        payload = json.loads(codec.decode_gene(strand))
        if parts[1] == "header":
            meta = payload
        elif parts[1] == "chrM":
            mito = payload
        else:
            chroms.setdefault(parts[1], []).append((int(parts[2]), Gene.from_dict(payload)))
    if meta is None or mito is None:
        raise ValueError("FASTA is missing the header or chrM record")
    chromosomes = [Chromosome(n, [g for _, g in sorted(gs, key=lambda x: x[0])]) for n, gs in chroms.items()]
    g = Genome(meta["individual"], meta["generation"], meta["parents"], chromosomes, mito,
               meta.get("telomere", 64), meta.get("born", ""), meta.get("species", SPECIES),
               conception=meta.get("conception", {}))
    return g
