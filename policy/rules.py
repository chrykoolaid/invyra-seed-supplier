"""Structured policy decisions for governed supplier seed behavior."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Optional

from supplier_seed.domain.enums import (
    LegalAcceptanceState,
    LifecycleStatus,
    ModerationStatus,
    PolicyOutcome,
    SupplierAction,
    SupplierMode,
    VerificationStatus,
    VerificationVisibility,
)
from supplier_seed.domain.models import SupplierRecord


OUTCOME_PRIORITY = {
    PolicyOutcome.ALLOWED: 0,
    PolicyOutcome.ALLOWED_WITH_WARNING: 1,
    PolicyOutcome.REQUIRES_REVIEW: 2,
    PolicyOutcome.BLOCKED: 3,
}


def _normalize_code(value: Optional[str], *, default: Optional[str] = None) -> Optional[str]:
    if value is None:
        return default
    cleaned = value.strip().upper()
    return cleaned or default


def _clean_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


@dataclass(frozen=True, slots=True)
class PolicyContext:
    region_code: Optional[str] = None
    market_code: str = "PH"
    pilot_enabled: bool = False
    allow_seeded_supplier_creation: bool = False
    require_region_for_supplier: bool = True
    require_legal_acceptance_for_manual: bool = True
    require_moderation_for_seeded_activation: bool = True
    block_failed_verification_activation: bool = True
    require_actor_for_moderation_actions: bool = True
    require_reason_for_moderation_rejection: bool = True
    require_reason_for_moderation_escalation: bool = True
    require_actor_for_legal_actions: bool = True
    require_reason_for_legal_withdrawal: bool = False
    require_reason_for_legal_supersede: bool = False
    allow_seeded_legal_acceptance: bool = False
    require_actor_for_verification_actions: bool = True
    require_assignment_for_verification_decisions: bool = False
    require_assignment_match_for_verification_decisions: bool = False
    require_verified_status_for_visible_verification: bool = True
    allow_verification_visibility_for_archived: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "region_code", _normalize_code(self.region_code))
        object.__setattr__(self, "market_code", _normalize_code(self.market_code, default="PH") or "PH")


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    outcome: PolicyOutcome
    code: str
    message: str
    field: Optional[str] = None
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PolicyResult:
    outcome: PolicyOutcome
    decisions: tuple[PolicyDecision, ...] = ()

    @property
    def is_allowed(self) -> bool:
        return self.outcome in {PolicyOutcome.ALLOWED, PolicyOutcome.ALLOWED_WITH_WARNING}


class SupplierPolicyEngine:
    """Centralized policy checks for governed supplier actions."""

    def evaluate_action(
        self,
        *,
        action: SupplierAction,
        supplier: Optional[SupplierRecord] = None,
        mode: Optional[SupplierMode] = None,
        context: Optional[PolicyContext] = None,
    ) -> PolicyResult:
        resolved_context = context or PolicyContext()

        if action is SupplierAction.CREATE_SEEDED:
            return self.evaluate_seeded_creation(context=resolved_context)
        if action is SupplierAction.CREATE_MANUAL:
            return self.evaluate_manual_creation(context=resolved_context)
        if action is SupplierAction.ACTIVATE:
            if supplier is None:
                raise ValueError("supplier is required when evaluating activation")
            return self.evaluate_activation(supplier=supplier, context=resolved_context)
        if action in {SupplierAction.ARCHIVE, SupplierAction.SUSPEND, SupplierAction.REJECT, SupplierAction.SUBMIT_FOR_REVIEW}:
            return PolicyResult(
                outcome=PolicyOutcome.ALLOWED,
                decisions=(
                    PolicyDecision(
                        outcome=PolicyOutcome.ALLOWED,
                        code=f"policy.action.{action.value}.allowed",
                        message=f"{action.value.replace('_', ' ').title()} is allowed by the current policy.",
                    ),
                ),
            )

        if mode is None and supplier is not None:
            mode = supplier.mode
        if mode is not None:
            return self.evaluate_legal_acceptance_requirement(mode=mode, context=resolved_context)
        return PolicyResult(
            outcome=PolicyOutcome.ALLOWED,
            decisions=(
                PolicyDecision(
                    outcome=PolicyOutcome.ALLOWED,
                    code="policy.default.allowed",
                    message="No blocking supplier policy rule was triggered.",
                ),
            ),
        )

    def evaluate_seeded_creation(self, *, context: PolicyContext) -> PolicyResult:
        if not context.allow_seeded_supplier_creation:
            return PolicyResult(
                outcome=PolicyOutcome.BLOCKED,
                decisions=(
                    PolicyDecision(
                        outcome=PolicyOutcome.BLOCKED,
                        code="policy.seeded_creation.blocked",
                        field="mode",
                        message="Seeded supplier creation is blocked because the current region or pilot is not enabled.",
                        metadata={"region_code": context.region_code, "pilot_enabled": context.pilot_enabled},
                    ),
                ),
            )
        if context.region_code is None:
            return PolicyResult(
                outcome=PolicyOutcome.ALLOWED_WITH_WARNING,
                decisions=(
                    PolicyDecision(
                        outcome=PolicyOutcome.ALLOWED_WITH_WARNING,
                        code="policy.seeded_creation.warning.region_missing",
                        field="region_context.region_code",
                        message="Seeded supplier creation is allowed, but the region is missing and should be captured.",
                    ),
                ),
            )
        return PolicyResult(
            outcome=PolicyOutcome.ALLOWED,
            decisions=(
                PolicyDecision(
                    outcome=PolicyOutcome.ALLOWED,
                    code="policy.seeded_creation.allowed",
                    message="Seeded supplier creation is allowed for the current region or pilot.",
                    metadata={"region_code": context.region_code, "pilot_enabled": context.pilot_enabled},
                ),
            ),
        )

    def evaluate_manual_creation(self, *, context: PolicyContext) -> PolicyResult:
        if context.require_region_for_supplier and context.region_code is None:
            return PolicyResult(
                outcome=PolicyOutcome.REQUIRES_REVIEW,
                decisions=(
                    PolicyDecision(
                        outcome=PolicyOutcome.REQUIRES_REVIEW,
                        code="policy.manual_creation.requires_review.region_missing",
                        field="region_context.region_code",
                        message="Manual supplier creation requires review because the region is missing.",
                    ),
                ),
            )
        return PolicyResult(
            outcome=PolicyOutcome.ALLOWED,
            decisions=(
                PolicyDecision(
                    outcome=PolicyOutcome.ALLOWED,
                    code="policy.manual_creation.allowed",
                    message="Manual supplier creation is allowed under the current policy.",
                ),
            ),
        )

    def evaluate_legal_acceptance_requirement(self, *, mode: SupplierMode, context: PolicyContext) -> PolicyResult:
        if mode is SupplierMode.MANUAL and context.require_legal_acceptance_for_manual:
            return PolicyResult(
                outcome=PolicyOutcome.REQUIRES_REVIEW,
                decisions=(
                    PolicyDecision(
                        outcome=PolicyOutcome.REQUIRES_REVIEW,
                        code="policy.legal_acceptance.manual_required",
                        field="legal_acceptance_state",
                        message="Manual suppliers require legal acceptance before activation.",
                    ),
                ),
            )
        return PolicyResult(
            outcome=PolicyOutcome.ALLOWED,
            decisions=(
                PolicyDecision(
                    outcome=PolicyOutcome.ALLOWED,
                    code="policy.legal_acceptance.not_required",
                    field="legal_acceptance_state",
                    message="Legal acceptance is not required for this supplier mode under the current policy.",
                ),
            ),
        )

    def evaluate_activation(self, *, supplier: SupplierRecord, context: PolicyContext) -> PolicyResult:
        decisions: list[PolicyDecision] = []

        if supplier.is_manual and context.require_legal_acceptance_for_manual:
            if supplier.legal_acceptance_state is not LegalAcceptanceState.ACCEPTED:
                decisions.append(
                    PolicyDecision(
                        outcome=PolicyOutcome.BLOCKED,
                        code="policy.activation.blocked.legal_missing",
                        field="legal_acceptance_state",
                        message="Manual suppliers cannot become active until legal acceptance is accepted.",
                    )
                )

        if supplier.is_seeded and context.require_moderation_for_seeded_activation:
            if supplier.moderation_status is not ModerationStatus.APPROVED:
                decisions.append(
                    PolicyDecision(
                        outcome=PolicyOutcome.BLOCKED,
                        code="policy.activation.blocked.moderation_missing",
                        field="moderation_status",
                        message="Seeded suppliers cannot become active until moderation approval is complete.",
                    )
                )

        if context.block_failed_verification_activation and supplier.verification_status is VerificationStatus.FAILED:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code="policy.activation.blocked.verification_failed",
                    field="verification_status",
                    message="Suppliers with failed verification cannot become active.",
                )
            )
        elif supplier.verification_status is VerificationStatus.NEEDS_REVIEW:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.REQUIRES_REVIEW,
                    code="policy.activation.review.verification_needs_review",
                    field="verification_status",
                    message="Activation requires review because verification is marked as needs review.",
                )
            )
        elif supplier.verification_status is VerificationStatus.UNVERIFIED:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.ALLOWED_WITH_WARNING,
                    code="policy.activation.warning.unverified",
                    field="verification_status",
                    message="Activation is allowed by policy, but the supplier is still unverified.",
                )
            )

        if context.require_region_for_supplier and not supplier.region_context.region_code:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.REQUIRES_REVIEW,
                    code="policy.activation.review.region_missing",
                    field="region_context.region_code",
                    message="Activation requires review because the supplier region is missing.",
                )
            )

        if not decisions:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.ALLOWED,
                    code="policy.activation.allowed",
                    message="Activation is allowed under the current policy.",
                )
            )

        return PolicyResult(outcome=self._collapse_outcome(decisions), decisions=tuple(decisions))

    def evaluate_moderation_submission(
        self,
        *,
        supplier: SupplierRecord,
        actor: Optional[str],
        context: PolicyContext,
    ) -> PolicyResult:
        return self._evaluate_moderation_action(
            supplier=supplier,
            actor=actor,
            action_code="submit",
            context=context,
        )

    def evaluate_moderation_approval(
        self,
        *,
        supplier: SupplierRecord,
        actor: Optional[str],
        context: PolicyContext,
    ) -> PolicyResult:
        return self._evaluate_moderation_action(
            supplier=supplier,
            actor=actor,
            action_code="approve",
            context=context,
        )

    def evaluate_moderation_rejection(
        self,
        *,
        supplier: SupplierRecord,
        actor: Optional[str],
        reason: Optional[str],
        context: PolicyContext,
    ) -> PolicyResult:
        return self._evaluate_moderation_action(
            supplier=supplier,
            actor=actor,
            action_code="reject",
            context=context,
            reason=reason,
            require_reason=context.require_reason_for_moderation_rejection,
        )

    def evaluate_moderation_escalation(
        self,
        *,
        supplier: SupplierRecord,
        actor: Optional[str],
        reason: Optional[str],
        context: PolicyContext,
    ) -> PolicyResult:
        return self._evaluate_moderation_action(
            supplier=supplier,
            actor=actor,
            action_code="escalate",
            context=context,
            reason=reason,
            require_reason=context.require_reason_for_moderation_escalation,
        )

    def evaluate_legal_acceptance(
        self,
        *,
        supplier: SupplierRecord,
        actor: Optional[str],
        version: Optional[str],
        context: PolicyContext,
    ) -> PolicyResult:
        return self._evaluate_legal_action(
            supplier=supplier,
            actor=actor,
            action_code="accept",
            context=context,
            version=version,
        )

    def evaluate_legal_withdrawal(
        self,
        *,
        supplier: SupplierRecord,
        actor: Optional[str],
        reason: Optional[str],
        context: PolicyContext,
    ) -> PolicyResult:
        return self._evaluate_legal_action(
            supplier=supplier,
            actor=actor,
            action_code="withdraw",
            context=context,
            reason=reason,
            require_reason=context.require_reason_for_legal_withdrawal,
        )

    def evaluate_legal_supersede(
        self,
        *,
        supplier: SupplierRecord,
        actor: Optional[str],
        pending_version: Optional[str],
        reason: Optional[str],
        context: PolicyContext,
    ) -> PolicyResult:
        return self._evaluate_legal_action(
            supplier=supplier,
            actor=actor,
            action_code="supersede",
            context=context,
            version=pending_version,
            reason=reason,
            require_reason=context.require_reason_for_legal_supersede,
        )

    def evaluate_verification_assignment(
        self,
        *,
        supplier: SupplierRecord,
        actor: Optional[str],
        assignee: Optional[str],
        context: PolicyContext,
    ) -> PolicyResult:
        decisions: list[PolicyDecision] = []
        cleaned_actor = _clean_optional_text(actor)
        cleaned_assignee = _clean_optional_text(assignee)

        if context.require_actor_for_verification_actions and not cleaned_actor:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code="policy.verification.assign.blocked.actor_required",
                    field="actor",
                    message="Verification assignment requires an actor for audit traceability.",
                )
            )

        if not cleaned_assignee:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code="policy.verification.assign.blocked.assignee_required",
                    field="verification_assigned_to",
                    message="Verification assignment requires a non-empty assignee.",
                )
            )

        if supplier.lifecycle_status is LifecycleStatus.ARCHIVED:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code="policy.verification.assign.blocked.archived_supplier",
                    field="lifecycle_status",
                    message="Verification assignment is blocked for archived suppliers.",
                )
            )

        if not decisions:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.ALLOWED,
                    code="policy.verification.assign.allowed",
                    message="Verification assignment is allowed under the current policy.",
                    metadata={
                        "current_assignee": supplier.verification_assigned_to,
                        "next_assignee": cleaned_assignee,
                        "verification_status": supplier.verification_status.value,
                    },
                )
            )

        return PolicyResult(outcome=self._collapse_outcome(decisions), decisions=tuple(decisions))

    def evaluate_verification_unassignment(
        self,
        *,
        supplier: SupplierRecord,
        actor: Optional[str],
        context: PolicyContext,
    ) -> PolicyResult:
        decisions: list[PolicyDecision] = []
        cleaned_actor = _clean_optional_text(actor)

        if context.require_actor_for_verification_actions and not cleaned_actor:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code="policy.verification.unassign.blocked.actor_required",
                    field="actor",
                    message="Verification unassignment requires an actor for audit traceability.",
                )
            )

        if supplier.lifecycle_status is LifecycleStatus.ARCHIVED:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code="policy.verification.unassign.blocked.archived_supplier",
                    field="lifecycle_status",
                    message="Verification unassignment is blocked for archived suppliers.",
                )
            )

        if not decisions:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.ALLOWED,
                    code="policy.verification.unassign.allowed",
                    message="Verification unassignment is allowed under the current policy.",
                    metadata={
                        "current_assignee": supplier.verification_assigned_to,
                        "verification_status": supplier.verification_status.value,
                    },
                )
            )

        return PolicyResult(outcome=self._collapse_outcome(decisions), decisions=tuple(decisions))

    def evaluate_verification_status_change(
        self,
        *,
        supplier: SupplierRecord,
        actor: Optional[str],
        target_status: VerificationStatus,
        context: PolicyContext,
    ) -> PolicyResult:
        decisions: list[PolicyDecision] = []
        cleaned_actor = _clean_optional_text(actor)

        if context.require_actor_for_verification_actions and not cleaned_actor:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code="policy.verification.status_change.blocked.actor_required",
                    field="actor",
                    message="Verification decisions require an actor for audit traceability.",
                )
            )

        if supplier.lifecycle_status is LifecycleStatus.ARCHIVED:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code="policy.verification.status_change.blocked.archived_supplier",
                    field="lifecycle_status",
                    message="Verification decisions are blocked for archived suppliers.",
                )
            )

        if context.require_assignment_for_verification_decisions and not supplier.verification_assigned_to:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code="policy.verification.status_change.blocked.assignment_required",
                    field="verification_assigned_to",
                    message="Verification decisions require an assigned verifier under the current policy.",
                )
            )

        if (
            context.require_assignment_match_for_verification_decisions
            and cleaned_actor
            and supplier.verification_assigned_to
            and cleaned_actor != supplier.verification_assigned_to
        ):
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code="policy.verification.status_change.blocked.actor_assignment_mismatch",
                    field="actor",
                    message="Verification decisions must be made by the assigned verifier under the current policy.",
                    metadata={
                        "assigned_to": supplier.verification_assigned_to,
                        "actor": cleaned_actor,
                    },
                )
            )

        if not decisions:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.ALLOWED,
                    code="policy.verification.status_change.allowed",
                    message="Verification status change is allowed under the current policy.",
                    metadata={
                        "from_status": supplier.verification_status.value,
                        "to_status": target_status.value,
                        "assigned_to": supplier.verification_assigned_to,
                    },
                )
            )

        return PolicyResult(outcome=self._collapse_outcome(decisions), decisions=tuple(decisions))

    def evaluate_verification_visibility(
        self,
        *,
        supplier: SupplierRecord,
        actor: Optional[str],
        target_visibility: VerificationVisibility,
        context: PolicyContext,
    ) -> PolicyResult:
        decisions: list[PolicyDecision] = []
        cleaned_actor = _clean_optional_text(actor)

        if context.require_actor_for_verification_actions and not cleaned_actor:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code="policy.verification.visibility.blocked.actor_required",
                    field="actor",
                    message="Verification visibility changes require an actor for audit traceability.",
                )
            )

        if supplier.lifecycle_status is LifecycleStatus.ARCHIVED and not context.allow_verification_visibility_for_archived:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code="policy.verification.visibility.blocked.archived_supplier",
                    field="lifecycle_status",
                    message="Verification visibility cannot be changed for archived suppliers under the current policy.",
                )
            )

        if (
            context.require_assignment_match_for_verification_decisions
            and cleaned_actor
            and supplier.verification_assigned_to
            and cleaned_actor != supplier.verification_assigned_to
        ):
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code="policy.verification.visibility.blocked.actor_assignment_mismatch",
                    field="actor",
                    message="Verification visibility changes must be made by the assigned verifier under the current policy.",
                    metadata={
                        "assigned_to": supplier.verification_assigned_to,
                        "actor": cleaned_actor,
                    },
                )
            )

        if (
            context.require_verified_status_for_visible_verification
            and target_visibility is VerificationVisibility.VISIBLE
            and supplier.verification_status is not VerificationStatus.VERIFIED
        ):
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code="policy.verification.visibility.blocked.verification_required",
                    field="verification_status",
                    message="Verification visibility can only become visible once the supplier is verified.",
                )
            )

        if not decisions:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.ALLOWED,
                    code="policy.verification.visibility.allowed",
                    message="Verification visibility change is allowed under the current policy.",
                    metadata={
                        "from_visibility": supplier.verification_visibility.value,
                        "to_visibility": target_visibility.value,
                        "verification_status": supplier.verification_status.value,
                    },
                )
            )

        return PolicyResult(outcome=self._collapse_outcome(decisions), decisions=tuple(decisions))

    @staticmethod
    def _collapse_outcome(decisions: list[PolicyDecision]) -> PolicyOutcome:
        highest = max(decisions, key=lambda decision: OUTCOME_PRIORITY[decision.outcome])
        return highest.outcome

    def _evaluate_moderation_action(
        self,
        *,
        supplier: SupplierRecord,
        actor: Optional[str],
        action_code: str,
        context: PolicyContext,
        reason: Optional[str] = None,
        require_reason: bool = False,
    ) -> PolicyResult:
        decisions: list[PolicyDecision] = []
        cleaned_reason = reason.strip() if reason else None

        if context.require_actor_for_moderation_actions and not actor:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code=f"policy.moderation.{action_code}.blocked.actor_required",
                    field="actor",
                    message="Moderation actions require an actor for audit traceability.",
                )
            )

        if require_reason and not cleaned_reason:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code=f"policy.moderation.{action_code}.blocked.reason_required",
                    field="reason",
                    message=f"Moderation {action_code} requires a non-empty reason.",
                )
            )

        if not decisions:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.ALLOWED,
                    code=f"policy.moderation.{action_code}.allowed",
                    message=f"Moderation {action_code} is allowed under the current policy.",
                    metadata={
                        "supplier_mode": supplier.mode.value,
                        "region_code": supplier.region_context.region_code,
                    },
                )
            )

        return PolicyResult(outcome=self._collapse_outcome(decisions), decisions=tuple(decisions))

    def _evaluate_legal_action(
        self,
        *,
        supplier: SupplierRecord,
        actor: Optional[str],
        action_code: str,
        context: PolicyContext,
        version: Optional[str] = None,
        reason: Optional[str] = None,
        require_reason: bool = False,
    ) -> PolicyResult:
        decisions: list[PolicyDecision] = []
        cleaned_version = _clean_optional_text(version)
        cleaned_reason = _clean_optional_text(reason)

        if context.require_actor_for_legal_actions and not actor:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code=f"policy.legal.{action_code}.blocked.actor_required",
                    field="actor",
                    message="Legal governance actions require an actor for audit traceability.",
                )
            )

        if supplier.is_seeded and not context.allow_seeded_legal_acceptance:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code=f"policy.legal.{action_code}.blocked.seeded_not_applicable",
                    field="mode",
                    message="Legal governance actions are not applicable to seeded suppliers under the current policy.",
                )
            )

        if action_code in {"accept", "supersede"} and not cleaned_version:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code=f"policy.legal.{action_code}.blocked.version_required",
                    field="legal_acceptance_version",
                    message=f"Legal {action_code} requires a non-empty version identifier.",
                )
            )

        if require_reason and not cleaned_reason:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.BLOCKED,
                    code=f"policy.legal.{action_code}.blocked.reason_required",
                    field="reason",
                    message=f"Legal {action_code} requires a non-empty reason.",
                )
            )

        if not decisions:
            decisions.append(
                PolicyDecision(
                    outcome=PolicyOutcome.ALLOWED,
                    code=f"policy.legal.{action_code}.allowed",
                    message=f"Legal {action_code} is allowed under the current policy.",
                    metadata={
                        "supplier_mode": supplier.mode.value,
                        "region_code": supplier.region_context.region_code,
                        "legal_acceptance_state": supplier.legal_acceptance_state.value,
                    },
                )
            )

        return PolicyResult(outcome=self._collapse_outcome(decisions), decisions=tuple(decisions))
