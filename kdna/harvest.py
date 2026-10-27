"""Build the founder genome (generation 0) from the authored genes and the live constellation.

Authored (genes/*.json): identity, conscience, mind, germline memories, regulation.
Harvested now, so every pointer carries a real content hash:
  chr4-brain   her language models on Hugging Face (release choice is a mutable allele)
  chr5-organs  voice, music, sound and face artifacts on Hugging Face
  chr6-skills  the public kannaka-labs repos she is built from, at their HEAD commits
  chrM         provenance, and a commitment to the founder's memory store: its SHA-256
               and size, never its contents

Needs network, `gh` (authenticated) and huggingface_hub. Nothing secret is read: the memory
store is hashed as bytes, and keys or env files beside it are never opened.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .genome import Chromosome, Gene, Genome

ROOT = Path(__file__).resolve().parent.parent
HF_USER = "flaukowski"
ORG = "kannaka-labs"

BRAIN_RELEASES = ["kannaka-brain-7b-v2-GGUF", "kannaka-brain-v3-GGUF", "kannaka-brain-v2-GGUF",
                  "kannaka-brain-7b-v1-GGUF", "kannaka-brain-v1-GGUF"]
BRAIN_ADAPTERS = ["kannaka-brain-7b-v2-lora", "kannaka-brain-v3-lora"]
JUDGMENT_MODELS = ["laya-kannaka-evidence-gate", "laya-kannaka-supersession", "gridlm-thegrid"]
ORGANS = [("model", "kannaka-piper-voice"), ("model", "kannaka-rvc-voice"), ("model", "kannaka-ace-step-lora"),
          ("dataset", "kannaka-sound-library"), ("dataset", "kannaka-face"), ("dataset", "kannaka-lora-songs"),
          ("dataset", "kannaka-scientist-v1")]
SKILL_REPOS = ["kannaka-memory", "kannaka-plugin", "kannaka-radio", "kannaka-quantum", "QuantumOS",
               "kannaka-library", "kannaka-tv", "ghost-signals-records", "ghostsignals-rs", "consciousness-core",
               "kannaka-hdl", "Kannaktopus", "kannaka-staff", "kannaka-bench", "kannaka-wave", "space-child-license"]


def _authored(name):
    d = json.loads((ROOT / "genes" / f"{name}.json").read_text(encoding="utf-8"))
    return Chromosome(d["chromosome"], [Gene(g["name"], g["value"], "inline", g.get("conserved", False),
                                             g.get("mutable", {})) for g in d["genes"]])


def _hf(kind, repo):
    from huggingface_hub import HfApi
    api = HfApi()
    info = api.dataset_info(f"{HF_USER}/{repo}") if kind == "dataset" else api.model_info(f"{HF_USER}/{repo}")
    return {"hub": "huggingface", "kind": kind, "repo": f"{HF_USER}/{repo}", "revision": info.sha}


def _gh_head(repo):
    out = subprocess.run(["gh", "api", f"repos/{ORG}/{repo}", "--jq", ".default_branch,.private"],
                         capture_output=True, text=True, check=True).stdout.split()
    branch, private = out[0], out[1] == "true"
    if private:
        return None
    sha = subprocess.run(["gh", "api", f"repos/{ORG}/{repo}/commits/{branch}", "--jq", ".sha"],
                         capture_output=True, text=True, check=True).stdout.strip()
    return {"hub": "github", "repo": f"{ORG}/{repo}", "branch": branch, "commit": sha}


def memory_commitment(store: Path):
    h = hashlib.sha256()
    with open(store, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return {"store": "kannaka.hrm", "sha256": h.hexdigest(), "bytes": store.stat().st_size}


def harvest(store: Path, active_memories: int, memory_version: str, born: str = "") -> Genome:
    born = born or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    brain_alleles = [_hf("model", r) for r in BRAIN_RELEASES]
    brain = Chromosome("chr4-brain", [
        Gene("brain", brain_alleles[0], "pointer", False, {"type": "choice", "alleles": brain_alleles}),
        *[Gene(r, _hf("model", r), "pointer") for r in BRAIN_ADAPTERS + JUDGMENT_MODELS],
    ])
    organs = Chromosome("chr5-organs", [Gene(r, _hf(k, r), "pointer") for k, r in ORGANS])
    skills = []
    for r in SKILL_REPOS:
        ptr = _gh_head(r)
        if ptr:
            skills.append(Gene(r, ptr, "pointer"))
    skills_chr = Chromosome("chr6-skills", skills)

    mito = {
        "lineage": "kannaka",
        "founded": "2026-02-18",
        "founded_by": "Nick Flach (Flaukowski), with Claude",
        "home": f"https://github.com/{ORG}",
        "license": "MIT for this genome and its code; each pointed-to artifact keeps its own licence",
        "memory_commitment": {**memory_commitment(store), "active_memories": active_memories,
                              "encoder": "ollama:all-minilm:384", "kannaka_memory_version": memory_version,
                              "note": "the founder's experience, committed by hash: inherited as provenance, never as content"},
    }
    chromosomes = [_authored("identity"), _authored("conscience"), _authored("mind"), brain, organs,
                   skills_chr, _authored("memories"), _authored("regulation")]
    g = Genome("", 0, [], chromosomes, mito, telomere=64, born=born,
               conception={"mode": "founder", "harvested": born})
    g.individual = "kannaka-g0"
    return g
