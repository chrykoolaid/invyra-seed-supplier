from dataclasses import replace
from supplier_seed.domain.enums import LegalAcceptanceState, LifecycleStatus, GovernanceEventType, SupplierMode
from supplier_seed.domain.validation import ValidationIssue
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.services.results import GovernanceServiceResult

class LegalService:
    def accept(self, supplier, version, actor=None, context=None, policy_engine=None):
        if supplier.mode == SupplierMode.SEEDED and context and not context.allow_seeded_legal_acceptance:
            return GovernanceServiceResult(False, supplier, (ValidationIssue("policy.legal.accept.blocked.seeded_not_applicable"),), ())
        if supplier.legal_acceptance_state == LegalAcceptanceState.ACCEPTED and supplier.legal_acceptance_version != version:
            return GovernanceServiceResult(False, supplier, (ValidationIssue("legal.accept.supersede_required"),), ())
        updated = replace(supplier, legal_acceptance_state=LegalAcceptanceState.ACCEPTED, legal_acceptance_version=version).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(updated.supplier_id, GovernanceEventType.LEGAL_ACCEPTED, actor=actor, metadata={"version": version})
        return GovernanceServiceResult(True, updated, (), (event,))

    def withdraw(self, supplier, actor=None, reason="", context=None, policy_engine=None):
        if context and context.require_reason_for_legal_withdrawal and not reason.strip():
            return GovernanceServiceResult(False, supplier, (ValidationIssue("policy.legal.withdraw.blocked.reason_required"),), ())
        if supplier.lifecycle_status == LifecycleStatus.ACTIVE:
            return GovernanceServiceResult(False, supplier, (ValidationIssue("legal.withdraw.active_supplier_blocked"),), ())
        updated = replace(supplier, legal_acceptance_state=LegalAcceptanceState.WITHDRAWN).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(updated.supplier_id, GovernanceEventType.LEGAL_WITHDRAWN, actor=actor, metadata={"reason": reason})
        return GovernanceServiceResult(True, updated, (), (event,))

    def supersede(self, supplier, pending_version, actor=None, reason="", context=None, policy_engine=None):
        if context and context.require_reason_for_legal_supersede and not reason.strip():
            return GovernanceServiceResult(False, supplier, (ValidationIssue("policy.legal.supersede.blocked.reason_required"),), ())
        updated = replace(supplier, legal_acceptance_state=LegalAcceptanceState.SUPERSEDED).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(updated.supplier_id, GovernanceEventType.LEGAL_SUPERSEDED, actor=actor, metadata={"pending_version": pending_version, "reason": reason})
        return GovernanceServiceResult(True, updated, (), (event,))
