import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path

from supplier_seed.domain.enums import GovernanceEventType, LegalAcceptanceState, LifecycleStatus, ModerationStatus, SupplierMode, VerificationStatus, VerificationVisibility
from supplier_seed.domain.models import SupplierRecord, SupplierRegionContext
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.repository.memory_impl import InMemorySupplierRepository

class JsonFileSupplierRepository(InMemorySupplierRepository):
    def __init__(self, path=None):
        super().__init__()
        self.path = Path(path) if path is not None else None
        if self.path and self.path.exists():
            self._load()
        elif self.path:
            self._persist()

    def _enum_value(self, value):
        return value.value if hasattr(value, "value") else value

    def _supplier_to_dict(self, supplier):
        payload = asdict(supplier)
        payload["region_context"] = asdict(supplier.region_context)
        for key in ("mode", "lifecycle_status", "moderation_status", "legal_acceptance_state", "verification_status", "verification_visibility"):
            payload[key] = self._enum_value(payload[key])
        for key in ("created_at", "updated_at", "activated_at", "assigned_at", "last_reviewed_at"):
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
        region = SupplierRegionContext(**region_payload)
        data = dict(payload)
        data["region_context"] = region
        data["mode"] = SupplierMode(data["mode"])
        data["lifecycle_status"] = LifecycleStatus(data["lifecycle_status"])
        data["moderation_status"] = ModerationStatus(data["moderation_status"])
        data["legal_acceptance_state"] = LegalAcceptanceState(data["legal_acceptance_state"])
        data["verification_status"] = VerificationStatus(data["verification_status"])
        data["verification_visibility"] = VerificationVisibility(data["verification_visibility"])
        for key in ("created_at", "updated_at", "activated_at", "assigned_at", "last_reviewed_at"):
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
            "suppliers": [self._supplier_to_dict(supplier) for supplier in self.suppliers.values()],
            "audit_events": [self._event_to_dict(event) for event in self.audit_events],
        }

    def _persist(self):
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._payload(), indent=2), encoding="utf-8")

    def _load(self):
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.suppliers = {supplier.supplier_id: supplier for supplier in (self._supplier_from_dict(item) for item in payload.get("suppliers", []))}
        self.audit_events = [self._event_from_dict(item) for item in payload.get("audit_events", [])]

    def save(self, supplier):
        self.suppliers[supplier.supplier_id] = supplier
        self._persist()
        return supplier

    def append_events(self, events):
        self.audit_events.extend(events)
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
        self.audit_events.extend(events)
        self._persist()
        return supplier
