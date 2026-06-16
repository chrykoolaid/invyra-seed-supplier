"""Verification governance services."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from supplier_seed.domain.enums import (
    GovernanceEventType,
    LifecycleStatus,
    ValidationSeverity,
    VerificationStatus,
    VerificationVisibility,
)
from supplier_seed.domain.models import SupplierRecord
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
SOURCE = "services.verification"


def _clean_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class VerificationService:
    def __init__(self, *, authorizer: Optional[GovernanceAuthorizer] = None) -> None:
        self.authorizer = authorizer or GovernanceAuthorizer()

    def assign(
        self,
        supplier: SupplierRecord,
        *,
        assignee: str,
        actor: Optional[str],
        at: Optional[datetime] = None,
        context: Optional[PolicyContext] = None,
        policy_engine: Optional[SupplierPolicyEngine] = None,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        effective_actor = resolve_actor(actor, access_context)
        permission_result = self.authorizer.authorize(
            GovernancePermission.ASSIGN_VERIFICATION,
            access_context=access_context,
        )
        if not permission_result.allowed:
            return GovernanceServiceResult(False, supplier, issues=permission_result.issues)
        resolved_context = context or PolicyContext(region_code=supplier.region_context.region_code)
        engine = policy_engine or SupplierPolicyEngine()
        cleaned_assignee = _clean_optional_text(assignee)
        policy_result = engine.evaluate_verification_assignment(
            supplier=supplier,
            actor=effective_actor,
            assignee=cleaned_assignee,
            context=resolved_context,
        )
        policy_issues = issues_from_policy_result(policy_result, include_allowed=False)
        if not policy_result.is_allowed:
            return GovernanceServiceResult(False, supplier, issues=policy_issues)

        if supplier.verification_assigned_to == cleaned_assignee:
            return GovernanceServiceResult(
                allowed=False,
                supplier=supplier,
                issues=policy_issues + (
                    ValidationIssue(
                        code="verification.assign.duplicate_assignee",
                        field="verification_assigned_to",
                        message="Verification is already assigned to that verifier.",
                        severity=ValidationSeverity.ERROR,
                    ),
                ),
            )

        timestamp = at or datetime.now(tz=UTC)
        updated_supplier = supplier.with_governance_update(
            actor=effective_actor,
            at=timestamp,
            verification_assigned_to=cleaned_assignee,
            verification_assigned_at=timestamp,
            verification_last_updated_at=timestamp,
            verification_last_updated_by=effective_actor,
        )
        event = GovernanceEventRecord.new(
            supplier_id=supplier.identity.supplier_id,
            event_type=GovernanceEventType.VERIFICATION_ASSIGNED,
            occurred_at=timestamp,
            actor=effective_actor,
            source=SOURCE,
            summary="Supplier verification was assigned.",
            metadata={
                "from_assignee": supplier.verification_assigned_to,
                "to_assignee": cleaned_assignee,
                "verification_status": supplier.verification_status.value,
            },
        )
        return GovernanceServiceResult(True, updated_supplier, events=(event,), issues=policy_issues)

    def unassign(
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
            GovernancePermission.UNASSIGN_VERIFICATION,
            access_context=access_context,
        )
        if not permission_result.allowed:
            return GovernanceServiceResult(False, supplier, issues=permission_result.issues)
        resolved_context = context or PolicyContext(region_code=supplier.region_context.region_code)
        engine = policy_engine or SupplierPolicyEngine()
        policy_result = engine.evaluate_verification_unassignment(
            supplier=supplier,
            actor=effective_actor,
            context=resolved_context,
        )
        policy_issues = issues_from_policy_result(policy_result, include_allowed=False)
        if not policy_result.is_allowed:
            return GovernanceServiceResult(False, supplier, issues=policy_issues)

        if not supplier.verification_assigned_to:
            return GovernanceServiceResult(
                allowed=False,
                supplier=supplier,
                issues=policy_issues + (
                    ValidationIssue(
                        code="verification.unassign.assignment_missing",
                        field="verification_assigned_to",
                        message="Verification cannot be unassigned because no verifier is currently assigned.",
                        severity=ValidationSeverity.ERROR,
                    ),
                ),
            )

        timestamp = at or datetime.now(tz=UTC)
        updated_supplier = supplier.with_governance_update(
            actor=effective_actor,
            at=timestamp,
            verification_assigned_to=None,
            verification_assigned_at=None,
            verification_last_updated_at=timestamp,
            verification_last_updated_by=effective_actor,
        )
        event = GovernanceEventRecord.new(
            supplier_id=supplier.identity.supplier_id,
            event_type=GovernanceEventType.VERIFICATION_UNASSIGNED,
            occurred_at=timestamp,
            actor=effective_actor,
            source=SOURCE,
            summary="Supplier verification was unassigned.",
            metadata={
                "from_assignee": supplier.verification_assigned_to,
                "verification_status": supplier.verification_status.value,
            },
        )
        return GovernanceServiceResult(True, updated_supplier, events=(event,), issues=policy_issues)

    def mark_pending(
        self,
        supplier: SupplierRecord,
        *,
        actor: Optional[str],
        at: Optional[datetime] = None,
        context: Optional[PolicyContext] = None,
        policy_engine: Optional[SupplierPolicyEngine] = None,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        return self._set_status(
            supplier,
            target_status=VerificationStatus.PENDING,
            actor=actor,
            at=at,
            event_type=GovernanceEventType.VERIFICATION_PENDING,
            summary="Supplier verification was moved to pending.",
            context=context,
            policy_engine=policy_engine,
            access_context=access_context,
            permission=GovernancePermission.MARK_VERIFICATION_PENDING,
        )

    def mark_verified(
        self,
        supplier: SupplierRecord,
        *,
        actor: Optional[str],
        at: Optional[datetime] = None,
        context: Optional[PolicyContext] = None,
        policy_engine: Optional[SupplierPolicyEngine] = None,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        return self._set_status(
            supplier,
            target_status=VerificationStatus.VERIFIED,
            actor=actor,
            at=at,
            event_type=GovernanceEventType.VERIFICATION_VERIFIED,
            summary="Supplier verification was marked as verified.",
            context=context,
            policy_engine=policy_engine,
            access_context=access_context,
            permission=GovernancePermission.MARK_VERIFIED,
        )

    def mark_failed(
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
        return self._set_status(
            supplier,
            target_status=VerificationStatus.FAILED,
            actor=actor,
            at=at,
            event_type=GovernanceEventType.VERIFICATION_FAILED,
            summary="Supplier verification was marked as failed.",
            metadata={"reason": _clean_optional_text(reason)} if _clean_optional_text(reason) else None,
            context=context,
            policy_engine=policy_engine,
            access_context=access_context,
            permission=GovernancePermission.MARK_VERIFICATION_FAILED,
        )

    def mark_needs_review(
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
        return self._set_status(
            supplier,
            target_status=VerificationStatus.NEEDS_REVIEW,
            actor=actor,
            at=at,
            event_type=GovernanceEventType.VERIFICATION_NEEDS_REVIEW,
            summary="Supplier verification was marked as needs review.",
            metadata={"reason": _clean_optional_text(reason)} if _clean_optional_text(reason) else None,
            context=context,
            policy_engine=policy_engine,
            access_context=access_context,
            permission=GovernancePermission.MARK_VERIFICATION_NEEDS_REVIEW,
        )

    def set_visibility(
        self,
        supplier: SupplierRecord,
        *,
        target_visibility: VerificationVisibility,
        actor: Optional[str],
        at: Optional[datetime] = None,
        context: Optional[PolicyContext] = None,
        policy_engine: Optional[SupplierPolicyEngine] = None,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        effective_actor = resolve_actor(actor, access_context)
        permission_result = self.authorizer.authorize(
            GovernancePermission.SET_VERIFICATION_VISIBILITY,
            access_context=access_context,
        )
        if not permission_result.allowed:
            return GovernanceServiceResult(False, supplier, issues=permission_result.issues)
        resolved_context = context or PolicyContext(region_code=supplier.region_context.region_code)
        engine = policy_engine or SupplierPolicyEngine()
        policy_result = engine.evaluate_verification_visibility(
            supplier=supplier,
            actor=effective_actor,
            target_visibility=target_visibility,
            context=resolved_context,
        )
        policy_issues = issues_from_policy_result(policy_result, include_allowed=False)
        if not policy_result.is_allowed:
            return GovernanceServiceResult(False, supplier, issues=policy_issues)

        if supplier.verification_visibility is target_visibility:
            return GovernanceServiceResult(
                allowed=False,
                supplier=supplier,
                issues=policy_issues + (
                    ValidationIssue(
                        code="verification.visibility.same_state",
                        field="verification_visibility",
                        message="Verification visibility is already set to that state.",
                        severity=ValidationSeverity.ERROR,
                    ),
                ),
            )

        timestamp = at or datetime.now(tz=UTC)
        updated_supplier = supplier.with_governance_update(
            actor=effective_actor,
            at=timestamp,
            verification_visibility=target_visibility,
            verification_visibility_last_updated_at=timestamp,
            verification_visibility_last_updated_by=effective_actor,
            verification_last_updated_at=timestamp,
            verification_last_updated_by=effective_actor,
        )
        event = GovernanceEventRecord.new(
            supplier_id=supplier.identity.supplier_id,
            event_type=GovernanceEventType.VERIFICATION_VISIBILITY_CHANGED,
            occurred_at=timestamp,
            actor=effective_actor,
            source=SOURCE,
            summary="Supplier verification visibility was changed.",
            metadata={
                "from_visibility": supplier.verification_visibility.value,
                "to_visibility": target_visibility.value,
                "verification_status": supplier.verification_status.value,
            },
        )
        return GovernanceServiceResult(True, updated_supplier, events=(event,), issues=policy_issues)

    def _set_status(
        self,
        supplier: SupplierRecord,
        *,
        target_status: VerificationStatus,
        actor: Optional[str],
        at: Optional[datetime],
        event_type: GovernanceEventType,
        summary: str,
        context: Optional[PolicyContext],
        policy_engine: Optional[SupplierPolicyEngine],
        metadata: Optional[dict[str, str]] = None,
        access_context: Optional[AccessContext] = None,
        permission: Optional[GovernancePermission] = None,
    ) -> GovernanceServiceResult:
        effective_actor = resolve_actor(actor, access_context)
        if permission is not None:
            permission_result = self.authorizer.authorize(permission, access_context=access_context)
            if not permission_result.allowed:
                return GovernanceServiceResult(False, supplier, issues=permission_result.issues)
        resolved_context = context or PolicyContext(region_code=supplier.region_context.region_code)
        engine = policy_engine or SupplierPolicyEngine()
        policy_result = engine.evaluate_verification_status_change(
            supplier=supplier,
            actor=effective_actor,
            target_status=target_status,
            context=resolved_context,
        )
        policy_issues = issues_from_policy_result(policy_result, include_allowed=False)
        if not policy_result.is_allowed:
            return GovernanceServiceResult(False, supplier, issues=policy_issues)

        if supplier.verification_status is target_status:
            return GovernanceServiceResult(
                allowed=False,
                supplier=supplier,
                issues=policy_issues + (
                    ValidationIssue(
                        code="verification.status.same_state",
                        field="verification_status",
                        message=f"Supplier verification is already in state {target_status.value}.",
                        severity=ValidationSeverity.ERROR,
                    ),
                ),
            )

        if target_status in {VerificationStatus.FAILED, VerificationStatus.NEEDS_REVIEW} and supplier.lifecycle_status is LifecycleStatus.ACTIVE:
            return GovernanceServiceResult(
                allowed=False,
                supplier=supplier,
                issues=policy_issues + (
                    ValidationIssue(
                        code=f"verification.{target_status.value}.active_supplier_blocked",
                        field="lifecycle_status",
                        message=f"Verification cannot be moved to {target_status.value.replace('_', ' ')} while the supplier is active. Suspend first.",
                        severity=ValidationSeverity.ERROR,
                    ),
                ),
            )

        timestamp = at or datetime.now(tz=UTC)
        extra_metadata = dict(metadata or {})
        changes: dict[str, object] = {
            "verification_status": target_status,
            "verification_last_updated_at": timestamp,
            "verification_last_updated_by": effective_actor,
        }
        events: list[GovernanceEventRecord] = []

        if supplier.verification_visibility is VerificationVisibility.VISIBLE and target_status is not VerificationStatus.VERIFIED:
            changes["verification_visibility"] = VerificationVisibility.INTERNAL_ONLY
            changes["verification_visibility_last_updated_at"] = timestamp
            changes["verification_visibility_last_updated_by"] = effective_actor
            extra_metadata["visibility_downgraded"] = "true"
            events.append(
                GovernanceEventRecord.new(
                    supplier_id=supplier.identity.supplier_id,
                    event_type=GovernanceEventType.VERIFICATION_VISIBILITY_CHANGED,
                    occurred_at=timestamp,
                    actor=effective_actor,
                    source=SOURCE,
                    summary="Supplier verification visibility was reduced because the supplier is no longer verified.",
                    metadata={
                        "from_visibility": supplier.verification_visibility.value,
                        "to_visibility": VerificationVisibility.INTERNAL_ONLY.value,
                        "reason": "verification_status_changed",
                        "to_status": target_status.value,
                    },
                )
            )

        updated_supplier = supplier.with_governance_update(actor=effective_actor, at=timestamp, **changes)
        events.insert(
            0,
            GovernanceEventRecord.new(
                supplier_id=supplier.identity.supplier_id,
                event_type=event_type,
                occurred_at=timestamp,
                actor=effective_actor,
                source=SOURCE,
                summary=summary,
                metadata={
                    "from_status": supplier.verification_status.value,
                    "to_status": target_status.value,
                    **extra_metadata,
                },
            ),
        )
        return GovernanceServiceResult(True, updated_supplier, events=tuple(events), issues=policy_issues)
