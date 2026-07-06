from dataclasses import replace
from supplier_seed.domain.enums import VerificationStatus, VerificationVisibility, LifecycleStatus, GovernanceEventType
from supplier_seed.domain.validation import ValidationIssue
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.services.results import GovernanceServiceResult

class VerificationService:
    def mark_verified(self, supplier, actor=None):
        updated = replace(supplier, verification_status=VerificationStatus.VERIFIED, verification_visibility=VerificationVisibility.PUBLIC).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(updated.supplier_id, GovernanceEventType.VERIFICATION_VERIFIED, actor=actor)
        return GovernanceServiceResult(True, updated, (), (event,))

    def mark_failed(self, supplier, actor=None):
        if supplier.lifecycle_status == LifecycleStatus.ACTIVE:
            return GovernanceServiceResult(False, supplier, (ValidationIssue("verification.failed.active_supplier_blocked"),), ())
        updated = replace(supplier, verification_status=VerificationStatus.FAILED).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(updated.supplier_id, GovernanceEventType.VERIFICATION_FAILED, actor=actor)
        return GovernanceServiceResult(True, updated, (), (event,))
