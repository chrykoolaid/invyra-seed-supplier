import json
import time
from uuid import uuid4

from fastapi.testclient import TestClient

from supplier_seed.api.internal_app import (
    INTERNAL_CREATE_PATH,
    InMemoryInternalMutationStateStore,
    InternalSupplierApiSettings,
    content_sha256,
    sign_internal_request,
)
from supplier_seed.api.internal_review_app import (
    INTERNAL_REVIEW_CONTRACT_VERSION,
    create_internal_review_app,
)
from supplier_seed.pilot import SupplierSeedEngine


KEY_ID = "inventory-r3-p5-test"
SECRET = "r3-p5-test-secret-not-for-production"


def _settings():
    return InternalSupplierApiSettings(
        enabled=True,
        service_id="inventory",
        hmac_keys={KEY_ID: SECRET},
        maximum_clock_skew_seconds=300,
        allowed_environments=("LIVE",),
        allow_nondurable_test_mode=True,
    )


def _body(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _headers(*, method, path, body, idempotency_key=None, nonce=None):
    timestamp = str(int(time.time()))
    nonce = nonce or uuid4().hex
    idempotency_key = idempotency_key or f"idem-{uuid4().hex}"
    correlation_id = f"corr-{uuid4().hex}"
    digest = content_sha256(body)
    signature = sign_internal_request(
        secret=SECRET,
        method=method,
        path=path,
        timestamp=timestamp,
        nonce=nonce,
        content_hash=digest,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    return {
        "X-Invyra-Service": "inventory",
        "X-Invyra-Key-Id": KEY_ID,
        "X-Invyra-Timestamp": timestamp,
        "X-Invyra-Nonce": nonce,
        "X-Invyra-Content-SHA256": digest,
        "X-Invyra-Signature": signature,
        "Idempotency-Key": idempotency_key,
        "X-Correlation-Id": correlation_id,
    }


def _request(client, method, path, payload=None, idempotency_key=None):
    raw = b"" if payload is None else _body(payload)
    headers = _headers(
        method=method,
        path=path,
        body=raw,
        idempotency_key=idempotency_key,
    )
    return client.request(method, path, content=raw, headers=headers)


def _create_payload(name="R3-P5 Test Supplier", role="admin"):
    return {
        "contract_version": "R3-P0A-v1",
        "environment": "LIVE",
        "actor": {"id": "admin-123", "role": role},
        "candidate": {
            "name": name,
            "mode": "manual",
            "region_context": {
                "market_code": "PH",
                "region_code": "PH-06",
                "pilot_enabled": False,
            },
            "contact_email": "supplier@example.test",
            "contact_phone": "+63 912 345 6789",
            "website_url": "https://supplier.example.test",
            "tax_identifier": "PH-R3-P5-001",
        },
    }


def _decision_payload(*, decision, role="admin", reason=""):
    return {
        "contract_version": INTERNAL_REVIEW_CONTRACT_VERSION,
        "environment": "LIVE",
        "actor": {"id": "reviewer-123", "role": role},
        "decision": decision,
        "reason": reason,
        "expected_lifecycle_status": "draft",
        "expected_moderation_status": "not_reviewed",
    }


def _client():
    engine = SupplierSeedEngine()
    state = InMemoryInternalMutationStateStore()
    app = create_internal_review_app(engine, settings=_settings(), state_store=state)
    return TestClient(app), engine


def _stage_supplier(client, name="R3-P5 Test Supplier"):
    response = _request(client, "POST", INTERNAL_CREATE_PATH, _create_payload(name))
    assert response.status_code == 202
    return response.json()["supplier_id"]


def test_review_snapshot_is_hmac_authenticated_and_keeps_candidate_non_operational():
    client, engine = _client()
    supplier_id = _stage_supplier(client)
    path = f"/internal/v1/suppliers/{supplier_id}/review"

    unsigned = client.get(path)
    assert unsigned.status_code == 401

    response = _request(client, "GET", path)
    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_version"] == INTERNAL_REVIEW_CONTRACT_VERSION
    assert payload["supplier_id"] == supplier_id
    assert payload["supplier"]["name"] == "R3-P5 Test Supplier"
    assert payload["governance_state"] == {
        "lifecycle_status": "draft",
        "moderation_status": "not_reviewed",
        "verification_status": "not_verified",
    }
    assert engine.repository.get(supplier_id).lifecycle_status.value == "draft"


def test_admin_can_approve_review_without_activating_supplier():
    client, engine = _client()
    supplier_id = _stage_supplier(client)
    path = f"/internal/v1/suppliers/{supplier_id}/review/decision"

    response = _request(client, "POST", path, _decision_payload(decision="approve"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["result_kind"] == "APPROVED"
    assert payload["supplier_usable"] is False
    assert payload["governance_state"]["lifecycle_status"] == "approved"
    assert payload["governance_state"]["moderation_status"] == "approved"
    assert payload["governance_state"]["verification_status"] == "not_verified"
    supplier = engine.repository.get(supplier_id)
    assert supplier.lifecycle_status.value == "approved"
    assert supplier.lifecycle_status.value != "active"


def test_reject_requires_reason_and_transitions_to_rejected():
    client, engine = _client()
    supplier_id = _stage_supplier(client, "R3-P5 Reject Supplier")
    path = f"/internal/v1/suppliers/{supplier_id}/review/decision"

    missing_reason = _request(client, "POST", path, _decision_payload(decision="reject"))
    assert missing_reason.status_code == 400
    assert missing_reason.json()["detail"]["code"] == "supplier.review.rejection_reason_required"

    response = _request(
        client,
        "POST",
        path,
        _decision_payload(decision="reject", reason="Supplier details could not be confirmed."),
    )
    assert response.status_code == 200
    assert response.json()["result_kind"] == "REJECTED"
    supplier = engine.repository.get(supplier_id)
    assert supplier.lifecycle_status.value == "rejected"
    assert supplier.moderation_status.value == "rejected"


def test_review_decision_is_admin_owner_only_and_stale_state_fails_closed():
    client, engine = _client()
    supplier_id = _stage_supplier(client, "R3-P5 Guard Supplier")
    path = f"/internal/v1/suppliers/{supplier_id}/review/decision"

    denied = _request(client, "POST", path, _decision_payload(decision="approve", role="manager"))
    assert denied.status_code == 403
    assert engine.repository.get(supplier_id).moderation_status.value == "not_reviewed"

    stale_payload = _decision_payload(decision="approve")
    stale_payload["expected_moderation_status"] = "pending_review"
    stale = _request(client, "POST", path, stale_payload)
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "supplier.review.stale"
    assert engine.repository.get(supplier_id).moderation_status.value == "not_reviewed"


def test_same_decision_idempotency_key_replays_without_second_transition():
    client, engine = _client()
    supplier_id = _stage_supplier(client, "R3-P5 Replay Supplier")
    path = f"/internal/v1/suppliers/{supplier_id}/review/decision"
    payload = _decision_payload(decision="approve")
    key = f"r3p5-{uuid4().hex}"

    first = _request(client, "POST", path, payload, idempotency_key=key)
    second = _request(client, "POST", path, payload, idempotency_key=key)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["result_kind"] == "APPROVED"
    assert second.json()["result_kind"] == "APPROVED"
    assert second.json()["replayed"] is True
    supplier = engine.repository.get(supplier_id)
    assert supplier.lifecycle_status.value == "approved"
