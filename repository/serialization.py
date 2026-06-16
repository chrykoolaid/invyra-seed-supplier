"""Serialization helpers for persistence adapters.

These helpers keep persistence formatting concerns out of the engine, services, and domain layers.
They provide a stable reference shape for file-backed adapters and future database adapters.
Part O extends the snapshot shape with persisted idempotency receipts so retry-safe mutation
replays can be enforced across process restarts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from supplier_seed.domain.enums import (
    GovernanceEventType,
    LegalAcceptanceState,
    LifecycleStatus,
    ModerationStatus,
    SupplierMode,
    VerificationStatus,
    VerificationVisibility,
)
from supplier_seed.domain.models import SupplierIdentity, SupplierRecord, SupplierRegionContext
from supplier_seed.events.audit import GovernanceEventRecord


UTC = timezone.utc
SNAPSHOT_SCHEMA_VERSION = 4
SUPPORTED_SNAPSHOT_SCHEMA_VERSIONS = frozenset({1, 2, 3, SNAPSHOT_SCHEMA_VERSION})


@dataclass(frozen=True, slots=True)
class OperationReceipt:
    idempotency_key: str
    action_name: str
    result_type: str
    created_at: datetime
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    suppliers: tuple[SupplierRecord, ...]
    audit_events: tuple[GovernanceEventRecord, ...]
    revision: int = 0
    operation_receipts: tuple[OperationReceipt, ...] = ()


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat()


def _deserialize_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Datetime fields must be ISO 8601 strings when present.")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def serialize_supplier(supplier: SupplierRecord) -> dict[str, Any]:
    return {
        "identity": {
            "supplier_id": supplier.identity.supplier_id,
            "supplier_code": supplier.identity.supplier_code,
            "external_reference": supplier.identity.external_reference,
        },
        "name": supplier.name,
        "mode": supplier.mode.value,
        "lifecycle_status": supplier.lifecycle_status.value,
        "verification_status": supplier.verification_status.value,
        "verification_visibility": supplier.verification_visibility.value,
        "moderation_status": supplier.moderation_status.value,
        "legal_acceptance_state": supplier.legal_acceptance_state.value,
        "region_context": {
            "region_code": supplier.region_context.region_code,
            "market_code": supplier.region_context.market_code,
            "pilot_name": supplier.region_context.pilot_name,
            "pilot_enabled": supplier.region_context.pilot_enabled,
        },
        "seeded_source": supplier.seeded_source,
        "seeded_source_reference": supplier.seeded_source_reference,
        "contact_email": supplier.contact_email,
        "contact_phone": supplier.contact_phone,
        "website_url": supplier.website_url,
        "tax_identifier": supplier.tax_identifier,
        "pilot_terms_accepted_version": supplier.pilot_terms_accepted_version,
        "pilot_terms_accepted_at": _serialize_datetime(supplier.pilot_terms_accepted_at),
        "pilot_terms_accepted_by": supplier.pilot_terms_accepted_by,
        "pilot_enabled_at": _serialize_datetime(supplier.pilot_enabled_at),
        "pilot_enabled_by": supplier.pilot_enabled_by,
        "pilot_disabled_at": _serialize_datetime(supplier.pilot_disabled_at),
        "pilot_disabled_by": supplier.pilot_disabled_by,
        "created_at": _serialize_datetime(supplier.created_at),
        "updated_at": _serialize_datetime(supplier.updated_at),
        "created_by": supplier.created_by,
        "updated_by": supplier.updated_by,
        "last_reviewed_at": _serialize_datetime(supplier.last_reviewed_at),
        "last_reviewed_by": supplier.last_reviewed_by,
        "activated_at": _serialize_datetime(supplier.activated_at),
        "suspended_at": _serialize_datetime(supplier.suspended_at),
        "archived_at": _serialize_datetime(supplier.archived_at),
        "provenance_last_updated_at": _serialize_datetime(supplier.provenance_last_updated_at),
        "provenance_last_updated_by": supplier.provenance_last_updated_by,
        "legal_acceptance_version": supplier.legal_acceptance_version,
        "legal_last_updated_at": _serialize_datetime(supplier.legal_last_updated_at),
        "legal_last_updated_by": supplier.legal_last_updated_by,
        "verification_assigned_to": supplier.verification_assigned_to,
        "verification_assigned_at": _serialize_datetime(supplier.verification_assigned_at),
        "verification_last_updated_at": _serialize_datetime(supplier.verification_last_updated_at),
        "verification_last_updated_by": supplier.verification_last_updated_by,
        "verification_visibility_last_updated_at": _serialize_datetime(supplier.verification_visibility_last_updated_at),
        "verification_visibility_last_updated_by": supplier.verification_visibility_last_updated_by,
    }


def deserialize_supplier(payload: dict[str, Any]) -> SupplierRecord:
    identity_payload = payload["identity"]
    region_payload = payload.get("region_context") or {}
    return SupplierRecord(
        identity=SupplierIdentity(
            supplier_id=identity_payload["supplier_id"],
            supplier_code=identity_payload.get("supplier_code"),
            external_reference=identity_payload.get("external_reference"),
        ),
        name=payload["name"],
        mode=SupplierMode(payload["mode"]),
        lifecycle_status=LifecycleStatus(payload["lifecycle_status"]),
        verification_status=VerificationStatus(payload["verification_status"]),
        verification_visibility=VerificationVisibility(
            payload.get("verification_visibility", VerificationVisibility.HIDDEN.value)
        ),
        moderation_status=ModerationStatus(payload["moderation_status"]),
        legal_acceptance_state=LegalAcceptanceState(payload["legal_acceptance_state"]),
        region_context=SupplierRegionContext(
            region_code=region_payload.get("region_code"),
            market_code=region_payload.get("market_code", "PH"),
            pilot_name=region_payload.get("pilot_name"),
            pilot_enabled=bool(region_payload.get("pilot_enabled", False)),
        ),
        seeded_source=payload.get("seeded_source"),
        seeded_source_reference=payload.get("seeded_source_reference"),
        contact_email=payload.get("contact_email"),
        contact_phone=payload.get("contact_phone"),
        website_url=payload.get("website_url"),
        tax_identifier=payload.get("tax_identifier"),
        pilot_terms_accepted_version=payload.get("pilot_terms_accepted_version"),
        pilot_terms_accepted_at=_deserialize_datetime(payload.get("pilot_terms_accepted_at")),
        pilot_terms_accepted_by=payload.get("pilot_terms_accepted_by"),
        pilot_enabled_at=_deserialize_datetime(payload.get("pilot_enabled_at")),
        pilot_enabled_by=payload.get("pilot_enabled_by"),
        pilot_disabled_at=_deserialize_datetime(payload.get("pilot_disabled_at")),
        pilot_disabled_by=payload.get("pilot_disabled_by"),
        created_at=_deserialize_datetime(payload.get("created_at")),
        updated_at=_deserialize_datetime(payload.get("updated_at")),
        created_by=payload.get("created_by"),
        updated_by=payload.get("updated_by"),
        last_reviewed_at=_deserialize_datetime(payload.get("last_reviewed_at")),
        last_reviewed_by=payload.get("last_reviewed_by"),
        activated_at=_deserialize_datetime(payload.get("activated_at")),
        suspended_at=_deserialize_datetime(payload.get("suspended_at")),
        archived_at=_deserialize_datetime(payload.get("archived_at")),
        provenance_last_updated_at=_deserialize_datetime(payload.get("provenance_last_updated_at")),
        provenance_last_updated_by=payload.get("provenance_last_updated_by"),
        legal_acceptance_version=payload.get("legal_acceptance_version"),
        legal_last_updated_at=_deserialize_datetime(payload.get("legal_last_updated_at")),
        legal_last_updated_by=payload.get("legal_last_updated_by"),
        verification_assigned_to=payload.get("verification_assigned_to"),
        verification_assigned_at=_deserialize_datetime(payload.get("verification_assigned_at")),
        verification_last_updated_at=_deserialize_datetime(payload.get("verification_last_updated_at")),
        verification_last_updated_by=payload.get("verification_last_updated_by"),
        verification_visibility_last_updated_at=_deserialize_datetime(
            payload.get("verification_visibility_last_updated_at")
        ),
        verification_visibility_last_updated_by=payload.get("verification_visibility_last_updated_by"),
    )


def _normalize_metadata(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Event metadata must be a dictionary.")
    return dict(value)


def serialize_event(event: GovernanceEventRecord) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "supplier_id": event.supplier_id,
        "event_type": event.event_type.value,
        "occurred_at": _serialize_datetime(event.occurred_at),
        "actor": event.actor,
        "source": event.source,
        "summary": event.summary,
        "metadata": dict(event.metadata),
    }


def deserialize_event(payload: dict[str, Any]) -> GovernanceEventRecord:
    return GovernanceEventRecord(
        event_id=payload["event_id"],
        supplier_id=payload["supplier_id"],
        event_type=GovernanceEventType(payload["event_type"]),
        occurred_at=_deserialize_datetime(payload.get("occurred_at")),
        actor=payload.get("actor"),
        source=payload.get("source"),
        summary=payload["summary"],
        metadata=_normalize_metadata(payload.get("metadata")),
    )


def serialize_operation_receipt(receipt: OperationReceipt) -> dict[str, Any]:
    return {
        "idempotency_key": receipt.idempotency_key,
        "action_name": receipt.action_name,
        "result_type": receipt.result_type,
        "created_at": _serialize_datetime(receipt.created_at),
        "payload": dict(receipt.payload),
    }


def deserialize_operation_receipt(payload: dict[str, Any]) -> OperationReceipt:
    return OperationReceipt(
        idempotency_key=payload["idempotency_key"],
        action_name=payload["action_name"],
        result_type=payload["result_type"],
        created_at=_deserialize_datetime(payload.get("created_at")) or datetime.now(tz=UTC),
        payload=_normalize_metadata(payload.get("payload")),
    )


def serialize_snapshot(
    *,
    suppliers: Iterable[SupplierRecord],
    audit_events: Iterable[GovernanceEventRecord],
    revision: int = 0,
    operation_receipts: Iterable[OperationReceipt] = (),
) -> dict[str, Any]:
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "snapshot_revision": revision,
        "suppliers": [serialize_supplier(supplier) for supplier in suppliers],
        "audit_events": [serialize_event(event) for event in audit_events],
        "operation_receipts": [serialize_operation_receipt(receipt) for receipt in operation_receipts],
    }


def deserialize_snapshot(payload: dict[str, Any]) -> RepositorySnapshot:
    if not isinstance(payload, dict):
        raise ValueError("Repository snapshot payload must be a dictionary.")
    schema_version = payload.get("schema_version", 1)
    if schema_version not in SUPPORTED_SNAPSHOT_SCHEMA_VERSIONS:
        raise ValueError(f"Unsupported repository snapshot schema version: {schema_version!r}.")

    suppliers_payload = payload.get("suppliers") or []
    events_payload = payload.get("audit_events") or []
    receipts_payload = payload.get("operation_receipts") or []
    if not isinstance(suppliers_payload, list):
        raise ValueError("Repository snapshot 'suppliers' must be a list.")
    if not isinstance(events_payload, list):
        raise ValueError("Repository snapshot 'audit_events' must be a list.")
    if not isinstance(receipts_payload, list):
        raise ValueError("Repository snapshot 'operation_receipts' must be a list.")

    revision = payload.get("snapshot_revision", 0)
    if not isinstance(revision, int) or revision < 0:
        raise ValueError("Repository snapshot 'snapshot_revision' must be a non-negative integer.")

    suppliers = tuple(deserialize_supplier(item) for item in suppliers_payload)
    audit_events = tuple(deserialize_event(item) for item in events_payload)
    operation_receipts = tuple(deserialize_operation_receipt(item) for item in receipts_payload)
    return RepositorySnapshot(
        suppliers=suppliers,
        audit_events=audit_events,
        revision=revision,
        operation_receipts=operation_receipts,
    )
