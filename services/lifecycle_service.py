"""Lifecycle service wrappers that enforce permissions before domain transitions."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from supplier_seed.domain.enums import LifecycleStatus
from supplier_seed.domain.models import SupplierRecord
from supplier_seed.domain.transitions import TransitionResult, apply_lifecycle_transition
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine
from supplier_seed.services.permissions import (
    AccessContext,
    GovernanceAuthorizer,
    GovernancePermission,
    resolve_actor,
)


class LifecycleService:
    def __init__(self, *, authorizer: Optional[GovernanceAuthorizer] = None) -> None:
        self.authorizer = authorizer or GovernanceAuthorizer()

    def activate(
        self,
        supplier: SupplierRecord,
        *,
        actor: Optional[str],
        at: Optional[datetime] = None,
        context: Optional[PolicyContext] = None,
        policy_engine: Optional[SupplierPolicyEngine] = None,
        access_context: Optional[AccessContext] = None,
    ) -> TransitionResult:
        effective_actor = resolve_actor(actor, access_context)
        permission_result = self.authorizer.authorize(
            GovernancePermission.ACTIVATE_SUPPLIER,
            access_context=access_context,
        )
        if not permission_result.allowed:
            return TransitionResult(
                allowed=False,
                supplier=supplier,
                from_status=supplier.lifecycle_status,
                to_status=LifecycleStatus.ACTIVE,
                issues=permission_result.issues,
            )
        return apply_lifecycle_transition(
            supplier,
            target_status=LifecycleStatus.ACTIVE,
            actor=effective_actor,
            at=at,
            context=context,
            policy_engine=policy_engine,
        )
