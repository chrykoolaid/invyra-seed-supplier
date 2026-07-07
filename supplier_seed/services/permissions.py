from dataclasses import dataclass
from enum import Enum

class GovernanceRole(str, Enum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    REVIEWER = "reviewer"
    ADMIN = "admin"

class GovernancePermission(str, Enum):
    VIEW_SUPPLIER = "view_supplier"
    INGEST_SUPPLIER = "ingest_supplier"
    MODERATE_SUPPLIER = "moderate_supplier"
    VERIFY_SUPPLIER = "verify_supplier"
    ADMINISTER = "administer"

@dataclass(frozen=True)
class AccessContext:
    actor: str
    role: GovernanceRole

@dataclass(frozen=True)
class PermissionResult:
    allowed: bool
    reason: str = ""

class GovernanceAuthorizer:
    grants = {
        GovernanceRole.VIEWER: {GovernancePermission.VIEW_SUPPLIER},
        GovernanceRole.OPERATOR: {GovernancePermission.VIEW_SUPPLIER, GovernancePermission.INGEST_SUPPLIER},
        GovernanceRole.REVIEWER: {GovernancePermission.VIEW_SUPPLIER, GovernancePermission.MODERATE_SUPPLIER, GovernancePermission.VERIFY_SUPPLIER},
        GovernanceRole.ADMIN: set(GovernancePermission),
    }
    def authorize(self, context, permission):
        role = GovernanceRole(context.role)
        permission = GovernancePermission(permission)
        return PermissionResult(permission in self.grants[role], "allowed" if permission in self.grants[role] else "permission_denied")
