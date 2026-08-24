import json
import time
from uuid import uuid4

from fastapi.testclient import TestClient

from supplier_seed import JsonFileSupplierRepository, SupplierSeedEngine
from supplier_seed.api.internal_app import (
    INTERNAL_CAPABILITIES_PATH,
    INTERNAL_CREATE_PATH,
    InternalSupplierApiSettings,
    content_sha256,
    create_internal_app,
    sign_internal_request,
)
from supplier_seed.api.internal_runtime import (
    DEPLOYMENT_CERTIFIED_ENV,
    DURABILITY_ATTESTED_ENV,
    REPOSITORY_PATH_ENV,
    STATE_PATH_ENV,
    create_internal_runtime_app_from_env,
)
from supplier_seed.api.internal_state import JsonFileInternalMutationStateStore


KEY_ID = "inventory-r3-s2"
SECRET = "r3-s2-test-secret-not-for-production"


def _settings():
    return InternalSupplierApiSettings(
        enabled=True,
        service_id="inventory",
        hmac_keys={KEY_ID: SECRET},
        maximum_clock_skew_seconds=300,
        allowed_environments=("LIVE",),
        allow_nondurable_test_mode=False,
    )


def _body(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _headers(method, path, body, *, idempotency_key=None, correlation_id=None, nonce=None):
    timestamp = str(int(time.time()))
    nonce = nonce or uuid4().hex
    idempotency_key = idempotency_key or f"idem-{uuid4().hex}"
    correlation_id = correlation_id or f"corr-{uuid4().hex}"
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


def _candidate(name="Durable Supplier", tax_identifier="PH-900-100"):
    return {
        "contract_version": "R3-P0A-v1",
        "environment": "LIVE",
        "actor": {"id": "admin-456", "role": "admin"},
        "candidate": {
            "name": name,
            "mode": "manual",
            "region_context": {
                "market_code": "PH",
                "region_code": "PH-06",
                "pilot_enabled": False,
            },
            "contact_email": "durable@example.test",
            "contact_phone": None,
            "website_url": None,
            "tax_identifier": tax_identifier,
        },
    }


def _durable_client(repo_path, state_path):
    repository = JsonFileSupplierRepository(repo_path)
    engine = SupplierSeedEngine(repository=repository)
    state = JsonFileInternalMutationStateStore(
        state_path,
        durability_attested=True,
        deployment_certified=True,
    )
    app = create_internal_app(engine, settings=_settings(), state_store=state)
    return TestClient(app), engine, state


def test_nonce_and_receipt_survive_state_store_restart(tmp_path):
    path = tmp_path / "internal-state.json"
    first = JsonFileInternalMutationStateStore(
        path,
        durability_attested=True,
        deployment_certified=True,
    )
    expiry = int(time.time()) + 300
    assert first.claim_nonce("restart-nonce", expiry) is True
    saved = first.save_receipt(
        "restart-idempotency",
        "fingerprint-a",
        202,
        {"result_kind": "REVIEW_REQUIRED", "supplier_id": "supplier-1"},
    )
    assert saved.fingerprint == "fingerprint-a"

    restarted = JsonFileInternalMutationStateStore(
        path,
        durability_attested=True,
        deployment_certified=True,
    )
    assert restarted.claim_nonce("restart-nonce", expiry) is False
    receipt = restarted.get_receipt("restart-idempotency")
    assert receipt is not None
    assert receipt.fingerprint == "fingerprint-a"
    assert receipt.status_code == 202
    assert receipt.payload["supplier_id"] == "supplier-1"


def test_two_store_instances_coordinate_nonce_and_receipt_claims(tmp_path):
    path = tmp_path / "shared-state.json"
    left = JsonFileInternalMutationStateStore(path, durability_attested=True, deployment_certified=True)
    right = JsonFileInternalMutationStateStore(path, durability_attested=True, deployment_certified=True)

    expiry = int(time.time()) + 300
    assert left.claim_nonce("shared-nonce", expiry) is True
    assert right.claim_nonce("shared-nonce", expiry) is False

    left.save_receipt("shared-idem", "fingerprint-left", 202, {"value": "first"})
    replay = right.save_receipt("shared-idem", "fingerprint-right", 409, {"value": "second"})
    assert replay.fingerprint == "fingerprint-left"
    assert replay.status_code == 202
    assert replay.payload == {"value": "first"}


def test_internal_api_replays_same_result_after_full_process_restart(tmp_path):
    repo_path = tmp_path / "supplier-repository.json"
    state_path = tmp_path / "internal-state.json"
    idempotency_key = "idem-restart-safe"
    request_payload = _candidate()
    raw = _body(request_payload)

    client_one, engine_one, _ = _durable_client(repo_path, state_path)
    first_headers = _headers(
        "POST",
        INTERNAL_CREATE_PATH,
        raw,
        idempotency_key=idempotency_key,
        correlation_id="corr-first",
    )
    first = client_one.post(INTERNAL_CREATE_PATH, content=raw, headers=first_headers)
    assert first.status_code == 202
    assert len(engine_one.repository.list()) == 1

    client_two, engine_two, _ = _durable_client(repo_path, state_path)
    second_headers = _headers(
        "POST",
        INTERNAL_CREATE_PATH,
        raw,
        idempotency_key=idempotency_key,
        correlation_id="corr-second",
    )
    second = client_two.post(INTERNAL_CREATE_PATH, content=raw, headers=second_headers)
    assert second.status_code == 202
    assert second.json() == first.json()
    assert len(engine_two.repository.list()) == 1


def test_changed_payload_with_same_key_conflicts_after_restart(tmp_path):
    repo_path = tmp_path / "supplier-repository.json"
    state_path = tmp_path / "internal-state.json"
    idempotency_key = "idem-restart-conflict"

    first_payload = _candidate(name="Supplier Alpha", tax_identifier="PH-111-222")
    first_raw = _body(first_payload)
    client_one, _, _ = _durable_client(repo_path, state_path)
    first = client_one.post(
        INTERNAL_CREATE_PATH,
        content=first_raw,
        headers=_headers("POST", INTERNAL_CREATE_PATH, first_raw, idempotency_key=idempotency_key),
    )
    assert first.status_code == 202

    changed_payload = _candidate(name="Supplier Beta", tax_identifier="PH-333-444")
    changed_raw = _body(changed_payload)
    client_two, engine_two, _ = _durable_client(repo_path, state_path)
    changed = client_two.post(
        INTERNAL_CREATE_PATH,
        content=changed_raw,
        headers=_headers("POST", INTERNAL_CREATE_PATH, changed_raw, idempotency_key=idempotency_key),
    )
    assert changed.status_code == 409
    assert changed.json()["detail"]["code"] == "idempotency.conflict"
    assert len(engine_two.repository.list()) == 1


def test_runtime_remains_fail_closed_until_deployment_certification(monkeypatch, tmp_path):
    repo_path = tmp_path / "supplier-repository.json"
    state_path = tmp_path / "internal-state.json"
    monkeypatch.setenv("SUPPLIER_SEED_INTERNAL_WRITE_ENABLED", "true")
    monkeypatch.setenv("SUPPLIER_SEED_INTERNAL_HMAC_KEYS_JSON", json.dumps({KEY_ID: SECRET}))
    monkeypatch.setenv(REPOSITORY_PATH_ENV, str(repo_path.resolve()))
    monkeypatch.setenv(STATE_PATH_ENV, str(state_path.resolve()))
    monkeypatch.setenv(DURABILITY_ATTESTED_ENV, "true")
    monkeypatch.delenv(DEPLOYMENT_CERTIFIED_ENV, raising=False)

    client = TestClient(create_internal_runtime_app_from_env())
    response = client.get(
        INTERNAL_CAPABILITIES_PATH,
        headers=_headers("GET", INTERNAL_CAPABILITIES_PATH, b""),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["durable_repository"] is True
    assert payload["durable_mutation_state"] is False
    assert payload["supplier_creation_supported"] is False


def test_certified_runtime_with_absolute_persistent_paths_survives_restart(monkeypatch, tmp_path):
    repo_path = tmp_path / "supplier-repository.json"
    state_path = tmp_path / "internal-state.json"
    monkeypatch.setenv("SUPPLIER_SEED_INTERNAL_WRITE_ENABLED", "true")
    monkeypatch.setenv("SUPPLIER_SEED_INTERNAL_HMAC_KEYS_JSON", json.dumps({KEY_ID: SECRET}))
    monkeypatch.setenv(REPOSITORY_PATH_ENV, str(repo_path.resolve()))
    monkeypatch.setenv(STATE_PATH_ENV, str(state_path.resolve()))
    monkeypatch.setenv(DURABILITY_ATTESTED_ENV, "true")
    monkeypatch.setenv(DEPLOYMENT_CERTIFIED_ENV, "true")

    first_client = TestClient(create_internal_runtime_app_from_env())
    capabilities = first_client.get(
        INTERNAL_CAPABILITIES_PATH,
        headers=_headers("GET", INTERNAL_CAPABILITIES_PATH, b""),
    )
    assert capabilities.status_code == 200
    assert capabilities.json()["supplier_creation_supported"] is True

    request_payload = _candidate()
    raw = _body(request_payload)
    first = first_client.post(
        INTERNAL_CREATE_PATH,
        content=raw,
        headers=_headers(
            "POST",
            INTERNAL_CREATE_PATH,
            raw,
            idempotency_key="idem-runtime-restart",
            correlation_id="corr-runtime-first",
        ),
    )
    assert first.status_code == 202

    second_client = TestClient(create_internal_runtime_app_from_env())
    replay = second_client.post(
        INTERNAL_CREATE_PATH,
        content=raw,
        headers=_headers(
            "POST",
            INTERNAL_CREATE_PATH,
            raw,
            idempotency_key="idem-runtime-restart",
            correlation_id="corr-runtime-second",
        ),
    )
    assert replay.status_code == 202
    assert replay.json() == first.json()


def test_relative_or_corrupt_persistence_configuration_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPPLIER_SEED_INTERNAL_WRITE_ENABLED", "true")
    monkeypatch.setenv("SUPPLIER_SEED_INTERNAL_HMAC_KEYS_JSON", json.dumps({KEY_ID: SECRET}))
    monkeypatch.setenv(DURABILITY_ATTESTED_ENV, "true")
    monkeypatch.setenv(DEPLOYMENT_CERTIFIED_ENV, "true")
    monkeypatch.setenv(REPOSITORY_PATH_ENV, "relative-repository.json")
    monkeypatch.setenv(STATE_PATH_ENV, str((tmp_path / "state.json").resolve()))

    relative_client = TestClient(create_internal_runtime_app_from_env())
    response = relative_client.get(
        INTERNAL_CAPABILITIES_PATH,
        headers=_headers("GET", INTERNAL_CAPABILITIES_PATH, b""),
    )
    assert response.status_code == 200
    assert response.json()["supplier_creation_supported"] is False

    repo_path = tmp_path / "supplier-repository.json"
    state_path = tmp_path / "corrupt-state.json"
    state_path.write_text("{not-json", encoding="utf-8")
    monkeypatch.setenv(REPOSITORY_PATH_ENV, str(repo_path.resolve()))
    monkeypatch.setenv(STATE_PATH_ENV, str(state_path.resolve()))

    corrupt_client = TestClient(create_internal_runtime_app_from_env())
    corrupt = corrupt_client.get(
        INTERNAL_CAPABILITIES_PATH,
        headers=_headers("GET", INTERNAL_CAPABILITIES_PATH, b""),
    )
    assert corrupt.status_code == 200
    assert corrupt.json()["supplier_creation_supported"] is False
