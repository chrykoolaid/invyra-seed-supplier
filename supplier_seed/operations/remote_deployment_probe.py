from __future__ import annotations

import argparse
import json
import os
import secrets
import time
import uuid
from urllib.parse import urlparse

import httpx

from supplier_seed.api.internal_app import (
    INTERNAL_CAPABILITIES_PATH,
    INTERNAL_CONTRACT_VERSION,
    content_sha256,
    sign_internal_request,
)


DEFAULT_KEY_ID = "inventory-r3p4-v1"
SECRET_ENV = "SUPPLIER_SEED_PROBE_SECRET"


def _base_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("The production probe base URL must be an absolute HTTPS origin.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("The production probe base URL must not contain credentials, query parameters, or fragments.")
    if parsed.path not in {"", "/"}:
        raise ValueError("The production probe base URL must not contain a path prefix.")
    port = f":{parsed.port}" if parsed.port else ""
    return f"https://{parsed.hostname}{port}"


def _signed_headers(*, key_id: str, secret: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(24)
    idempotency_key = f"r3p4-capability-{uuid.uuid4()}"
    correlation_id = f"r3p4-probe-{uuid.uuid4()}"
    content_hash = content_sha256(b"")
    signature = sign_internal_request(
        secret=secret,
        method="GET",
        path=INTERNAL_CAPABILITIES_PATH,
        timestamp=timestamp,
        nonce=nonce,
        content_hash=content_hash,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    return {
        "X-Invyra-Service": "inventory",
        "X-Invyra-Key-Id": key_id,
        "X-Invyra-Timestamp": timestamp,
        "X-Invyra-Nonce": nonce,
        "X-Invyra-Content-SHA256": content_hash,
        "X-Invyra-Signature": signature,
        "Idempotency-Key": idempotency_key,
        "X-Correlation-Id": correlation_id,
    }


def _assert_capabilities(payload: object, *, expect_ready: bool) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise RuntimeError("Supplier Seed returned a non-object capability payload.")

    expected = {
        "api_version": "internal-v1",
        "supplier_creation_contract_version": INTERNAL_CONTRACT_VERSION,
        "idempotency_payload_conflict_detection": True,
        "hmac_authentication": True,
        "manual_supplier_mode_supported": True,
        "durable_repository": True,
        "durable_mutation_state": expect_ready,
        "public_enterprise_api_read_only": True,
        "supplier_creation_supported": expect_ready,
    }
    failures = [
        f"{key}={payload.get(key)!r} (expected {value!r})"
        for key, value in expected.items()
        if payload.get(key) != value
    ]
    if not str(payload.get("service_version") or "").strip():
        failures.append("service_version is missing")
    if failures:
        raise RuntimeError("Capability gate mismatch: " + "; ".join(failures))
    return payload


def run_probe(*, base_url: str, key_id: str, secret: str, expect_ready: bool, timeout_seconds: float) -> dict[str, object]:
    origin = _base_url(base_url)
    response = httpx.get(
        f"{origin}{INTERNAL_CAPABILITIES_PATH}",
        headers=_signed_headers(key_id=key_id, secret=secret),
        timeout=timeout_seconds,
        follow_redirects=False,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Capability request failed with HTTP {response.status_code}.")
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError("Capability response was not valid JSON.") from exc
    validated = _assert_capabilities(payload, expect_ready=expect_ready)
    return {
        "base_url": origin,
        "api_version": validated["api_version"],
        "service_version": validated["service_version"],
        "contract_version": validated["supplier_creation_contract_version"],
        "hmac_authentication": validated["hmac_authentication"],
        "durable_repository": validated["durable_repository"],
        "durable_mutation_state": validated["durable_mutation_state"],
        "supplier_creation_supported": validated["supplier_creation_supported"],
        "public_enterprise_api_read_only": validated["public_enterprise_api_read_only"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="R3-P4 signed, non-mutating Supplier Seed production capability probe.",
    )
    parser.add_argument("--base-url", required=True, help="Supplier Seed HTTPS origin, without a path.")
    parser.add_argument("--key-id", default=DEFAULT_KEY_ID)
    parser.add_argument("--expect-ready", action="store_true", help="Require the production mutation capability to be fully enabled.")
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    args = parser.parse_args()

    secret = os.getenv(SECRET_ENV, "")
    if not secret:
        raise SystemExit(f"{SECRET_ENV} is required and is never printed by this probe.")

    result = run_probe(
        base_url=args.base_url,
        key_id=args.key_id,
        secret=secret,
        expect_ready=args.expect_ready,
        timeout_seconds=args.timeout_seconds,
    )
    print("R3-P4 remote capability probe: PASS")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
