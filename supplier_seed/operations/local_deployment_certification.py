from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from supplier_seed.api.internal_app import (
    INTERNAL_CAPABILITIES_PATH,
    INTERNAL_CONTRACT_VERSION,
    INTERNAL_CREATE_PATH,
    content_sha256,
    sign_internal_request,
)


INTERNAL_RUNTIME_TARGET = "supplier_seed.api.internal_runtime:app"
PUBLIC_RUNTIME_TARGET = "supplier_seed.api.app:app"
CERTIFICATION_ID = "R3-S3"
LOCAL_BIND_HOST = "127.0.0.1"
KEY_ID = "r3-s3-local-certification"
SERVICE_ID = "inventory"


@dataclass(frozen=True)
class CertificationCheck:
    code: str
    passed: bool
    observed: Any = None


class CertificationFailure(RuntimeError):
    pass


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind((LOCAL_BIND_HOST, 0))
        return int(handle.getsockname()[1])


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _start_runtime(target: str, *, env: dict[str, str]) -> tuple[subprocess.Popen[bytes], str]:
    port = _reserve_loopback_port()
    base_url = f"http://{LOCAL_BIND_HOST}:{port}"
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        target,
        "--host",
        LOCAL_BIND_HOST,
        "--port",
        str(port),
        "--log-level",
        "error",
    ]
    process = subprocess.Popen(
        command,
        cwd=_project_root(),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _wait_until_ready(process, base_url)
    return process, base_url


def _wait_until_ready(process: subprocess.Popen[bytes], base_url: str, timeout_seconds: float = 8.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    with httpx.Client(timeout=0.4, trust_env=False) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=1)
                detail = (stderr or stdout).decode("utf-8", errors="replace").strip()
                raise CertificationFailure(f"Runtime exited before readiness: {detail or process.returncode}")
            try:
                response = client.get(f"{base_url}/__r3_s3_readiness_probe__")
                if response.status_code in {401, 404, 405, 503}:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
    raise CertificationFailure(f"Runtime did not become ready at {base_url}")


def _stop_runtime(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _body(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _signed_headers(
    *,
    secret: str,
    method: str,
    path: str,
    body: bytes,
    idempotency_key: str,
    correlation_id: str,
    nonce: str | None = None,
) -> tuple[dict[str, str], str]:
    timestamp = str(int(time.time()))
    nonce_value = nonce or uuid4().hex
    digest = content_sha256(body)
    signature = sign_internal_request(
        secret=secret,
        method=method,
        path=path,
        timestamp=timestamp,
        nonce=nonce_value,
        content_hash=digest,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    return (
        {
            "X-Invyra-Service": SERVICE_ID,
            "X-Invyra-Key-Id": KEY_ID,
            "X-Invyra-Timestamp": timestamp,
            "X-Invyra-Nonce": nonce_value,
            "X-Invyra-Content-SHA256": digest,
            "X-Invyra-Signature": signature,
            "Idempotency-Key": idempotency_key,
            "X-Correlation-Id": correlation_id,
        },
        nonce_value,
    )


def _candidate_payload(*, name: str, tax_identifier: str) -> dict[str, Any]:
    return {
        "contract_version": INTERNAL_CONTRACT_VERSION,
        "environment": "LIVE",
        "actor": {"id": "r3-s3-local-admin", "role": "admin"},
        "candidate": {
            "name": name,
            "mode": "manual",
            "region_context": {
                "market_code": "PH",
                "region_code": "PH-06",
                "pilot_enabled": False,
            },
            "contact_email": "r3-s3-certification@example.test",
            "contact_phone": None,
            "website_url": None,
            "tax_identifier": tax_identifier,
        },
    }


def _base_child_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("SUPPLIER_SEED_INTERNAL_HMAC_KEYS_JSON", None)
    env.pop("SUPPLIER_SEED_INTERNAL_REPOSITORY_PATH", None)
    env.pop("SUPPLIER_SEED_INTERNAL_STATE_PATH", None)
    env.pop("SUPPLIER_SEED_INTERNAL_DURABLE_STORAGE_ATTESTED", None)
    env.pop("SUPPLIER_SEED_INTERNAL_DEPLOYMENT_CERTIFIED", None)
    env.pop("SUPPLIER_SEED_INTERNAL_WRITE_ENABLED", None)
    env.pop("SUPPLIER_SEED_INTERNAL_SERVICE_ID", None)
    return env


def _internal_env(
    *,
    secret: str,
    repository_path: Path,
    state_path: Path,
    deployment_certified: bool,
) -> dict[str, str]:
    env = _base_child_env()
    env.update(
        {
            "SUPPLIER_SEED_INTERNAL_WRITE_ENABLED": "true",
            "SUPPLIER_SEED_INTERNAL_SERVICE_ID": SERVICE_ID,
            "SUPPLIER_SEED_INTERNAL_HMAC_KEYS_JSON": json.dumps({KEY_ID: secret}),
            "SUPPLIER_SEED_INTERNAL_REPOSITORY_PATH": str(repository_path.resolve()),
            "SUPPLIER_SEED_INTERNAL_STATE_PATH": str(state_path.resolve()),
            "SUPPLIER_SEED_INTERNAL_DURABLE_STORAGE_ATTESTED": "true",
            "SUPPLIER_SEED_INTERNAL_DEPLOYMENT_CERTIFIED": "true" if deployment_certified else "false",
        }
    )
    return env


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CertificationFailure(f"Expected JSON object in {path}")
    return payload


def _record(checks: list[CertificationCheck], code: str, condition: bool, observed: Any = None) -> None:
    checks.append(CertificationCheck(code=code, passed=bool(condition), observed=observed))
    if not condition:
        raise CertificationFailure(f"Certification gate failed: {code}; observed={observed!r}")


def _assert_workspace_is_safe(output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise CertificationFailure(
            f"Certification output directory must be new or empty: {output_dir}. "
            "R3-S3 never deletes existing evidence or repository data."
        )
    output_dir.mkdir(parents=True, exist_ok=True)


def run_local_deployment_certification(output_dir: str | os.PathLike[str]) -> dict[str, Any]:
    """Certify the real R3-S3 local Supplier Seed runtime on loopback only.

    The function launches the module-level Uvicorn targets in child processes,
    uses an ephemeral test-only HMAC secret, writes only inside ``output_dir``,
    and never changes Inventory/Base44 configuration.
    """

    workspace = Path(output_dir).expanduser().resolve()
    _assert_workspace_is_safe(workspace)

    repository_path = workspace / "supplier-repository.json"
    state_path = workspace / "internal-state.json"
    fail_closed_repository_path = workspace / "fail-closed-supplier-repository.json"
    fail_closed_state_path = workspace / "fail-closed-internal-state.json"
    report_path = workspace / "r3-s3-certification-report.json"

    checks: list[CertificationCheck] = []
    evidence: dict[str, Any] = {
        "runtime_target": INTERNAL_RUNTIME_TARGET,
        "public_runtime_target": PUBLIC_RUNTIME_TARGET,
        "bind_host": LOCAL_BIND_HOST,
        "repository_path": str(repository_path),
        "state_path": str(state_path),
    }
    secret = secrets.token_urlsafe(32)
    process: subprocess.Popen[bytes] | None = None

    try:
        # Gate 1: prove creation is still fail-closed when deployment certification is absent.
        process, base_url = _start_runtime(
            INTERNAL_RUNTIME_TARGET,
            env=_internal_env(
                secret=secret,
                repository_path=fail_closed_repository_path,
                state_path=fail_closed_state_path,
                deployment_certified=False,
            ),
        )
        with httpx.Client(base_url=base_url, timeout=3.0, trust_env=False) as client:
            cap_headers, _ = _signed_headers(
                secret=secret,
                method="GET",
                path=INTERNAL_CAPABILITIES_PATH,
                body=b"",
                idempotency_key="r3-s3-fail-closed-capabilities",
                correlation_id="r3-s3-fail-closed-capabilities",
            )
            capabilities = client.get(INTERNAL_CAPABILITIES_PATH, headers=cap_headers)
            _record(checks, "fail_closed.capabilities_http_200", capabilities.status_code == 200, capabilities.status_code)
            _record(
                checks,
                "fail_closed.creation_not_supported",
                capabilities.json().get("supplier_creation_supported") is False,
                capabilities.json(),
            )

            fail_payload = _candidate_payload(name="R3-S3 Fail Closed Supplier", tax_identifier="PH-R3-S3-FAIL-CLOSED")
            fail_body = _body(fail_payload)
            fail_headers, _ = _signed_headers(
                secret=secret,
                method="POST",
                path=INTERNAL_CREATE_PATH,
                body=fail_body,
                idempotency_key="r3-s3-fail-closed-create",
                correlation_id="r3-s3-fail-closed-create",
            )
            fail_create = client.post(INTERNAL_CREATE_PATH, content=fail_body, headers=fail_headers)
            _record(checks, "fail_closed.create_http_503", fail_create.status_code == 503, fail_create.status_code)
        _stop_runtime(process)
        process = None
        if fail_closed_repository_path.exists():
            fail_closed_repository = _load_json(fail_closed_repository_path)
            _record(
                checks,
                "fail_closed.no_supplier_created",
                len(fail_closed_repository.get("suppliers", [])) == 0,
                len(fail_closed_repository.get("suppliers", [])),
            )

        # Gate 2: start the explicitly certified local runtime and create one governed supplier.
        process, base_url = _start_runtime(
            INTERNAL_RUNTIME_TARGET,
            env=_internal_env(
                secret=secret,
                repository_path=repository_path,
                state_path=state_path,
                deployment_certified=True,
            ),
        )
        idempotency_key = "r3-s3-restart-idempotency"
        payload = _candidate_payload(
            name="R3-S3 Local Certification Supplier",
            tax_identifier=f"PH-R3-S3-{uuid4().hex[:12].upper()}",
        )
        raw = _body(payload)
        with httpx.Client(base_url=base_url, timeout=3.0, trust_env=False) as client:
            cap_headers, _ = _signed_headers(
                secret=secret,
                method="GET",
                path=INTERNAL_CAPABILITIES_PATH,
                body=b"",
                idempotency_key="r3-s3-certified-capabilities",
                correlation_id="r3-s3-certified-capabilities",
            )
            capabilities = client.get(INTERNAL_CAPABILITIES_PATH, headers=cap_headers)
            _record(checks, "certified.capabilities_http_200", capabilities.status_code == 200, capabilities.status_code)
            _record(
                checks,
                "certified.creation_supported",
                capabilities.json().get("supplier_creation_supported") is True,
                capabilities.json(),
            )

            create_headers, create_nonce = _signed_headers(
                secret=secret,
                method="POST",
                path=INTERNAL_CREATE_PATH,
                body=raw,
                idempotency_key=idempotency_key,
                correlation_id="r3-s3-create-first",
            )
            created = client.post(INTERNAL_CREATE_PATH, content=raw, headers=create_headers)
            _record(checks, "certified.create_http_202", created.status_code == 202, created.status_code)
            created_payload = created.json()
            _record(checks, "certified.result_review_required", created_payload.get("result_kind") == "REVIEW_REQUIRED", created_payload)
            _record(checks, "certified.supplier_not_usable", created_payload.get("supplier_usable") is False, created_payload)

            origin_probe = client.options(
                INTERNAL_CREATE_PATH,
                headers={
                    "Origin": "https://inventory.example.invalid",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
            _record(
                checks,
                "browser.no_cross_origin_mutation_cors",
                origin_probe.headers.get("access-control-allow-origin") is None,
                dict(origin_probe.headers),
            )

        _stop_runtime(process)
        process = None

        repository_before_restart = _load_json(repository_path)
        state_before_restart = _load_json(state_path)
        supplier_count_before_restart = len(repository_before_restart.get("suppliers", []))
        event_count_before_restart = len(repository_before_restart.get("audit_events", []))
        nonce_count_before_restart = len(state_before_restart.get("nonces", {}))
        receipt_count_before_restart = len(state_before_restart.get("receipts", {}))
        evidence.update(
            {
                "supplier_id": created_payload.get("supplier_id"),
                "supplier_count_before_restart": supplier_count_before_restart,
                "governance_event_count_before_restart": event_count_before_restart,
                "nonce_count_before_restart": nonce_count_before_restart,
                "idempotency_receipt_count_before_restart": receipt_count_before_restart,
            }
        )
        _record(checks, "persistence.one_supplier", supplier_count_before_restart == 1, supplier_count_before_restart)
        _record(checks, "persistence.governance_events_present", event_count_before_restart > 0, event_count_before_restart)
        _record(checks, "persistence.nonce_present", create_nonce in state_before_restart.get("nonces", {}), create_nonce)
        _record(checks, "persistence.idempotency_receipt_present", idempotency_key in state_before_restart.get("receipts", {}), idempotency_key)

        # Gate 3: restart the real runtime with the exact same persistence paths.
        process, base_url = _start_runtime(
            INTERNAL_RUNTIME_TARGET,
            env=_internal_env(
                secret=secret,
                repository_path=repository_path,
                state_path=state_path,
                deployment_certified=True,
            ),
        )
        with httpx.Client(base_url=base_url, timeout=3.0, trust_env=False) as client:
            replay_headers, _ = _signed_headers(
                secret=secret,
                method="POST",
                path=INTERNAL_CREATE_PATH,
                body=raw,
                idempotency_key=idempotency_key,
                correlation_id="r3-s3-create-replay",
            )
            replayed = client.post(INTERNAL_CREATE_PATH, content=raw, headers=replay_headers)
            _record(checks, "restart.replay_http_202", replayed.status_code == 202, replayed.status_code)
            _record(checks, "restart.replays_original_result", replayed.json() == created_payload, replayed.json())

            replay_nonce_headers, _ = _signed_headers(
                secret=secret,
                method="POST",
                path=INTERNAL_CREATE_PATH,
                body=raw,
                idempotency_key="r3-s3-nonce-replay-probe",
                correlation_id="r3-s3-nonce-replay-probe",
                nonce=create_nonce,
            )
            nonce_replay = client.post(INTERNAL_CREATE_PATH, content=raw, headers=replay_nonce_headers)
            _record(checks, "restart.persisted_nonce_rejected", nonce_replay.status_code == 401, nonce_replay.status_code)
            _record(
                checks,
                "restart.persisted_nonce_error_code",
                nonce_replay.json().get("detail", {}).get("code") == "service.replay_detected",
                nonce_replay.json(),
            )

            changed_payload = _candidate_payload(
                name="R3-S3 Changed Payload Supplier",
                tax_identifier=f"PH-R3-S3-CHANGED-{uuid4().hex[:8].upper()}",
            )
            changed_raw = _body(changed_payload)
            changed_headers, _ = _signed_headers(
                secret=secret,
                method="POST",
                path=INTERNAL_CREATE_PATH,
                body=changed_raw,
                idempotency_key=idempotency_key,
                correlation_id="r3-s3-changed-payload",
            )
            changed = client.post(INTERNAL_CREATE_PATH, content=changed_raw, headers=changed_headers)
            _record(checks, "restart.changed_payload_http_409", changed.status_code == 409, changed.status_code)
            _record(
                checks,
                "restart.changed_payload_conflict_code",
                changed.json().get("detail", {}).get("code") == "idempotency.conflict",
                changed.json(),
            )
        _stop_runtime(process)
        process = None

        repository_after_restart = _load_json(repository_path)
        _record(
            checks,
            "restart.no_duplicate_supplier",
            len(repository_after_restart.get("suppliers", [])) == 1,
            len(repository_after_restart.get("suppliers", [])),
        )

        # Gate 4: prove the separate public /v1 runtime remains read-only.
        process, public_url = _start_runtime(PUBLIC_RUNTIME_TARGET, env=_base_child_env())
        with httpx.Client(base_url=public_url, timeout=3.0, trust_env=False) as client:
            public_capabilities = client.get("/v1/capabilities")
            _record(checks, "public.capabilities_http_200", public_capabilities.status_code == 200, public_capabilities.status_code)
            _record(
                checks,
                "public.v1_declares_read_only",
                public_capabilities.json().get("enterprise_api_read_only") is True,
                public_capabilities.json(),
            )
            public_create = client.post("/v1/suppliers", json={})
            _record(checks, "public.v1_create_method_not_allowed", public_create.status_code == 405, public_create.status_code)
        _stop_runtime(process)
        process = None

        evidence["supplier_count_after_restart"] = len(repository_after_restart.get("suppliers", []))
        evidence["public_v1_post_status"] = public_create.status_code
        evidence["changed_payload_status"] = changed.status_code
        evidence["replay_status"] = replayed.status_code
        evidence["nonce_replay_status"] = nonce_replay.status_code
        certified = all(check.passed for check in checks)
        error = None
    except Exception as exc:  # keep a durable local report even when a gate fails
        certified = False
        error = f"{type(exc).__name__}: {exc}"
        if not checks or checks[-1].passed:
            checks.append(CertificationCheck(code="certification.execution", passed=False, observed=error))
    finally:
        _stop_runtime(process)

    report = {
        "certification_id": CERTIFICATION_ID,
        "certified": certified,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "python_version": sys.version.split()[0],
        "runtime_target": INTERNAL_RUNTIME_TARGET,
        "public_runtime_target": PUBLIC_RUNTIME_TARGET,
        "local_only": True,
        "production_activation_approved": False,
        "inventory_base44_changed": False,
        "error": error,
        "checks": [asdict(check) for check in checks],
        "evidence": evidence,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run R3-S3 local deployment certification against real Uvicorn runtime processes."
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="New or empty directory used only for R3-S3 local certification evidence.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_local_deployment_certification(args.output_dir)
    report_path = Path(args.output_dir).expanduser().resolve() / "r3-s3-certification-report.json"
    print(f"R3-S3 certified: {report['certified']}")
    print(f"Report: {report_path}")
    if report.get("error"):
        print(f"Failure: {report['error']}", file=sys.stderr)
    return 0 if report["certified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
