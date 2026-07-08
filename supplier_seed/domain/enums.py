from enum import Enum

class StrEnum(str, Enum):
    def __str__(self):
        return self.value

class SupplierMode(StrEnum):
    MANUAL = "manual"
    SEEDED = "seeded"

class LifecycleStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    ACTIVE = "active"
    REJECTED = "rejected"
    ARCHIVED = "archived"

class ModerationStatus(StrEnum):
    NOT_REVIEWED = "not_reviewed"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"

class LegalAcceptanceState(StrEnum):
    NOT_REQUIRED = "not_required"
    NOT_ACCEPTED = "not_accepted"
    ACCEPTED = "accepted"
    WITHDRAWN = "withdrawn"
    SUPERSEDED = "superseded"

class VerificationStatus(StrEnum):
    NOT_VERIFIED = "not_verified"
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"

class VerificationVisibility(StrEnum):
    INTERNAL = "internal"
    PUBLIC = "public"
    HIDDEN = "hidden"
    VISIBLE = "visible"
    INTERNAL_ONLY = "internal_only"

class ValidationSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

class PolicyOutcome(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    REQUIRES_REVIEW = "requires_review"
    WARNING = "warning"

class SupplierAction(StrEnum):
    CREATE_MANUAL = "create_manual"
    CREATE_SEEDED = "create_seeded"
    ACTIVATE = "activate"
    APPROVE = "approve"
    REJECT = "reject"
    VERIFY = "verify"
    MODERATE = "moderate"

class GovernanceEventType(StrEnum):
    SUPPLIER_STAGED = "supplier_staged"
    LIFECYCLE_CHANGED = "lifecycle_changed"
    LIFECYCLE_STATUS_CHANGED = "lifecycle_status_changed"
    GOVERNANCE_ACTION_BLOCKED = "governance_action_blocked"
    PROVENANCE_SEEDED_CAPTURED = "provenance_seeded_captured"
    PROVENANCE_MANUAL_RECORDED = "provenance_manual_recorded"
    LEGAL_ACCEPTED = "legal_accepted"
    LEGAL_WITHDRAWN = "legal_withdrawn"
    LEGAL_SUPERSEDED = "legal_superseded"
    VERIFICATION_ASSIGNED = "verification_assigned"
    VERIFICATION_VERIFIED = "verification_verified"
    VERIFICATION_FAILED = "verification_failed"
    VERIFICATION_NEEDS_REVIEW = "verification_needs_review"
    VERIFICATION_VISIBILITY_CHANGED = "verification_visibility_changed"
    MODERATION_SUBMITTED = "moderation_submitted"
    MODERATION_APPROVED = "moderation_approved"
    MODERATION_REJECTED = "moderation_rejected"
    MODERATION_ESCALATED = "moderation_escalated"

class DedupeMatchClassification(StrEnum):
    NO_MATCH = "no_match"
    POSSIBLE_DUPLICATE = "possible_duplicate"
    LIKELY_DUPLICATE = "likely_duplicate"
    EXACT_DUPLICATE = "exact_duplicate"

class PilotIncidentSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
