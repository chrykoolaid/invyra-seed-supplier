"""Normalization and dedupe intelligence for supplier seed."""

from supplier_seed.intelligence.dedupe import (
    DedupeEvaluation,
    DuplicateSignal,
    SupplierDedupeEngine,
    SupplierMatchCandidate,
)
from supplier_seed.intelligence.normalization import NormalizedSupplierProfile, SupplierNormalizer

__all__ = [
    "DedupeEvaluation",
    "DuplicateSignal",
    "NormalizedSupplierProfile",
    "SupplierDedupeEngine",
    "SupplierMatchCandidate",
    "SupplierNormalizer",
]
