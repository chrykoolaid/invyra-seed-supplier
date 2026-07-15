import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from supplier_seed.repository.json_file import JsonFileSupplierRepository


@dataclass(frozen=True)
class SnapshotIntegrityReport:
    valid: bool
    schema_version: int
    snapshot_revision: int
    supplier_count: int
    audit_event_count: int
    operation_receipt_count: int
    errors: Tuple[str, ...] = ()


def inspect_snapshot(path) -> SnapshotIntegrityReport:
    snapshot_path = Path(path)
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        repository = JsonFileSupplierRepository(snapshot_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return SnapshotIntegrityReport(False, 0, 0, 0, 0, 0, (f"snapshot.unreadable:{exc.__class__.__name__}",))

    errors = []
    supplier_ids = [supplier.supplier_id for supplier in repository.list_suppliers()]
    supplier_id_set = set(supplier_ids)
    event_ids = [event.event_id for event in repository.list_audit_events()]

    if len(supplier_ids) != len(supplier_id_set):
        errors.append("snapshot.duplicate_supplier_id")
    if len(event_ids) != len(set(event_ids)):
        errors.append("snapshot.duplicate_event_id")

    for event in repository.list_audit_events():
        if event.supplier_id not in supplier_id_set:
            errors.append("snapshot.orphan_audit_event")
            break

    receipt_keys = []
    for receipt in repository.operation_receipts:
        key = receipt.get("idempotency_key")
        receipt_keys.append(key)
        if receipt.get("supplier_id") not in supplier_id_set:
            errors.append("snapshot.orphan_operation_receipt")
        if any(event_id not in set(event_ids) for event_id in receipt.get("event_ids", ())):
            errors.append("snapshot.receipt_missing_event")
    if len(receipt_keys) != len(set(receipt_keys)):
        errors.append("snapshot.duplicate_idempotency_key")

    return SnapshotIntegrityReport(
        valid=not errors,
        schema_version=int(payload.get("schema_version", 0)),
        snapshot_revision=int(payload.get("snapshot_revision", 0)),
        supplier_count=len(supplier_ids),
        audit_event_count=len(event_ids),
        operation_receipt_count=len(repository.operation_receipts),
        errors=tuple(dict.fromkeys(errors)),
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_bytes(payload)
    os.replace(tmp_path, path)


def create_snapshot_backup(source_path, backup_path) -> SnapshotIntegrityReport:
    source = Path(source_path)
    backup = Path(backup_path)
    report = inspect_snapshot(source)
    if not report.valid:
        raise ValueError("Source snapshot failed integrity validation")

    repository = JsonFileSupplierRepository(source)
    with repository._lock_for_path(source):
        with repository._process_lock():
            payload = source.read_bytes()
            _atomic_write(backup, payload)

    backup_report = inspect_snapshot(backup)
    if not backup_report.valid:
        raise ValueError("Backup snapshot failed integrity validation")
    return backup_report


def restore_snapshot(backup_path, target_path) -> SnapshotIntegrityReport:
    backup = Path(backup_path)
    target = Path(target_path)
    backup_report = inspect_snapshot(backup)
    if not backup_report.valid:
        raise ValueError("Backup snapshot failed integrity validation")

    target_repository = JsonFileSupplierRepository(target) if target.exists() else JsonFileSupplierRepository()
    target_repository.path = target
    with target_repository._lock_for_path(target):
        with target_repository._process_lock():
            _atomic_write(target, backup.read_bytes())

    restored_report = inspect_snapshot(target)
    if not restored_report.valid:
        raise ValueError("Restored snapshot failed integrity validation")
    return restored_report
