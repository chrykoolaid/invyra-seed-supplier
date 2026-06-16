"""JSON file-backed repository adapter.

This adapter stays file-oriented on purpose. Part L hardened it with repository-level
atomicity, stale-state protection across repository instances, basic file locking, and
idempotent audit persistence without moving governance rules into storage.
Part O extends it with persisted idempotency receipts so replay-safe retries survive
process restarts and can be committed atomically beside supplier state and audit history.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable, Optional

from supplier_seed.domain.models import SupplierRecord
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.repository.serialization import (
    OperationReceipt,
    deserialize_snapshot,
    serialize_snapshot,
)


class JsonFileSupplierRepository:
    def __init__(self, path: str | Path, *, lock_timeout_seconds: float = 5.0, lock_retry_seconds: float = 0.05) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_timeout_seconds = lock_timeout_seconds
        self.lock_retry_seconds = lock_retry_seconds
        self._suppliers: dict[str, SupplierRecord] = {}
        self._events: list[GovernanceEventRecord] = []
        self._operation_receipts: dict[tuple[str, str], OperationReceipt] = {}
        self._revision = 0
        if self.path.exists():
            self._load_from_disk()

    def list_suppliers(self) -> Iterable[SupplierRecord]:
        self._refresh_from_disk_if_present()
        return tuple(self._suppliers.values())

    def get_supplier(self, supplier_id: str) -> Optional[SupplierRecord]:
        self._refresh_from_disk_if_present()
        return self._suppliers.get(supplier_id)

    def save_supplier(self, supplier: SupplierRecord) -> SupplierRecord:
        self._commit(supplier=supplier, events=(), event_supplier_id=None, receipt=None)
        return supplier

    def append_audit_events(self, events: Iterable[GovernanceEventRecord]) -> tuple[GovernanceEventRecord, ...]:
        return self.append_audit_events_with_receipt(events, receipt=None)

    def append_audit_events_with_receipt(
        self,
        events: Iterable[GovernanceEventRecord],
        *,
        receipt: Optional[OperationReceipt] = None,
    ) -> tuple[GovernanceEventRecord, ...]:
        stored_events = tuple(events)
        self._commit(supplier=None, events=stored_events, event_supplier_id=None, receipt=receipt)
        return self._resolve_persisted_events(stored_events)

    def list_audit_events(self, supplier_id: Optional[str] = None) -> Iterable[GovernanceEventRecord]:
        self._refresh_from_disk_if_present()
        if supplier_id is None:
            return tuple(self._events)
        return tuple(event for event in self._events if event.supplier_id == supplier_id)

    def get_operation_receipt(self, idempotency_key: str, *, action_name: str) -> Optional[OperationReceipt]:
        self._refresh_from_disk_if_present()
        return self._operation_receipts.get((action_name, idempotency_key))

    def save_operation_receipt(self, receipt: OperationReceipt) -> OperationReceipt:
        self._commit(supplier=None, events=(), event_supplier_id=None, receipt=receipt)
        return receipt

    def save_supplier_with_events(
        self,
        supplier: SupplierRecord,
        *,
        events: Iterable[GovernanceEventRecord] = (),
    ) -> SupplierRecord:
        return self.save_supplier_with_events_and_receipt(supplier, events=events, receipt=None)

    def save_supplier_with_events_and_receipt(
        self,
        supplier: SupplierRecord,
        *,
        events: Iterable[GovernanceEventRecord] = (),
        receipt: Optional[OperationReceipt] = None,
    ) -> SupplierRecord:
        stored_events = tuple(events)
        if any(event.supplier_id != supplier.identity.supplier_id for event in stored_events):
            raise ValueError("All audit events must belong to the supplier being saved.")

        self._commit(
            supplier=supplier,
            events=stored_events,
            event_supplier_id=supplier.identity.supplier_id,
            receipt=receipt,
        )
        return supplier

    def _refresh_from_disk_if_present(self) -> None:
        if self.path.exists():
            self._load_from_disk()

    def _load_from_disk(self) -> None:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        snapshot = deserialize_snapshot(payload)
        self._suppliers = {supplier.identity.supplier_id: supplier for supplier in snapshot.suppliers}
        self._events = list(snapshot.audit_events)
        self._operation_receipts = {
            (receipt.action_name, receipt.idempotency_key): receipt for receipt in snapshot.operation_receipts
        }
        self._revision = snapshot.revision

    def _commit(
        self,
        *,
        supplier: Optional[SupplierRecord],
        events: Iterable[GovernanceEventRecord],
        event_supplier_id: Optional[str],
        receipt: Optional[OperationReceipt],
    ) -> None:
        normalized_events = tuple(events)
        with self._repository_lock():
            current_suppliers, current_events, current_revision, current_receipts = self._read_current_state()
            if event_supplier_id is not None and any(event.supplier_id != event_supplier_id for event in normalized_events):
                raise ValueError("All audit events must belong to the supplier being saved.")

            merged_suppliers = dict(current_suppliers)
            supplier_changed = False
            if supplier is not None:
                supplier_id = supplier.identity.supplier_id
                existing_supplier = merged_suppliers.get(supplier_id)
                supplier_changed = existing_supplier != supplier
                merged_suppliers[supplier_id] = supplier

            merged_events, event_changed = self._merge_events(current_events, normalized_events)
            merged_receipts, receipt_changed = self._merge_receipts(current_receipts, receipt)
            changed = supplier_changed or event_changed or receipt_changed
            next_revision = current_revision + 1 if changed else current_revision

            if changed:
                self._write_snapshot(
                    suppliers=merged_suppliers,
                    events=merged_events,
                    revision=next_revision,
                    operation_receipts=merged_receipts,
                )
                self._fsync_directory()

            self._suppliers = merged_suppliers
            self._events = list(merged_events)
            self._operation_receipts = {
                (stored.action_name, stored.idempotency_key): stored for stored in merged_receipts
            }
            self._revision = next_revision

    def _read_current_state(
        self,
    ) -> tuple[dict[str, SupplierRecord], tuple[GovernanceEventRecord, ...], int, tuple[OperationReceipt, ...]]:
        if not self.path.exists():
            return {}, (), 0, ()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        snapshot = deserialize_snapshot(payload)
        suppliers = {supplier.identity.supplier_id: supplier for supplier in snapshot.suppliers}
        return suppliers, snapshot.audit_events, snapshot.revision, snapshot.operation_receipts

    @staticmethod
    def _merge_events(
        current_events: Iterable[GovernanceEventRecord],
        incoming_events: Iterable[GovernanceEventRecord],
    ) -> tuple[tuple[GovernanceEventRecord, ...], bool]:
        merged = list(current_events)
        existing_ids = {event.event_id for event in merged}
        changed = False
        for event in incoming_events:
            if event.event_id in existing_ids:
                continue
            merged.append(event)
            existing_ids.add(event.event_id)
            changed = True
        return tuple(merged), changed

    @staticmethod
    def _merge_receipts(
        current_receipts: Iterable[OperationReceipt],
        incoming_receipt: Optional[OperationReceipt],
    ) -> tuple[tuple[OperationReceipt, ...], bool]:
        merged = list(current_receipts)
        index = {(receipt.action_name, receipt.idempotency_key): idx for idx, receipt in enumerate(merged)}
        if incoming_receipt is None:
            return tuple(merged), False
        key = (incoming_receipt.action_name, incoming_receipt.idempotency_key)
        existing_idx = index.get(key)
        if existing_idx is None:
            merged.append(incoming_receipt)
            return tuple(merged), True
        if merged[existing_idx] == incoming_receipt:
            return tuple(merged), False
        merged[existing_idx] = incoming_receipt
        return tuple(merged), True

    def _resolve_persisted_events(self, requested_events: tuple[GovernanceEventRecord, ...]) -> tuple[GovernanceEventRecord, ...]:
        if not requested_events:
            return ()
        persisted_by_id = {event.event_id: event for event in self._events}
        return tuple(persisted_by_id.get(event.event_id, event) for event in requested_events)

    def _write_snapshot(
        self,
        *,
        suppliers: dict[str, SupplierRecord],
        events: Iterable[GovernanceEventRecord],
        revision: int,
        operation_receipts: Iterable[OperationReceipt],
    ) -> None:
        payload = serialize_snapshot(
            suppliers=suppliers.values(),
            audit_events=events,
            revision=revision,
            operation_receipts=operation_receipts,
        )
        temp_dir = self.path.parent if self.path.parent.exists() else None
        with NamedTemporaryFile("w", encoding="utf-8", dir=temp_dir, delete=False) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temp_name = handle.name
        self._replace_snapshot_file(Path(temp_name), self.path)

    @staticmethod
    def _replace_snapshot_file(temp_path: Path, destination_path: Path) -> None:
        temp_path.replace(destination_path)

    def _fsync_directory(self) -> None:
        if os.name == "nt":
            return
        directory_fd = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @contextmanager
    def _repository_lock(self):
        lock_fd = self._acquire_lock_file()
        try:
            yield
        finally:
            self._release_lock_file(lock_fd)

    def _acquire_lock_file(self) -> int:
        deadline = time.monotonic() + self.lock_timeout_seconds
        while True:
            try:
                return os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for repository lock: {self.lock_path}")
                time.sleep(self.lock_retry_seconds)

    def _release_lock_file(self, lock_fd: int) -> None:
        try:
            os.close(lock_fd)
        finally:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass
