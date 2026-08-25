# R3-P4 — Render Production Deployment Preparation

Status: **PREPARED / FAIL-CLOSED / NOT YET LIVE-ACTIVATED**

This deployment profile exists to complete the hosted Supplier Seed side of R3-P4 without using GitHub Actions and without enabling Base44 production supplier creation before persistent storage is verified.

## Deployment target

Render web service:

- region: `singapore`
- runtime: Python 3.12
- service: `invyra-supplier-seed-internal`
- branch: `r3-p4-render-deployment-prep`
- one service instance
- auto-deploy: off
- persistent disk: 1 GB mounted at `/var/data`
- start command:

```text
uvicorn supplier_seed.api.internal_runtime:app --host 0.0.0.0 --port $PORT
```

A paid Render web-service plan is required because the internal runtime needs a persistent disk. The service must remain internet-addressable over HTTPS because Base44 is outside Render's private network. The internal API remains HMAC-authenticated and exposes no Swagger/OpenAPI documentation.

## Why the first deploy is fail-closed

The Blueprint intentionally sets:

```text
SUPPLIER_SEED_INTERNAL_WRITE_ENABLED=true
SUPPLIER_SEED_INTERNAL_DURABLE_STORAGE_ATTESTED=true
SUPPLIER_SEED_INTERNAL_DEPLOYMENT_CERTIFIED=false
```

This allows the signed capability endpoint and HMAC configuration to be tested against the real hosted service while keeping `durable_mutation_state=false` and `supplier_creation_supported=false`.

The internal create endpoint checks the complete write-ready gate before validating or mutating a supplier, so with deployment certification still false it returns `503 service.unavailable` and cannot create a supplier.

Do not set `SUPPLIER_SEED_INTERNAL_DEPLOYMENT_CERTIFIED=true` until the persistent disk survives a real service restart.

## HMAC key

Use key id:

```text
inventory-r3p4-v1
```

Generate a new random secret locally. Example:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Store the secret securely. Do not commit it.

During the initial Render Blueprint creation, set:

```text
SUPPLIER_SEED_INTERNAL_HMAC_KEYS_JSON
```

to:

```json
{"inventory-r3p4-v1":"<the generated secret>"}
```

The same secret will later be configured server-side in Base44 as `SUPPLIER_SEED_WRITE_SECRET`. It must never be placed in frontend/Vite configuration.

## Stage A — initial hosted deployment

Create the Render Blueprint from branch:

```text
r3-p4-render-deployment-prep
```

The `render.yaml` file disables auto-deploys, so later repository changes do not redeploy this service automatically.

After the first deploy, record the HTTPS service origin, for example:

```text
https://invyra-supplier-seed-internal.onrender.com
```

Do not add a path to the Base44 write base URL.

### Expected unsigned result

An unsigned request to:

```text
GET /internal/v1/capabilities
```

should return `401 service.authentication_failed` after the HMAC keyring is configured. This confirms that the public network surface does not reveal internal capability data without a valid signature.

## Stage B — signed non-mutating capability probe

Set the probe secret only in the local terminal session:

```powershell
$env:SUPPLIER_SEED_PROBE_SECRET = "<the generated secret>"
```

Run:

```powershell
python -m supplier_seed.operations.remote_deployment_probe `
  --base-url https://<render-service-host> `
  --key-id inventory-r3p4-v1
```

The pre-certification probe must PASS with:

```text
hmac_authentication=true
durable_repository=true
durable_mutation_state=false
supplier_creation_supported=false
public_enterprise_api_read_only=true
```

The probe performs only a signed GET. It never calls the supplier-create endpoint and never prints the HMAC secret.

## Stage C — persistent disk restart evidence

Open the Render service Shell and write a non-secret sentinel to the persistent mount:

```bash
python - <<'PY'
from pathlib import Path
from secrets import token_hex
p = Path('/var/data/r3-p4-persistence-sentinel.txt')
if p.exists():
    print('Existing sentinel:', p.read_text(encoding='utf-8').strip())
else:
    value = token_hex(16)
    p.write_text(value + '\n', encoding='utf-8')
    print('Created sentinel:', value)
PY
```

Record the sentinel value, then restart the Render service from the Render Dashboard.

After the service is healthy again, open Shell and run:

```bash
cat /var/data/r3-p4-persistence-sentinel.txt
```

The value must be identical.

Also confirm that the configured application paths are under the same persistent mount:

```text
/var/data/supplier-repository.json
/var/data/internal-state.json
```

If the sentinel is missing or changes, stop. Do not certify the deployment and do not enable Base44 writes.

## Stage D — certify the hosted persistence gate

Only after Stage C passes, change the Render environment variable to:

```text
SUPPLIER_SEED_INTERNAL_DEPLOYMENT_CERTIFIED=true
```

Then perform a manual deploy/restart.

Run the signed probe again with the ready expectation:

```powershell
python -m supplier_seed.operations.remote_deployment_probe `
  --base-url https://<render-service-host> `
  --key-id inventory-r3p4-v1 `
  --expect-ready
```

It must PASS with:

```text
hmac_authentication=true
durable_repository=true
durable_mutation_state=true
supplier_creation_supported=true
public_enterprise_api_read_only=true
```

This is still non-mutating evidence.

## Stage E — Base44 server configuration

After Stage D passes, configure these as Base44 server-only values:

```text
SUPPLIER_SEED_WRITE_BASE_URL=https://<render-service-host>
SUPPLIER_SEED_WRITE_KEY_ID=inventory-r3p4-v1
SUPPLIER_SEED_WRITE_SECRET=<same generated secret>
SUPPLIER_SEED_WRITE_ENABLED=false
```

Keep `SUPPLIER_SEED_WRITE_ENABLED=false` until the R3-P4 acceptance operator explicitly authorizes the first controlled LIVE submission.

Never create any `VITE_SUPPLIER_SEED_WRITE_*` variable.

## Stage F — controlled R3-P4 acceptance submission

The first real Base44 submission is a separate acceptance gate. Before it occurs:

1. confirm Render `--expect-ready` capability PASS;
2. confirm Base44 R3-P1 validator PASS;
3. confirm zero unintended SupplierOnboardingAuthorityReceipt rows;
4. choose an explicitly approved real supplier or an explicitly approved certification supplier record;
5. enable `SUPPLIER_SEED_WRITE_ENABLED=true` in Base44;
6. submit once through the governed Add Supplier UI;
7. verify the Base44 receipt and Supplier Seed persisted result;
8. retry the same submission identity only if recovery evidence is required;
9. do not mutate InventoryItem, PurchaseOrder, Receiving, stock, pricing, or POS as part of this acceptance.

Do not create test supplier data in production without explicit approval.

## GitHub Actions constraint

The repository's Supplier Seed workflow runs on:

```text
push to main
pull_request targeting main
```

This deployment preparation is intentionally kept on `r3-p4-render-deployment-prep` with no PR opened. A normal push to this non-main branch does not match those workflow triggers.

Do not open a PR or merge this branch while GitHub Actions minutes are unavailable unless the workflow configuration is intentionally changed first.

## Stop gate

R3-P4 remains blocked until all of the following are evidenced:

```text
Render HTTPS deployment                     PASS
HMAC-authenticated capabilities             PASS
Persistent disk survives restart            PASS
Hosted deployment certification flag        true
Remote capability probe --expect-ready       PASS
Base44 write URL/key/secret configured       PASS
Base44 write enable explicitly authorized    PASS
Controlled governed supplier submission      PASS
Base44 receipt evidence                      PASS
Supplier Seed persistence evidence           PASS
No unrelated Inventory mutations             PASS
```
