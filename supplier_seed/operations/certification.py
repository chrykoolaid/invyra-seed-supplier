from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from supplier_seed.operations.performance import RepositoryPerformanceReport, measure_repository_workload
from supplier_seed.repository.recovery import create_snapshot_backup, inspect_snapshot, restore_snapshot


@dataclass(frozen=True)
class CertificationGate:
    code: str
    passed: bool
    observed: object = None
    limit: object = None


@dataclass(frozen=True)
class ProductionHardeningCertification:
    certified: bool
    performance: RepositoryPerformanceReport
    gates: Tuple[CertificationGate, ...]


def certify_production_hardening(
    path,
    candidates,
    policy_context=None,
    policy_engine=None,
    *,
    max_ingest_seconds=15.0,
    max_reload_seconds=3.0,
    max_peak_memory_bytes=128 * 1024 * 1024,
):
    """Run the executable Phase R production-hardening certification gate."""
    snapshot_path = Path(path)
    backup_path = snapshot_path.with_suffix(snapshot_path.suffix + ".certification-backup")
    restore_path = snapshot_path.with_suffix(snapshot_path.suffix + ".certification-restore")

    performance = measure_repository_workload(
        snapshot_path,
        candidates,
        policy_context=policy_context,
        policy_engine=policy_engine,
    )
    integrity = inspect_snapshot(snapshot_path)

    recovery_ok = False
    if integrity.valid:
        backup_report = create_snapshot_backup(snapshot_path, backup_path)
        restored_report = restore_snapshot(backup_path, restore_path)
        recovery_ok = (
            backup_report.valid
            and restored_report.valid
            and backup_report.snapshot_revision == restored_report.snapshot_revision
            and backup_report.supplier_count == restored_report.supplier_count
            and backup_report.audit_event_count == restored_report.audit_event_count
            and backup_report.operation_receipt_count == restored_report.operation_receipt_count
        )

    expected_count = performance.supplier_count
    gates = (
        CertificationGate("integrity.valid", integrity.valid, integrity.errors, ()),
        CertificationGate("records.accepted", performance.accepted_count == expected_count, performance.accepted_count, expected_count),
        CertificationGate("records.suppliers_persisted", performance.persisted_supplier_count == expected_count, performance.persisted_supplier_count, expected_count),
        CertificationGate("records.events_persisted", performance.persisted_event_count == expected_count, performance.persisted_event_count, expected_count),
        CertificationGate("performance.ingest", performance.ingest_seconds <= max_ingest_seconds, performance.ingest_seconds, max_ingest_seconds),
        CertificationGate("performance.reload", performance.reload_seconds <= max_reload_seconds, performance.reload_seconds, max_reload_seconds),
        CertificationGate("performance.memory", performance.peak_memory_bytes <= max_peak_memory_bytes, performance.peak_memory_bytes, max_peak_memory_bytes),
        CertificationGate("recovery.round_trip", recovery_ok, recovery_ok, True),
    )
    return ProductionHardeningCertification(
        certified=all(gate.passed for gate in gates),
        performance=performance,
        gates=gates,
    )
