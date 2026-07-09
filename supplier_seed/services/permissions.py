from dataclasses import dataclass
from enum import Enum

class GovernanceRole(str, Enum):
    STAFF = "staff"
    MANAGER = "manager"
    MODERATOR = "moderator"
    ADMIN = "admin"
    VIEWER = "viewer"
    OPERATOR = "operator"
    REVIEWER = "reviewer"

class GovernancePermission(str, Enum):
    VIEW_SUPPLIER = "view_supplier"
    INGEST_MANUAL_SUPPLIER = "ingest_manual_supplier"
    INGEST_SEEDED_SUPPLIER = "ingest_seeded_supplier"
    ACCEPT_LEGAL = "accept_legal"
    SUBMIT_FOR_REVIEW = "submit_for_review"
    APPROVE_MODERATION = "approve_moderation"
    ACTIVATE_SUPPLIER = "activate_supplier"
    ASSIGN_VERIFICATION = "assign_verification"
    MARK_VERIFICATION_FAILED = "mark_verification_failed"
    ADMINISTER = "administer"

@dataclass(frozen=True)
class AccessContext:
    actor_id: str
    role: GovernanceRole

    @property
    def actor(self):
        return self.actor_id

@dataclass(frozen=True)
class PermissionResult:
    allowed: bool
    reason: str = ""

class GovernanceAuthorizer:
    grants = {
        GovernanceRole.STAFF: {
            GovernancePermission.VIEW_SUPPLIER,
            GovernancePermission.INGEST_MANUAL_SUPPLIER,
            GovernancePermission.SUBMIT_FOR_REVIEW,
        },
        GovernanceRole.MANAGER: {
            GovernancePermission.VIEW_SUPPLIER,
            GovernancePermission.INGEST_MANUAL_SUPPLIER,
            GovernancePermission.INGEST_SEEDED_SUPPLIER,
            GovernancePermission.ACCEPT_LEGAL,
            GovernancePermission.SUBMIT_FOR_REVIEW,
            GovernancePermission.ACTIVATE_SUPPLIER,
            GovernancePermission.ASSIGN_VERIFICATION,
        },
        GovernanceRole.MODERATOR: {
            GovernancePermission.VIEW_SUPPLIER,
            GovernancePermission.SUBMIT_FOR_REVIEW,
            GovernancePermission.APPROVE_MODERATION,
            GovernancePermission.MARK_VERIFICATION_FAILED,
        },
        GovernanceRole.ADMIN: set(GovernancePermission),
        GovernanceRole.VIEWER: {GovernancePermission.VIEW_SUPPLIER},
        GovernanceRole.OPERATOR: {
            GovernancePermission.VIEW_SUPPLIER,
            GovernancePermission.INGEST_MANUAL_SUPPLIER,
            GovernancePermission.SUBMIT_FOR_REVIEW,
        },
        GovernanceRole.REVIEWER: {
            GovernancePermission.VIEW_SUPPLIER,
            GovernancePermission.APPROVE_MODERATION,
            GovernancePermission.MARK_VERIFICATION_FAILED,
        },
    }

    def authorize(self, context, permission):
        if context is None:
            return PermissionResult(True, "allowed")
        role = GovernanceRole(context.role)
        permission = GovernancePermission(permission)
        allowed = permission in self.grants[role]
        return PermissionResult(allowed, "allowed" if allowed else f"permission.{permission.value}.denied")
