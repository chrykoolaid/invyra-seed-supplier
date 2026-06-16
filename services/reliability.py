"""Reliability helpers for retry-safe supplier seed mutations.

Part O keeps these helpers service/engine-facing only. They do not introduce background jobs
or distributed coordination. Their purpose is to make transient retries and replay-safe
mutation handling explicit at the correct layer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional, TypeVar

from supplier_seed.domain.enums import (
    LifecycleStatus,
    PolicyOutcome,
    ValidationSeverity,
)
from supplier_seed.domain.transitions import TransitionResult
from supplier_seed.domain.validation import ValidationIssue, ValidationResult
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.ingestion.ingestion_service import (
    IngestionDecision,
    SupplierIngestionResult,
)
from supplier_seed.intelligence.dedupe import SupplierDedupeEngine
from supplier_seed.policy.rules import PolicyDecision, PolicyResult
from supplier_seed.repository.serialization import (
    OperationReceipt,
    deserialize_event,
    deserialize_supplier,
    serialize_event,
    serialize_supplier,
)
from supplier_seed.services.results import GovernanceServiceResult


UTC = timezone.utc
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    backoff_seconds: float = 0.0
    retryable_exceptions: tuple[type[BaseException], ...] = (TimeoutError, OSError)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("RetryPolicy.max_attempts must be at least 1.")
        if self.backoff_seconds < 0:
            raise ValueError("RetryPolicy.backoff_seconds cannot be negative.")


def retry_call(operation: Callable[[], T], *, policy: RetryPolicy) -> T:
    last_error: Optional[BaseException] = None
    for attempt_index in range(policy.max_attempts):
        try:
            return operation()
        except policy.retryable_exceptions as exc:  # type: ignore[misc]
            last_error = exc
            if attempt_index >= policy.max_attempts - 1:
                raise
            if policy.backoff_seconds > 0:
                time.sleep(policy.backoff_seconds)
    assert last_error is not None
    raise last_error


def serialize_validation_issue(issue: ValidationIssue) -> dict[str, Any]:
    return {
        "code": issue.code,
        "field": issue.field,
        "message": issue.message,
        "severity": issue.severity.value,
    }


def deserialize_validation_issue(payload: dict[str, Any]) -> ValidationIssue:
    return ValidationIssue(
        code=payload["code"],
        field=payload.get("field"),
        message=payload["message"],
        severity=ValidationSeverity(payload.get("severity", ValidationSeverity.ERROR.value)),
    )


def serialize_policy_decision(decision: PolicyDecision) -> dict[str, Any]:
    return {
        "outcome": decision.outcome.value,
        "code": decision.code,
        "message": decision.message,
        "field": decision.field,
        "metadata": dict(decision.metadata),
    }


def deserialize_policy_decision(payload: dict[str, Any]) -> PolicyDecision:
    return PolicyDecision(
        outcome=PolicyOutcome(payload["outcome"]),
        code=payload["code"],
        message=payload["message"],
        field=payload.get("field"),
        metadata=dict(payload.get("metadata") or {}),
    )


def serialize_ingestion_decision(decision: IngestionDecision) -> dict[str, Any]:
    return {
        "outcome": decision.outcome.value,
        "code": decision.code,
        "message": decision.message,
        "field": decision.field,
        "metadata": dict(decision.metadata),
    }


def deserialize_ingestion_decision(payload: dict[str, Any]) -> IngestionDecision:
    return IngestionDecision(
        outcome=PolicyOutcome(payload["outcome"]),
        code=payload["code"],
        message=payload["message"],
        field=payload.get("field"),
        metadata=dict(payload.get("metadata") or {}),
    )


def build_ingestion_receipt(
    *,
    idempotency_key: str,
    action_name: str,
    result: SupplierIngestionResult,
) -> OperationReceipt:
    return OperationReceipt(
        idempotency_key=idempotency_key,
        action_name=action_name,
        result_type="ingestion",
        created_at=datetime.now(tz=UTC),
        payload={
            "supplier": serialize_supplier(result.supplier),
            "outcome": result.outcome.value,
            "accepted_for_staging": result.accepted_for_staging,
            "decisions": [serialize_ingestion_decision(item) for item in result.decisions],
            "policy_outcome": result.policy_result.outcome.value,
            "policy_decisions": [serialize_policy_decision(item) for item in result.policy_result.decisions],
            "validation_issues": [serialize_validation_issue(item) for item in result.validation_result.issues],
            "events": [serialize_event(item) for item in result.events],
        },
    )


def restore_ingestion_result(
    receipt: OperationReceipt,
    *,
    dedupe_engine: Optional[SupplierDedupeEngine] = None,
    existing_suppliers: tuple = (),
) -> SupplierIngestionResult:
    payload = receipt.payload
    supplier = deserialize_supplier(payload["supplier"])
    engine = dedupe_engine or SupplierDedupeEngine()
    existing_without_supplier = tuple(
        item for item in existing_suppliers if item.identity.supplier_id != supplier.identity.supplier_id
    )
    dedupe_evaluation = engine.evaluate_supplier(supplier, existing_without_supplier)
    return SupplierIngestionResult(
        supplier=supplier,
        outcome=PolicyOutcome(payload["outcome"]),
        accepted_for_staging=bool(payload.get("accepted_for_staging", False)),
        decisions=tuple(deserialize_ingestion_decision(item) for item in payload.get("decisions") or []),
        policy_result=PolicyResult(
            outcome=PolicyOutcome(payload.get("policy_outcome", payload["outcome"])),
            decisions=tuple(
                deserialize_policy_decision(item) for item in payload.get("policy_decisions") or []
            ),
        ),
        validation_result=ValidationResult(
            issues=tuple(
                deserialize_validation_issue(item) for item in payload.get("validation_issues") or []
            )
        ),
        dedupe_evaluation=dedupe_evaluation,
        events=tuple(deserialize_event(item) for item in payload.get("events") or []),
    )


def build_governance_receipt(
    *,
    idempotency_key: str,
    action_name: str,
    result: GovernanceServiceResult,
) -> OperationReceipt:
    return OperationReceipt(
        idempotency_key=idempotency_key,
        action_name=action_name,
        result_type="governance",
        created_at=datetime.now(tz=UTC),
        payload={
            "allowed": result.allowed,
            "supplier": serialize_supplier(result.supplier),
            "issues": [serialize_validation_issue(item) for item in result.issues],
            "events": [serialize_event(item) for item in result.events],
        },
    )


def restore_governance_result(receipt: OperationReceipt) -> GovernanceServiceResult:
    payload = receipt.payload
    return GovernanceServiceResult(
        allowed=bool(payload.get("allowed", False)),
        supplier=deserialize_supplier(payload["supplier"]),
        events=tuple(deserialize_event(item) for item in payload.get("events") or []),
        issues=tuple(deserialize_validation_issue(item) for item in payload.get("issues") or []),
    )


def build_transition_receipt(
    *,
    idempotency_key: str,
    action_name: str,
    result: TransitionResult,
) -> OperationReceipt:
    return OperationReceipt(
        idempotency_key=idempotency_key,
        action_name=action_name,
        result_type="transition",
        created_at=datetime.now(tz=UTC),
        payload={
            "allowed": result.allowed,
            "supplier": serialize_supplier(result.supplier),
            "from_status": result.from_status.value,
            "to_status": result.to_status.value,
            "issues": [serialize_validation_issue(item) for item in result.issues],
            "events": [serialize_event(item) for item in result.events],
        },
    )


def restore_transition_result(receipt: OperationReceipt) -> TransitionResult:
    payload = receipt.payload
    return TransitionResult(
        allowed=bool(payload.get("allowed", False)),
        supplier=deserialize_supplier(payload["supplier"]),
        from_status=LifecycleStatus(payload["from_status"]),
        to_status=LifecycleStatus(payload["to_status"]),
        issues=tuple(deserialize_validation_issue(item) for item in payload.get("issues") or []),
        events=tuple(deserialize_event(item) for item in payload.get("events") or []),
    )
