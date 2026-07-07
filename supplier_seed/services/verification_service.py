from dataclasses import replace
from datetime import datetime
from supplier_seed.domain.enums import VerificationStatus, VerificationVisibility, LifecycleStatus, GovernanceEventType
from supplier_seed.domain.validation import ValidationIssue
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.services.results import GovernanceServiceResult

class VerificationService:
    def assign(self, supplier, assignee, actor=None, context=None, policy_engine=None):
        updated = replace(supplier, assigned_verifier=assignee, assigned_at=datetime.utcnow()).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(updated.supplier_id, GovernanceEventType.VERIFICATION_ASSIGNED, actor=actor, metadata={"to_assignee": assignee})
        return GovernanceServiceResult(True, updated, (), (event,))

    def _decision_issues(self, supplier, actor, context):
        issues = []
        if context and context.require_assignment_for_verification_decisions and not supplier.assigned_verifier:
            issues.append(ValidationIssue("policy.verification.status_change.blocked.assignment_required"))
        if context and context.require_assignment_match_for_verification_decisions and supplier.assigned_verifier and actor != supplier.assigned_verifier:
            issues.append(ValidationIssue("policy.verification.status_change.blocked.actor_assignment_mismatch"))
        return tuple(issues)

    def mark_verified(self, supplier, actor=None, context=None, policy_engine=None):
        issues = self._decision_issues(supplier, actor, context)
        if issues:
            return GovernanceServiceResult(False, supplier, issues, ())
        updated = replace(supplier, verification_status=VerificationStatus.VERIFIED).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(updated.supplier_id, GovernanceEventType.VERIFICATION_VERIFIED, actor=actor)
        return GovernanceServiceResult(True, updated, (), (event,))

    def mark_failed(self, supplier, actor=None, context=None, policy_engine=None):
        if supplier.lifecycle_status == LifecycleStatus.ACTIVE:
            return GovernanceServiceResult(False, supplier, (ValidationIssue("verification.failed.active_supplier_blocked"),), ())
        updated = replace(supplier, verification_status=VerificationStatus.FAILED, verification_visibility=VerificationVisibility.INTERNAL_ONLY).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(updated.supplier_id, GovernanceEventType.VERIFICATION_FAILED, actor=actor)
        return GovernanceServiceResult(True, updated, (), (event,))

    def set_visibility(self, supplier, visibility, actor=None, context=None, policy_engine=None):
        visibility = VerificationVisibility(visibility)
        if context and context.require_verified_status_for_visible_verification and visibility == VerificationVisibility.VISIBLE and supplier.verification_status != VerificationStatus.VERIFIED:
            return GovernanceServiceResult(False, supplier, (ValidationIssue("policy.verification.visibility.blocked.verification_required"),), ())
        updated = replace(supplier, verification_visibility=visibility).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(updated.supplier_id, GovernanceEventType.VERIFICATION_VISIBILITY_CHANGED, actor=actor, metadata={"to_visibility": visibility.value})
        return GovernanceServiceResult(True, updated, (), (event,))

    def mark_needs_review(self, supplier, actor=None, reason="", context=None, policy_engine=None):
        updated = replace(supplier, verification_status=VerificationStatus.NEEDS_REVIEW, verification_visibility=VerificationVisibility.INTERNAL_ONLY).with_updated_metadata(actor)
        status_event = GovernanceEventRecord.for_supplier(updated.supplier_id, GovernanceEventType.VERIFICATION_NEEDS_REVIEW, actor=actor, metadata={"reason": reason})
        visibility_event = GovernanceEventRecord.for_supplier(updated.supplier_id, GovernanceEventType.VERIFICATION_VISIBILITY_CHANGED, actor=actor, metadata={"to_visibility": VerificationVisibility.INTERNAL_ONLY.value})
        return GovernanceServiceResult(True, updated, (), (status_event, visibility_event))
