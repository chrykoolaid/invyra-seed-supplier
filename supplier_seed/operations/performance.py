from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
import tracemalloc

from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.repository.json_file import JsonFileSupplierRepository


@dataclass(frozen=True)
class RepositoryPerformanceReport:
    supplier_count: int
    accepted_count: int
    persisted_supplier_count: int
    persisted_event_count: int
    ingest_seconds: float
    reload_seconds: float
    peak_memory_bytes: int
    snapshot_size_bytes: int


def measure_repository_workload(path, candidates, policy_context=None, policy_engine=None):
    """Run and measure one representative persisted ingestion workload."""
    snapshot_path = Path(path)
    candidate_batch = tuple(candidates)

    repository = JsonFileSupplierRepository(snapshot_path)
    engine = SupplierSeedEngine(repository=repository, policy_engine=policy_engine)

    tracemalloc.start()
    try:
        started = perf_counter()
        result = engine.ingest_batch(candidate_batch, context=policy_context)
        ingest_seconds = perf_counter() - started
        _, peak_memory_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    reload_started = perf_counter()
    reopened = JsonFileSupplierRepository(snapshot_path)
    persisted_suppliers = tuple(reopened.list_suppliers())
    persisted_events = tuple(reopened.list_audit_events())
    reload_seconds = perf_counter() - reload_started

    return RepositoryPerformanceReport(
        supplier_count=len(candidate_batch),
        accepted_count=sum(1 for item in result.results if item.accepted_for_staging),
        persisted_supplier_count=len(persisted_suppliers),
        persisted_event_count=len(persisted_events),
        ingest_seconds=ingest_seconds,
        reload_seconds=reload_seconds,
        peak_memory_bytes=peak_memory_bytes,
        snapshot_size_bytes=snapshot_path.stat().st_size,
    )
