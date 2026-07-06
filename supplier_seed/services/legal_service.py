from dataclasses import replace
from supplier_seed.domain.enums import LegalAcceptanceState, LifecycleStatus, GovernanceEventType
from supplier_seed.domain.validation import ValidationIssue
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.services.results import GovernanceServiceResult

class LegalService:
    def accept(self, supplier, version, actor=None):
        updated = replace(supplier, legal_acceptance_state=LegalAcceptanceState.ACCEPTED, legal_acceptance_version=version).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(updated.supplier_id, GovernanceEventType.LEGAL_ACCEPTED, actor=actor)
        return GovernanceServiceResult(True, updated, (), (event,))

    def withdraw(self, supplier, actor=None):
        if supplier.lifecycle_status == LifecycleStatus.ACTIVE:
            return GovernanceServiceResult(False, supplier, (ValidationIssue("legal.withdraw.active_supplier_blocked"),), ())
        updated = replace(supplier, legal_acceptance_state=LegalAcceptanceState.WITHDRAWN).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(updated.supplier_id, GovernanceEventType.LEGAL_WITHDRAWN, actor=actor)
        return GovernanceServiceResult(True, updated, (), (event,))
