from dataclasses import dataclass

@dataclass(frozen=True)
class QueueEntry:
    summary: object
    queue_bucket: str
    assigned_to: object = None
    verification_status: object = None

@dataclass(frozen=True)
class ProvenanceView:
    origin_label: str
    seeded_source: object = None
    seeded_source_reference: object = None

@dataclass(frozen=True)
class StatusHistoryView:
    current_status: object
    events: tuple = ()

@dataclass(frozen=True)
class VerificationView:
    current_status: object
    assigned_to: object = None
    events: tuple = ()

@dataclass(frozen=True)
class AuditSummary:
    total_events: int
    latest_event_type: object = None

@dataclass(frozen=True)
class SupplierDetail:
    summary: object
    provenance: ProvenanceView
    moderation: StatusHistoryView
    verification: VerificationView
    audit_summary: AuditSummary
    timeline: tuple
