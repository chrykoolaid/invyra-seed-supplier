from dataclasses import dataclass
from typing import Tuple
from supplier_seed.domain.enums import ValidationSeverity, SupplierMode, LifecycleStatus, ModerationStatus

@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str = ""
    severity: ValidationSeverity = ValidationSeverity.ERROR

@dataclass(frozen=True)
class ValidationResult:
    issues: Tuple[ValidationIssue, ...] = ()
    @property
    def has_errors(self):
        return any(i.severity == ValidationSeverity.ERROR for i in self.issues)

def validate_supplier(supplier, context=None, policy_engine=None):
    issues = []
    if not supplier.name:
        issues.append(ValidationIssue("supplier.name.required"))
    if supplier.mode == SupplierMode.MANUAL and (supplier.seeded_source or supplier.seeded_source_reference):
        issues.append(ValidationIssue("supplier.mode.manual_seeded_contradiction"))
    if getattr(context, "require_region_for_supplier", False) and not supplier.region_context.region_code:
        issues.append(ValidationIssue("supplier.region.required"))
    if supplier.lifecycle_status == LifecycleStatus.PENDING_REVIEW and supplier.moderation_status not in (ModerationStatus.PENDING_REVIEW, ModerationStatus.ESCALATED):
        issues.append(ValidationIssue("supplier.state.pending_review_moderation_invalid"))
    return ValidationResult(tuple(issues))
