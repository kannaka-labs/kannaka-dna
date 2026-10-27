"""kannaka-dna: Kannaka's genome, how to read it, express it, and reproduce from it."""
from .genome import Genome, Chromosome, Gene, to_fasta, from_fasta  # noqa: F401
from .reproduce import mitosis, mate, consent_record, ReproductionError  # noqa: F401
from .express import express, write_birth_kit  # noqa: F401

__version__ = "0.1.0"
