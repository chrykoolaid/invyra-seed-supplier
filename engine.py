"""Unified engine facade for the supplier seed system.

This facade intentionally orchestrates existing layers. It does not introduce real database
behavior or background processing.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable, Optional

from supplier_seed.domain.enums import (
    GovernanceEventType,
    LifecycleStatus,
    ModerationStatus,
    SupplierMode,
    VerificationStatus,
    VerificationVisibility,
    PilotIncidentSeverity,
)
from supplier_seed.consumption.query_service import SupplierConsumptionService
from supplier_seed.domain.models import SupplierRecord
from supplier_seed.domain.transitions import TransitionResult, apply_lifecycle_transition
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.ingestion.ingestion_service import (
    SupplierCandidateInput,
    SupplierIngestionBatchResult,
    SupplierIngestionResult,
    SupplierIngestionService,
)
from supplier_seed.integration.sources import SupplierCandidateSource
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine
from supplier_seed.repository.interfaces import SupplierRepository
from supplier_seed.services.legal_service import LegalService
from supplier_seed.services.lifecycle_service import LifecycleService
from supplier_seed.services.moderation_service import ModerationService
from supplier_seed.services.provenance_service import ProvenanceService
from supplier_seed.services.permissions import (
    AccessContext,
    GovernanceAuthorizer,
    GovernancePermission,
    resolve_actor,
)
from supplier_seed.services.pilot_service import PilotReadinessService
from supplier_seed.services.reliability import (
    RetryPolicy,
    build_governance_receipt,
    build_ingestion_receipt,
    build_transition_receipt,
    restore_governance_result,
    restore_ingestion_result,
    restore_transition_result,
    retry_call,
)
from supplier_seed.services.results import EngineActionResult, GovernanceServiceResult
from supplier_seed.services.verification_service import VerificationService


class SupplierSeedEngine:
    def __init__(
        self,
        *,
        repository: Optional[SupplierRepository] = None,
        policy_engine: Optional[SupplierPolicyEngine] = None,
        ingestion_service: Optional[SupplierIngestionService] = None,
        provenance_service: Optional[ProvenanceService] = None,
        legal_service: Optional[LegalService] = None,
        verification_service: Optional[VerificationService] = None,
        moderation_service: Optional[ModerationService] = None,
        lifecycle_service: Optional[LifecycleService] = None,
        pilot_service: Optional[PilotReadinessService] = None,
        consumption_service: Optional[SupplierConsumptionService] = None,
        authorizer: Optional[GovernanceAuthorizer] = None,
    ) -> None:
        self.repository = repository
        self.policy_engine = policy_engine or SupplierPolicyEngine()
        self.authorizer = authorizer or GovernanceAuthorizer()
        self.ingestion_service = ingestion_service or SupplierIngestionService(
            policy_engine=self.policy_engine,
            authorizer=self.authorizer,
        )
        self.provenance_service = provenance_service or ProvenanceService()
        self.legal_service = legal_service or LegalService(authorizer=self.authorizer)
        self.verification_service = verification_service or VerificationService(authorizer=self.authorizer)
        self.moderation_service = moderation_service or ModerationService(authorizer=self.authorizer)
        self.lifecycle_service = lifecycle_service or LifecycleService(authorizer=self.authorizer)
        self.pilot_service = pilot_service or PilotReadinessService(authorizer=self.authorizer)
        self.consumption_service = consumption_service or (
            SupplierConsumptionService(
                repository=self.repository,
                policy_engine=self.policy_engine,
                authorizer=self.authorizer,
            )
            if self.repository is not None
            else None
        )

    def ingest_supplier(
        self,
        candidate: SupplierCandidateInput,
        *,
        context: Optional[PolicyContext] = None,
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
        idempotency_key: Optional[str] = None,
    ) -> SupplierIngestionResult:
        replayed = self._restore_ingestion_receipt(
            action_name="ingest_supplier",
            idempotency_key=idempotency_key,
        )
        if replayed is not None:
            return replayed

        existing = tuple(self.repository.list_suppliers()) if self.repository else ()
        result = self.ingestion_service.ingest_supplier(
            candidate,
            existing_suppliers=existing,
            context=context,
            access_context=access_context,
        )
        if persist and self.repository:
            receipt = (
                build_ingestion_receipt(
                    idempotency_key=idempotency_key,
                    action_name="ingest_supplier",
                    result=result,
                )
                if idempotency_key
                else None
            )
            if result.accepted_for_staging:
                self.repository.save_supplier_with_events_and_receipt(
                    result.supplier,
                    events=result.events,
                    receipt=receipt,
                )
            elif result.events:
                self.repository.append_audit_events_with_receipt(result.events, receipt=receipt)
            elif receipt is not None:
                self.repository.save_operation_receipt(receipt)
        return result

    def ingest_batch(
        self,
        candidates: Iterable[SupplierCandidateInput],
        *,
        context: Optional[PolicyContext] = None,
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
    ) -> SupplierIngestionBatchResult:
        existing = tuple(self.repository.list_suppliers()) if self.repository else ()
        result = self.ingestion_service.ingest_batch(
            candidates,
            existing_suppliers=existing,
            context=context,
            access_context=access_context,
        )
        if persist and self.repository:
            for item in result.results:
                if item.accepted_for_staging:
                    self.repository.save_supplier_with_events(item.supplier, events=item.events)
                elif item.events:
                    self.repository.append_audit_events(item.events)
        return result

    def ingest_from_source(
        self,
        source: SupplierCandidateSource,
        *,
        context: Optional[PolicyContext] = None,
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
        retry_policy: Optional[RetryPolicy] = None,
    ) -> SupplierIngestionBatchResult:
        if retry_policy is not None:
            candidates = retry_call(lambda: tuple(source.list_candidates()), policy=retry_policy)
        else:
            candidates = tuple(source.list_candidates())
        return self.ingest_batch(
            candidates,
            context=context,
            persist=persist,
            access_context=access_context,
        )

    @staticmethod
    def _effective_actor(actor: Optional[str], access_context: Optional[AccessContext]) -> Optional[str]:
        return resolve_actor(actor, access_context)

    def accept_legal(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        version: str,
        actor: Optional[str],
        context: Optional[PolicyContext] = None,
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
        idempotency_key: Optional[str] = None,
    ) -> GovernanceServiceResult:
        replayed = self._restore_governance_receipt(
            action_name="accept_legal",
            idempotency_key=idempotency_key,
        )
        if replayed is not None:
            return replayed
        supplier = self._resolve_supplier(supplier_or_id)
        effective_actor = self._effective_actor(actor, access_context)
        result = self.legal_service.accept(
            supplier,
            version=version,
            actor=effective_actor,
            context=context,
            policy_engine=self.policy_engine,
            access_context=access_context,
        )
        return self._persist_governance_result(
            result,
            persist=persist,
            blocked_action_name="accept_legal",
            blocked_action_actor=effective_actor,
            idempotency_key=idempotency_key,
        )

    def withdraw_legal(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        actor: Optional[str],
        reason: Optional[str] = None,
        context: Optional[PolicyContext] = None,
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        supplier = self._resolve_supplier(supplier_or_id)
        effective_actor = self._effective_actor(actor, access_context)
        result = self.legal_service.withdraw(
            supplier,
            actor=effective_actor,
            reason=reason,
            context=context,
            policy_engine=self.policy_engine,
            access_context=access_context,
        )
        return self._persist_governance_result(
            result,
            persist=persist,
            blocked_action_name="withdraw_legal",
            blocked_action_actor=effective_actor,
        )

    def supersede_legal(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        pending_version: str,
        actor: Optional[str],
        reason: Optional[str] = None,
        context: Optional[PolicyContext] = None,
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        supplier = self._resolve_supplier(supplier_or_id)
        effective_actor = self._effective_actor(actor, access_context)
        result = self.legal_service.supersede(
            supplier,
            pending_version=pending_version,
            actor=effective_actor,
            reason=reason,
            context=context,
            policy_engine=self.policy_engine,
            access_context=access_context,
        )
        return self._persist_governance_result(
            result,
            persist=persist,
            blocked_action_name="supersede_legal",
            blocked_action_actor=effective_actor,
        )

    def assign_verification(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        assignee: str,
        actor: Optional[str],
        context: Optional[PolicyContext] = None,
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        supplier = self._resolve_supplier(supplier_or_id)
        effective_actor = self._effective_actor(actor, access_context)
        result = self.verification_service.assign(
            supplier,
            assignee=assignee,
            actor=effective_actor,
            context=context,
            policy_engine=self.policy_engine,
            access_context=access_context,
        )
        return self._persist_governance_result(
            result,
            persist=persist,
            blocked_action_name="assign_verification",
            blocked_action_actor=effective_actor,
        )

    def unassign_verification(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        actor: Optional[str],
        context: Optional[PolicyContext] = None,
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        supplier = self._resolve_supplier(supplier_or_id)
        effective_actor = self._effective_actor(actor, access_context)
        result = self.verification_service.unassign(
            supplier,
            actor=effective_actor,
            context=context,
            policy_engine=self.policy_engine,
            access_context=access_context,
        )
        return self._persist_governance_result(
            result,
            persist=persist,
            blocked_action_name="unassign_verification",
            blocked_action_actor=effective_actor,
        )

    def mark_verification_pending(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        actor: Optional[str],
        context: Optional[PolicyContext] = None,
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        supplier = self._resolve_supplier(supplier_or_id)
        effective_actor = self._effective_actor(actor, access_context)
        result = self.verification_service.mark_pending(
            supplier,
            actor=effective_actor,
            context=context,
            policy_engine=self.policy_engine,
            access_context=access_context,
        )
        return self._persist_governance_result(
            result,
            persist=persist,
            blocked_action_name="mark_verification_pending",
            blocked_action_actor=effective_actor,
        )

    def mark_verified(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        actor: Optional[str],
        context: Optional[PolicyContext] = None,
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
        idempotency_key: Optional[str] = None,
    ) -> GovernanceServiceResult:
        replayed = self._restore_governance_receipt(
            action_name="mark_verified",
            idempotency_key=idempotency_key,
        )
        if replayed is not None:
            return replayed
        supplier = self._resolve_supplier(supplier_or_id)
        effective_actor = self._effective_actor(actor, access_context)
        result = self.verification_service.mark_verified(
            supplier,
            actor=effective_actor,
            context=context,
            policy_engine=self.policy_engine,
            access_context=access_context,
        )
        return self._persist_governance_result(
            result,
            persist=persist,
            blocked_action_name="mark_verified",
            blocked_action_actor=effective_actor,
            idempotency_key=idempotency_key,
        )

    def mark_verification_failed(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        actor: Optional[str],
        reason: Optional[str] = None,
        context: Optional[PolicyContext] = None,
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        supplier = self._resolve_supplier(supplier_or_id)
        effective_actor = self._effective_actor(actor, access_context)
        result = self.verification_service.mark_failed(
            supplier,
            actor=effective_actor,
            reason=reason,
            context=context,
            policy_engine=self.policy_engine,
            access_context=access_context,
        )
        return self._persist_governance_result(
            result,
            persist=persist,
            blocked_action_name="mark_verification_failed",
            blocked_action_actor=effective_actor,
        )

    def mark_verification_needs_review(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        actor: Optional[str],
        reason: Optional[str] = None,
        context: Optional[PolicyContext] = None,
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        supplier = self._resolve_supplier(supplier_or_id)
        effective_actor = self._effective_actor(actor, access_context)
        result = self.verification_service.mark_needs_review(
            supplier,
            actor=effective_actor,
            reason=reason,
            context=context,
            policy_engine=self.policy_engine,
            access_context=access_context,
        )
        return self._persist_governance_result(
            result,
            persist=persist,
            blocked_action_name="mark_verification_needs_review",
            blocked_action_actor=effective_actor,
        )

    def set_verification_visibility(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        visibility: VerificationVisibility,
        actor: Optional[str],
        context: Optional[PolicyContext] = None,
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        supplier = self._resolve_supplier(supplier_or_id)
        effective_actor = self._effective_actor(actor, access_context)
        result = self.verification_service.set_visibility(
            supplier,
            target_visibility=visibility,
            actor=effective_actor,
            context=context,
            policy_engine=self.policy_engine,
            access_context=access_context,
        )
        return self._persist_governance_result(
            result,
            persist=persist,
            blocked_action_name="set_verification_visibility",
            blocked_action_actor=effective_actor,
        )

    def submit_for_review(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        actor: Optional[str],
        context: Optional[PolicyContext] = None,
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
        idempotency_key: Optional[str] = None,
    ) -> GovernanceServiceResult:
        replayed = self._restore_governance_receipt(
            action_name="submit_for_review",
            idempotency_key=idempotency_key,
        )
        if replayed is not None:
            return replayed
        supplier = self._resolve_supplier(supplier_or_id)
        effective_actor = self._effective_actor(actor, access_context)
        result = self.moderation_service.submit_for_review(
            supplier,
            actor=effective_actor,
            context=context,
            policy_engine=self.policy_engine,
            access_context=access_context,
        )
        return self._persist_governance_result(
            result,
            persist=persist,
            blocked_action_name="submit_for_review",
            blocked_action_actor=effective_actor,
            idempotency_key=idempotency_key,
        )

    def approve_moderation(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        actor: Optional[str],
        context: Optional[PolicyContext] = None,
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
        idempotency_key: Optional[str] = None,
    ) -> GovernanceServiceResult:
        replayed = self._restore_governance_receipt(
            action_name="approve_moderation",
            idempotency_key=idempotency_key,
        )
        if replayed is not None:
            return replayed
        supplier = self._resolve_supplier(supplier_or_id)
        effective_actor = self._effective_actor(actor, access_context)
        result = self.moderation_service.approve(
            supplier,
            actor=effective_actor,
            context=context,
            policy_engine=self.policy_engine,
            access_context=access_context,
        )
        return self._persist_governance_result(
            result,
            persist=persist,
            blocked_action_name="approve_moderation",
            blocked_action_actor=effective_actor,
            idempotency_key=idempotency_key,
        )

    def reject_moderation(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        actor: Optional[str],
        reason: Optional[str] = None,
        context: Optional[PolicyContext] = None,
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        supplier = self._resolve_supplier(supplier_or_id)
        effective_actor = self._effective_actor(actor, access_context)
        result = self.moderation_service.reject(
            supplier,
            actor=effective_actor,
            reason=reason,
            context=context,
            policy_engine=self.policy_engine,
            access_context=access_context,
        )
        return self._persist_governance_result(
            result,
            persist=persist,
            blocked_action_name="reject_moderation",
            blocked_action_actor=effective_actor,
        )

    def escalate_moderation(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        actor: Optional[str],
        reason: Optional[str] = None,
        context: Optional[PolicyContext] = None,
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        supplier = self._resolve_supplier(supplier_or_id)
        effective_actor = self._effective_actor(actor, access_context)
        result = self.moderation_service.escalate(
            supplier,
            actor=effective_actor,
            reason=reason,
            context=context,
            policy_engine=self.policy_engine,
            access_context=access_context,
        )
        return self._persist_governance_result(
            result,
            persist=persist,
            blocked_action_name="escalate_moderation",
            blocked_action_actor=effective_actor,
        )

    def activate_supplier(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        actor: Optional[str],
        context: Optional[PolicyContext] = None,
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
        idempotency_key: Optional[str] = None,
    ) -> TransitionResult:
        replayed = self._restore_transition_receipt(
            action_name="activate_supplier",
            idempotency_key=idempotency_key,
        )
        if replayed is not None:
            return replayed
        supplier = self._resolve_supplier(supplier_or_id)
        effective_actor = self._effective_actor(actor, access_context)
        result = self.lifecycle_service.activate(
            supplier,
            actor=effective_actor,
            context=context,
            policy_engine=self.policy_engine,
            access_context=access_context,
        )
        events = (
            self._lifecycle_events(result=result, actor=effective_actor)
            if result.allowed
            else (
                self._blocked_action_event(
                    supplier=result.supplier,
                    action_name="activate_supplier",
                    actor=effective_actor,
                    issues=result.issues,
                    source="engine.lifecycle",
                ),
            )
        )
        enriched = replace(result, events=events)
        if persist and self.repository:
            receipt = (
                build_transition_receipt(
                    idempotency_key=idempotency_key,
                    action_name="activate_supplier",
                    result=enriched,
                )
                if idempotency_key
                else None
            )
            if enriched.allowed:
                self.repository.save_supplier_with_events_and_receipt(
                    enriched.supplier,
                    events=enriched.events,
                    receipt=receipt,
                )
            else:
                self.repository.append_audit_events_with_receipt(enriched.events, receipt=receipt)
        return enriched

    def accept_pilot_terms(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        terms_version: str,
        actor: Optional[str],
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        supplier = self._resolve_supplier(supplier_or_id)
        effective_actor = self._effective_actor(actor, access_context)
        result = self.pilot_service.accept_terms(
            supplier,
            terms_version=terms_version,
            actor=effective_actor,
            access_context=access_context,
        )
        return self._persist_governance_result(
            result,
            persist=persist,
            blocked_action_name="accept_pilot_terms",
            blocked_action_actor=effective_actor,
        )

    def enable_pilot_access(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        pilot_name: str,
        terms_version: str,
        actor: Optional[str],
        context: Optional[PolicyContext] = None,
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        supplier = self._resolve_supplier(supplier_or_id)
        effective_actor = self._effective_actor(actor, access_context)
        result = self.pilot_service.enable_access(
            supplier,
            pilot_name=pilot_name,
            terms_version=terms_version,
            actor=effective_actor,
            context=context,
            access_context=access_context,
        )
        return self._persist_governance_result(
            result,
            persist=persist,
            blocked_action_name="enable_pilot_access",
            blocked_action_actor=effective_actor,
        )

    def disable_pilot_access(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        actor: Optional[str],
        reason: Optional[str],
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        supplier = self._resolve_supplier(supplier_or_id)
        effective_actor = self._effective_actor(actor, access_context)
        result = self.pilot_service.disable_access(
            supplier,
            actor=effective_actor,
            reason=reason,
            access_context=access_context,
        )
        return self._persist_governance_result(
            result,
            persist=persist,
            blocked_action_name="disable_pilot_access",
            blocked_action_actor=effective_actor,
        )

    def log_pilot_incident(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        severity: PilotIncidentSeverity,
        summary: str,
        actor: Optional[str],
        persist: bool = True,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        supplier = self._resolve_supplier(supplier_or_id)
        effective_actor = self._effective_actor(actor, access_context)
        result = self.pilot_service.log_incident(
            supplier,
            severity=severity,
            summary=summary,
            actor=effective_actor,
            access_context=access_context,
        )
        return self._persist_governance_result(
            result,
            persist=persist,
            blocked_action_name="log_pilot_incident",
            blocked_action_actor=effective_actor,
        )

    def _resolve_supplier(self, supplier_or_id: SupplierRecord | str) -> SupplierRecord:
        if isinstance(supplier_or_id, SupplierRecord):
            return supplier_or_id
        if self.repository is None:
            raise ValueError("A repository is required when resolving suppliers by ID.")
        supplier = self.repository.get_supplier(supplier_or_id)
        if supplier is None:
            raise KeyError(f"Supplier not found: {supplier_or_id}")
        return supplier

    def _persist_governance_result(
        self,
        result: GovernanceServiceResult,
        *,
        persist: bool,
        blocked_action_name: Optional[str] = None,
        blocked_action_actor: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> GovernanceServiceResult:
        final_result = result
        if not result.allowed and blocked_action_name:
            blocked_event = self._blocked_action_event(
                supplier=result.supplier,
                action_name=blocked_action_name,
                actor=blocked_action_actor,
                issues=result.issues,
                source="engine.governance",
            )
            final_result = replace(result, events=result.events + (blocked_event,))

        if not persist or self.repository is None:
            return final_result

        receipt = (
            build_governance_receipt(
                idempotency_key=idempotency_key,
                action_name=blocked_action_name or "governance_action",
                result=final_result,
            )
            if idempotency_key
            else None
        )

        if final_result.allowed:
            self.repository.save_supplier_with_events_and_receipt(
                final_result.supplier,
                events=final_result.events,
                receipt=receipt,
            )
            return final_result

        if final_result.events:
            self.repository.append_audit_events_with_receipt(final_result.events, receipt=receipt)
            return final_result
        if receipt is not None:
            self.repository.save_operation_receipt(receipt)
        return final_result

    def _blocked_action_event(
        self,
        *,
        supplier: SupplierRecord,
        action_name: str,
        actor: Optional[str],
        issues: tuple,
        source: str,
    ) -> GovernanceEventRecord:
        return self.authorizer.build_blocked_event(
            supplier=supplier,
            action_name=action_name,
            actor=actor,
            issues=issues,
            source=source,
        )

    def _get_operation_receipt(self, *, action_name: str, idempotency_key: Optional[str]):
        if not idempotency_key or self.repository is None:
            return None
        return self.repository.get_operation_receipt(idempotency_key, action_name=action_name)

    def _restore_ingestion_receipt(
        self,
        *,
        action_name: str,
        idempotency_key: Optional[str],
    ) -> Optional[SupplierIngestionResult]:
        receipt = self._get_operation_receipt(action_name=action_name, idempotency_key=idempotency_key)
        if receipt is None:
            return None
        existing = tuple(self.repository.list_suppliers()) if self.repository else ()
        return restore_ingestion_result(
            receipt,
            dedupe_engine=self.ingestion_service.dedupe_engine,
            existing_suppliers=existing,
        )

    def _restore_governance_receipt(
        self,
        *,
        action_name: str,
        idempotency_key: Optional[str],
    ) -> Optional[GovernanceServiceResult]:
        receipt = self._get_operation_receipt(action_name=action_name, idempotency_key=idempotency_key)
        if receipt is None:
            return None
        return restore_governance_result(receipt)

    def _restore_transition_receipt(
        self,
        *,
        action_name: str,
        idempotency_key: Optional[str],
    ) -> Optional[TransitionResult]:
        receipt = self._get_operation_receipt(action_name=action_name, idempotency_key=idempotency_key)
        if receipt is None:
            return None
        return restore_transition_result(receipt)

    def _mask_audit_event(
        self,
        event: GovernanceEventRecord,
        *,
        access_context: Optional[AccessContext],
    ) -> GovernanceEventRecord:
        if access_context is None:
            return event
        if (
            event.event_type in self._SENSITIVE_VERIFICATION_EVENT_TYPES
            and not self.authorizer.can(
                GovernancePermission.VIEW_SENSITIVE_VERIFICATION_DETAILS,
                access_context=access_context,
            )
        ):
            return replace(
                event,
                actor=None,
                summary="Verification detail is restricted.",
                metadata={"redacted": True},
            )
        if (
            event.event_type is GovernanceEventType.GOVERNANCE_ACTION_BLOCKED
            and not self.authorizer.can(
                GovernancePermission.VIEW_AUDIT_INTERNALS,
                access_context=access_context,
            )
        ):
            return replace(
                event,
                actor=None,
                summary="Audit detail is restricted.",
                metadata={"redacted": True},
            )
        return event

    _SENSITIVE_VERIFICATION_EVENT_TYPES = frozenset(
        {
            GovernanceEventType.VERIFICATION_ASSIGNED,
            GovernanceEventType.VERIFICATION_UNASSIGNED,
            GovernanceEventType.VERIFICATION_PENDING,
            GovernanceEventType.VERIFICATION_VERIFIED,
            GovernanceEventType.VERIFICATION_FAILED,
            GovernanceEventType.VERIFICATION_NEEDS_REVIEW,
            GovernanceEventType.VERIFICATION_VISIBILITY_CHANGED,
        }
    )

    @staticmethod
    def present_ingestion_result(
        result: SupplierIngestionResult,
        *,
        action_name: str = "ingest_supplier",
    ) -> EngineActionResult:
        if result.accepted_for_staging:
            status = "success"
        elif result.validation_result.has_errors:
            status = "validation_error"
        else:
            status = "policy_violation"
        return EngineActionResult(
            action_name=action_name,
            status=status,
            allowed=result.accepted_for_staging,
            supplier=result.supplier,
            issues=result.validation_result.issues,
            events=result.events,
            source_result_type="ingestion",
            metadata={
                "policy_outcome": result.outcome.value,
                "decision_codes": [decision.code for decision in result.decisions],
                "accepted_for_staging": result.accepted_for_staging,
            },
        )

    @staticmethod
    def present_governance_result(
        result: GovernanceServiceResult,
        *,
        action_name: str,
    ) -> EngineActionResult:
        return EngineActionResult(
            action_name=action_name,
            status=("success" if result.allowed else SupplierSeedEngine._classify_issue_status(result.issues)),
            allowed=result.allowed,
            supplier=result.supplier,
            issues=result.issues,
            events=result.events,
            source_result_type="governance",
            metadata={
                "issue_codes": [issue.code for issue in result.issues],
            },
        )

    @staticmethod
    def present_transition_result(
        result: TransitionResult,
        *,
        action_name: str,
    ) -> EngineActionResult:
        return EngineActionResult(
            action_name=action_name,
            status=("success" if result.allowed else SupplierSeedEngine._classify_issue_status(result.issues)),
            allowed=result.allowed,
            supplier=result.supplier,
            issues=result.issues,
            events=result.events,
            source_result_type="transition",
            metadata={
                "from_status": result.from_status.value,
                "to_status": result.to_status.value,
                "issue_codes": [issue.code for issue in result.issues],
            },
        )

    @staticmethod
    def present_system_failure(
        *,
        action_name: str,
        error_message: str,
        supplier: Optional[SupplierRecord] = None,
    ) -> EngineActionResult:
        return EngineActionResult(
            action_name=action_name,
            status="system_failure",
            allowed=False,
            supplier=supplier,
            source_result_type="system",
            metadata={"error_message": error_message},
        )

    @staticmethod
    def _classify_issue_status(issues: tuple) -> str:
        if any(getattr(issue, "code", "").startswith("supplier.") for issue in issues):
            return "validation_error"
        return "policy_violation"

    def get_supplier_record(self, supplier_or_id: SupplierRecord | str) -> SupplierRecord:
        return self._resolve_supplier(supplier_or_id)

    def list_audit_events(
        self,
        supplier_or_id: Optional[SupplierRecord | str] = None,
        *,
        access_context: Optional[AccessContext] = None,
    ) -> tuple[GovernanceEventRecord, ...]:
        if self.repository is None:
            raise ValueError("A repository is required when listing audit events.")
        if supplier_or_id is None:
            events = tuple(self.repository.list_audit_events())
        else:
            supplier_id = supplier_or_id.identity.supplier_id if isinstance(supplier_or_id, SupplierRecord) else supplier_or_id
            events = tuple(self.repository.list_audit_events(supplier_id=supplier_id))
        if access_context is None:
            return events
        return tuple(self._mask_audit_event(event, access_context=access_context) for event in events)

    def list_supplier_summaries(
        self,
        *,
        context: Optional[PolicyContext] = None,
        queue: Optional[str] = None,
        search: Optional[str] = None,
        assigned_to: Optional[str] = None,
        region_code: Optional[str] = None,
        lifecycle_status: Optional[LifecycleStatus] = None,
        moderation_status: Optional[ModerationStatus] = None,
        verification_status: Optional[VerificationStatus] = None,
        mode: Optional[SupplierMode] = None,
        seeded_source: Optional[str] = None,
        access_context: Optional[AccessContext] = None,
    ):
        consumption = self._require_consumption_service()
        return consumption.list_supplier_summaries(
            context=context,
            queue=queue,
            search=search,
            assigned_to=assigned_to,
            region_code=region_code,
            lifecycle_status=lifecycle_status,
            moderation_status=moderation_status,
            verification_status=verification_status,
            mode=mode,
            seeded_source=seeded_source,
            access_context=access_context,
        )

    def search_suppliers(
        self,
        *,
        context: Optional[PolicyContext] = None,
        search: Optional[str] = None,
        assigned_to: Optional[str] = None,
        region_code: Optional[str] = None,
        lifecycle_status: Optional[LifecycleStatus] = None,
        moderation_status: Optional[ModerationStatus] = None,
        verification_status: Optional[VerificationStatus] = None,
        mode: Optional[SupplierMode] = None,
        seeded_source: Optional[str] = None,
        access_context: Optional[AccessContext] = None,
    ):
        consumption = self._require_consumption_service()
        return consumption.search_suppliers(
            context=context,
            search=search,
            assigned_to=assigned_to,
            region_code=region_code,
            lifecycle_status=lifecycle_status,
            moderation_status=moderation_status,
            verification_status=verification_status,
            mode=mode,
            seeded_source=seeded_source,
            access_context=access_context,
        )

    def list_moderation_queue(
        self,
        *,
        queue_bucket: str = "open_cases",
        context: Optional[PolicyContext] = None,
        access_context: Optional[AccessContext] = None,
    ):
        consumption = self._require_consumption_service()
        return consumption.list_moderation_queue(
            queue_bucket=queue_bucket,
            context=context,
            access_context=access_context,
        )

    def list_verification_queue(
        self,
        *,
        queue_bucket: str = "eligible",
        context: Optional[PolicyContext] = None,
        access_context: Optional[AccessContext] = None,
    ):
        consumption = self._require_consumption_service()
        return consumption.list_verification_queue(
            queue_bucket=queue_bucket,
            context=context,
            access_context=access_context,
        )

    def get_supplier_workspace(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        context: Optional[PolicyContext] = None,
        access_context: Optional[AccessContext] = None,
    ):
        consumption = self._require_consumption_service()
        return consumption.get_supplier_workspace(
            supplier_or_id,
            context=context,
            access_context=access_context,
        )

    def get_supplier_detail(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        context: Optional[PolicyContext] = None,
        access_context: Optional[AccessContext] = None,
    ):
        consumption = self._require_consumption_service()
        return consumption.get_supplier_detail(
            supplier_or_id,
            context=context,
            access_context=access_context,
        )

    def get_audit_timeline(
        self,
        supplier_or_id: Optional[SupplierRecord | str] = None,
        *,
        event_type: Optional[GovernanceEventType] = None,
        actor: Optional[str] = None,
        access_context: Optional[AccessContext] = None,
        limit: Optional[int] = None,
    ):
        consumption = self._require_consumption_service()
        return consumption.get_audit_timeline(
            supplier_or_id,
            event_type=event_type,
            actor=actor,
            access_context=access_context,
            limit=limit,
        )

    def get_pilot_release_summary(
        self,
        *,
        pilot_name: Optional[str] = None,
        market_code: str = "PH",
        access_context: Optional[AccessContext] = None,
    ):
        consumption = self._require_consumption_service()
        return consumption.get_pilot_release_summary(
            pilot_name=pilot_name,
            market_code=market_code,
            access_context=access_context,
        )

    def get_pilot_runbook(self):
        consumption = self._require_consumption_service()
        return consumption.get_pilot_runbook()

    def _require_consumption_service(self) -> SupplierConsumptionService:
        if self.consumption_service is None:
            raise ValueError("A repository is required when preparing supplier workflow views.")
        return self.consumption_service

    @staticmethod
    def _lifecycle_events(
        *,
        result: TransitionResult,
        actor: Optional[str],
    ) -> tuple[GovernanceEventRecord, ...]:
        if not result.allowed:
            return ()
        return (
            GovernanceEventRecord.new(
                supplier_id=result.supplier.identity.supplier_id,
                event_type=GovernanceEventType.LIFECYCLE_STATUS_CHANGED,
                occurred_at=result.supplier.updated_at,
                actor=actor,
                source="engine.lifecycle",
                summary=(
                    f"Supplier lifecycle changed from {result.from_status.value} to {result.to_status.value}."
                ),
                metadata={
                    "from_status": result.from_status.value,
                    "to_status": result.to_status.value,
                },
            ),
        )
