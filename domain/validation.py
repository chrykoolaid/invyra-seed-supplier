"""Structured validation for supplier seed domain objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from supplier_seed.domain.enums import (
    LegalAcceptanceState,
    LifecycleStatus,
    ModerationStatus,
    PolicyOutcome,
    ValidationSeverity,
    VerificationStatus,
    VerificationVisibility,
)
from supplier_seed.domain.models import SupplierRecord
from supplier_seed.policy.rules import PolicyContext, PolicyResult, SupplierPolicyEngine


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    field: Optional[str]
    message: str
    severity: ValidationSeverity = ValidationSeverity.ERROR


@dataclass(frozen=True, slots=True)
class ValidationResult:
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def has_errors(self) -> bool:
        return any(issue.severity is ValidationSeverity.ERROR for issue in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(issue.severity is ValidationSeverity.WARNING for issue in self.issues)

    def extend(self, *issues: ValidationIssue) -> "ValidationResult":
        return ValidationResult(issues=self.issues + tuple(issues))


POLICY_SEVERITY_MAP = {
    PolicyOutcome.BLOCKED: ValidationSeverity.ERROR,
    PolicyOutcome.REQUIRES_REVIEW: ValidationSeverity.ERROR,
    PolicyOutcome.ALLOWED_WITH_WARNING: ValidationSeverity.WARNING,
    PolicyOutcome.ALLOWED: ValidationSeverity.INFO,
}


REVIEW_PENDING_MODERATION_STATES = {ModerationStatus.PENDING_REVIEW, ModerationStatus.ESCALATED}
POST_REVIEW_MODERATION_STATES = {ModerationStatus.APPROVED, ModerationStatus.REJECTED}


def validate_supplier(
    supplier: SupplierRecord,
    *,
    context: Optional[PolicyContext] = None,
    policy_engine: Optional[SupplierPolicyEngine] = None,
) -> ValidationResult:
    resolved_context = context or PolicyContext(region_code=supplier.region_context.region_code)
    engine = policy_engine or SupplierPolicyEngine()
    issues: list[ValidationIssue] = []

    if not supplier.identity.supplier_id:
        issues.append(
            ValidationIssue(
                code="supplier.identity.id_required",
                field="identity.supplier_id",
                message="Supplier identity must include a supplier_id.",
            )
        )

    if not supplier.name or not supplier.name.strip():
        issues.append(
            ValidationIssue(
                code="supplier.name.required",
                field="name",
                message="Supplier name is required.",
            )
        )

    if resolved_context.require_region_for_supplier and not supplier.region_context.region_code:
        issues.append(
            ValidationIssue(
                code="supplier.region.required",
                field="region_context.region_code",
                message="Supplier region is required by policy.",
            )
        )

    if supplier.is_manual and (supplier.seeded_source or supplier.seeded_source_reference):
        issues.append(
            ValidationIssue(
                code="supplier.mode.manual_seeded_contradiction",
                field="mode",
                message="Manual suppliers cannot carry seeded provenance fields.",
            )
        )

    if supplier.is_seeded and not supplier.has_seeded_provenance:
        issues.append(
            ValidationIssue(
                code="supplier.mode.seeded_provenance_missing",
                field="seeded_source_reference",
                message="Seeded suppliers require a source and source reference.",
            )
        )

    if supplier.is_manual and resolved_context.require_legal_acceptance_for_manual:
        if supplier.legal_acceptance_state is LegalAcceptanceState.NOT_REQUIRED:
            issues.append(
                ValidationIssue(
                    code="supplier.legal.manual_required",
                    field="legal_acceptance_state",
                    message="Manual suppliers cannot use NOT_REQUIRED when legal acceptance is required by policy.",
                )
            )

    if supplier.is_seeded and supplier.legal_acceptance_state is LegalAcceptanceState.REQUIRED_MISSING:
        issues.append(
            ValidationIssue(
                code="supplier.legal.seeded_required_missing_invalid",
                field="legal_acceptance_state",
                message="Seeded suppliers cannot use REQUIRED_MISSING because that state is reserved for manual legal acceptance flows.",
            )
        )

    if supplier.lifecycle_status is LifecycleStatus.PENDING_REVIEW and supplier.moderation_status not in REVIEW_PENDING_MODERATION_STATES:
        issues.append(
            ValidationIssue(
                code="supplier.state.pending_review_moderation_invalid",
                field="moderation_status",
                message="Pending review suppliers must carry pending review or escalated moderation status.",
            )
        )

    if supplier.moderation_status is ModerationStatus.ESCALATED and supplier.lifecycle_status is not LifecycleStatus.PENDING_REVIEW:
        issues.append(
            ValidationIssue(
                code="supplier.state.escalated_requires_pending_review",
                field="lifecycle_status",
                message="Escalated moderation is only valid while the supplier is in pending review.",
            )
        )

    if supplier.lifecycle_status in {LifecycleStatus.APPROVED, LifecycleStatus.ACTIVE} and supplier.moderation_status in {
        ModerationStatus.NOT_REVIEWED,
        ModerationStatus.PENDING_REVIEW,
        ModerationStatus.ESCALATED,
    }:
        issues.append(
            ValidationIssue(
                code="supplier.state.review_completion_missing",
                field="moderation_status",
                message="Approved or active suppliers must carry a completed moderation decision.",
            )
        )

    if supplier.lifecycle_status in {LifecycleStatus.APPROVED, LifecycleStatus.ACTIVE} and supplier.moderation_status is ModerationStatus.REJECTED:
        issues.append(
            ValidationIssue(
                code="supplier.state.moderation_rejected_conflict",
                field="moderation_status",
                message="Approved or active suppliers cannot have rejected moderation status.",
            )
        )

    if supplier.verification_assigned_to and supplier.verification_assigned_at is None:
        issues.append(
            ValidationIssue(
                code="supplier.verification.assignment.timestamp_missing",
                field="verification_assigned_at",
                message="Verification assignment requires an assignment timestamp.",
            )
        )

    if supplier.verification_assigned_at is not None and not supplier.verification_assigned_to:
        issues.append(
            ValidationIssue(
                code="supplier.verification.assignment.assignee_missing",
                field="verification_assigned_to",
                message="Verification assignment timestamp cannot exist without an assigned verifier.",
            )
        )

    if supplier.verification_visibility is VerificationVisibility.VISIBLE and supplier.verification_status is not VerificationStatus.VERIFIED:
        issues.append(
            ValidationIssue(
                code="supplier.verification.visibility.requires_verified_status",
                field="verification_visibility",
                message="Visible verification requires the supplier verification status to be VERIFIED.",
            )
        )

    if supplier.lifecycle_status is LifecycleStatus.ARCHIVED and supplier.verification_visibility is VerificationVisibility.VISIBLE:
        issues.append(
            ValidationIssue(
                code="supplier.verification.visibility.archived_visible_invalid",
                field="verification_visibility",
                message="Archived suppliers cannot remain verification-visible.",
            )
        )

    if supplier.lifecycle_status is LifecycleStatus.ACTIVE:
        if supplier.legal_acceptance_state in {LegalAcceptanceState.REQUIRED_MISSING, LegalAcceptanceState.WITHDRAWN, LegalAcceptanceState.SUPERSEDED}:
            issues.append(
                ValidationIssue(
                    code="supplier.state.active_legal_invalid",
                    field="legal_acceptance_state",
                    message="Active suppliers cannot have missing, withdrawn, or superseded legal acceptance when legal acceptance applies.",
                )
            )
        if resolved_context.require_moderation_for_seeded_activation and supplier.is_seeded and supplier.moderation_status is not ModerationStatus.APPROVED:
            issues.append(
                ValidationIssue(
                    code="supplier.state.active_seeded_moderation_invalid",
                    field="moderation_status",
                    message="Seeded active suppliers require approved moderation status.",
                )
            )
        if supplier.verification_status is VerificationStatus.FAILED:
            issues.append(
                ValidationIssue(
                    code="supplier.state.active_verification_failed",
                    field="verification_status",
                    message="Active suppliers cannot have failed verification.",
                )
            )

    activation_policy = engine.evaluate_activation(supplier=supplier, context=resolved_context)
    if supplier.lifecycle_status is LifecycleStatus.ACTIVE:
        issues.extend(_policy_result_to_issues(activation_policy, include_allowed=False))

    return ValidationResult(issues=tuple(issues))


def issues_from_policy_result(
    result: PolicyResult,
    *,
    include_allowed: bool = False,
) -> tuple[ValidationIssue, ...]:
    return tuple(_policy_result_to_issues(result, include_allowed=include_allowed))


def _policy_result_to_issues(result: PolicyResult, *, include_allowed: bool) -> Iterable[ValidationIssue]:
    for decision in result.decisions:
        severity = POLICY_SEVERITY_MAP[decision.outcome]
        if not include_allowed and severity is ValidationSeverity.INFO:
            continue
        yield ValidationIssue(
            code=decision.code,
            field=decision.field,
            message=decision.message,
            severity=severity,
        )
