"""Repository interfaces and concrete persistence adapters."""

from supplier_seed.repository.interfaces import SupplierRepository
from supplier_seed.repository.json_file import JsonFileSupplierRepository
from supplier_seed.repository.memory_impl import InMemorySupplierRepository
from supplier_seed.repository.serialization import RepositorySnapshot

__all__ = [
    "InMemorySupplierRepository",
    "JsonFileSupplierRepository",
    "RepositorySnapshot",
    "SupplierRepository",
]
