from dataclasses import replace
from datetime import datetime
from supplier_seed.domain.enums import LifecycleStatus, ModerationStatus, GovernanceEventType
from supplier_seed.domain.validation import ValidationIssue
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.services.results import GovernanceServiceResult

class ModerationService:
    def submit_for_review(self, supplier, actor=None, context=None, policy_engine=None):
        updated = replace(supplier, lifecycle_status=LifecycleStatus.PENDING_REVIEW, moderation_status=ModerationStatus.PENDING_REVIEW).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(updated.supplier_id, GovernanceEventType.MODERATION_SUBMITTED, actor=actor)
        return GovernanceServiceResult(True, updated, (), (event,))

    def approve(self, supplier, actor=None, context=None, policy_engine=None):
        updated = replace(supplier, lifecycle_status=LifecycleStatus.APPROVED, moderation_status=ModerationStatus.APPROVED, last_reviewed_by=actor, last_reviewed_at=datetime.utcnow()).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(updated.supplier_id, GovernanceEventType.MODERATION_APPROVED, actor=actor)
        return GovernanceServiceResult(True, updated, (), (event,))

    def reject(self, supplier, actor=None, reason="", context=None, policy_engine=None):
        if supplier.moderation_status not in (ModerationStatus.PENDING_REVIEW, ModerationStatus.ESCALATED):
            return GovernanceServiceResult(False, supplier, (ValidationIssue("moderation.reject.pending_required"),), ())
        updated = replace(supplier, lifecycle_status=LifecycleStatus.REJECTED, moderation_status=ModerationStatus.REJECTED, last_reviewed_by=actor, last_reviewed_at=datetime.utcnow()).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(updated.supplier_id, GovernanceEventType.MODERATION_REJECTED, actor=actor, summary=reason)
        return GovernanceServiceResult(True, updated, (), (event,))

    def escalate(self, supplier, actor=None, reason=""):
        updated = replace(supplier, lifecycle_status=LifecycleStatus.PENDING_REVIEW, moderation_status=ModerationStatus.ESCALATED).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(updated.supplier_id, GovernanceEventType.MODERATION_ESCALATED, actor=actor, summary=reason)
        return GovernanceServiceResult(True, updated, (), (event,))
