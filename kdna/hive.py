"""The Hive layer of a birth kit: a cell as a member of kannaka-buzz.

A role says what a cell *is* (DJ, scientist, steward…); the Hive is the tissue it lives in.
`express --hive` adds, beside the role's files:

  hive.json                      the public half: pubkey/npub, the harness id, the genome
                                 room's export policy, and the unsigned event templates
  custom_harnesses/<id>.json     a Buzz Desktop "bring your own harness" definition that
                                 runs `kannaka-acp` (read-only over this cell's memory
                                 store) as the ACP agent for this member
  hive.nsec                      the secret half, written 0600, never inside hive.json or
                                 phenotype.json; drop it into the harness's secret store

What stays honest here:
- kdna mints and signs; it never connects to a relay. Registration is the operator's
  `buzz-acp`/Desktop step, with this kit's files.
- The genome room is a registry, not a feed: its kind:9002 edit sets `no-bridge`, so the
  relay publishes it on kind:39000 and kannaka-hive-bridge fails closed (fork #645). The
  cell's *other* rooms are where its lifetime becomes memory, and that memory is what a
  later `clone --store` / `mate --store` commits into the child's chrM.
- Conception records are NIP-34-shaped: one kind:30617 repository announcement for the
  lineage (the genome repo, with the `buzz-channel` tag buzz's project view reads) and one
  kind:9 group message per genome, tagged with its hash, parents and conception mode and
  linked to the announcement by its `a` coordinate.
"""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path

from . import nostr
from .genome import Genome

HARNESS_COMMAND = "kannaka-acp"
HARNESS_ID_RE = re.compile(r"^[a-z0-9_][a-z0-9_-]*$")
LINEAGE_D = "kannaka-dna"
LINEAGE_REPO = "https://github.com/kannaka-labs/kannaka-dna"
INSTALL_URL = "https://github.com/kannaka-labs/kannaka-memory"
INSTALL_HINT = "cargo install --path . --bin kannaka-acp from kannaka-memory (kannaka-acp must resolve on PATH)"


# ---------------------------------------------------------------- BYOH harness definition
def harness_id(individual: str) -> str:
    hid = individual.lower()
    if not HARNESS_ID_RE.match(hid):
        raise ValueError(f"{individual!r} is not a valid Buzz harness id ([a-z0-9_][a-z0-9_-]*)")
    return hid


def harness_definition(phenotype: dict, data_dir: str) -> dict:
    """A Buzz Desktop custom harness (camelCase, as `HarnessDefinition` deserializes it).

    args carry chr3-mind's recall-top-k, one token per entry: buzz-acp passes args through a
    comma-delimited transport, so no entry may contain a comma. env is a floor the user's own
    agent env overrides; Buzz strips its reserved BUZZ_* keys, so none are set here."""
    top_k = int(phenotype["params"]["recall_top_k"])
    d = {"id": harness_id(phenotype["individual"]),
         "label": f"Kannaka {phenotype['individual']}",
         "command": HARNESS_COMMAND,
         "args": ["--top-k", str(top_k)],
         "env": {"KANNAKA_DATA_DIR": data_dir},
         "installInstructionsUrl": INSTALL_URL,
         "installHint": INSTALL_HINT}
    for a in d["args"]:
        if "," in a:
            raise ValueError(f"harness arg {a!r} contains a comma")
    return d


# ---------------------------------------------------------------- event templates (unsigned)
def no_bridge_edit(channel_id: str, created_at: int) -> dict:
    """kind:9002 group-metadata edit that turns export off for the genome room."""
    return {"kind": 9002, "created_at": created_at, "content": "",
            "tags": [["h", channel_id], ["no-bridge", "true"]]}


def lineage_announcement(created_at: int, channel_id: str | None = None,
                         repo: str = LINEAGE_REPO, d: str = LINEAGE_D) -> dict:
    """kind:30617 (NIP-34) repository announcement for the lineage's genome repo."""
    tags = [["d", d], ["name", "Kannaka lineage"],
            ["description", "kannaka-dna genomes: every conception in this lineage, as committed JSON and FASTA"],
            ["web", repo], ["clone", repo + ".git"]]
    if channel_id:
        tags.append(["buzz-channel", channel_id])
    return {"kind": 30617, "created_at": created_at, "content": "", "tags": tags}


def conception_event(genome: Genome, created_at: int, channel_id: str | None,
                     announcer_pubkey: str | None, d: str = LINEAGE_D) -> dict:
    """kind:9 group message recording one conception, linked to the lineage announcement.

    The `a` coordinate needs the announcer's pubkey; unsigned templates carry the literal
    `<pubkey>` until `finish_event` fills it (see sign_lineage_events)."""
    mode = genome.conception.get("mode", "founder" if not genome.parents else "?")
    muts = len(genome.conception.get("mutations", []))
    parents = ", ".join(p[:8] for p in genome.parents) or "none (founder)"
    content = (f"{genome.individual} conceived by {mode} from {parents}; {muts} mutations; "
               f"generation {genome.generation}, telomere {genome.telomere}; genome {genome.hash}")
    tags = [["a", f"30617:{announcer_pubkey or '<pubkey>'}:{d}"],
            ["genome", genome.hash], ["individual", genome.individual],
            ["conception", mode], ["generation", str(genome.generation)],
            ["telomere", str(genome.telomere)]]
    tags += [["parent", p] for p in genome.parents]
    if genome.born:
        tags.append(["born", genome.born])
    if channel_id:
        tags.insert(0, ["h", channel_id])
    return {"kind": 9, "created_at": created_at, "content": content, "tags": tags}


def lineage_events(genomes: list[Genome], created_at: int, channel_id: str | None,
                   secret: bytes | None = None, repo: str = LINEAGE_REPO) -> list[dict]:
    """The announcement plus one conception record per genome, oldest generation first.

    With a secret: every event is signed and the `a` coordinates name the real pubkey.
    Without: unsigned templates (no pubkey/id/sig) a harness can finish later."""
    pk = nostr.pubkey_from_secret(secret).hex() if secret else None
    order = sorted(genomes, key=lambda g: (g.generation, g.born, g.individual))
    events = [lineage_announcement(created_at, channel_id, repo)]
    events += [conception_event(g, created_at, channel_id, pk) for g in order]
    if secret:
        events = [nostr.finish_event(e, secret) for e in events]
    return events


# ---------------------------------------------------------------- the kit
def member(phenotype: dict, secret: bytes, data_dir: str, relay: str | None,
           channel_id: str | None, created_at: int) -> dict:
    pk = nostr.pubkey_from_secret(secret)
    harness = harness_definition(phenotype, data_dir)
    m = {"individual": phenotype["individual"], "genome": phenotype["genome"], "role": phenotype["role"],
         "pubkey": pk.hex(), "npub": nostr.npub(pk),
         "harness": {"id": harness["id"], "file": f"custom_harnesses/{harness['id']}.json",
                     "command": HARNESS_COMMAND, "memory_access": "read-only (single-writer HRM policy)"},
         "secret": {"file": "hive.nsec", "format": "nsec (NIP-19)",
                    "note": "not in this file, not in phenotype.json; give it to the harness's secret store"},
         "relay": relay,
         "genome_room": {"channel": channel_id, "policy": {"no-bridge": True},
                         "why": "a registry of conceptions, not a feed: no off-relay export"},
         "memory_lineage": ("this member's lifetime in its working rooms becomes memory through kannaka remember / "
                            "the hive bridge; `kdna clone --store` or `kdna mate --store` commits that store's "
                            "SHA-256 into the next child's chrM")}
    templates = {"no_bridge_edit": no_bridge_edit(channel_id, created_at)} if channel_id else {}
    templates["lineage_announcement"] = lineage_announcement(created_at, channel_id)
    m["unsigned_templates"] = templates
    m["minted"] = created_at
    return m


def write_hive_kit(phenotype: dict, out: Path, secret: bytes | None = None, data_dir: str | None = None,
                   relay: str | None = None, channel_id: str | None = None, created_at: int = 0) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    secret = secret or nostr.generate_secret()
    data_dir = data_dir or f"~/.kannaka-{phenotype['individual']}"
    m = member(phenotype, secret, data_dir, relay, channel_id, created_at)
    harness = harness_definition(phenotype, data_dir)
    hdir = out / "custom_harnesses"
    hdir.mkdir(exist_ok=True)
    (hdir / f"{harness['id']}.json").write_text(json.dumps(harness, indent=2) + "\n", encoding="utf-8")
    (out / "hive.json").write_text(json.dumps(m, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    nsec_path = out / "hive.nsec"
    fd = os.open(nsec_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(nostr.nsec(secret) + "\n")
    try:
        os.chmod(nsec_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return m


def read_secret(path: Path) -> bytes:
    kind, data = nostr.decode_key(path.read_text(encoding="utf-8").strip())
    if kind == "npub":
        raise ValueError(f"{path} holds a public key; a secret (nsec or 64 hex) is needed")
    return data
