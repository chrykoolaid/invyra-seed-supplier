from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from supplier_seed import AccessContext, GovernanceRole, PolicyContext, SupplierSeedEngine
from supplier_seed.api.internal_app import (
    InMemoryInternalMutationStateStore,
    InternalActorPayload,
    InternalMutationStateStore,
    InternalSupplierApiSettings,
    _authenticate_transport,
    _error,
    _governance_state,
    _store_result,
    _write_ready,
    create_internal_app,
)
from supplier_seed.domain.enums import ModerationStatus
from supplier_seed.domain.models import SupplierRecord
from supplier_seed.intelligence.dedupe import SupplierDedupeEngine


INTERNAL_REVIEW_CONTRACT_VERSION = "R3-P5-v1"
INTERNAL_REVIEW_PATH_TEMPLATE = "/internal/v1/suppliers/{supplier_id}/review"
INTERNAL_REVIEW_DECISION_PATH_TEMPLATE = "/internal/v1/suppliers/{supplier_id}/review/decision"


class InternalSupplierReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str
    environment: str
    actor: InternalActorPayload
    decision: str = Field(min_length=1, max_length=16)
    reason: str = Field(default="", max_length=500)
    expected_lifecycle_status: str = Field(min_length=1, max_length=32)
    expected_moderation_status: str = Field(min_length=1, max_length=32)


def _request_fingerprint(payload: BaseModel) -> str:
    canonical = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _review_policy_context(supplier: SupplierRecord) -> PolicyContext:
    region = supplier.region_context
    return PolicyContext(
        region_code=region.region_code,
        market_code=region.market_code,
        pilot_enabled=bool(region.pilot_enabled),
    )


def _review_duplicates(supplier: SupplierRecord, engine: SupplierSeedEngine) -> list[dict[str, Any]]:
    repository = getattr(engine, "repository", None)
    existing = tuple(
        row for row in (repository.list() if repository is not None else ())
        if row.supplier_id != supplier.supplier_id
    )
    matches = SupplierDedupeEngine().evaluate_supplier(supplier, existing).candidates
    return [
        {
            "supplier_id": candidate.supplier.supplier_id,
            "name": candidate.supplier.name,
            "classification": candidate.classification.value,
            "confidence": candidate.confidence,
            "match_signals": [signal.code for signal in candidate.signals],
        }
        for candidate in matches
    ]


def _review_snapshot(
    supplier: SupplierRecord,
    engine: SupplierSeedEngine,
    correlation_id: str,
) -> dict[str, Any]:
    region = supplier.region_context
    return {
        "contract_version": INTERNAL_REVIEW_CONTRACT_VERSION,
        "supplier_id": supplier.supplier_id,
        "supplier": {
            "name": supplier.name,
            "mode": supplier.mode.value,
            "country_code": region.market_code,
            "region_code": region.region_code,
            "contact_email": supplier.contact_email,
            "contact_phone": supplier.contact_phone,
            "website_url": supplier.website_url,
            "business_identifier": supplier.tax_identifier,
        },
        "governance_state": _governance_state(supplier),
        "possible_matches": _review_duplicates(supplier, engine),
        "correlation_id": correlation_id,
    }


def _decision_result(
    *,
    result_kind: str,
    supplier: SupplierRecord,
    engine: SupplierSeedEngine,
    correlation_id: str,
    replayed: bool = False,
) -> dict[str, Any]:
    return {
        "contract_version": INTERNAL_REVIEW_CONTRACT_VERSION,
        "result_kind": result_kind,
        "supplier_id": supplier.supplier_id,
        "supplier_usable": False,
        "governance_state": _governance_state(supplier),
        "possible_matches": _review_duplicates(supplier, engine),
        "retry_safe": True,
        "replayed": replayed,
        "correlation_id": correlation_id,
    }


def _engine_operation_receipt(engine: SupplierSeedEngine, key: str) -> dict[str, Any] | None:
    repository = getattr(engine, "repository", None)
    if repository is None or not hasattr(repository, "find_operation_receipt"):
        return None
    receipt = repository.find_operation_receipt(key)
    return receipt if isinstance(receipt, dict) else None


def create_internal_review_app(
    engine: SupplierSeedEngine | None = None,
    *,
    settings: InternalSupplierApiSettings | None = None,
    state_store: InternalMutationStateStore | None = None,
) -> FastAPI:
    """Build the certified internal API plus the R3-P5 supplier-review surface.

    The review routes are HMAC-authenticated server-only operations. They reuse
    Supplier Seed's existing moderation state machine, durable repository audit
    events and idempotency receipts. They never activate a supplier.
    """

    review_engine = engine or SupplierSeedEngine()
    runtime_settings = settings or InternalSupplierApiSettings.from_env()
    mutation_state = state_store or InMemoryInternalMutationStateStore()
    application = create_internal_app(
        review_engine,
        settings=runtime_settings,
        state_store=mutation_state,
    )

    @application.get(INTERNAL_REVIEW_PATH_TEMPLATE)
    async def supplier_review_snapshot(supplier_id: str, request: Request) -> JSONResponse:
        body = await request.body()
        auth = await _authenticate_transport(request, body, runtime_settings, mutation_state)
        if isinstance(auth, JSONResponse):
            return auth

        supplier = review_engine.repository.get(supplier_id)
        if supplier is None:
            return _error(404, "supplier.review.not_found", auth.correlation_id)

        return JSONResponse(
            status_code=200,
            content=_review_snapshot(supplier, review_engine, auth.correlation_id),
        )

    @application.post(INTERNAL_REVIEW_DECISION_PATH_TEMPLATE)
    async def decide_supplier_review(supplier_id: str, request: Request) -> JSONResponse:
        body = await request.body()
        auth = await _authenticate_transport(request, body, runtime_settings, mutation_state)
        if isinstance(auth, JSONResponse):
            return auth

        if not _write_ready(review_engine, runtime_settings, mutation_state) and not runtime_settings.allow_nondurable_test_mode:
            return _error(503, "service.unavailable", auth.correlation_id)

        try:
            payload = InternalSupplierReviewDecisionRequest.model_validate_json(body)
        except ValidationError:
            return _error(400, "request.validation_failed", auth.correlation_id)

        if payload.contract_version != INTERNAL_REVIEW_CONTRACT_VERSION:
            return _error(400, "request.validation_failed", auth.correlation_id)
        if payload.environment not in runtime_settings.allowed_environments:
            return _error(400, "request.validation_failed", auth.correlation_id)
        if payload.actor.role.lower() not in {"admin", "owner"}:
            return _error(403, "service.authorization_failed", auth.correlation_id)

        decision = payload.decision.strip().lower()
        if decision not in {"approve", "reject"}:
            return _error(400, "request.validation_failed", auth.correlation_id)
        if decision == "reject" and not payload.reason.strip():
            return _error(400, "supplier.review.rejection_reason_required", auth.correlation_id)

        fingerprint = _request_fingerprint(payload)
        stored_receipt = mutation_state.get_receipt(auth.idempotency_key)
        if stored_receipt is not None:
            if not hmac.compare_digest(stored_receipt.fingerprint, fingerprint):
                return _error(409, "idempotency.conflict", auth.correlation_id)
            replay = dict(stored_receipt.payload)
            replay["replayed"] = True
            replay["correlation_id"] = auth.correlation_id
            return JSONResponse(status_code=stored_receipt.status_code, content=replay)

        supplier = review_engine.repository.get(supplier_id)
        if supplier is None:
            return _error(404, "supplier.review.not_found", auth.correlation_id)

        actor_id = f"inventory:{payload.actor.id.strip()}"
        access_context = AccessContext(actor_id=actor_id, role=GovernanceRole.ADMIN)
        policy_context = _review_policy_context(supplier)
        submit_key = f"{auth.idempotency_key}:submit"
        decision_key = f"{auth.idempotency_key}:decision"
        expected_action = "approve_moderation" if decision == "approve" else "reject_moderation"

        prior_decision = _engine_operation_receipt(review_engine, decision_key)
        if prior_decision is not None and prior_decision.get("action") == expected_action:
            current = review_engine.repository.get(supplier_id) or supplier
            result_payload = _decision_result(
                result_kind="APPROVED" if decision == "approve" else "REJECTED",
                supplier=current,
                engine=review_engine,
                correlation_id=auth.correlation_id,
                replayed=True,
            )
            return _store_result(
                mutation_state,
                idempotency_key=auth.idempotency_key,
                fingerprint=fingerprint,
                status_code=200,
                payload=result_payload,
            )

        current_lifecycle = supplier.lifecycle_status.value
        current_moderation = supplier.moderation_status.value
        if (
            current_lifecycle != payload.expected_lifecycle_status
            or current_moderation != payload.expected_moderation_status
        ):
            return _error(409, "supplier.review.stale", auth.correlation_id)

        if supplier.moderation_status == ModerationStatus.NOT_REVIEWED:
            submitted = review_engine.submit_for_review(
                supplier_id,
                actor=actor_id,
                context=policy_context,
                access_context=access_context,
                idempotency_key=submit_key,
            )
            if not submitted.allowed or submitted.supplier is None:
                return _error(409, "supplier.review.submit_blocked", auth.correlation_id)
            supplier = submitted.supplier
        elif supplier.moderation_status not in {ModerationStatus.PENDING_REVIEW, ModerationStatus.ESCALATED}:
            return _error(409, "supplier.review.already_reviewed", auth.correlation_id)

        if decision == "approve":
            decided = review_engine.approve_moderation(
                supplier_id,
                actor=actor_id,
                context=policy_context,
                access_context=access_context,
                idempotency_key=decision_key,
            )
            result_kind = "APPROVED"
        else:
            decided = review_engine.reject_moderation(
                supplier_id,
                actor=actor_id,
                reason=payload.reason.strip(),
                context=policy_context,
                access_context=access_context,
                idempotency_key=decision_key,
            )
            result_kind = "REJECTED"

        if not decided.allowed or decided.supplier is None:
            return _error(409, "supplier.review.decision_blocked", auth.correlation_id)

        result_payload = _decision_result(
            result_kind=result_kind,
            supplier=decided.supplier,
            engine=review_engine,
            correlation_id=auth.correlation_id,
        )
        return _store_result(
            mutation_state,
            idempotency_key=auth.idempotency_key,
            fingerprint=fingerprint,
            status_code=200,
            payload=result_payload,
        )

    return application


__all__ = [
    "INTERNAL_REVIEW_CONTRACT_VERSION",
    "INTERNAL_REVIEW_DECISION_PATH_TEMPLATE",
    "INTERNAL_REVIEW_PATH_TEMPLATE",
    "InternalSupplierReviewDecisionRequest",
    "create_internal_review_app",
]
