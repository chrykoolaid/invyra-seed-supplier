from dataclasses import dataclass
from typing import Optional, Tuple
from supplier_seed.domain.enums import PolicyOutcome, SupplierAction, SupplierMode, LifecycleStatus, LegalAcceptanceState, ModerationStatus
from supplier_seed.domain.validation import ValidationIssue

@dataclass(frozen=True)
class PolicyContext:
    region_code: Optional[str] = None
    market_code: str = "PH"
    pilot_enabled: bool = False
    allow_seeded_supplier_creation: bool = True
    require_region_for_supplier: bool = False
    require_legal_acceptance_for_manual: bool = True
    require_moderation_for_seeded_activation: bool = True
    require_actor_for_moderation_actions: bool = False
    require_reason_for_moderation_rejection: bool = False
    require_reason_for_moderation_escalation: bool = False
    require_actor_for_legal_actions: bool = False
    require_reason_for_legal_withdrawal: bool = False
    require_reason_for_legal_supersede: bool = False
    allow_seeded_legal_acceptance: bool = False
    require_actor_for_verification_actions: bool = False
    require_assignment_for_verification_decisions: bool = False
    require_assignment_match_for_verification_decisions: bool = False
    require_verified_status_for_visible_verification: bool = False

@dataclass(frozen=True)
class PolicyDecision:
    code: str
    outcome: PolicyOutcome
    message: str = ""

@dataclass(frozen=True)
class PolicyResult:
    outcome: PolicyOutcome
    decisions: Tuple[PolicyDecision, ...] = ()

class SupplierPolicyEngine:
    def evaluate_action(self, action, context: PolicyContext, supplier=None):
        action = SupplierAction(action) if isinstance(action, str) else action
        if action == SupplierAction.CREATE_SEEDED and not context.allow_seeded_supplier_creation:
            return PolicyResult(PolicyOutcome.BLOCKED, (PolicyDecision("policy.seeded_creation.blocked", PolicyOutcome.BLOCKED),))
        return PolicyResult(PolicyOutcome.ALLOWED, (PolicyDecision("policy.allowed", PolicyOutcome.ALLOWED),))

    def activation_issues(self, supplier, context: PolicyContext):
        issues = []
        if supplier.lifecycle_status == LifecycleStatus.REJECTED:
            issues.append(ValidationIssue("transition.lifecycle.path_blocked"))
        if supplier.lifecycle_status == LifecycleStatus.ARCHIVED:
            issues.append(ValidationIssue("transition.lifecycle.archived_terminal"))
        if supplier.mode == SupplierMode.MANUAL and context.require_legal_acceptance_for_manual and supplier.legal_acceptance_state != LegalAcceptanceState.ACCEPTED:
            issues.append(ValidationIssue("policy.activation.blocked.legal_missing"))
        if supplier.mode == SupplierMode.SEEDED and context.require_moderation_for_seeded_activation and supplier.moderation_status != ModerationStatus.APPROVED:
            issues.append(ValidationIssue("policy.activation.blocked.moderation_missing"))
        return tuple(issues)
