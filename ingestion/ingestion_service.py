"""Supplier ingestion orchestration.

Part D composes the existing domain, policy, validation, and dedupe layers into a single
 deterministic ingestion flow. It does not perform real database integration.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Iterable, Optional

from supplier_seed.domain.enums import (
    DedupeMatchClassification,
    GovernanceEventType,
    PolicyOutcome,
    SupplierAction,
    SupplierMode,
    ValidationSeverity,
)
from supplier_seed.domain.models import SupplierIdentity, SupplierRecord, SupplierRegionContext
from supplier_seed.domain.validation import ValidationResult, validate_supplier
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.intelligence.dedupe import DedupeEvaluation, SupplierDedupeEngine
from supplier_seed.policy.rules import PolicyContext, PolicyDecision, PolicyResult, SupplierPolicyEngine
from supplier_seed.services.permissions import (
    AccessContext,
    GovernanceAuthorizer,
    GovernancePermission,
    resolve_actor,
)


@dataclass(frozen=True, slots=True)
class SupplierCandidateInput:
    name: str
    mode: SupplierMode
    region_context: SupplierRegionContext
    created_by: Optional[str] = None
    seeded_source: Optional[str] = None
    seeded_source_reference: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    website_url: Optional[str] = None
    tax_identifier: Optional[str] = None
    supplier_code: Optional[str] = None
    external_reference: Optional[str] = None


@dataclass(frozen=True, slots=True)
class IngestionDecision:
    outcome: PolicyOutcome
    code: str
    message: str
    field: Optional[str] = None
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SupplierIngestionResult:
    supplier: SupplierRecord
    outcome: PolicyOutcome
    accepted_for_staging: bool
    decisions: tuple[IngestionDecision, ...]
    policy_result: PolicyResult
    validation_result: ValidationResult
    dedupe_evaluation: DedupeEvaluation
    events: tuple[GovernanceEventRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class SupplierIngestionBatchResult:
    results: tuple[SupplierIngestionResult, ...]

    @property
    def allowed_count(self) -> int:
        return sum(1 for item in self.results if item.outcome is PolicyOutcome.ALLOWED)

    @property
    def warning_count(self) -> int:
        return sum(1 for item in self.results if item.outcome is PolicyOutcome.ALLOWED_WITH_WARNING)

    @property
    def review_count(self) -> int:
        return sum(1 for item in self.results if item.outcome is PolicyOutcome.REQUIRES_REVIEW)

    @property
    def blocked_count(self) -> int:
        return sum(1 for item in self.results if item.outcome is PolicyOutcome.BLOCKED)


class SupplierIngestionService:
    def __init__(
        self,
        *,
        policy_engine: Optional[SupplierPolicyEngine] = None,
        dedupe_engine: Optional[SupplierDedupeEngine] = None,
        authorizer: Optional[GovernanceAuthorizer] = None,
    ) -> None:
        self.policy_engine = policy_engine or SupplierPolicyEngine()
        self.dedupe_engine = dedupe_engine or SupplierDedupeEngine()
        self.authorizer = authorizer or GovernanceAuthorizer()

    def ingest_supplier(
        self,
        candidate: SupplierCandidateInput,
        *,
        existing_suppliers: Iterable[SupplierRecord] = (),
        context: Optional[PolicyContext] = None,
        access_context: Optional[AccessContext] = None,
    ) -> SupplierIngestionResult:
        supplier = self._build_supplier(candidate)
        resolved_context = context or PolicyContext(region_code=supplier.region_context.region_code)
        action = SupplierAction.CREATE_SEEDED if supplier.is_seeded else SupplierAction.CREATE_MANUAL
        permission = (
            GovernancePermission.INGEST_SEEDED_SUPPLIER
            if supplier.is_seeded
            else GovernancePermission.CREATE_MANUAL_SUPPLIER
        )
        permission_result = self.authorizer.authorize(permission, access_context=access_context)
        if not permission_result.allowed:
            blocked_policy = PolicyResult(
                outcome=PolicyOutcome.BLOCKED,
                decisions=tuple(
                    PolicyDecision(
                        outcome=PolicyOutcome.BLOCKED,
                        code=issue.code,
                        message=issue.message,
                        field=issue.field,
                        metadata={"permission": permission.value},
                    )
                    for issue in permission_result.issues
                ),
            )
            dedupe_evaluation = self.dedupe_engine.evaluate_supplier(supplier, ())
            blocked_event = self.authorizer.build_blocked_event(
                supplier=supplier,
                action_name=permission.value,
                actor=resolve_actor(candidate.created_by, access_context),
                issues=permission_result.issues,
                source="services.ingestion.permissions",
            )
            decisions = self._decisions_from_policy(blocked_policy)
            return SupplierIngestionResult(
                supplier=supplier,
                outcome=PolicyOutcome.BLOCKED,
                accepted_for_staging=False,
                decisions=decisions,
                policy_result=blocked_policy,
                validation_result=ValidationResult(),
                dedupe_evaluation=dedupe_evaluation,
                events=(blocked_event,),
            )
        policy_result = self.policy_engine.evaluate_action(
            action=action,
            supplier=supplier,
            context=resolved_context,
        )
        validation_result = validate_supplier(
            supplier,
            context=resolved_context,
            policy_engine=self.policy_engine,
        )
        dedupe_evaluation = self.dedupe_engine.evaluate_supplier(supplier, existing_suppliers)
        decisions = (
            self._decisions_from_policy(policy_result)
            + self._decisions_from_validation(validation_result)
            + self._decisions_from_dedupe(dedupe_evaluation)
        )
        outcome = self._resolve_outcome(
            policy_result=policy_result,
            validation_result=validation_result,
            dedupe_evaluation=dedupe_evaluation,
        )
        events = self._events_for_result(supplier=supplier, outcome=outcome)
        return SupplierIngestionResult(
            supplier=supplier,
            outcome=outcome,
            accepted_for_staging=outcome is not PolicyOutcome.BLOCKED,
            decisions=decisions,
            policy_result=policy_result,
            validation_result=validation_result,
            dedupe_evaluation=dedupe_evaluation,
            events=events,
        )

    def ingest_batch(
        self,
        candidates: Iterable[SupplierCandidateInput],
        *,
        existing_suppliers: Iterable[SupplierRecord] = (),
        context: Optional[PolicyContext] = None,
        access_context: Optional[AccessContext] = None,
    ) -> SupplierIngestionBatchResult:
        staged_suppliers = list(existing_suppliers)
        results: list[SupplierIngestionResult] = []
        for candidate in candidates:
            result = self.ingest_supplier(candidate, existing_suppliers=tuple(staged_suppliers), context=context, access_context=access_context)
            results.append(result)
            if result.accepted_for_staging:
                staged_suppliers.append(result.supplier)
        return SupplierIngestionBatchResult(results=tuple(results))

    @staticmethod
    def _build_supplier(candidate: SupplierCandidateInput) -> SupplierRecord:
        identity = SupplierIdentity.new(
            supplier_code=candidate.supplier_code,
            external_reference=candidate.external_reference,
        )
        common = dict(
            name=candidate.name,
            region_context=candidate.region_context,
            created_by=candidate.created_by,
            identity=identity,
            contact_email=candidate.contact_email,
            contact_phone=candidate.contact_phone,
            website_url=candidate.website_url,
            tax_identifier=candidate.tax_identifier,
        )
        if candidate.mode is SupplierMode.MANUAL:
            return SupplierRecord.manual_draft(**common)
        if candidate.mode is SupplierMode.SEEDED:
            return SupplierRecord.seeded_draft(
                seeded_source=candidate.seeded_source or "",
                seeded_source_reference=candidate.seeded_source_reference or "",
                **common,
            )
        raise ValueError(f"Unsupported supplier mode for ingestion: {candidate.mode!r}")

    @staticmethod
    def _decisions_from_policy(result: PolicyResult) -> tuple[IngestionDecision, ...]:
        return tuple(
            IngestionDecision(
                outcome=decision.outcome,
                code=decision.code,
                message=decision.message,
                field=decision.field,
                metadata=decision.metadata,
            )
            for decision in result.decisions
        )

    @staticmethod
    def _decisions_from_validation(result: ValidationResult) -> tuple[IngestionDecision, ...]:
        decisions: list[IngestionDecision] = []
        for issue in result.issues:
            mapped_outcome = PolicyOutcome.BLOCKED if issue.severity is ValidationSeverity.ERROR else PolicyOutcome.ALLOWED_WITH_WARNING
            decisions.append(
                IngestionDecision(
                    outcome=mapped_outcome,
                    code=issue.code,
                    message=issue.message,
                    field=issue.field,
                    metadata={"severity": issue.severity.value},
                )
            )
        return tuple(decisions)

    @staticmethod
    def _decisions_from_dedupe(result: DedupeEvaluation) -> tuple[IngestionDecision, ...]:
        best_candidate = result.best_candidate
        if best_candidate is None:
            return ()

        if best_candidate.classification is DedupeMatchClassification.EXACT_DUPLICATE:
            return (
                IngestionDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code="ingestion.dedupe.exact_duplicate",
                    field=None,
                    message="Candidate matches an existing supplier exactly and cannot be ingested as a new supplier.",
                    metadata={
                        "matched_supplier_id": best_candidate.supplier.identity.supplier_id,
                        "score": best_candidate.score,
                    },
                ),
            )
        if best_candidate.classification is DedupeMatchClassification.LIKELY_DUPLICATE:
            return (
                IngestionDecision(
                    outcome=PolicyOutcome.REQUIRES_REVIEW,
                    code="ingestion.dedupe.likely_duplicate",
                    field=None,
                    message="Candidate is likely a duplicate and requires operator review before continuing.",
                    metadata={
                        "matched_supplier_id": best_candidate.supplier.identity.supplier_id,
                        "score": best_candidate.score,
                    },
                ),
            )
        if best_candidate.classification is DedupeMatchClassification.POSSIBLE_DUPLICATE:
            return (
                IngestionDecision(
                    outcome=PolicyOutcome.ALLOWED_WITH_WARNING,
                    code="ingestion.dedupe.possible_duplicate",
                    field=None,
                    message="Candidate may be a duplicate. Continue with caution and verify before activation.",
                    metadata={
                        "matched_supplier_id": best_candidate.supplier.identity.supplier_id,
                        "score": best_candidate.score,
                    },
                ),
            )
        return ()

    @staticmethod
    def _resolve_outcome(
        *,
        policy_result: PolicyResult,
        validation_result: ValidationResult,
        dedupe_evaluation: DedupeEvaluation,
    ) -> PolicyOutcome:
        outcome = policy_result.outcome
        if validation_result.has_errors:
            outcome = PolicyOutcome.BLOCKED
        elif validation_result.has_warnings and outcome is PolicyOutcome.ALLOWED:
            outcome = PolicyOutcome.ALLOWED_WITH_WARNING

        best_candidate = dedupe_evaluation.best_candidate
        if best_candidate is not None:
            if best_candidate.classification is DedupeMatchClassification.EXACT_DUPLICATE:
                return PolicyOutcome.BLOCKED
            if best_candidate.classification is DedupeMatchClassification.LIKELY_DUPLICATE and outcome is not PolicyOutcome.BLOCKED:
                return PolicyOutcome.REQUIRES_REVIEW
            if best_candidate.classification is DedupeMatchClassification.POSSIBLE_DUPLICATE and outcome is PolicyOutcome.ALLOWED:
                return PolicyOutcome.ALLOWED_WITH_WARNING
        return outcome

    @staticmethod
    def _events_for_result(*, supplier: SupplierRecord, outcome: PolicyOutcome) -> tuple[GovernanceEventRecord, ...]:
        if outcome is PolicyOutcome.BLOCKED:
            return ()
        return (
            GovernanceEventRecord.new(
                supplier_id=supplier.identity.supplier_id,
                event_type=GovernanceEventType.SUPPLIER_STAGED,
                occurred_at=supplier.updated_at,
                actor=supplier.updated_by,
                source="ingestion.service",
                summary="Supplier candidate was accepted into staging.",
                metadata={
                    "mode": supplier.mode.value,
                    "outcome": outcome.value,
                    "region_code": supplier.region_context.region_code,
                    "market_code": supplier.region_context.market_code,
                    "seeded_source": supplier.seeded_source,
                    "seeded_source_reference": supplier.seeded_source_reference,
                },
            ),
        )
