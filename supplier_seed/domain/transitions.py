from dataclasses import dataclass, replace
from datetime import datetime
from typing import Tuple, Optional
from supplier_seed.domain.enums import LifecycleStatus, GovernanceEventType
from supplier_seed.domain.validation import ValidationIssue
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.policy.rules import SupplierPolicyEngine, PolicyContext

@dataclass(frozen=True)
class TransitionResult:
    allowed: bool
    supplier: object
    issues: Tuple[ValidationIssue, ...] = ()
    events: tuple = ()

def evaluate_lifecycle_transition(supplier, target_status, context: PolicyContext, policy_engine: Optional[SupplierPolicyEngine] = None):
    target_status = LifecycleStatus(target_status) if isinstance(target_status, str) else target_status
    engine = policy_engine or SupplierPolicyEngine()
    issues = []
    if supplier.lifecycle_status == LifecycleStatus.ARCHIVED:
        issues.append(ValidationIssue("transition.lifecycle.archived_terminal"))
    elif supplier.lifecycle_status == LifecycleStatus.REJECTED and target_status == LifecycleStatus.ACTIVE:
        issues.append(ValidationIssue("transition.lifecycle.path_blocked"))
    if target_status == LifecycleStatus.ACTIVE:
        issues.extend(engine.activation_issues(supplier, context))
    return TransitionResult(not issues, supplier, tuple(issues))

def apply_lifecycle_transition(supplier, target_status, actor=None, context=None, policy_engine=None):
    result = evaluate_lifecycle_transition(supplier, target_status, context, policy_engine)
    if not result.allowed:
        return result
    target_status = LifecycleStatus(target_status) if isinstance(target_status, str) else target_status
    updated = replace(supplier, lifecycle_status=target_status, updated_by=actor, updated_at=datetime.utcnow(), activated_at=(datetime.utcnow() if target_status == LifecycleStatus.ACTIVE else supplier.activated_at))
    event = GovernanceEventRecord.for_supplier(updated.supplier_id, GovernanceEventType.LIFECYCLE_CHANGED, actor=actor)
    return TransitionResult(True, updated, (), (event,))
