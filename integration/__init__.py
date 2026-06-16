"""Integration adapters for ingestion sources.

These adapters are intentionally thin and convert external input shapes into engine-native
candidate inputs. They do not apply policy, validation, or governance decisions.
"""

from supplier_seed.integration.sources import (
    JsonFileSupplierCandidateSource,
    StaticSupplierCandidateSource,
    SupplierCandidateSource,
)

__all__ = [
    "JsonFileSupplierCandidateSource",
    "StaticSupplierCandidateSource",
    "SupplierCandidateSource",
]
