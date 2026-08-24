from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from supplier_seed import (
    AccessContext,
    GovernanceRole,
    PolicyContext,
    SupplierCandidateInput,
    SupplierMode,
    SupplierRegionContext,
    SupplierSeedEngine,
)
from supplier_seed.domain.enums import DedupeMatchClassification, LifecycleStatus, PolicyOutcome
from supplier_seed.domain.models import SupplierRecord
from supplier_seed.intelligence.dedupe import SupplierDedupeEngine
from supplier_seed.repository.json_file import JsonFileSupplierRepository


INTERNAL_CONTRACT_VERSION = "R3-P0A-v1"
INTERNAL_SERVICE_VERSION = "1.3.0-r3-s1"
INTERNAL_CAPABILITIES_PATH = "/internal/v1/capabilities"
INTERNAL_CREATE_PATH = "/internal/v1/suppliers"

_REQUIRED_HEADERS = (
    "X-Invyra-Service",
    "X-Invyra-Key-Id",
    "X-Invyra-Timestamp",
    "X-Invyra-Nonce",
    "X-Invyra-Content-SHA256",
    "X-Invyra-Signature",
    "Idempotency-Key",
    "X-Correlation-Id",
)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_keyring() -> dict[str, str]:
    raw = os.getenv("SUPPLIER_SEED_INTERNAL_HMAC_KEYS_JSON", "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(key_id): str(secret)
        for key_id, secret in payload.items()
        if str(key_id).strip() and str(secret)
    }


@dataclass(frozen=True)
class InternalSupplierApiSettings:
    """Server-only configuration for the R3-S1 internal mutation surface.

    The defaults are deliberately disabled and fail closed. R3-S1 permits a
    non-durable test mode so the authentication and mutation contract can be
    exercised in CI without claiming production readiness.
    """

    enabled: bool = False
    service_id: str = "inventory"
    hmac_keys: Mapping[str, str] = field(default_factory=dict)
    maximum_clock_skew_seconds: int = 300
    allowed_environments: tuple[str, ...] = ("LIVE",)
    allow_nondurable_test_mode: bool = False

    @classmethod
    def from_env(cls) -> "InternalSupplierApiSettings":
        return cls(
            enabled=_env_flag("SUPPLIER_SEED_INTERNAL_WRITE_ENABLED", False),
            service_id=os.getenv("SUPPLIER_SEED_INTERNAL_SERVICE_ID", "inventory").strip() or "inventory",
            hmac_keys=_env_keyring(),
            maximum_clock_skew_seconds=300,
            allowed_environments=("LIVE",),
            allow_nondurable_test_mode=False,
        )


@dataclass(frozen=True)
class StoredMutationReceipt:
    fingerprint: str
    status_code: int
    payload: dict[str, Any]


class InternalMutationStateStore(Protocol):
    durable: bool

    def claim_nonce(self, nonce: str, expires_at: int) -> bool: ...

    def get_receipt(self, idempotency_key: str) -> StoredMutationReceipt | None: ...

    def save_receipt(
        self,
        idempotency_key: str,
        fingerprint: str,
        status_code: int,
        payload: dict[str, Any],
    ) -> StoredMutationReceipt: ...


class InMemoryInternalMutationStateStore:
    """R3-S1 test state only. Not acceptable for LIVE activation."""

    durable = False

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._nonces: dict[str, int] = {}
        self._receipts: dict[str, StoredMutationReceipt] = {}

    def claim_nonce(self, nonce: str, expires_at: int) -> bool:
        now = int(time.time())
        with self._lock:
            self._nonces = {value: expiry for value, expiry in self._nonces.items() if expiry >= now}
            if nonce in self._nonces:
                return False
            self._nonces[nonce] = expires_at
            return True

    def get_receipt(self, idempotency_key: str) -> StoredMutationReceipt | None:
        with self._lock:
            return self._receipts.get(idempotency_key)

    def save_receipt(
        self,
        idempotency_key: str,
        fingerprint: str,
        status_code: int,
        payload: dict[str, Any],
    ) -> StoredMutationReceipt:
        with self._lock:
            existing = self._receipts.get(idempotency_key)
            if existing is not None:
                return existing
            receipt = StoredMutationReceipt(
                fingerprint=fingerprint,
                status_code=status_code,
                payload=json.loads(json.dumps(payload)),
            )
            self._receipts[idempotency_key] = receipt
            return receipt


class InternalActorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=32)


class InternalRegionContextPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_code: str = Field(min_length=2, max_length=8)
    region_code: str | None = Field(default=None, max_length=32)
    pilot_enabled: bool = False


class InternalSupplierCandidatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    mode: str = "manual"
    region_context: InternalRegionContextPayload
    contact_email: str | None = Field(default=None, max_length=320)
    contact_phone: str | None = Field(default=None, max_length=80)
    website_url: str | None = Field(default=None, max_length=500)
    tax_identifier: str | None = Field(default=None, max_length=160)


class InternalSupplierCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str
    environment: str
    actor: InternalActorPayload
    candidate: InternalSupplierCandidatePayload


@dataclass(frozen=True)
class AuthenticatedTransport:
    idempotency_key: str
    correlation_id: str
    nonce: str


def content_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical_signature_material(
    *,
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    content_hash: str,
    idempotency_key: str,
    correlation_id: str,
) -> str:
    return "\n".join(
        (
            method.upper(),
            path,
            timestamp,
            nonce,
            content_hash.lower(),
            idempotency_key,
            correlation_id,
        )
    )


def sign_internal_request(
    *,
    secret: str,
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    content_hash: str,
    idempotency_key: str,
    correlation_id: str,
) -> str:
    material = canonical_signature_material(
        method=method,
        path=path,
        timestamp=timestamp,
        nonce=nonce,
        content_hash=content_hash,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    return hmac.new(secret.encode("utf-8"), material.encode("utf-8"), hashlib.sha256).hexdigest()


def _error(status_code: int, code: str, correlation_id: str | None, message: str | None = None) -> JSONResponse:
    detail: dict[str, Any] = {"code": code, "correlation_id": correlation_id}
    if message:
        detail["message"] = message
    return JSONResponse(status_code=status_code, content={"detail": detail})


def _repository_is_durable(engine: SupplierSeedEngine) -> bool:
    repository = getattr(engine, "repository", None)
    if repository is None:
        return False
    if bool(getattr(repository, "durable", False)):
        return True
    return isinstance(repository, JsonFileSupplierRepository) and getattr(repository, "path", None) is not None


def _authentication_configured(settings: InternalSupplierApiSettings) -> bool:
    return bool(settings.enabled and settings.service_id and settings.hmac_keys)


def _write_ready(
    engine: SupplierSeedEngine,
    settings: InternalSupplierApiSettings,
    state_store: InternalMutationStateStore,
) -> bool:
    return bool(
        _authentication_configured(settings)
        and _repository_is_durable(engine)
        and state_store.durable
    )


def _capability_payload(
    engine: SupplierSeedEngine,
    settings: InternalSupplierApiSettings,
    state_store: InternalMutationStateStore,
) -> dict[str, Any]:
    return {
        "api_version": "internal-v1",
        "service_version": INTERNAL_SERVICE_VERSION,
        "supplier_creation_supported": _write_ready(engine, settings, state_store),
        "supplier_creation_contract_version": INTERNAL_CONTRACT_VERSION,
        "idempotency_payload_conflict_detection": True,
        "hmac_authentication": _authentication_configured(settings),
        "manual_supplier_mode_supported": True,
        "durable_repository": _repository_is_durable(engine),
        "durable_mutation_state": bool(state_store.durable),
        "public_enterprise_api_read_only": True,
    }


async def _authenticate_transport(
    request: Request,
    body: bytes,
    settings: InternalSupplierApiSettings,
    state_store: InternalMutationStateStore,
) -> AuthenticatedTransport | JSONResponse:
    headers = request.headers
    correlation_id = headers.get("X-Correlation-Id")

    if not settings.enabled:
        return _error(503, "service.unavailable", correlation_id)

    missing = [header for header in _REQUIRED_HEADERS if not headers.get(header)]
    if missing:
        return _error(401, "service.authentication_failed", correlation_id)

    if headers.get("X-Invyra-Service") != settings.service_id:
        return _error(401, "service.authentication_failed", correlation_id)

    key_id = headers.get("X-Invyra-Key-Id", "")
    secret = settings.hmac_keys.get(key_id)
    if not secret:
        return _error(401, "service.authentication_failed", correlation_id)

    timestamp_raw = headers.get("X-Invyra-Timestamp", "")
    try:
        timestamp = int(timestamp_raw)
    except ValueError:
        return _error(401, "service.authentication_failed", correlation_id)

    now = int(time.time())
    if abs(now - timestamp) > settings.maximum_clock_skew_seconds:
        return _error(401, "service.authentication_failed", correlation_id)

    actual_content_hash = content_sha256(body)
    supplied_content_hash = headers.get("X-Invyra-Content-SHA256", "").lower()
    if not hmac.compare_digest(actual_content_hash, supplied_content_hash):
        return _error(401, "service.authentication_failed", correlation_id)

    idempotency_key = headers.get("Idempotency-Key", "")
    nonce = headers.get("X-Invyra-Nonce", "")
    expected_signature = sign_internal_request(
        secret=secret,
        method=request.method,
        path=request.url.path,
        timestamp=timestamp_raw,
        nonce=nonce,
        content_hash=actual_content_hash,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id or "",
    )
    supplied_signature = headers.get("X-Invyra-Signature", "").lower()
    if not hmac.compare_digest(expected_signature, supplied_signature):
        return _error(401, "service.authentication_failed", correlation_id)

    expires_at = timestamp + settings.maximum_clock_skew_seconds
    if not state_store.claim_nonce(nonce, expires_at):
        return _error(401, "service.replay_detected", correlation_id)

    return AuthenticatedTransport(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id or "",
        nonce=nonce,
    )


def _request_fingerprint(payload: InternalSupplierCreateRequest) -> str:
    canonical = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _duplicate_candidates(preview_supplier: SupplierRecord, engine: SupplierSeedEngine) -> tuple[Any, ...]:
    repository = getattr(engine, "repository", None)
    existing = tuple(repository.list()) if repository is not None else ()
    return SupplierDedupeEngine().evaluate_supplier(preview_supplier, existing).candidates


def _format_duplicate_candidates(candidates: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [
        {
            "supplier_id": candidate.supplier.supplier_id,
            "name": candidate.supplier.name,
            "classification": candidate.classification.value,
            "confidence": candidate.confidence,
            "match_signals": [signal.code for signal in candidate.signals],
        }
        for candidate in candidates
    ]


def _governance_state(supplier: SupplierRecord | None) -> dict[str, Any] | None:
    if supplier is None:
        return None
    return {
        "lifecycle_status": supplier.lifecycle_status.value,
        "moderation_status": supplier.moderation_status.value,
        "verification_status": supplier.verification_status.value,
    }


def _normalized_result(
    *,
    result_kind: str,
    supplier: SupplierRecord | None,
    duplicate_candidates: list[dict[str, Any]],
    correlation_id: str,
    retry_safe: bool,
) -> dict[str, Any]:
    return {
        "contract_version": INTERNAL_CONTRACT_VERSION,
        "result_kind": result_kind,
        "supplier_id": supplier.supplier_id if supplier is not None else None,
        "supplier_usable": bool(supplier is not None and supplier.lifecycle_status == LifecycleStatus.ACTIVE),
        "governance_state": _governance_state(supplier),
        "duplicate_candidates": duplicate_candidates,
        "retry_safe": retry_safe,
        "correlation_id": correlation_id,
    }


def _store_result(
    state_store: InternalMutationStateStore,
    *,
    idempotency_key: str,
    fingerprint: str,
    status_code: int,
    payload: dict[str, Any],
) -> JSONResponse:
    state_store.save_receipt(idempotency_key, fingerprint, status_code, payload)
    return JSONResponse(status_code=status_code, content=payload)


def create_internal_app(
    engine: SupplierSeedEngine | None = None,
    *,
    settings: InternalSupplierApiSettings | None = None,
    state_store: InternalMutationStateStore | None = None,
) -> FastAPI:
    """Build the isolated server-only Supplier Seed mutation application.

    R3-S1 intentionally keeps this application separate from the public `/v1`
    read API. The module-level app is disabled unless server configuration is
    supplied, and LIVE writes remain blocked until durable mutation state is
    provided in R3-S2.
    """

    write_engine = engine or SupplierSeedEngine()
    runtime_settings = settings or InternalSupplierApiSettings.from_env()
    mutation_state = state_store or InMemoryInternalMutationStateStore()

    application = FastAPI(
        title="Invyra Supplier Seed Internal API",
        version=INTERNAL_SERVICE_VERSION,
        description="Server-only governed Supplier Seed mutation API.",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.get(INTERNAL_CAPABILITIES_PATH)
    async def internal_capabilities(request: Request) -> JSONResponse:
        body = await request.body()
        auth = await _authenticate_transport(request, body, runtime_settings, mutation_state)
        if isinstance(auth, JSONResponse):
            return auth
        return JSONResponse(
            status_code=200,
            content={**_capability_payload(write_engine, runtime_settings, mutation_state), "correlation_id": auth.correlation_id},
        )

    @application.post(INTERNAL_CREATE_PATH)
    async def create_supplier(request: Request) -> JSONResponse:
        body = await request.body()
        auth = await _authenticate_transport(request, body, runtime_settings, mutation_state)
        if isinstance(auth, JSONResponse):
            return auth

        if not _write_ready(write_engine, runtime_settings, mutation_state) and not runtime_settings.allow_nondurable_test_mode:
            return _error(503, "service.unavailable", auth.correlation_id)

        try:
            payload = InternalSupplierCreateRequest.model_validate_json(body)
        except ValidationError:
            return _error(400, "request.validation_failed", auth.correlation_id)

        if payload.contract_version != INTERNAL_CONTRACT_VERSION:
            return _error(400, "request.validation_failed", auth.correlation_id)
        if payload.environment not in runtime_settings.allowed_environments:
            return _error(400, "request.validation_failed", auth.correlation_id)
        if payload.actor.role.lower() not in {"admin", "owner"}:
            return _error(403, "service.authorization_failed", auth.correlation_id)
        if payload.candidate.mode != SupplierMode.MANUAL.value:
            return _error(400, "request.validation_failed", auth.correlation_id)
        if payload.candidate.region_context.pilot_enabled:
            return _error(400, "request.validation_failed", auth.correlation_id)

        fingerprint = _request_fingerprint(payload)
        existing_receipt = mutation_state.get_receipt(auth.idempotency_key)
        if existing_receipt is not None:
            if not hmac.compare_digest(existing_receipt.fingerprint, fingerprint):
                return _error(409, "idempotency.conflict", auth.correlation_id)
            return JSONResponse(status_code=existing_receipt.status_code, content=existing_receipt.payload)

        actor_id = f"inventory:{payload.actor.id.strip()}"
        region_context = SupplierRegionContext(
            market_code=payload.candidate.region_context.market_code,
            region_code=payload.candidate.region_context.region_code,
            pilot_enabled=False,
        )
        candidate_kwargs = {
            "region_context": region_context,
            "contact_email": payload.candidate.contact_email,
            "contact_phone": payload.candidate.contact_phone,
            "website_url": payload.candidate.website_url,
            "tax_identifier": payload.candidate.tax_identifier,
            "created_by": actor_id,
        }
        preview_supplier = SupplierRecord.manual_draft(payload.candidate.name, **candidate_kwargs)
        duplicate_matches = _duplicate_candidates(preview_supplier, write_engine)
        formatted_duplicates = _format_duplicate_candidates(duplicate_matches)

        if duplicate_matches and duplicate_matches[0].classification == DedupeMatchClassification.EXACT_DUPLICATE:
            result_payload = _normalized_result(
                result_kind="DUPLICATE_FOUND",
                supplier=None,
                duplicate_candidates=formatted_duplicates,
                correlation_id=auth.correlation_id,
                retry_safe=False,
            )
            return _store_result(
                mutation_state,
                idempotency_key=auth.idempotency_key,
                fingerprint=fingerprint,
                status_code=409,
                payload=result_payload,
            )

        access_context = AccessContext(actor_id=actor_id, role=GovernanceRole.ADMIN)
        policy_context = PolicyContext(
            region_code=region_context.region_code,
            market_code=region_context.market_code,
            pilot_enabled=False,
        )
        candidate = SupplierCandidateInput(
            name=payload.candidate.name,
            mode=SupplierMode.MANUAL,
            **candidate_kwargs,
        )
        result = write_engine.ingest_supplier(
            candidate,
            context=policy_context,
            persist=True,
            access_context=access_context,
            idempotency_key=auth.idempotency_key,
        )

        if not result.accepted_for_staging or result.supplier is None:
            result_payload = _normalized_result(
                result_kind="REJECTED",
                supplier=None,
                duplicate_candidates=formatted_duplicates,
                correlation_id=auth.correlation_id,
                retry_safe=False,
            )
            result_payload["decision_codes"] = [decision.code for decision in result.decisions]
            return _store_result(
                mutation_state,
                idempotency_key=auth.idempotency_key,
                fingerprint=fingerprint,
                status_code=422,
                payload=result_payload,
            )

        if result.outcome not in {PolicyOutcome.ALLOWED, PolicyOutcome.WARNING, PolicyOutcome.REQUIRES_REVIEW}:
            result_kind = "REJECTED"
            status_code = 422
            retry_safe = False
        else:
            result_kind = "REVIEW_REQUIRED"
            status_code = 202
            retry_safe = True

        result_payload = _normalized_result(
            result_kind=result_kind,
            supplier=result.supplier,
            duplicate_candidates=formatted_duplicates,
            correlation_id=auth.correlation_id,
            retry_safe=retry_safe,
        )
        result_payload["decision_codes"] = [decision.code for decision in result.decisions]
        return _store_result(
            mutation_state,
            idempotency_key=auth.idempotency_key,
            fingerprint=fingerprint,
            status_code=status_code,
            payload=result_payload,
        )

    return application


# Safe module-level target for a future separate internal deployment. Without
# server-side configuration it rejects all signed mutation traffic with 503.
app = create_internal_app()


__all__ = [
    "INTERNAL_CAPABILITIES_PATH",
    "INTERNAL_CONTRACT_VERSION",
    "INTERNAL_CREATE_PATH",
    "InMemoryInternalMutationStateStore",
    "InternalSupplierApiSettings",
    "app",
    "canonical_signature_material",
    "content_sha256",
    "create_internal_app",
    "sign_internal_request",
]
