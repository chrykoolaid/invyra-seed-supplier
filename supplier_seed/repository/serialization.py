from dataclasses import dataclass
from datetime import datetime

from supplier_seed.domain.enums import GovernanceEventType, LegalAcceptanceState, LifecycleStatus, ModerationStatus, SupplierMode, VerificationStatus, VerificationVisibility
from supplier_seed.domain.models import SupplierRecord, SupplierRegionContext
from supplier_seed.events.audit import GovernanceEventRecord

@dataclass(frozen=True)
class OperationReceipt:
    supplier_id: str
    event_count: int = 0
    accepted: bool = True

@dataclass(frozen=True)
class RepositorySnapshot:
    suppliers: tuple
    audit_events: tuple = ()
    revision: int = 0
    operation_receipts: tuple = ()
    schema_version: int = 1

def _parse_dt(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value

def _supplier_from_dict(payload):
    region_payload = payload.get("region_context", {})
    data = dict(payload)
    data["region_context"] = SupplierRegionContext(**region_payload)
    data["mode"] = SupplierMode(data["mode"])
    data["lifecycle_status"] = LifecycleStatus(data["lifecycle_status"])
    data["moderation_status"] = ModerationStatus(data["moderation_status"])
    data["legal_acceptance_state"] = LegalAcceptanceState(data["legal_acceptance_state"])
    data["verification_status"] = VerificationStatus(data["verification_status"])
    data["verification_visibility"] = VerificationVisibility(data["verification_visibility"])
    for key in ("created_at", "updated_at", "activated_at", "assigned_at", "last_reviewed_at"):
        data[key] = _parse_dt(data.get(key))
    return SupplierRecord(**data)

def _event_from_dict(payload):
    return GovernanceEventRecord(
        event_id=payload["event_id"],
        supplier_id=payload["supplier_id"],
        event_type=GovernanceEventType(payload["event_type"]),
        occurred_at=_parse_dt(payload.get("occurred_at")),
        actor=payload.get("actor"),
        source=payload.get("source"),
        summary=payload.get("summary", ""),
        metadata=payload.get("metadata", {}),
    )

def deserialize_snapshot(payload):
    schema_version = int(payload.get("schema_version", 1))
    revision = int(payload.get("snapshot_revision", 0)) if schema_version >= 4 else 0
    suppliers = tuple(_supplier_from_dict(item) for item in payload.get("suppliers", ()))
    audit_events = tuple(_event_from_dict(item) for item in payload.get("audit_events", ()))
    receipts = tuple(OperationReceipt(**item) for item in payload.get("operation_receipts", ()))
    return RepositorySnapshot(suppliers=suppliers, audit_events=audit_events, revision=revision, operation_receipts=receipts, schema_version=schema_version)
