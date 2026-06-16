"""Strict enums for the supplier seed system domain."""

from __future__ import annotations

from enum import Enum


class StrictStrEnum(str, Enum):
    """String enum base with stable repr/serialization behavior."""

    def __str__(self) -> str:
        return self.value


class SupplierMode(StrictStrEnum):
    SEEDED = "seeded"
    MANUAL = "manual"


class LifecycleStatus(StrictStrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class VerificationStatus(StrictStrEnum):
    UNVERIFIED = "unverified"
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class VerificationVisibility(StrictStrEnum):
    HIDDEN = "hidden"
    INTERNAL_ONLY = "internal_only"
    VISIBLE = "visible"


class ModerationStatus(StrictStrEnum):
    NOT_REVIEWED = "not_reviewed"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"


class LegalAcceptanceState(StrictStrEnum):
    NOT_REQUIRED = "not_required"
    REQUIRED_MISSING = "required_missing"
    ACCEPTED = "accepted"
    WITHDRAWN = "withdrawn"
    SUPERSEDED = "superseded"


class PolicyOutcome(StrictStrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    ALLOWED_WITH_WARNING = "allowed_with_warning"
    REQUIRES_REVIEW = "requires_review"


class ValidationSeverity(StrictStrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class PilotIncidentSeverity(StrictStrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SupplierAction(StrictStrEnum):
    CREATE_MANUAL = "create_manual"
    CREATE_SEEDED = "create_seeded"
    SUBMIT_FOR_REVIEW = "submit_for_review"
    ACTIVATE = "activate"
    SUSPEND = "suspend"
    ARCHIVE = "archive"
    REJECT = "reject"


class GovernanceEventType(StrictStrEnum):
    SUPPLIER_STAGED = "supplier_staged"
    GOVERNANCE_ACTION_BLOCKED = "governance_action_blocked"
    LIFECYCLE_STATUS_CHANGED = "lifecycle_status_changed"
    PROVENANCE_MANUAL_RECORDED = "provenance_manual_recorded"
    PROVENANCE_SEEDED_CAPTURED = "provenance_seeded_captured"
    LEGAL_ACCEPTED = "legal_accepted"
    LEGAL_WITHDRAWN = "legal_withdrawn"
    LEGAL_SUPERSEDED = "legal_superseded"
    VERIFICATION_ASSIGNED = "verification_assigned"
    VERIFICATION_UNASSIGNED = "verification_unassigned"
    VERIFICATION_VISIBILITY_CHANGED = "verification_visibility_changed"
    VERIFICATION_PENDING = "verification_pending"
    VERIFICATION_VERIFIED = "verification_verified"
    VERIFICATION_FAILED = "verification_failed"
    VERIFICATION_NEEDS_REVIEW = "verification_needs_review"
    MODERATION_SUBMITTED = "moderation_submitted"
    MODERATION_APPROVED = "moderation_approved"
    MODERATION_REJECTED = "moderation_rejected"
    MODERATION_ESCALATED = "moderation_escalated"
    PILOT_TERMS_ACCEPTED = "pilot_terms_accepted"
    PILOT_ACCESS_ENABLED = "pilot_access_enabled"
    PILOT_ACCESS_DISABLED = "pilot_access_disabled"
    INCIDENT_LOGGED = "incident_logged"


class DedupeMatchClassification(StrictStrEnum):
    DISTINCT = "distinct"
    POSSIBLE_DUPLICATE = "possible_duplicate"
    LIKELY_DUPLICATE = "likely_duplicate"
    EXACT_DUPLICATE = "exact_duplicate"
