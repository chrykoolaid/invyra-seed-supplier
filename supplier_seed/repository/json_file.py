import json
import os
import threading
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from supplier_seed.domain.enums import GovernanceEventType, LegalAcceptanceState, LifecycleStatus, ModerationStatus, SupplierMode, VerificationStatus, VerificationVisibility
from supplier_seed.domain.models import SupplierRecord, SupplierRegionContext
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.repository.memory_impl import InMemorySupplierRepository


class JsonFileSupplierRepository(InMemorySupplierRepository):
    SCHEMA_VERSION = 4
    _path_locks = {}
    _path_locks_guard = threading.Lock()

    @classmethod
    def _lock_for_path(cls, path):
        resolved = str(Path(path).resolve())
        with cls._path_locks_guard:
            lock = cls._path_locks.get(resolved)
            if lock is None:
                lock = threading.RLock()
                cls._path_locks[resolved] = lock
            return lock

    def __init__(self, path=None):
        super().__init__()
        self.path = Path(path) if path is not None else None
        self._write_lock = self._lock_for_path(self.path) if self.path else threading.RLock()
        self.snapshot_revision = 0
        self.operation_receipts = []
        if self.path and self.path.exists():
            self._load()
        elif self.path:
            self._persist(increment_revision=False, merge_disk=False)

    def _enum_value(self, value):
        return value.value if hasattr(value, "value") else value

    def _supplier_to_dict(self, supplier):
        payload = asdict(supplier)
        payload["region_context"] = asdict(supplier.region_context)
        for key in ("mode", "lifecycle_status", "moderation_status", "legal_acceptance_state", "verification_status", "verification_visibility"):
            payload[key] = self._enum_value(payload[key])
        for key in ("created_at", "updated_at", "activated_at", "assigned_at", "last_reviewed_at", "pilot_terms_accepted_at"):
            if payload.get(key) is not None:
                payload[key] = payload[key].isoformat() if hasattr(payload[key], "isoformat") else payload[key]
        return payload

    def _event_to_dict(self, event):
        return {
            "event_id": event.event_id,
            "supplier_id": event.supplier_id,
            "event_type": self._enum_value(event.event_type),
            "occurred_at": event.occurred_at.isoformat() if hasattr(event.occurred_at, "isoformat") else event.occurred_at,
            "actor": event.actor,
            "source": event.source,
            "summary": event.summary,
            "metadata": event.metadata,
        }

    def _parse_datetime(self, value):
        return datetime.fromisoformat(value) if isinstance(value, str) else value

    def _supplier_from_dict(self, payload):
        region_payload = payload.get("region_context", {})
        data = dict(payload)
        data["region_context"] = SupplierRegionContext(**region_payload)
        data["mode"] = SupplierMode(data["mode"])
        data["lifecycle_status"] = LifecycleStatus(data["lifecycle_status"])
        data["moderation_status"] = ModerationStatus(data["moderation_status"])
        data["legal_acceptance_state"] = LegalAcceptanceState(data["legal_acceptance_state"])
        data["verification_status"] = VerificationStatus(data["verification_status"])
        data["verification_visibility"] = VerificationVisibility(data["verification_visibility"])
        for key in ("created_at", "updated_at", "activated_at", "assigned_at", "last_reviewed_at", "pilot_terms_accepted_at"):
            data[key] = self._parse_datetime(data.get(key))
        return SupplierRecord(**data)

    def _event_from_dict(self, payload):
        return GovernanceEventRecord(
            event_id=payload["event_id"],
            supplier_id=payload["supplier_id"],
            event_type=GovernanceEventType(payload["event_type"]),
            occurred_at=self._parse_datetime(payload.get("occurred_at")),
            actor=payload.get("actor"),
            source=payload.get("source"),
            summary=payload.get("summary", ""),
            metadata=payload.get("metadata", {}),
        )

    def _payload(self):
        return {
            "schema_version": self.SCHEMA_VERSION,
            "snapshot_revision": self.snapshot_revision,
            "operation_receipts": self.operation_receipts,
            "suppliers": [self._supplier_to_dict(supplier) for supplier in self.suppliers.values()],
            "audit_events": [self._event_to_dict(event) for event in self.audit_events],
        }

    def _load(self):
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.snapshot_revision = int(payload.get("snapshot_revision", 0))
        self.operation_receipts = list(payload.get("operation_receipts", []))
        self.suppliers = {supplier.supplier_id: supplier for supplier in (self._supplier_from_dict(item) for item in payload.get("suppliers", []))}
        self.audit_events = [self._event_from_dict(item) for item in payload.get("audit_events", [])]

    def _merge_disk_state(self):
        if not self.path or not self.path.exists():
            return
        disk = JsonFileSupplierRepository(self.path)
        self.suppliers = {**disk.suppliers, **self.suppliers}
        existing_event_ids = {event.event_id for event in disk.audit_events}
        merged_events = list(disk.audit_events)
        for event in self.audit_events:
            if event.event_id not in existing_event_ids:
                merged_events.append(event)
                existing_event_ids.add(event.event_id)
        self.audit_events = merged_events
        existing_keys = {receipt.get("idempotency_key") for receipt in disk.operation_receipts}
        merged_receipts = list(disk.operation_receipts)
        for receipt in self.operation_receipts:
            if receipt.get("idempotency_key") not in existing_keys:
                merged_receipts.append(receipt)
                existing_keys.add(receipt.get("idempotency_key"))
        self.operation_receipts = merged_receipts
        self.snapshot_revision = max(self.snapshot_revision, disk.snapshot_revision)

    def _replace_snapshot_file(self, payload_text):
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(payload_text, encoding="utf-8")
        os.replace(tmp_path, self.path)

    def _persist(self, increment_revision=True, merge_disk=True):
        if not self.path:
            return
        with self._write_lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if merge_disk:
                self._merge_disk_state()
            if increment_revision:
                self.snapshot_revision += 1
            self._replace_snapshot_file(json.dumps(self._payload(), indent=2))

    def find_operation_receipt(self, idempotency_key):
        if not idempotency_key:
            return None
        if self.path and self.path.exists():
            self._load()
        return next((receipt for receipt in self.operation_receipts if receipt.get("idempotency_key") == idempotency_key), None)

    def record_operation_receipt(self, idempotency_key, supplier_id, event_ids, action):
        if not idempotency_key:
            return None
        existing = self.find_operation_receipt(idempotency_key)
        if existing:
            return existing
        receipt = {"idempotency_key": idempotency_key, "supplier_id": supplier_id, "event_ids": list(event_ids), "action": action}
        self.operation_receipts.append(receipt)
        self._persist()
        return receipt

    def events_by_ids(self, event_ids):
        by_id = {event.event_id: event for event in self.audit_events}
        return tuple(by_id[event_id] for event_id in event_ids if event_id in by_id)

    def save(self, supplier):
        self.suppliers[supplier.supplier_id] = supplier
        self._persist(increment_revision=False)
        return supplier

    def append_events(self, events):
        existing_ids = {event.event_id for event in self.audit_events}
        for event in events:
            if event.event_id not in existing_ids:
                self.audit_events.append(event)
                existing_ids.add(event.event_id)
        self._persist()
        return tuple(events)

    def get_supplier(self, supplier_id):
        return self.get(supplier_id)

    def list_suppliers(self):
        return self.list()

    def list_audit_events(self, supplier_id=None):
        return self.list_events(supplier_id)

    def save_supplier_with_events(self, supplier, events=()):
        for event in events:
            if event.supplier_id != supplier.supplier_id:
                raise ValueError("Audit event supplier_id must match saved supplier")
        self.suppliers[supplier.supplier_id] = supplier
        existing_ids = {event.event_id for event in self.audit_events}
        for event in events:
            if event.event_id not in existing_ids:
                self.audit_events.append(event)
                existing_ids.add(event.event_id)
        self._persist()
        return supplier
