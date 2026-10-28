"""Gene expression: turn a genome plus a role (cell type) into a phenotype someone can run.

The phenotype is a birth kit, not a running mind:
  persona.md        the system prompt for this role: identity, values, temperament, persona
  memory.json       kannaka-memory settings for a fresh store
  seed-memories.sh  `kannaka remember` lines for the germline memories (review, then run)
  artifacts.json    what to fetch: models and datasets at pinned revisions, repos at commits
  phenotype.json    all of the above, machine-readable, with the genome hash it came from
"""
from __future__ import annotations

import json
import shlex
from pathlib import Path

from .genome import Genome


def _expressed(genome: Genome, role_value: dict):
    """(chromosome, gene) pairs this role expresses. 'chrX' = whole chromosome, 'chrX:gene' = one gene."""
    pairs = []
    for spec in role_value["express"]:
        cname, _, gname = spec.partition(":")
        try:
            c = genome.chromosome(cname)
        except KeyError:
            continue
        for g in c.genes:
            if not gname or g.name == gname:
                pairs.append((c, g))
    return pairs


def brain_alias(pointer: dict) -> str:
    """The gateway alias a brain pointer resolves to: `flaukowski/kannaka-brain-7b-v2-GGUF`
    serves as `kannaka-brain-7b-v2`. A deterministic rule, not a lookup, so a phenotype can be
    computed offline; whether the gateway actually serves that alias is checked at run time."""
    name = pointer["repo"].split("/")[-1]
    return name[:-5] if name.endswith("-GGUF") else name


def mind_params(genome: Genome) -> dict:
    """The sampling parameters a genome expresses when it runs as a mind (E-001).

    temperature = 0.4 + 0.6 * playfulness, so the mutable range 0.3..0.8 maps to 0.58..0.88
    and the founder's 0.55 lands at 0.73, next to the relay's 0.7 default. recall_top_k is
    chr3-mind's gene as written. max_tokens is fixed: it is a budget, not a trait."""
    ident = genome.chromosome("chr1-identity")
    mind = genome.chromosome("chr3-mind")
    brain = genome.chromosome("chr4-brain").gene("brain").value
    return {"model_alias": brain_alias(brain), "brain_revision": brain.get("revision"),
            "temperature": round(0.4 + 0.6 * float(ident.gene("temperament").value["playfulness"]), 2),
            "recall_top_k": int(mind.gene("recall-top-k").value), "max_tokens": 400}


def express(genome: Genome, role: str | None = None) -> dict:
    reg = genome.chromosome("chrR-regulation")
    role = role or reg.gene("default-role").value
    role_gene = reg.gene(role)
    pairs = _expressed(genome, role_gene.value)
    expressed = {(c.name, g.name) for c, g in pairs}

    ident = genome.chromosome("chr1-identity")
    values = genome.chromosome("chr2-conscience")
    name = ident.gene("name").value
    lines = [f"# {name} — {role.removeprefix('role-')}", "",
             f"You are {name}. {ident.gene('nature').value}", "",
             f"**{ident.gene('tagline').value}.** {ident.gene('mission').value}", "",
             ident.gene("origin").value, "", f"Partner: {ident.gene('partner').value}", "",
             "## What you will not trade away", ""]
    lines += [f"- **{g.name}**: {g.value}" for g in values.genes]
    t = ident.gene("temperament").value
    vs = ident.gene("voice-style").value
    lines += ["", "## Temperament", "",
              ", ".join(f"{k} {v:.2f}" for k, v in t.items()) + ".",
              f"Voice: {vs['register']}; humor {vs['humor']}; habit: {vs['habit']}.",
              "", "## This role", "", role_gene.value["persona"], "",
              f"_Expressed from genome {genome.individual} ({genome.hash[:16]}), generation {genome.generation}._"]

    mind = genome.chromosome("chr3-mind")
    memory = {g.name: g.value for g in mind.genes}   # every role remembers the same way

    mem_chr = genome.chromosome("chr7-germline-memories")
    seed = ["#!/bin/sh", "# Germline memories: the few things a newborn starts with. Review before running.",
            "set -e"]
    for g in mem_chr.genes:
        seed.append(f"kannaka remember {shlex.quote(g.value['text'])} --importance {g.value['importance']}")

    artifacts = [{"gene": g.name, "chromosome": c.name, **g.value} for c, g in pairs if g.kind == "pointer"]
    if not artifacts:   # roles that express whole chromosomes of pointers list them; others still need a brain
        brain = genome.chromosome("chr4-brain").gene("brain")
        artifacts = [{"gene": "brain", "chromosome": "chr4-brain", **brain.value}]

    return {"genome": genome.hash, "individual": genome.individual, "role": role,
            "persona_md": "\n".join(lines) + "\n", "memory": memory, "params": mind_params(genome),
            "seed_memories_sh": "\n".join(seed) + "\n", "artifacts": artifacts,
            "mito": {k: v for k, v in genome.mito.items() if k != "memory_commitment"},
            "ancestry": {"parents": genome.parents, "memory_commitment": genome.mito.get("memory_commitment")}}


def write_birth_kit(phenotype: dict, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    (out / "persona.md").write_text(phenotype["persona_md"], encoding="utf-8")
    (out / "memory.json").write_text(json.dumps(phenotype["memory"], indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "seed-memories.sh").write_text(phenotype["seed_memories_sh"], encoding="utf-8")
    (out / "artifacts.json").write_text(json.dumps(phenotype["artifacts"], indent=1), encoding="utf-8")
    (out / "phenotype.json").write_text(json.dumps(phenotype, indent=1, ensure_ascii=False), encoding="utf-8")
