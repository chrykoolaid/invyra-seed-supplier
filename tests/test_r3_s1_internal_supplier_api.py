import json
import time
from uuid import uuid4

from fastapi.testclient import TestClient

from supplier_seed.api.app import create_app as create_public_app
from supplier_seed.api.internal_app import (
    INTERNAL_CAPABILITIES_PATH,
    INTERNAL_CREATE_PATH,
    InMemoryInternalMutationStateStore,
    InternalSupplierApiSettings,
    content_sha256,
    create_internal_app,
    sign_internal_request,
)
from supplier_seed.engine import SupplierSeedEngine as CoreSupplierSeedEngine
from supplier_seed.pilot import SupplierSeedEngine
from supplier_seed.services.permissions import GovernanceRole


KEY_ID = "inventory-r3-test"
SECRET = "r3-s1-test-secret-not-for-production"


def _settings(*, allow_nondurable_test_mode=True):
    return InternalSupplierApiSettings(
        enabled=True,
        service_id="inventory",
        hmac_keys={KEY_ID: SECRET},
        maximum_clock_skew_seconds=300,
        allowed_environments=("LIVE",),
        allow_nondurable_test_mode=allow_nondurable_test_mode,
    )


def _body(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _headers(
    *,
    method,
    path,
    body,
    idempotency_key=None,
    correlation_id=None,
    nonce=None,
    timestamp=None,
    secret=SECRET,
    key_id=KEY_ID,
):
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    nonce = nonce or uuid4().hex
    idempotency_key = idempotency_key or f"idem-{uuid4().hex}"
    correlation_id = correlation_id or f"corr-{uuid4().hex}"
    digest = content_sha256(body)
    signature = sign_internal_request(
        secret=secret,
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
        "X-Invyra-Key-Id": key_id,
        "X-Invyra-Timestamp": timestamp,
        "X-Invyra-Nonce": nonce,
        "X-Invyra-Content-SHA256": digest,
        "X-Invyra-Signature": signature,
        "Idempotency-Key": idempotency_key,
        "X-Correlation-Id": correlation_id,
    }


def _candidate(*, name="LaundryChem Direct", actor_role="admin", tax_identifier="PH-TAX-100"):
    return {
        "contract_version": "R3-P0A-v1",
        "environment": "LIVE",
        "actor": {"id": "admin-123", "role": actor_role},
        "candidate": {
            "name": name,
            "mode": "manual",
            "region_context": {
                "market_code": "PH",
                "region_code": "PH-06",
                "pilot_enabled": False,
            },
            "contact_email": "orders@example.test",
            "contact_phone": None,
            "website_url": None,
            "tax_identifier": tax_identifier,
        },
    }


def _client(*, engine=None, allow_nondurable_test_mode=True, state_store=None):
    engine = engine or SupplierSeedEngine()
    state_store = state_store or InMemoryInternalMutationStateStore()
    app = create_internal_app(
        engine,
        settings=_settings(allow_nondurable_test_mode=allow_nondurable_test_mode),
        state_store=state_store,
    )
    return TestClient(app), engine, state_store


def _signed_request(client, method, path, payload=None, **header_overrides):
    raw = b"" if payload is None else _body(payload)
    headers = _headers(method=method, path=path, body=raw, **header_overrides)
    return client.request(method, path, content=raw, headers=headers)


def test_internal_capabilities_are_authenticated_and_fail_closed_for_nondurable_state():
    client, _, _ = _client()

    unsigned = client.get(INTERNAL_CAPABILITIES_PATH)
    assert unsigned.status_code == 401

    response = _signed_request(client, "GET", INTERNAL_CAPABILITIES_PATH)
    assert response.status_code == 200
    payload = response.json()
    assert payload["supplier_creation_contract_version"] == "R3-P0A-v1"
    assert payload["hmac_authentication"] is True
    assert payload["manual_supplier_mode_supported"] is True
    assert payload["durable_repository"] is False
    assert payload["durable_mutation_state"] is False
    assert payload["supplier_creation_supported"] is False
    assert payload["public_enterprise_api_read_only"] is True


def test_valid_admin_submission_stages_manual_supplier_but_does_not_make_it_usable():
    client, engine, _ = _client()
    request_payload = _candidate()

    response = _signed_request(client, "POST", INTERNAL_CREATE_PATH, request_payload)

    assert response.status_code == 202
    payload = response.json()
    assert payload["result_kind"] == "REVIEW_REQUIRED"
    assert payload["supplier_usable"] is False
    assert payload["governance_state"]["lifecycle_status"] == "draft"
    assert payload["supplier_id"]
    supplier = engine.repository.get(payload["supplier_id"])
    assert supplier is not None
    assert supplier.created_by == "inventory:admin-123"
    assert supplier.mode.value == "manual"
    assert supplier.region_context.pilot_enabled is False


def test_owner_claim_is_allowed_but_manager_claim_is_rejected_before_mutation():
    owner_client, owner_engine, _ = _client()
    owner_response = _signed_request(owner_client, "POST", INTERNAL_CREATE_PATH, _candidate(actor_role="owner"))
    assert owner_response.status_code == 202
    assert len(owner_engine.repository.list()) == 1

    manager_client, manager_engine, _ = _client()
    manager_response = _signed_request(manager_client, "POST", INTERNAL_CREATE_PATH, _candidate(actor_role="manager"))
    assert manager_response.status_code == 403
    assert manager_response.json()["detail"]["code"] == "service.authorization_failed"
    assert len(manager_engine.repository.list()) == 0


def test_bad_signature_expired_timestamp_and_content_hash_are_rejected_without_mutation():
    client, engine, _ = _client()
    request_payload = _candidate()
    raw = _body(request_payload)

    bad_signature_headers = _headers(method="POST", path=INTERNAL_CREATE_PATH, body=raw, secret="wrong-secret")
    bad_signature = client.post(INTERNAL_CREATE_PATH, content=raw, headers=bad_signature_headers)
    assert bad_signature.status_code == 401

    expired_headers = _headers(
        method="POST",
        path=INTERNAL_CREATE_PATH,
        body=raw,
        timestamp=int(time.time()) - 301,
    )
    expired = client.post(INTERNAL_CREATE_PATH, content=raw, headers=expired_headers)
    assert expired.status_code == 401

    hash_headers = _headers(method="POST", path=INTERNAL_CREATE_PATH, body=raw)
    hash_headers["X-Invyra-Content-SHA256"] = "0" * 64
    hash_mismatch = client.post(INTERNAL_CREATE_PATH, content=raw, headers=hash_headers)
    assert hash_mismatch.status_code == 401

    assert len(engine.repository.list()) == 0


def test_nonce_replay_is_rejected():
    client, engine, _ = _client()
    request_payload = _candidate()
    raw = _body(request_payload)
    nonce = uuid4().hex
    headers = _headers(method="POST", path=INTERNAL_CREATE_PATH, body=raw, nonce=nonce)

    first = client.post(INTERNAL_CREATE_PATH, content=raw, headers=headers)
    second = client.post(INTERNAL_CREATE_PATH, content=raw, headers=headers)

    assert first.status_code == 202
    assert second.status_code == 401
    assert second.json()["detail"]["code"] == "service.replay_detected"
    assert len(engine.repository.list()) == 1


def test_same_idempotency_key_same_payload_replays_original_result_with_new_nonce():
    client, engine, _ = _client()
    request_payload = _candidate()
    raw = _body(request_payload)
    idempotency_key = f"idem-{uuid4().hex}"

    first_headers = _headers(
        method="POST",
        path=INTERNAL_CREATE_PATH,
        body=raw,
        idempotency_key=idempotency_key,
        correlation_id="corr-first",
    )
    second_headers = _headers(
        method="POST",
        path=INTERNAL_CREATE_PATH,
        body=raw,
        idempotency_key=idempotency_key,
        correlation_id="corr-second",
    )

    first = client.post(INTERNAL_CREATE_PATH, content=raw, headers=first_headers)
    second = client.post(INTERNAL_CREATE_PATH, content=raw, headers=second_headers)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json() == first.json()
    assert len(engine.repository.list()) == 1


def test_same_idempotency_key_with_changed_payload_returns_conflict():
    client, engine, _ = _client()
    idempotency_key = f"idem-{uuid4().hex}"

    first_payload = _candidate(name="Supplier One", tax_identifier="PH-TAX-ONE")
    first_raw = _body(first_payload)
    first_headers = _headers(
        method="POST",
        path=INTERNAL_CREATE_PATH,
        body=first_raw,
        idempotency_key=idempotency_key,
    )
    first = client.post(INTERNAL_CREATE_PATH, content=first_raw, headers=first_headers)
    assert first.status_code == 202

    changed_payload = _candidate(name="Supplier Two", tax_identifier="PH-TAX-TWO")
    changed_raw = _body(changed_payload)
    changed_headers = _headers(
        method="POST",
        path=INTERNAL_CREATE_PATH,
        body=changed_raw,
        idempotency_key=idempotency_key,
    )
    changed = client.post(INTERNAL_CREATE_PATH, content=changed_raw, headers=changed_headers)

    assert changed.status_code == 409
    assert changed.json()["detail"]["code"] == "idempotency.conflict"
    assert len(engine.repository.list()) == 1


def test_exact_duplicate_returns_existing_candidate_and_does_not_stage_second_supplier():
    client, engine, _ = _client()

    first = _signed_request(
        client,
        "POST",
        INTERNAL_CREATE_PATH,
        _candidate(name="Original Supplier", tax_identifier="PH-TAX-DUP"),
    )
    assert first.status_code == 202
    existing_supplier_id = first.json()["supplier_id"]

    duplicate = _signed_request(
        client,
        "POST",
        INTERNAL_CREATE_PATH,
        _candidate(name="Renamed Supplier", tax_identifier="PH-TAX-DUP"),
    )

    assert duplicate.status_code == 409
    payload = duplicate.json()
    assert payload["result_kind"] == "DUPLICATE_FOUND"
    assert payload["supplier_id"] is None
    assert payload["supplier_usable"] is False
    assert payload["duplicate_candidates"][0]["supplier_id"] == existing_supplier_id
    assert payload["duplicate_candidates"][0]["classification"] == "exact_duplicate"
    assert len(engine.repository.list()) == 1


def test_live_mutation_fails_closed_without_durable_repository_and_mutation_state():
    client, engine, _ = _client(allow_nondurable_test_mode=False)
    response = _signed_request(client, "POST", INTERNAL_CREATE_PATH, _candidate())

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "service.unavailable"
    assert len(engine.repository.list()) == 0


def test_public_enterprise_api_remains_read_only_and_internal_app_isolated():
    public_client = TestClient(create_public_app(CoreSupplierSeedEngine()))
    public_capabilities = public_client.get("/v1/capabilities")
    assert public_capabilities.status_code == 200
    assert public_capabilities.json()["enterprise_api_read_only"] is True
    assert public_capabilities.json()["mutation_authority"] == "domain_service_only"
    assert public_client.post("/v1/suppliers", json={}).status_code == 405
    assert public_client.get(INTERNAL_CAPABILITIES_PATH).status_code == 404

    internal_client, _, _ = _client()
    assert internal_client.get("/v1/suppliers").status_code == 404


def test_engine_access_context_for_internal_create_is_never_none():
    class RecordingEngine(SupplierSeedEngine):
        def __init__(self):
            super().__init__()
            self.seen_access_context = None

        def ingest_supplier(self, *args, **kwargs):
            self.seen_access_context = kwargs.get("access_context")
            return super().ingest_supplier(*args, **kwargs)

    engine = RecordingEngine()
    client, _, _ = _client(engine=engine)
    response = _signed_request(client, "POST", INTERNAL_CREATE_PATH, _candidate())

    assert response.status_code == 202
    assert engine.seen_access_context is not None
    assert engine.seen_access_context.role == GovernanceRole.ADMIN
    assert engine.seen_access_context.actor_id == "inventory:admin-123"
