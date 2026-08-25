# R3-S3 — Local Deployment Certification

Status: **LOCAL CERTIFICATION HARNESS IMPLEMENTED / NOT PRODUCTION ACTIVATION**

## Purpose

R3-S3 certifies the real Supplier Seed internal runtime target:

```text
supplier_seed.api.internal_runtime:app
```

The certification runs local Uvicorn child processes on loopback only. It does not use GitHub Actions, does not change Inventory/Base44, and does not authorize production supplier creation.

## What the certification proves

The executable harness verifies all of the following against real HTTP processes:

- a signed internal supplier-create request succeeds when the local deployment gates are explicitly enabled;
- exactly one supplier record persists;
- governance audit events persist in the Supplier Seed repository;
- nonce replay state persists;
- API idempotency receipt state persists;
- after a full runtime restart, the same idempotency key and same payload replay the original result;
- after restart, a changed payload with the same idempotency key returns `409 idempotency.conflict`;
- after restart, the original nonce is still rejected as replay;
- restart does not create a duplicate supplier;
- the separate public `/v1` API continues to declare itself read-only and `POST /v1/suppliers` returns `405`;
- the internal mutation route does not opt into cross-origin browser CORS;
- creation remains fail-closed when `SUPPLIER_SEED_INTERNAL_DEPLOYMENT_CERTIFIED` is false.

## Safety model

The harness is intentionally local-only:

- Uvicorn binds only to `127.0.0.1`;
- a fresh random test-only HMAC secret is generated for each run and is never written to the report;
- all Supplier Seed repository and mutation-state evidence is written only inside the supplied output directory;
- the output directory must be new or empty;
- the harness never deletes existing evidence or repository data;
- production activation is explicitly reported as `false`;
- no Inventory or Base44 configuration is read or changed.

The harness temporarily sets these variables **only in its child runtime processes**:

```text
SUPPLIER_SEED_INTERNAL_WRITE_ENABLED=true
SUPPLIER_SEED_INTERNAL_SERVICE_ID=inventory
SUPPLIER_SEED_INTERNAL_HMAC_KEYS_JSON=<ephemeral local test key>
SUPPLIER_SEED_INTERNAL_REPOSITORY_PATH=<local certification path>
SUPPLIER_SEED_INTERNAL_STATE_PATH=<local certification path>
SUPPLIER_SEED_INTERNAL_DURABLE_STORAGE_ATTESTED=true
SUPPLIER_SEED_INTERNAL_DEPLOYMENT_CERTIFIED=true|false
```

The `true` values are controlled local certification inputs only. They are not a production deployment attestation.

## Windows PowerShell execution

From the Supplier Seed repository root, with the existing `.venv` activated:

```powershell
python -m supplier_seed.operations.local_deployment_certification `
  --output-dir .\r3-s3-local-evidence
```

Expected terminal result:

```text
R3-S3 certified: True
Report: <absolute path>\r3-s3-certification-report.json
```

The evidence directory will contain:

```text
r3-s3-certification-report.json
supplier-repository.json
supplier-repository.json.lock
internal-state.json
internal-state.json.lock
fail-closed-supplier-repository.json
fail-closed-supplier-repository.json.lock
fail-closed-internal-state.json
fail-closed-internal-state.json.lock
```

Lock files are operational artifacts and may remain after the local run.

## Required local verification

Run the focused certification test first:

```powershell
python -m pytest -q tests/test_r3_s3_local_deployment_certification.py
```

Then run the complete Supplier Seed suite:

```powershell
python -m pytest -q
python -m compileall supplier_seed tests
```

Before committing copied files in the real Git repository:

```powershell
git status
git diff --check
git diff
```

## Evidence interpretation

A passing `r3-s3-certification-report.json` contains:

```json
{
  "certification_id": "R3-S3",
  "certified": true,
  "local_only": true,
  "production_activation_approved": false,
  "inventory_base44_changed": false
}
```

Every entry in `checks` must have `passed: true`.

The supplier repository must still contain exactly one certification supplier after the restart/replay/conflict sequence. The mutation-state file must contain the persisted nonce and idempotency receipt used by the run.

## R3-S3 stop gate

A local PASS means only that the Supplier Seed runtime behaves correctly under this controlled local deployment profile.

It does **not** certify:

- a production persistent-volume mount;
- production secret provisioning or rotation;
- production firewall/private-network exposure;
- a hosted deployment platform;
- Base44 onboarding authority;
- Inventory `+ Add supplier` UI;
- browser-held credentials or browser-direct Supplier Seed writes.

R3-P1 remains a separate phase and must not be enabled from this certification alone.
