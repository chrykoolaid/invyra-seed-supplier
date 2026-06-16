"""Explicit, governed lifecycle transitions for supplier records."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Optional

from supplier_seed.domain.enums import LifecycleStatus, PolicyOutcome, ValidationSeverity
from supplier_seed.domain.models import SupplierRecord
from supplier_seed.domain.validation import ValidationIssue, issues_from_policy_result
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine


UTC = timezone.utc


ALLOWED_LIFECYCLE_TRANSITIONS: dict[LifecycleStatus, frozenset[LifecycleStatus]] = {
    LifecycleStatus.DRAFT: frozenset({LifecycleStatus.PENDING_REVIEW, LifecycleStatus.ARCHIVED}),
    LifecycleStatus.PENDING_REVIEW: frozenset({LifecycleStatus.APPROVED, LifecycleStatus.REJECTED, LifecycleStatus.ARCHIVED}),
    LifecycleStatus.APPROVED: frozenset({LifecycleStatus.ACTIVE, LifecycleStatus.ARCHIVED}),
    LifecycleStatus.REJECTED: frozenset({LifecycleStatus.PENDING_REVIEW, LifecycleStatus.ARCHIVED}),
    LifecycleStatus.ACTIVE: frozenset({LifecycleStatus.SUSPENDED, LifecycleStatus.ARCHIVED}),
    LifecycleStatus.SUSPENDED: frozenset({LifecycleStatus.ACTIVE, LifecycleStatus.ARCHIVED}),
    LifecycleStatus.ARCHIVED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class TransitionResult:
    allowed: bool
    supplier: SupplierRecord
    from_status: LifecycleStatus
    to_status: LifecycleStatus
    issues: tuple[ValidationIssue, ...] = ()
    events: tuple[GovernanceEventRecord, ...] = ()

    @property
    def has_events(self) -> bool:
        return bool(self.events)


def evaluate_lifecycle_transition(
    supplier: SupplierRecord,
    *,
    target_status: LifecycleStatus,
    context: Optional[PolicyContext] = None,
    policy_engine: Optional[SupplierPolicyEngine] = None,
) -> TransitionResult:
    issues: list[ValidationIssue] = []
    current_status = supplier.lifecycle_status
    resolved_context = context or PolicyContext(region_code=supplier.region_context.region_code)
    engine = policy_engine or SupplierPolicyEngine()

    if current_status is target_status:
        issues.append(
            ValidationIssue(
                code="transition.lifecycle.same_state",
                field="lifecycle_status",
                message=f"Supplier is already in lifecycle state {target_status.value}.",
            )
        )
        return TransitionResult(False, supplier, current_status, target_status, tuple(issues))

    if target_status not in ALLOWED_LIFECYCLE_TRANSITIONS[current_status]:
        issues.append(
            ValidationIssue(
                code="transition.lifecycle.path_blocked",
                field="lifecycle_status",
                message=(
                    f"Lifecycle transition from {current_status.value} to {target_status.value} is not allowed. "
                    "Use an explicit intermediate review path instead."
                ),
            )
        )

    if current_status is LifecycleStatus.ARCHIVED:
        issues.append(
            ValidationIssue(
                code="transition.lifecycle.archived_terminal",
                field="lifecycle_status",
                message="Archived suppliers are terminal and non-operational; they cannot transition to another lifecycle state.",
            )
        )

    if target_status is LifecycleStatus.ACTIVE:
        policy_result = engine.evaluate_activation(supplier=supplier, context=resolved_context)
        issues.extend(issues_from_policy_result(policy_result, include_allowed=False))
        if policy_result.outcome in {PolicyOutcome.BLOCKED, PolicyOutcome.REQUIRES_REVIEW}:
            return TransitionResult(False, supplier, current_status, target_status, tuple(issues))

    if issues:
        if any(issue.severity is ValidationSeverity.ERROR for issue in issues):
            return TransitionResult(False, supplier, current_status, target_status, tuple(issues))

    return TransitionResult(True, supplier, current_status, target_status, tuple(issues))


def apply_lifecycle_transition(
    supplier: SupplierRecord,
    *,
    target_status: LifecycleStatus,
    actor: Optional[str] = None,
    at: Optional[datetime] = None,
    context: Optional[PolicyContext] = None,
    policy_engine: Optional[SupplierPolicyEngine] = None,
) -> TransitionResult:
    evaluation = evaluate_lifecycle_transition(
        supplier,
        target_status=target_status,
        context=context,
        policy_engine=policy_engine,
    )
    if not evaluation.allowed:
        return evaluation

    timestamp = at or datetime.now(tz=UTC)
    updated_supplier = replace(
        supplier,
        lifecycle_status=target_status,
        updated_at=timestamp,
        updated_by=actor,
        activated_at=timestamp if target_status is LifecycleStatus.ACTIVE else supplier.activated_at,
        suspended_at=timestamp if target_status is LifecycleStatus.SUSPENDED else supplier.suspended_at,
        archived_at=timestamp if target_status is LifecycleStatus.ARCHIVED else supplier.archived_at,
        last_reviewed_at=(timestamp if target_status in {LifecycleStatus.APPROVED, LifecycleStatus.REJECTED, LifecycleStatus.PENDING_REVIEW} else supplier.last_reviewed_at),
        last_reviewed_by=(actor if target_status in {LifecycleStatus.APPROVED, LifecycleStatus.REJECTED, LifecycleStatus.PENDING_REVIEW} else supplier.last_reviewed_by),
    )
    return TransitionResult(True, updated_supplier, evaluation.from_status, target_status, evaluation.issues)
