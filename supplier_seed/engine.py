from dataclasses import replace

from supplier_seed.domain.enums import GovernanceEventType, LegalAcceptanceState, LifecycleStatus, ModerationStatus, PolicyOutcome, SupplierMode
from supplier_seed.domain.validation import ValidationIssue
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.ingestion.ingestion_service import SupplierIngestionBatchResult, SupplierIngestionService
from supplier_seed.policy.rules import SupplierPolicyEngine
from supplier_seed.read_models.workspace import OperationPresentation, SupplierRequirement, SupplierSummaryItem, SupplierWorkspace, SupplierWorkspaceSummary
from supplier_seed.repository.memory_impl import InMemorySupplierRepository
from supplier_seed.services.legal_service import LegalService
from supplier_seed.services.moderation_service import ModerationService
from supplier_seed.services.provenance_service import ProvenanceService
from supplier_seed.services.results import GovernanceServiceResult
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

    def ingest_supplier(self, candidate, context=None, persist=True):
        result = self.ingestion_service.ingest_supplier(candidate, existing_suppliers=self.repository.list(), context=context)
        if persist and result.accepted_for_staging and result.supplier is not None:
            self.repository.save(result.supplier)
            self.repository.append_events(result.events)
        return result

    def ingest_from_source(self, source, context=None):
        results = []
        for candidate in source.list_candidates():
            results.append(self.ingest_supplier(candidate, context=context))
        return SupplierIngestionBatchResult(tuple(results))

    def _apply_result(self, action, supplier_id, result, source=None):
        if result.allowed:
            self.repository.save(result.supplier)
            self.repository.append_events(result.events)
            return result
        event = GovernanceEventRecord.for_supplier(
            supplier_id,
            GovernanceEventType.GOVERNANCE_ACTION_BLOCKED,
            source=source,
            metadata={"action": action, "issue_codes": [issue.code for issue in result.issues]},
        )
        self.repository.append_events((event,))
        return replace(result, events=result.events + (event,))

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

    def assign_verification(self, supplier_id, assignee, actor=None, context=None):
        supplier = self.repository.get(supplier_id)
        result = self.verification_service.assign(supplier, assignee=assignee, actor=actor, context=context, policy_engine=self.policy_engine)
        return self._apply_result("assign_verification", supplier_id, result)

    def mark_verified(self, supplier_id, actor=None, context=None):
        supplier = self.repository.get(supplier_id)
        result = self.verification_service.mark_verified(supplier, actor=actor, context=context, policy_engine=self.policy_engine)
        return self._apply_result("mark_verified", supplier_id, result)

    def set_verification_visibility(self, supplier_id, visibility, actor=None, context=None):
        supplier = self.repository.get(supplier_id)
        result = self.verification_service.set_visibility(supplier, visibility=visibility, actor=actor, context=context, policy_engine=self.policy_engine)
        return self._apply_result("set_verification_visibility", supplier_id, result)

    def mark_verification_needs_review(self, supplier_id, actor=None, reason="", context=None):
        supplier = self.repository.get(supplier_id)
        result = self.verification_service.mark_needs_review(supplier, actor=actor, reason=reason, context=context, policy_engine=self.policy_engine)
        return self._apply_result("mark_verification_needs_review", supplier_id, result)

    def activate_supplier(self, supplier_id, actor=None, context=None):
        supplier = self.repository.get(supplier_id)
        requirements, activation_ok = self._activation_requirements(supplier, context)
        if not activation_ok:
            issues = tuple(ValidationIssue(f"activation.blocked.{item.code}") for item in requirements if item.blocking and not item.satisfied)
            result = GovernanceServiceResult(False, supplier, issues, ())
            return self._apply_result("activate_supplier", supplier_id, result, source="engine.lifecycle")
        updated = replace(supplier, lifecycle_status=LifecycleStatus.ACTIVE).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(
            supplier_id,
            GovernanceEventType.LIFECYCLE_STATUS_CHANGED,
            actor=actor,
            source="engine.lifecycle",
            metadata={"from_status": supplier.lifecycle_status.value, "to_status": LifecycleStatus.ACTIVE.value},
        )
        result = GovernanceServiceResult(True, updated, (), (event,))
        return self._apply_result("activate_supplier", supplier_id, result, source="engine.lifecycle")

    def _activation_requirements(self, supplier, context=None):
        moderation_required = supplier.mode == SupplierMode.SEEDED or (context and context.require_moderation_for_seeded_activation)
        moderation_ok = supplier.moderation_status == ModerationStatus.APPROVED
        legal_required = supplier.mode == SupplierMode.MANUAL and (not context or context.require_legal_acceptance_for_manual)
        legal_ok = (not legal_required) or supplier.legal_acceptance_state == LegalAcceptanceState.ACCEPTED
        requirements = [
            SupplierRequirement("moderation", moderation_ok, blocking=moderation_required),
            SupplierRequirement("legal_acceptance", legal_ok, blocking=legal_required),
        ]
        activation_ok = supplier.lifecycle_status in (LifecycleStatus.APPROVED, LifecycleStatus.ACTIVE) and moderation_ok and legal_ok
        requirements.append(SupplierRequirement("activation", activation_ok, blocking=True))
        return tuple(requirements), activation_ok

    def _queue_and_step(self, supplier, context=None):
        requirements, activation_ok = self._activation_requirements(supplier, context)
        legal_requirement = next(item for item in requirements if item.code == "legal_acceptance")
        if supplier.lifecycle_status == LifecycleStatus.ACTIVE:
            return "operational", "monitor_supplier"
        if supplier.mode == SupplierMode.SEEDED and supplier.moderation_status != ModerationStatus.APPROVED:
            return "moderation_review", "review_moderation"
        if supplier.lifecycle_status == LifecycleStatus.APPROVED and legal_requirement.blocking and not legal_requirement.satisfied:
            return "legal_review", "accept_legal"
        if activation_ok:
            return "activation_ready", "activate_supplier"
        return "supplier_review", "review_supplier"

    def get_supplier_workspace(self, supplier_id, context=None):
        supplier = self.repository.get(supplier_id)
        requirements, activation_ok = self._activation_requirements(supplier, context)
        queue, next_step = self._queue_and_step(supplier, context)
        timeline = tuple(sorted(self.repository.list_events(supplier_id), key=lambda event: event.occurred_at, reverse=True))
        summary = SupplierWorkspaceSummary(supplier_id=supplier.supplier_id, name=supplier.name, primary_queue=queue, next_step=next_step, lifecycle_status=supplier.lifecycle_status)
        return SupplierWorkspace(supplier=supplier, summary=summary, requirements=requirements, timeline=timeline, activation_allowed=activation_ok)

    def list_supplier_summaries(self, context=None, queue=None):
        items = []
        for supplier in self.repository.list():
            primary_queue, next_step = self._queue_and_step(supplier, context)
            if queue and primary_queue != queue:
                continue
            items.append(SupplierSummaryItem(supplier_id=supplier.supplier_id, name=supplier.name, mode=supplier.mode, primary_queue=primary_queue, next_step=next_step))
        return tuple(items)

    def present_governance_result(self, result, action_name=""):
        status = "success" if result.allowed else "policy_violation"
        return OperationPresentation(result.allowed, status, result.events, {"action": action_name, "issue_codes": [issue.code for issue in result.issues]})

    def present_transition_result(self, result, action_name=""):
        status = "success" if result.allowed else "policy_violation"
        return OperationPresentation(result.allowed, status, result.events, {"action": action_name, "to_status": LifecycleStatus.ACTIVE.value, "issue_codes": [issue.code for issue in result.issues]})

    def present_ingestion_result(self, result):
        if result.outcome == PolicyOutcome.BLOCKED:
            status = "validation_error"
        elif result.outcome == PolicyOutcome.REQUIRES_REVIEW:
            status = "requires_review"
        elif result.outcome == PolicyOutcome.WARNING:
            status = "warning"
        else:
            status = "success"
        return OperationPresentation(result.accepted_for_staging, status, result.events, {"decision_codes": [decision.code for decision in result.decisions]})

    def present_system_failure(self, action_name, error_message):
        return OperationPresentation(False, "system_failure", (), {"action": action_name, "error_message": error_message})

    def list_suppliers(self):
        return self.repository.list()

    def get_supplier(self, supplier_id):
        return self.repository.get(supplier_id)

    def get_supplier_record(self, supplier_id):
        return self.repository.get(supplier_id)

    def list_audit_events(self, supplier_id=None):
        return self.repository.list_events(supplier_id)
