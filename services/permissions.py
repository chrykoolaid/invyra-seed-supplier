"""Service-layer authorization primitives for governed supplier actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from supplier_seed.domain.enums import GovernanceEventType, StrictStrEnum, ValidationSeverity
from supplier_seed.domain.models import SupplierRecord
from supplier_seed.domain.validation import ValidationIssue
from supplier_seed.events.audit import GovernanceEventRecord


class GovernanceRole(StrictStrEnum):
    ADMIN = "admin"
    MANAGER = "manager"
    MODERATOR = "moderator"
    STAFF = "staff"


class GovernancePermission(StrictStrEnum):
    CREATE_MANUAL_SUPPLIER = "create_manual_supplier"
    INGEST_SEEDED_SUPPLIER = "ingest_seeded_supplier"
    SUBMIT_FOR_REVIEW = "submit_for_review"
    APPROVE_MODERATION = "approve_moderation"
    REJECT_MODERATION = "reject_moderation"
    ESCALATE_MODERATION = "escalate_moderation"
    ACCEPT_LEGAL = "accept_legal"
    WITHDRAW_LEGAL = "withdraw_legal"
    SUPERSEDE_LEGAL = "supersede_legal"
    ASSIGN_VERIFICATION = "assign_verification"
    UNASSIGN_VERIFICATION = "unassign_verification"
    MARK_VERIFICATION_PENDING = "mark_verification_pending"
    MARK_VERIFIED = "mark_verified"
    MARK_VERIFICATION_FAILED = "mark_verification_failed"
    MARK_VERIFICATION_NEEDS_REVIEW = "mark_verification_needs_review"
    SET_VERIFICATION_VISIBILITY = "set_verification_visibility"
    ACTIVATE_SUPPLIER = "activate_supplier"
    ACCEPT_PILOT_TERMS = "accept_pilot_terms"
    ENABLE_PILOT_ACCESS = "enable_pilot_access"
    DISABLE_PILOT_ACCESS = "disable_pilot_access"
    RECORD_PILOT_INCIDENT = "record_pilot_incident"
    VIEW_PILOT_INTERNALS = "view_pilot_internals"
    VIEW_SENSITIVE_VERIFICATION_DETAILS = "view_sensitive_verification_details"
    VIEW_AUDIT_INTERNALS = "view_audit_internals"
    OVERRIDE_RULES = "override_rules"


@dataclass(frozen=True, slots=True)
class AccessContext:
    actor_id: Optional[str]
    role: GovernanceRole


@dataclass(frozen=True, slots=True)
class PermissionResult:
    allowed: bool
    permission: GovernancePermission
    access_context: Optional[AccessContext]
    issues: tuple[ValidationIssue, ...] = ()


PERMISSION_MATRIX: dict[GovernanceRole, frozenset[GovernancePermission]] = {
    GovernanceRole.ADMIN: frozenset(permission for permission in GovernancePermission),
    GovernanceRole.MANAGER: frozenset(
        {
            GovernancePermission.CREATE_MANUAL_SUPPLIER,
            GovernancePermission.INGEST_SEEDED_SUPPLIER,
            GovernancePermission.SUBMIT_FOR_REVIEW,
            GovernancePermission.APPROVE_MODERATION,
            GovernancePermission.REJECT_MODERATION,
            GovernancePermission.ESCALATE_MODERATION,
            GovernancePermission.ACCEPT_LEGAL,
            GovernancePermission.WITHDRAW_LEGAL,
            GovernancePermission.SUPERSEDE_LEGAL,
            GovernancePermission.ASSIGN_VERIFICATION,
            GovernancePermission.UNASSIGN_VERIFICATION,
            GovernancePermission.MARK_VERIFICATION_PENDING,
            GovernancePermission.MARK_VERIFIED,
            GovernancePermission.MARK_VERIFICATION_FAILED,
            GovernancePermission.MARK_VERIFICATION_NEEDS_REVIEW,
            GovernancePermission.SET_VERIFICATION_VISIBILITY,
            GovernancePermission.ACTIVATE_SUPPLIER,
            GovernancePermission.ACCEPT_PILOT_TERMS,
            GovernancePermission.ENABLE_PILOT_ACCESS,
            GovernancePermission.DISABLE_PILOT_ACCESS,
            GovernancePermission.RECORD_PILOT_INCIDENT,
            GovernancePermission.VIEW_PILOT_INTERNALS,
            GovernancePermission.VIEW_SENSITIVE_VERIFICATION_DETAILS,
            GovernancePermission.VIEW_AUDIT_INTERNALS,
        }
    ),
    GovernanceRole.MODERATOR: frozenset(
        {
            GovernancePermission.CREATE_MANUAL_SUPPLIER,
            GovernancePermission.SUBMIT_FOR_REVIEW,
            GovernancePermission.APPROVE_MODERATION,
            GovernancePermission.REJECT_MODERATION,
            GovernancePermission.ESCALATE_MODERATION,
            GovernancePermission.ASSIGN_VERIFICATION,
            GovernancePermission.UNASSIGN_VERIFICATION,
            GovernancePermission.MARK_VERIFICATION_PENDING,
            GovernancePermission.MARK_VERIFIED,
            GovernancePermission.MARK_VERIFICATION_FAILED,
            GovernancePermission.MARK_VERIFICATION_NEEDS_REVIEW,
            GovernancePermission.SET_VERIFICATION_VISIBILITY,
            GovernancePermission.RECORD_PILOT_INCIDENT,
            GovernancePermission.VIEW_SENSITIVE_VERIFICATION_DETAILS,
            GovernancePermission.VIEW_AUDIT_INTERNALS,
        }
    ),
    GovernanceRole.STAFF: frozenset(
        {
            GovernancePermission.CREATE_MANUAL_SUPPLIER,
            GovernancePermission.SUBMIT_FOR_REVIEW,
        }
    ),
}


def resolve_actor(actor: Optional[str], access_context: Optional[AccessContext]) -> Optional[str]:
    cleaned_actor = (actor or "").strip() or None
    if cleaned_actor is not None:
        return cleaned_actor
    if access_context is None:
        return None
    return (access_context.actor_id or "").strip() or None


class GovernanceAuthorizer:
    def authorize(
        self,
        permission: GovernancePermission,
        *,
        access_context: Optional[AccessContext],
    ) -> PermissionResult:
        if access_context is None:
            return PermissionResult(True, permission, access_context)
        allowed_permissions = PERMISSION_MATRIX.get(access_context.role, frozenset())
        if permission in allowed_permissions:
            return PermissionResult(True, permission, access_context)
        issue = ValidationIssue(
            code=f"permission.{permission.value}.denied",
            field="actor_role",
            message=(
                f"Role '{access_context.role.value}' is not permitted to perform '{permission.value}'."
            ),
            severity=ValidationSeverity.ERROR,
        )
        return PermissionResult(False, permission, access_context, issues=(issue,))

    def can(
        self,
        permission: GovernancePermission,
        *,
        access_context: Optional[AccessContext],
    ) -> bool:
        return self.authorize(permission, access_context=access_context).allowed

    @staticmethod
    def build_blocked_event(
        *,
        supplier: SupplierRecord,
        action_name: str,
        actor: Optional[str],
        issues: tuple[ValidationIssue, ...],
        source: str,
    ) -> GovernanceEventRecord:
        return GovernanceEventRecord.new(
            supplier_id=supplier.identity.supplier_id,
            event_type=GovernanceEventType.GOVERNANCE_ACTION_BLOCKED,
            occurred_at=None,
            actor=actor,
            source=source,
            summary=f"Governance action '{action_name}' was blocked.",
            metadata={
                "action": action_name,
                "issue_codes": [issue.code for issue in issues],
                "issue_count": len(issues),
            },
        )

