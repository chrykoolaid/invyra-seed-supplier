"""Legal acceptance governance services."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from supplier_seed.domain.enums import GovernanceEventType, LegalAcceptanceState, LifecycleStatus, ValidationSeverity
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
SOURCE = "services.legal"


def _clean_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class LegalService:
    def __init__(self, *, authorizer: Optional[GovernanceAuthorizer] = None) -> None:
        self.authorizer = authorizer or GovernanceAuthorizer()

    def accept(
        self,
        supplier: SupplierRecord,
        *,
        version: str,
        actor: Optional[str],
        at: Optional[datetime] = None,
        context: Optional[PolicyContext] = None,
        policy_engine: Optional[SupplierPolicyEngine] = None,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        effective_actor = resolve_actor(actor, access_context)
        permission_result = self.authorizer.authorize(
            GovernancePermission.ACCEPT_LEGAL,
            access_context=access_context,
        )
        if not permission_result.allowed:
            return GovernanceServiceResult(False, supplier, issues=permission_result.issues)
        resolved_context = context or PolicyContext(region_code=supplier.region_context.region_code)
        engine = policy_engine or SupplierPolicyEngine()
        cleaned_version = _clean_optional_text(version)
        policy_result = engine.evaluate_legal_acceptance(
            supplier=supplier,
            actor=effective_actor,
            version=cleaned_version,
            context=resolved_context,
        )
        policy_issues = issues_from_policy_result(policy_result, include_allowed=False)
        if not policy_result.is_allowed:
            return GovernanceServiceResult(False, supplier, issues=policy_issues)

        if not cleaned_version:
            return GovernanceServiceResult(
                allowed=False,
                supplier=supplier,
                issues=policy_issues + (
                    ValidationIssue(
                        code="legal.accept.version_required",
                        field="legal_acceptance_version",
                        message="Legal acceptance requires a non-empty version identifier.",
                        severity=ValidationSeverity.ERROR,
                    ),
                ),
            )

        if supplier.legal_acceptance_state is LegalAcceptanceState.ACCEPTED:
            if supplier.legal_acceptance_version == cleaned_version:
                return GovernanceServiceResult(
                    allowed=False,
                    supplier=supplier,
                    issues=policy_issues + (
                        ValidationIssue(
                            code="legal.accept.duplicate_version",
                            field="legal_acceptance_version",
                            message="The same accepted legal version cannot be recorded twice.",
                            severity=ValidationSeverity.ERROR,
                        ),
                    ),
                )
            return GovernanceServiceResult(
                allowed=False,
                supplier=supplier,
                issues=policy_issues + (
                    ValidationIssue(
                        code="legal.accept.supersede_required",
                        field="legal_acceptance_version",
                        message="A different legal version cannot be accepted directly while another accepted version is active. Supersede it first.",
                        severity=ValidationSeverity.ERROR,
                    ),
                ),
            )

        timestamp = at or datetime.now(tz=UTC)
        updated_supplier = supplier.with_governance_update(
            actor=effective_actor,
            at=timestamp,
            legal_acceptance_state=LegalAcceptanceState.ACCEPTED,
            legal_acceptance_version=cleaned_version,
            legal_last_updated_at=timestamp,
            legal_last_updated_by=effective_actor,
        )
        event = GovernanceEventRecord.new(
            supplier_id=supplier.identity.supplier_id,
            event_type=GovernanceEventType.LEGAL_ACCEPTED,
            occurred_at=timestamp,
            actor=effective_actor,
            source=SOURCE,
            summary="Legal acceptance was recorded.",
            metadata={
                "from_state": supplier.legal_acceptance_state.value,
                "to_state": updated_supplier.legal_acceptance_state.value,
                "version": cleaned_version,
            },
        )
        return GovernanceServiceResult(True, updated_supplier, events=(event,), issues=policy_issues)

    def withdraw(
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
            GovernancePermission.WITHDRAW_LEGAL,
            access_context=access_context,
        )
        if not permission_result.allowed:
            return GovernanceServiceResult(False, supplier, issues=permission_result.issues)
        resolved_context = context or PolicyContext(region_code=supplier.region_context.region_code)
        engine = policy_engine or SupplierPolicyEngine()
        cleaned_reason = _clean_optional_text(reason)
        policy_result = engine.evaluate_legal_withdrawal(
            supplier=supplier,
            actor=effective_actor,
            reason=cleaned_reason,
            context=resolved_context,
        )
        policy_issues = issues_from_policy_result(policy_result, include_allowed=False)
        if not policy_result.is_allowed:
            return GovernanceServiceResult(False, supplier, issues=policy_issues)

        if supplier.legal_acceptance_state is not LegalAcceptanceState.ACCEPTED:
            return GovernanceServiceResult(
                allowed=False,
                supplier=supplier,
                issues=policy_issues + (
                    ValidationIssue(
                        code="legal.withdraw.accepted_required",
                        field="legal_acceptance_state",
                        message="Legal withdrawal requires an accepted legal state first.",
                        severity=ValidationSeverity.ERROR,
                    ),
                ),
            )

        if supplier.lifecycle_status is LifecycleStatus.ACTIVE:
            return GovernanceServiceResult(
                allowed=False,
                supplier=supplier,
                issues=policy_issues + (
                    ValidationIssue(
                        code="legal.withdraw.active_supplier_blocked",
                        field="lifecycle_status",
                        message="Legal acceptance cannot be withdrawn while the supplier is active. Suspend or archive first.",
                        severity=ValidationSeverity.ERROR,
                    ),
                ),
            )

        timestamp = at or datetime.now(tz=UTC)
        updated_supplier = supplier.with_governance_update(
            actor=effective_actor,
            at=timestamp,
            legal_acceptance_state=LegalAcceptanceState.WITHDRAWN,
            legal_last_updated_at=timestamp,
            legal_last_updated_by=effective_actor,
        )
        event = GovernanceEventRecord.new(
            supplier_id=supplier.identity.supplier_id,
            event_type=GovernanceEventType.LEGAL_WITHDRAWN,
            occurred_at=timestamp,
            actor=effective_actor,
            source=SOURCE,
            summary="Legal acceptance was withdrawn.",
            metadata={
                "from_state": supplier.legal_acceptance_state.value,
                "to_state": updated_supplier.legal_acceptance_state.value,
                **({"reason": cleaned_reason} if cleaned_reason else {}),
            },
        )
        return GovernanceServiceResult(True, updated_supplier, events=(event,), issues=policy_issues)

    def supersede(
        self,
        supplier: SupplierRecord,
        *,
        pending_version: str,
        actor: Optional[str],
        at: Optional[datetime] = None,
        reason: Optional[str] = None,
        context: Optional[PolicyContext] = None,
        policy_engine: Optional[SupplierPolicyEngine] = None,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        effective_actor = resolve_actor(actor, access_context)
        permission_result = self.authorizer.authorize(
            GovernancePermission.SUPERSEDE_LEGAL,
            access_context=access_context,
        )
        if not permission_result.allowed:
            return GovernanceServiceResult(False, supplier, issues=permission_result.issues)
        resolved_context = context or PolicyContext(region_code=supplier.region_context.region_code)
        engine = policy_engine or SupplierPolicyEngine()
        cleaned_pending_version = _clean_optional_text(pending_version)
        cleaned_reason = _clean_optional_text(reason)
        policy_result = engine.evaluate_legal_supersede(
            supplier=supplier,
            actor=effective_actor,
            pending_version=cleaned_pending_version,
            reason=cleaned_reason,
            context=resolved_context,
        )
        policy_issues = issues_from_policy_result(policy_result, include_allowed=False)
        if not policy_result.is_allowed:
            return GovernanceServiceResult(False, supplier, issues=policy_issues)

        if supplier.legal_acceptance_state is not LegalAcceptanceState.ACCEPTED:
            return GovernanceServiceResult(
                allowed=False,
                supplier=supplier,
                issues=policy_issues + (
                    ValidationIssue(
                        code="legal.supersede.accepted_required",
                        field="legal_acceptance_state",
                        message="Legal supersede requires an accepted legal state first.",
                        severity=ValidationSeverity.ERROR,
                    ),
                ),
            )

        if supplier.lifecycle_status is LifecycleStatus.ACTIVE:
            return GovernanceServiceResult(
                allowed=False,
                supplier=supplier,
                issues=policy_issues + (
                    ValidationIssue(
                        code="legal.supersede.active_supplier_blocked",
                        field="lifecycle_status",
                        message="Legal acceptance cannot be superseded while the supplier is active. Suspend or archive first.",
                        severity=ValidationSeverity.ERROR,
                    ),
                ),
            )

        if not cleaned_pending_version:
            return GovernanceServiceResult(
                allowed=False,
                supplier=supplier,
                issues=policy_issues + (
                    ValidationIssue(
                        code="legal.supersede.pending_version_required",
                        field="legal_acceptance_version",
                        message="Legal supersede requires a non-empty pending version identifier.",
                        severity=ValidationSeverity.ERROR,
                    ),
                ),
            )

        if supplier.legal_acceptance_version == cleaned_pending_version:
            return GovernanceServiceResult(
                allowed=False,
                supplier=supplier,
                issues=policy_issues + (
                    ValidationIssue(
                        code="legal.supersede.version_unchanged",
                        field="legal_acceptance_version",
                        message="Legal supersede requires a pending version that differs from the current accepted version.",
                        severity=ValidationSeverity.ERROR,
                    ),
                ),
            )

        timestamp = at or datetime.now(tz=UTC)
        updated_supplier = supplier.with_governance_update(
            actor=effective_actor,
            at=timestamp,
            legal_acceptance_state=LegalAcceptanceState.SUPERSEDED,
            legal_last_updated_at=timestamp,
            legal_last_updated_by=effective_actor,
        )
        metadata = {
            "from_state": supplier.legal_acceptance_state.value,
            "to_state": updated_supplier.legal_acceptance_state.value,
            "superseded_version": supplier.legal_acceptance_version,
            "pending_version": cleaned_pending_version,
        }
        if cleaned_reason:
            metadata["reason"] = cleaned_reason
        event = GovernanceEventRecord.new(
            supplier_id=supplier.identity.supplier_id,
            event_type=GovernanceEventType.LEGAL_SUPERSEDED,
            occurred_at=timestamp,
            actor=effective_actor,
            source=SOURCE,
            summary="Legal acceptance was superseded.",
            metadata=metadata,
        )
        return GovernanceServiceResult(True, updated_supplier, events=(event,), issues=policy_issues)
