from dataclasses import dataclass
from typing import Optional, Tuple

from supplier_seed.domain.enums import DedupeMatchClassification, GovernanceEventType, PolicyOutcome, SupplierAction, SupplierMode
from supplier_seed.domain.models import SupplierRecord, SupplierRegionContext
from supplier_seed.domain.validation import ValidationIssue, validate_supplier
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.intelligence.dedupe import SupplierDedupeEngine
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine, PolicyDecision

@dataclass(frozen=True)
class SupplierCandidateInput:
    name: str
    mode: SupplierMode
    region_context: SupplierRegionContext
    seeded_source: Optional[str] = None
    seeded_source_reference: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    website_url: Optional[str] = None
    tax_identifier: Optional[str] = None
    created_by: Optional[str] = None

@dataclass(frozen=True)
class IngestionDecision:
    code: str
    outcome: PolicyOutcome
    message: str = ""

@dataclass(frozen=True)
class SupplierIngestionResult:
    outcome: PolicyOutcome
    supplier: Optional[SupplierRecord]
    accepted_for_staging: bool
    decisions: Tuple[IngestionDecision, ...]
    events: tuple = ()

@dataclass(frozen=True)
class SupplierIngestionBatchResult:
    results: Tuple[SupplierIngestionResult, ...]

    @property
    def allowed_count(self):
        return sum(1 for result in self.results if result.outcome == PolicyOutcome.ALLOWED)

    @property
    def warning_count(self):
        return sum(1 for result in self.results if result.outcome == PolicyOutcome.WARNING)

    @property
    def review_count(self):
        return sum(1 for result in self.results if result.outcome == PolicyOutcome.REQUIRES_REVIEW)

    @property
    def blocked_count(self):
        return sum(1 for result in self.results if result.outcome == PolicyOutcome.BLOCKED)

class SupplierIngestionService:
    def __init__(self, policy_engine=None, dedupe_engine=None):
        self.policy_engine = policy_engine or SupplierPolicyEngine()
        self.dedupe_engine = dedupe_engine or SupplierDedupeEngine()

    def _build_supplier(self, candidate):
        mode = SupplierMode(candidate.mode)
        common = dict(
            region_context=candidate.region_context,
            contact_email=candidate.contact_email,
            contact_phone=candidate.contact_phone,
            website_url=candidate.website_url,
            tax_identifier=candidate.tax_identifier,
            created_by=candidate.created_by,
        )
        if mode == SupplierMode.SEEDED:
            return SupplierRecord.seeded_draft(candidate.name, candidate.seeded_source or "seed", candidate.seeded_source_reference or candidate.name, **common)
        return SupplierRecord.manual_draft(candidate.name, **common)

    def ingest_supplier(self, candidate, existing_suppliers=(), context=None):
        context = context or PolicyContext(region_code=candidate.region_context.region_code, market_code=candidate.region_context.market_code, pilot_enabled=candidate.region_context.pilot_enabled)
        action = SupplierAction.CREATE_SEEDED if SupplierMode(candidate.mode) == SupplierMode.SEEDED else SupplierAction.CREATE_MANUAL
        policy = self.policy_engine.evaluate_action(action=action, context=context)
        if policy.outcome == PolicyOutcome.BLOCKED:
            return SupplierIngestionResult(PolicyOutcome.BLOCKED, None, False, tuple(IngestionDecision(d.code, d.outcome, d.message) for d in policy.decisions), ())
        supplier = self._build_supplier(candidate)
        validation = validate_supplier(supplier, context=context, policy_engine=self.policy_engine)
        if validation.has_errors:
            return SupplierIngestionResult(PolicyOutcome.BLOCKED, supplier, False, tuple(IngestionDecision(i.code, PolicyOutcome.BLOCKED, i.message) for i in validation.issues), ())
        dedupe = self.dedupe_engine.evaluate_supplier(supplier, existing_suppliers)
        decisions = []
        outcome = PolicyOutcome.ALLOWED
        if dedupe.best_candidate:
            if dedupe.best_candidate.classification == DedupeMatchClassification.EXACT_DUPLICATE:
                decisions.append(IngestionDecision("ingestion.dedupe.exact_duplicate", PolicyOutcome.BLOCKED))
                outcome = PolicyOutcome.BLOCKED
            elif dedupe.best_candidate.classification == DedupeMatchClassification.LIKELY_DUPLICATE:
                decisions.append(IngestionDecision("ingestion.dedupe.likely_duplicate", PolicyOutcome.REQUIRES_REVIEW))
                outcome = PolicyOutcome.REQUIRES_REVIEW
            else:
                decisions.append(IngestionDecision("ingestion.dedupe.possible_duplicate", PolicyOutcome.WARNING))
                outcome = PolicyOutcome.WARNING
        if not decisions:
            decisions.append(IngestionDecision("ingestion.accepted", PolicyOutcome.ALLOWED))
        accepted = outcome != PolicyOutcome.BLOCKED
        events = (GovernanceEventRecord.for_supplier(supplier.supplier_id, GovernanceEventType.SUPPLIER_STAGED, actor=candidate.created_by),) if accepted else ()
        return SupplierIngestionResult(outcome, supplier, accepted, tuple(decisions), events)

    def ingest_batch(self, candidates, existing_suppliers=(), context=None):
        suppliers = list(existing_suppliers)
        results = []
        for candidate in candidates:
            result = self.ingest_supplier(candidate, suppliers, context)
            results.append(result)
            if result.accepted_for_staging and result.supplier:
                suppliers.append(result.supplier)
        return SupplierIngestionBatchResult(tuple(results))
