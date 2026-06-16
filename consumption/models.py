"""Stable read models for supplier workflow consumption."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from supplier_seed.domain.enums import (
    GovernanceEventType,
    LegalAcceptanceState,
    LifecycleStatus,
    ModerationStatus,
    SupplierMode,
    VerificationStatus,
    VerificationVisibility,
)


@dataclass(frozen=True, slots=True)
class SupplierSummaryView:
    supplier_id: str
    name: str
    mode: SupplierMode
    lifecycle_status: LifecycleStatus
    moderation_status: ModerationStatus
    legal_acceptance_state: LegalAcceptanceState
    verification_status: VerificationStatus
    verification_visibility: VerificationVisibility
    region_code: Optional[str]
    market_code: str
    assigned_verifier: Optional[str]
    seeded_source: Optional[str]
    updated_at: datetime
    primary_queue: str
    next_step: str


@dataclass(frozen=True, slots=True)
class SupplierWorkflowRequirementView:
    code: str
    label: str
    satisfied: bool
    blocking: bool
    message: str
    issue_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SupplierTimelineEntryView:
    event_id: str
    supplier_id: str
    occurred_at: datetime
    event_type: GovernanceEventType
    actor: Optional[str]
    source: Optional[str]
    summary: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SupplierWorkspaceView:
    summary: SupplierSummaryView
    requirements: tuple[SupplierWorkflowRequirementView, ...]
    timeline: tuple[SupplierTimelineEntryView, ...]
    activation_allowed: bool
    activation_issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SupplierProvenanceView:
    mode: SupplierMode
    origin_label: str
    seeded_source: Optional[str]
    seeded_source_reference: Optional[str]
    created_at: datetime
    created_by: Optional[str]
    last_updated_at: Optional[datetime]
    last_updated_by: Optional[str]


@dataclass(frozen=True, slots=True)
class SupplierModerationHistoryView:
    current_status: ModerationStatus
    lifecycle_status: LifecycleStatus
    last_reviewed_at: Optional[datetime]
    last_reviewed_by: Optional[str]
    events: tuple[SupplierTimelineEntryView, ...]


@dataclass(frozen=True, slots=True)
class SupplierVerificationOverviewView:
    current_status: VerificationStatus
    visibility: VerificationVisibility
    assigned_to: Optional[str]
    assigned_at: Optional[datetime]
    last_updated_at: Optional[datetime]
    last_updated_by: Optional[str]


@dataclass(frozen=True, slots=True)
class SupplierAuditSummaryView:
    total_events: int
    latest_event_type: Optional[GovernanceEventType]
    latest_occurred_at: Optional[datetime]
    blocked_action_count: int
    visible_actor_count: int


@dataclass(frozen=True, slots=True)
class SupplierDetailView:
    summary: SupplierSummaryView
    provenance: SupplierProvenanceView
    requirements: tuple[SupplierWorkflowRequirementView, ...]
    moderation: SupplierModerationHistoryView
    verification: SupplierVerificationOverviewView
    audit_summary: SupplierAuditSummaryView
    timeline: tuple[SupplierTimelineEntryView, ...]
    activation_allowed: bool
    activation_issue_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SupplierModerationQueueEntryView:
    summary: SupplierSummaryView
    queue_bucket: str
    moderation_status: ModerationStatus
    last_reviewed_at: Optional[datetime]
    last_reviewed_by: Optional[str]


@dataclass(frozen=True, slots=True)
class SupplierVerificationQueueEntryView:
    summary: SupplierSummaryView
    queue_bucket: str
    verification_status: VerificationStatus
    assigned_to: Optional[str]
    assigned_at: Optional[datetime]
    last_updated_at: Optional[datetime]



@dataclass(frozen=True, slots=True)
class PilotKpiView:
    ingestion_success_rate: float
    moderation_throughput: float
    rejection_rate: float
    verification_rate: float
    failure_rate: float
    enabled_supplier_count: int
    active_supplier_count: int


@dataclass(frozen=True, slots=True)
class PilotIncidentSummaryView:
    total_incidents: int
    critical_incidents: int
    latest_incident_at: Optional[datetime]


@dataclass(frozen=True, slots=True)
class PilotExpansionGateView:
    ready: bool
    blocking_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PilotReleaseSummaryView:
    pilot_name: Optional[str]
    market_code: str
    enabled_supplier_count: int
    eligible_supplier_count: int
    terms_accepted_count: int
    kpis: PilotKpiView
    incidents: PilotIncidentSummaryView
    expansion_gate: PilotExpansionGateView
    reversible: bool


@dataclass(frozen=True, slots=True)
class PilotRunbookStepView:
    sequence: int
    action_name: str
    label: str
    description: str


@dataclass(frozen=True, slots=True)
class PilotRunbookView:
    title: str
    support_flow: str
    rollback_action: str
    steps: tuple[PilotRunbookStepView, ...]
