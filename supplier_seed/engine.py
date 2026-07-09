from dataclasses import replace
from datetime import datetime

from supplier_seed.domain.enums import GovernanceEventType, LegalAcceptanceState, LifecycleStatus, ModerationStatus, PolicyOutcome, SupplierMode
from supplier_seed.domain.validation import ValidationIssue
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.ingestion.ingestion_service import IngestionDecision, SupplierIngestionBatchResult, SupplierIngestionResult, SupplierIngestionService
from supplier_seed.policy.rules import SupplierPolicyEngine
from supplier_seed.read_models.workspace import OperationPresentation, SupplierRequirement, SupplierSummaryItem, SupplierWorkspace, SupplierWorkspaceSummary
from supplier_seed.repository.memory_impl import InMemorySupplierRepository
from supplier_seed.services.legal_service import LegalService
from supplier_seed.services.moderation_service import ModerationService
from supplier_seed.services.permissions import GovernanceAuthorizer, GovernancePermission, GovernanceRole
from supplier_seed.services.provenance_service import ProvenanceService
from supplier_seed.services.results import GovernanceServiceResult
from supplier_seed.services.verification_service import VerificationService

class SupplierSeedEngine:
    def __init__(self, repository=None, ingestion_service=None, policy_engine=None):
        self.repository = repository or InMemorySupplierRepository()
        self.policy_engine = policy_engine or SupplierPolicyEngine()
        self.authorizer = GovernanceAuthorizer()
        self.ingestion_service = ingestion_service or SupplierIngestionService(policy_engine=self.policy_engine)
        self.legal_service = LegalService()
        self.moderation_service = ModerationService()
        self.provenance_service = ProvenanceService()
        self.verification_service = VerificationService()

    def _has_permission(self, access_context, permission):
        return self.authorizer.authorize(access_context, permission)

    def _blocked_event(self, supplier_id, action, issue_codes, source=None):
        return GovernanceEventRecord.for_supplier(
            supplier_id,
            GovernanceEventType.GOVERNANCE_ACTION_BLOCKED,
            source=source,
            metadata={"action": action, "issue_codes": list(issue_codes)},
        )

    def _blocked_result(self, supplier, supplier_id, action, issue_code, source=None):
        event = self._blocked_event(supplier_id, action, (issue_code,), source=source)
        self.repository.append_events((event,))
        return GovernanceServiceResult(False, supplier, (ValidationIssue(issue_code),), (event,))

    def ingest_supplier(self, candidate, context=None, persist=True, access_context=None):
        permission = GovernancePermission.INGEST_SEEDED_SUPPLIER if SupplierMode(candidate.mode) == SupplierMode.SEEDED else GovernancePermission.INGEST_MANUAL_SUPPLIER
        auth = self._has_permission(access_context, permission)
        if not auth.allowed:
            event = self._blocked_event("ingestion", "ingest_supplier", (auth.reason,))
            self.repository.append_events((event,))
            decision = IngestionDecision(auth.reason, PolicyOutcome.BLOCKED)
            return SupplierIngestionResult(PolicyOutcome.BLOCKED, None, False, (decision,), (event,))
        result = self.ingestion_service.ingest_supplier(candidate, existing_suppliers=self.repository.list(), context=context)
        if persist and result.accepted_for_staging and result.supplier is not None:
            self.repository.save(result.supplier)
            self.repository.append_events(result.events)
        return result

    def ingest_from_source(self, source, context=None):
        return SupplierIngestionBatchResult(tuple(self.ingest_supplier(candidate, context=context) for candidate in source.list_candidates()))

    def _apply_result(self, action, supplier_id, result, source=None):
        if result.allowed:
            self.repository.save(result.supplier)
            self.repository.append_events(result.events)
            return result
        event = self._blocked_event(supplier_id, action, [issue.code for issue in result.issues], source=source)
        self.repository.append_events((event,))
        return replace(result, events=result.events + (event,))

    def submit_for_review(self, supplier_id, actor=None, context=None, access_context=None):
        auth = self._has_permission(access_context, GovernancePermission.SUBMIT_FOR_REVIEW)
        supplier = self.repository.get(supplier_id)
        if not auth.allowed:
            return self._blocked_result(supplier, supplier_id, "submit_for_review", auth.reason)
        result = self.moderation_service.submit_for_review(supplier, actor=actor, context=context, policy_engine=self.policy_engine)
        return self._apply_result("submit_for_review", supplier_id, result)

    def approve_moderation(self, supplier_id, actor=None, context=None, access_context=None):
        auth = self._has_permission(access_context, GovernancePermission.APPROVE_MODERATION)
        supplier = self.repository.get(supplier_id)
        if not auth.allowed:
            return self._blocked_result(supplier, supplier_id, "approve_moderation", auth.reason)
        result = self.moderation_service.approve(supplier, actor=actor, context=context, policy_engine=self.policy_engine)
        return self._apply_result("approve_moderation", supplier_id, result)

    def reject_moderation(self, supplier_id, actor=None, reason="", context=None, access_context=None):
        auth = self._has_permission(access_context, GovernancePermission.APPROVE_MODERATION)
        supplier = self.repository.get(supplier_id)
        if not auth.allowed:
            return self._blocked_result(supplier, supplier_id, "reject_moderation", auth.reason)
        result = self.moderation_service.reject(supplier, actor=actor, reason=reason, context=context, policy_engine=self.policy_engine)
        return self._apply_result("reject_moderation", supplier_id, result)

    def escalate_moderation(self, supplier_id, actor=None, reason="", context=None, access_context=None):
        supplier = self.repository.get(supplier_id)
        result = self.moderation_service.escalate(supplier, actor=actor, reason=reason, context=context, policy_engine=self.policy_engine)
        return self._apply_result("escalate_moderation", supplier_id, result)

    def accept_legal(self, supplier_id, version, actor=None, context=None, access_context=None):
        auth = self._has_permission(access_context, GovernancePermission.ACCEPT_LEGAL)
        supplier = self.repository.get(supplier_id)
        if not auth.allowed:
            return self._blocked_result(supplier, supplier_id, "accept_legal", auth.reason)
        result = self.legal_service.accept(supplier, version=version, actor=actor, context=context, policy_engine=self.policy_engine)
        return self._apply_result("accept_legal", supplier_id, result)

    def withdraw_legal(self, supplier_id, actor=None, reason="", context=None, access_context=None):
        supplier = self.repository.get(supplier_id)
        result = self.legal_service.withdraw(supplier, actor=actor, reason=reason, context=context, policy_engine=self.policy_engine)
        return self._apply_result("withdraw_legal", supplier_id, result)

    def supersede_legal(self, supplier_id, pending_version, actor=None, reason="", context=None, access_context=None):
        supplier = self.repository.get(supplier_id)
        result = self.legal_service.supersede(supplier, pending_version=pending_version, actor=actor, reason=reason, context=context, policy_engine=self.policy_engine)
        return self._apply_result("supersede_legal", supplier_id, result)

    def assign_verification(self, supplier_id, assignee, actor=None, context=None, access_context=None):
        auth = self._has_permission(access_context, GovernancePermission.ASSIGN_VERIFICATION)
        supplier = self.repository.get(supplier_id)
        if not auth.allowed:
            return self._blocked_result(supplier, supplier_id, "assign_verification", auth.reason)
        result = self.verification_service.assign(supplier, assignee=assignee, actor=actor, context=context, policy_engine=self.policy_engine)
        return self._apply_result("assign_verification", supplier_id, result)

    def mark_verified(self, supplier_id, actor=None, context=None, access_context=None):
        supplier = self.repository.get(supplier_id)
        result = self.verification_service.mark_verified(supplier, actor=actor, context=context, policy_engine=self.policy_engine)
        return self._apply_result("mark_verified", supplier_id, result)

    def mark_verification_failed(self, supplier_id, actor=None, reason="", context=None, access_context=None):
        auth = self._has_permission(access_context, GovernancePermission.MARK_VERIFICATION_FAILED)
        supplier = self.repository.get(supplier_id)
        if not auth.allowed:
            return self._blocked_result(supplier, supplier_id, "mark_verification_failed", auth.reason)
        result = self.verification_service.mark_failed(supplier, actor=actor, context=context, policy_engine=self.policy_engine)
        result = replace(result, events=tuple(replace(event, metadata={**event.metadata, "reason": reason}) for event in result.events))
        return self._apply_result("mark_verification_failed", supplier_id, result)

    def set_verification_visibility(self, supplier_id, visibility, actor=None, context=None, access_context=None):
        supplier = self.repository.get(supplier_id)
        result = self.verification_service.set_visibility(supplier, visibility=visibility, actor=actor, context=context, policy_engine=self.policy_engine)
        return self._apply_result("set_verification_visibility", supplier_id, result)

    def mark_verification_needs_review(self, supplier_id, actor=None, reason="", context=None, access_context=None):
        supplier = self.repository.get(supplier_id)
        result = self.verification_service.mark_needs_review(supplier, actor=actor, reason=reason, context=context, policy_engine=self.policy_engine)
        return self._apply_result("mark_verification_needs_review", supplier_id, result)

    def activate_supplier(self, supplier_id, actor=None, context=None, access_context=None):
        auth = self._has_permission(access_context, GovernancePermission.ACTIVATE_SUPPLIER)
        supplier = self.repository.get(supplier_id)
        if not auth.allowed:
            return self._blocked_result(supplier, supplier_id, "activate_supplier", auth.reason, source="engine.lifecycle")
        requirements, activation_ok = self._activation_requirements(supplier, context)
        if not activation_ok:
            issues = tuple(ValidationIssue(f"activation.blocked.{item.code}") for item in requirements if item.blocking and not item.satisfied)
            return self._apply_result("activate_supplier", supplier_id, GovernanceServiceResult(False, supplier, issues, ()), source="engine.lifecycle")
        now = datetime.utcnow()
        updated = replace(supplier, lifecycle_status=LifecycleStatus.ACTIVE, activated_at=now).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(supplier_id, GovernanceEventType.LIFECYCLE_STATUS_CHANGED, actor=actor, source="engine.lifecycle", metadata={"from_status": supplier.lifecycle_status.value, "to_status": LifecycleStatus.ACTIVE.value})
        return self._apply_result("activate_supplier", supplier_id, GovernanceServiceResult(True, updated, (), (event,)), source="engine.lifecycle")

    def _activation_requirements(self, supplier, context=None):
        moderation_required = supplier.mode == SupplierMode.SEEDED or (context and context.require_moderation_for_seeded_activation)
        moderation_ok = supplier.moderation_status == ModerationStatus.APPROVED
        legal_required = supplier.mode == SupplierMode.MANUAL and (not context or context.require_legal_acceptance_for_manual)
        legal_ok = (not legal_required) or supplier.legal_acceptance_state == LegalAcceptanceState.ACCEPTED
        requirements = [SupplierRequirement("moderation", moderation_ok, moderation_required), SupplierRequirement("legal_acceptance", legal_ok, legal_required)]
        activation_ok = supplier.lifecycle_status in (LifecycleStatus.APPROVED, LifecycleStatus.ACTIVE) and moderation_ok and legal_ok
        return tuple(requirements + [SupplierRequirement("activation", activation_ok, True)]), activation_ok

    def _queue_and_step(self, supplier, context=None):
        requirements, activation_ok = self._activation_requirements(supplier, context)
        legal_requirement = next(item for item in requirements if item.code == "legal_acceptance")
        if supplier.lifecycle_status == LifecycleStatus.ACTIVE: return "operational", "monitor_supplier"
        if supplier.mode == SupplierMode.SEEDED and supplier.moderation_status != ModerationStatus.APPROVED: return "moderation_review", "review_moderation"
        if supplier.lifecycle_status == LifecycleStatus.APPROVED and legal_requirement.blocking and not legal_requirement.satisfied: return "legal_review", "accept_legal"
        if activation_ok: return "activation_ready", "activate_supplier"
        return "supplier_review", "review_supplier"

    def _redact_event(self, event, access_context=None):
        if access_context and access_context.role == GovernanceRole.STAFF and event.event_type in (GovernanceEventType.VERIFICATION_FAILED, GovernanceEventType.GOVERNANCE_ACTION_BLOCKED):
            return replace(event, actor=None, metadata={"redacted": True})
        return event

    def get_supplier_workspace(self, supplier_id, context=None, access_context=None):
        supplier = self.repository.get(supplier_id)
        requirements, activation_ok = self._activation_requirements(supplier, context)
        queue, next_step = self._queue_and_step(supplier, context)
        timeline = tuple(self._redact_event(event, access_context) for event in sorted(self.repository.list_events(supplier_id), key=lambda event: event.occurred_at, reverse=True))
        assigned = None if access_context and access_context.role == GovernanceRole.STAFF else supplier.assigned_verifier
        summary = SupplierWorkspaceSummary(supplier_id=supplier.supplier_id, name=supplier.name, primary_queue=queue, next_step=next_step, lifecycle_status=supplier.lifecycle_status, assigned_verifier=assigned)
        return SupplierWorkspace(supplier=supplier, summary=summary, requirements=requirements, timeline=timeline, activation_allowed=activation_ok)

    def list_supplier_summaries(self, context=None, queue=None):
        return tuple(SupplierSummaryItem(s.supplier_id, s.name, s.mode, *self._queue_and_step(s, context)) for s in self.repository.list() if not queue or self._queue_and_step(s, context)[0] == queue)

    def present_governance_result(self, result, action_name=""):
        return OperationPresentation(result.allowed, "success" if result.allowed else "policy_violation", result.events, {"action": action_name, "issue_codes": [issue.code for issue in result.issues]})

    def present_transition_result(self, result, action_name=""):
        return OperationPresentation(result.allowed, "success" if result.allowed else "policy_violation", result.events, {"action": action_name, "to_status": LifecycleStatus.ACTIVE.value, "issue_codes": [issue.code for issue in result.issues]})

    def present_ingestion_result(self, result):
        status = "validation_error" if result.outcome == PolicyOutcome.BLOCKED else "requires_review" if result.outcome == PolicyOutcome.REQUIRES_REVIEW else "warning" if result.outcome == PolicyOutcome.WARNING else "success"
        return OperationPresentation(result.accepted_for_staging, status, result.events, {"decision_codes": [decision.code for decision in result.decisions]})

    def present_system_failure(self, action_name, error_message):
        return OperationPresentation(False, "system_failure", (), {"action": action_name, "error_message": error_message})

    def list_suppliers(self): return self.repository.list()
    def get_supplier(self, supplier_id): return self.repository.get(supplier_id)
    def get_supplier_record(self, supplier_id): return self.repository.get(supplier_id)
    def list_audit_events(self, supplier_id=None, access_context=None):
        return tuple(self._redact_event(event, access_context) for event in self.repository.list_events(supplier_id))
