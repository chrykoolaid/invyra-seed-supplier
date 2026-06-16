"""Moderation governance services.

This layer coordinates moderation-specific state with lifecycle transition rules
already defined in the domain layer.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from supplier_seed.domain.enums import GovernanceEventType, LifecycleStatus, ModerationStatus, ValidationSeverity
from supplier_seed.domain.models import SupplierRecord
from supplier_seed.domain.transitions import apply_lifecycle_transition
from supplier_seed.domain.validation import ValidationIssue, issues_from_policy_result
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine
from supplier_seed.services.permissions import (
    AccessContext,
    GovernanceAuthorizer,
    GovernancePermission,
    resolve_actor,
)
from supplier_seed.services.results import GovernanceServiceResult


UTC = timezone.utc
SOURCE = "services.moderation"


class ModerationService:
    def __init__(self, *, authorizer: Optional[GovernanceAuthorizer] = None) -> None:
        self.authorizer = authorizer or GovernanceAuthorizer()

    def submit_for_review(
        self,
        supplier: SupplierRecord,
        *,
        actor: Optional[str],
        at: Optional[datetime] = None,
        context: Optional[PolicyContext] = None,
        policy_engine: Optional[SupplierPolicyEngine] = None,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        effective_actor = resolve_actor(actor, access_context)
        permission_result = self.authorizer.authorize(
            GovernancePermission.SUBMIT_FOR_REVIEW,
            access_context=access_context,
        )
        if not permission_result.allowed:
            return GovernanceServiceResult(False, supplier, issues=permission_result.issues)
        resolved_context = context or PolicyContext(region_code=supplier.region_context.region_code)
        engine = policy_engine or SupplierPolicyEngine()
        policy_result = engine.evaluate_moderation_submission(
            supplier=supplier,
            actor=effective_actor,
            context=resolved_context,
        )
        policy_issues = issues_from_policy_result(policy_result, include_allowed=False)
        if not policy_result.is_allowed:
            return GovernanceServiceResult(False, supplier, issues=policy_issues)

        transition = apply_lifecycle_transition(
            replace(supplier, moderation_status=ModerationStatus.PENDING_REVIEW),
            target_status=LifecycleStatus.PENDING_REVIEW,
            actor=effective_actor,
            at=at,
            context=resolved_context,
            policy_engine=engine,
        )
        if not transition.allowed:
            return GovernanceServiceResult(False, supplier, issues=policy_issues + transition.issues)

        timestamp = at or datetime.now(tz=UTC)
        event = GovernanceEventRecord.new(
            supplier_id=supplier.identity.supplier_id,
            event_type=GovernanceEventType.MODERATION_SUBMITTED,
            occurred_at=timestamp,
            actor=effective_actor,
            source=SOURCE,
            summary="Supplier was submitted for moderation review.",
            metadata={
                "from_lifecycle_status": supplier.lifecycle_status.value,
                "to_lifecycle_status": transition.supplier.lifecycle_status.value,
                "from_moderation_status": supplier.moderation_status.value,
                "to_moderation_status": transition.supplier.moderation_status.value,
            },
        )
        return GovernanceServiceResult(True, transition.supplier, events=(event,), issues=policy_issues + transition.issues)

    def approve(
        self,
        supplier: SupplierRecord,
        *,
        actor: Optional[str],
        at: Optional[datetime] = None,
        context: Optional[PolicyContext] = None,
        policy_engine: Optional[SupplierPolicyEngine] = None,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        effective_actor = resolve_actor(actor, access_context)
        permission_result = self.authorizer.authorize(
            GovernancePermission.APPROVE_MODERATION,
            access_context=access_context,
        )
        if not permission_result.allowed:
            return GovernanceServiceResult(False, supplier, issues=permission_result.issues)
        resolved_context = context or PolicyContext(region_code=supplier.region_context.region_code)
        engine = policy_engine or SupplierPolicyEngine()
        policy_result = engine.evaluate_moderation_approval(
            supplier=supplier,
            actor=effective_actor,
            context=resolved_context,
        )
        policy_issues = issues_from_policy_result(policy_result, include_allowed=False)
        if not policy_result.is_allowed:
            return GovernanceServiceResult(False, supplier, issues=policy_issues)

        if supplier.moderation_status not in {ModerationStatus.PENDING_REVIEW, ModerationStatus.ESCALATED}:
            return GovernanceServiceResult(
                allowed=False,
                supplier=supplier,
                issues=policy_issues + (
                    ValidationIssue(
                        code="moderation.approve.pending_required",
                        field="moderation_status",
                        message="Moderation approval requires a pending review or escalated supplier.",
                        severity=ValidationSeverity.ERROR,
                    ),
                ),
            )

        transition = apply_lifecycle_transition(
            replace(supplier, moderation_status=ModerationStatus.APPROVED),
            target_status=LifecycleStatus.APPROVED,
            actor=effective_actor,
            at=at,
            context=resolved_context,
            policy_engine=engine,
        )
        if not transition.allowed:
            return GovernanceServiceResult(False, supplier, issues=policy_issues + transition.issues)

        timestamp = at or datetime.now(tz=UTC)
        event = GovernanceEventRecord.new(
            supplier_id=supplier.identity.supplier_id,
            event_type=GovernanceEventType.MODERATION_APPROVED,
            occurred_at=timestamp,
            actor=effective_actor,
            source=SOURCE,
            summary="Supplier moderation was approved.",
            metadata={
                "from_lifecycle_status": supplier.lifecycle_status.value,
                "to_lifecycle_status": transition.supplier.lifecycle_status.value,
                "from_moderation_status": supplier.moderation_status.value,
                "to_moderation_status": transition.supplier.moderation_status.value,
            },
        )
        return GovernanceServiceResult(True, transition.supplier, events=(event,), issues=policy_issues + transition.issues)

    def reject(
        self,
        supplier: SupplierRecord,
        *,
        actor: Optional[str],
        at: Optional[datetime] = None,
        reason: Optional[str] = None,
        context: Optional[PolicyContext] = None,
        policy_engine: Optional[SupplierPolicyEngine] = None,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        effective_actor = resolve_actor(actor, access_context)
        permission_result = self.authorizer.authorize(
            GovernancePermission.REJECT_MODERATION,
            access_context=access_context,
        )
        if not permission_result.allowed:
            return GovernanceServiceResult(False, supplier, issues=permission_result.issues)
        resolved_context = context or PolicyContext(region_code=supplier.region_context.region_code)
        engine = policy_engine or SupplierPolicyEngine()
        policy_result = engine.evaluate_moderation_rejection(
            supplier=supplier,
            actor=effective_actor,
            reason=reason,
            context=resolved_context,
        )
        policy_issues = issues_from_policy_result(policy_result, include_allowed=False)
        if not policy_result.is_allowed:
            return GovernanceServiceResult(False, supplier, issues=policy_issues)

        if supplier.moderation_status not in {ModerationStatus.PENDING_REVIEW, ModerationStatus.ESCALATED}:
            return GovernanceServiceResult(
                allowed=False,
                supplier=supplier,
                issues=policy_issues + (
                    ValidationIssue(
                        code="moderation.reject.pending_required",
                        field="moderation_status",
                        message="Moderation rejection requires a pending review or escalated supplier.",
                        severity=ValidationSeverity.ERROR,
                    ),
                ),
            )

        transition = apply_lifecycle_transition(
            replace(supplier, moderation_status=ModerationStatus.REJECTED),
            target_status=LifecycleStatus.REJECTED,
            actor=effective_actor,
            at=at,
            context=resolved_context,
            policy_engine=engine,
        )
        if not transition.allowed:
            return GovernanceServiceResult(False, supplier, issues=policy_issues + transition.issues)

        timestamp = at or datetime.now(tz=UTC)
        event = GovernanceEventRecord.new(
            supplier_id=supplier.identity.supplier_id,
            event_type=GovernanceEventType.MODERATION_REJECTED,
            occurred_at=timestamp,
            actor=effective_actor,
            source=SOURCE,
            summary="Supplier moderation was rejected.",
            metadata={
                "reason": reason.strip() if reason else None,
                "from_lifecycle_status": supplier.lifecycle_status.value,
                "to_lifecycle_status": transition.supplier.lifecycle_status.value,
                "from_moderation_status": supplier.moderation_status.value,
                "to_moderation_status": transition.supplier.moderation_status.value,
            },
        )
        return GovernanceServiceResult(True, transition.supplier, events=(event,), issues=policy_issues + transition.issues)

    def escalate(
        self,
        supplier: SupplierRecord,
        *,
        actor: Optional[str],
        at: Optional[datetime] = None,
        reason: Optional[str] = None,
        context: Optional[PolicyContext] = None,
        policy_engine: Optional[SupplierPolicyEngine] = None,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        effective_actor = resolve_actor(actor, access_context)
        permission_result = self.authorizer.authorize(
            GovernancePermission.ESCALATE_MODERATION,
            access_context=access_context,
        )
        if not permission_result.allowed:
            return GovernanceServiceResult(False, supplier, issues=permission_result.issues)
        resolved_context = context or PolicyContext(region_code=supplier.region_context.region_code)
        engine = policy_engine or SupplierPolicyEngine()
        policy_result = engine.evaluate_moderation_escalation(
            supplier=supplier,
            actor=effective_actor,
            reason=reason,
            context=resolved_context,
        )
        policy_issues = issues_from_policy_result(policy_result, include_allowed=False)
        if not policy_result.is_allowed:
            return GovernanceServiceResult(False, supplier, issues=policy_issues)

        if supplier.lifecycle_status is not LifecycleStatus.PENDING_REVIEW:
            return GovernanceServiceResult(
                allowed=False,
                supplier=supplier,
                issues=policy_issues + (
                    ValidationIssue(
                        code="moderation.escalate.pending_review_required",
                        field="lifecycle_status",
                        message="Moderation escalation requires the supplier to already be in pending review.",
                        severity=ValidationSeverity.ERROR,
                    ),
                ),
            )

        timestamp = at or datetime.now(tz=UTC)
        updated_supplier = supplier.with_governance_update(
            actor=effective_actor,
            at=timestamp,
            moderation_status=ModerationStatus.ESCALATED,
            last_reviewed_at=timestamp,
            last_reviewed_by=effective_actor,
        )
        metadata = {"reason": reason.strip()} if reason and reason.strip() else {}
        event = GovernanceEventRecord.new(
            supplier_id=supplier.identity.supplier_id,
            event_type=GovernanceEventType.MODERATION_ESCALATED,
            occurred_at=timestamp,
            actor=effective_actor,
            source=SOURCE,
            summary="Supplier moderation was escalated for review.",
            metadata={
                **metadata,
                "from_lifecycle_status": supplier.lifecycle_status.value,
                "to_lifecycle_status": updated_supplier.lifecycle_status.value,
                "from_moderation_status": supplier.moderation_status.value,
                "to_moderation_status": updated_supplier.moderation_status.value,
            },
        )
        return GovernanceServiceResult(True, updated_supplier, events=(event,), issues=policy_issues)
