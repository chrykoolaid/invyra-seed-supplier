from supplier_seed.domain.enums import GovernanceEventType
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.ingestion.ingestion_service import SupplierIngestionService
from supplier_seed.policy.rules import SupplierPolicyEngine
from supplier_seed.repository.memory_impl import InMemorySupplierRepository
from supplier_seed.services.legal_service import LegalService
from supplier_seed.services.moderation_service import ModerationService
from supplier_seed.services.provenance_service import ProvenanceService
from supplier_seed.services.verification_service import VerificationService

class SupplierSeedEngine:
    def __init__(self, repository=None, ingestion_service=None, policy_engine=None):
        self.repository = repository or InMemorySupplierRepository()
        self.policy_engine = policy_engine or SupplierPolicyEngine()
        self.ingestion_service = ingestion_service or SupplierIngestionService(policy_engine=self.policy_engine)
        self.legal_service = LegalService()
        self.moderation_service = ModerationService()
        self.provenance_service = ProvenanceService()
        self.verification_service = VerificationService()

    def ingest_supplier(self, candidate, context=None):
        result = self.ingestion_service.ingest_supplier(candidate, existing_suppliers=self.repository.list(), context=context)
        if result.accepted_for_staging and result.supplier is not None:
            self.repository.save(result.supplier)
            self.repository.append_events(result.events)
        return result

    def _apply_result(self, action, supplier_id, result):
        if result.allowed:
            self.repository.save(result.supplier)
            self.repository.append_events(result.events)
        else:
            event = GovernanceEventRecord.for_supplier(
                supplier_id,
                GovernanceEventType.GOVERNANCE_ACTION_BLOCKED,
                metadata={"action": action, "issue_codes": [issue.code for issue in result.issues]},
            )
            self.repository.append_events((event,))
        return result

    def submit_for_review(self, supplier_id, actor=None, context=None):
        supplier = self.repository.get(supplier_id)
        result = self.moderation_service.submit_for_review(supplier, actor=actor, context=context, policy_engine=self.policy_engine)
        return self._apply_result("submit_for_review", supplier_id, result)

    def approve_moderation(self, supplier_id, actor=None, context=None):
        supplier = self.repository.get(supplier_id)
        result = self.moderation_service.approve(supplier, actor=actor, context=context, policy_engine=self.policy_engine)
        return self._apply_result("approve_moderation", supplier_id, result)

    def reject_moderation(self, supplier_id, actor=None, reason="", context=None):
        supplier = self.repository.get(supplier_id)
        result = self.moderation_service.reject(supplier, actor=actor, reason=reason, context=context, policy_engine=self.policy_engine)
        return self._apply_result("reject_moderation", supplier_id, result)

    def escalate_moderation(self, supplier_id, actor=None, reason="", context=None):
        supplier = self.repository.get(supplier_id)
        result = self.moderation_service.escalate(supplier, actor=actor, reason=reason, context=context, policy_engine=self.policy_engine)
        return self._apply_result("escalate_moderation", supplier_id, result)

    def accept_legal(self, supplier_id, version, actor=None, context=None):
        supplier = self.repository.get(supplier_id)
        result = self.legal_service.accept(supplier, version=version, actor=actor, context=context, policy_engine=self.policy_engine)
        return self._apply_result("accept_legal", supplier_id, result)

    def withdraw_legal(self, supplier_id, actor=None, reason="", context=None):
        supplier = self.repository.get(supplier_id)
        result = self.legal_service.withdraw(supplier, actor=actor, reason=reason, context=context, policy_engine=self.policy_engine)
        return self._apply_result("withdraw_legal", supplier_id, result)

    def supersede_legal(self, supplier_id, pending_version, actor=None, reason="", context=None):
        supplier = self.repository.get(supplier_id)
        result = self.legal_service.supersede(supplier, pending_version=pending_version, actor=actor, reason=reason, context=context, policy_engine=self.policy_engine)
        return self._apply_result("supersede_legal", supplier_id, result)

    def list_suppliers(self):
        return self.repository.list()

    def get_supplier(self, supplier_id):
        return self.repository.get(supplier_id)

    def list_audit_events(self, supplier_id=None):
        return self.repository.list_events(supplier_id)
