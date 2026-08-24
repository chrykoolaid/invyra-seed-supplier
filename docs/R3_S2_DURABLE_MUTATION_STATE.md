# R3-S2 — Durable Mutation State & Deployment Safety

Status: implemented on feature branch; merge only after Supplier Seed CI is green.

## Purpose

R3-S2 hardens the R3-S1 internal supplier creation API so nonce replay protection and payload-fingerprint idempotency receipts can survive a service restart.

This phase does **not** activate Inventory supplier onboarding and does not make the browser a Supplier Seed writer.

## Durable runtime target

The deployable internal application is:

```text
supplier_seed.api.internal_runtime:app
```

The R3-S1 module-level target remains fail-closed and unchanged.

## Persistence model

R3-S2 uses two separate JSON-backed stores:

1. Supplier Seed governed records and governance events:

```text
JsonFileSupplierRepository
```

2. Internal transport/mutation state:

```text
JsonFileInternalMutationStateStore
```

The second store persists:

- accepted request nonces and their expiry timestamps;
- idempotency keys;
- canonical payload fingerprints;
- original normalized HTTP status codes;
- original normalized response payloads.

Both files use atomic replacement on write and process/thread locking consistent with the existing Supplier Seed JSON repository approach.

## Restart guarantees

With the same persistent paths after restart:

```text
same nonce
  -> rejected as replay while still inside the replay window

same idempotency key + same payload
  -> original normalized result is replayed

same idempotency key + changed payload
  -> 409 idempotency.conflict
```

A restart must not create a second supplier for a completed request whose mutation receipt was already durably stored.

## Environment configuration

Existing R3-S1 server-only configuration remains required:

```text
SUPPLIER_SEED_INTERNAL_WRITE_ENABLED
SUPPLIER_SEED_INTERNAL_SERVICE_ID
SUPPLIER_SEED_INTERNAL_HMAC_KEYS_JSON
```

R3-S2 adds:

```text
SUPPLIER_SEED_INTERNAL_REPOSITORY_PATH
SUPPLIER_SEED_INTERNAL_STATE_PATH
SUPPLIER_SEED_INTERNAL_DURABLE_STORAGE_ATTESTED
SUPPLIER_SEED_INTERNAL_DEPLOYMENT_CERTIFIED
```

Both paths must be absolute and must not point to the same file.

## Two separate safety gates

### Durable storage attestation

`SUPPLIER_SEED_INTERNAL_DURABLE_STORAGE_ATTESTED=true` means the deployment operator confirms both configured files are located on storage that survives application/container restarts.

A normal writable container filesystem does not satisfy this requirement.

### Deployment certification

`SUPPLIER_SEED_INTERNAL_DEPLOYMENT_CERTIFIED=true` is deliberately separate and must remain unset until R3-S3 verifies the deployed service.

The durable state store reports `durable=false` unless **both** durability attestation and deployment certification are true.

Therefore, during R3-S2 itself:

```text
supplier_creation_supported = false
```

in the real deployment unless R3-S3 has explicitly certified it.

## Fail-closed behavior

The runtime refuses LIVE supplier creation when any of the following apply:

- internal writes are disabled;
- HMAC keys are absent;
- supplier repository path is absent;
- mutation-state path is absent;
- either path is relative;
- both paths resolve to the same file;
- the supplier repository cannot be opened;
- the mutation-state file is malformed;
- durable storage is not attested;
- deployment certification is absent.

A signed capabilities request may still succeed where authentication is configured, but it reports:

```text
supplier_creation_supported = false
```

## Deployment constraint for R3-S3

The current JSON persistence model is intended for a controlled **single-writer Supplier Seed service deployment**.

R3-S3 must verify, before setting the deployment-certified gate:

- exactly one Supplier Seed internal writer instance/process owns the mutation surface;
- both JSON paths are on persistent storage;
- file locking is supported by the selected storage;
- restart retains supplier records, governance events, nonces and idempotency receipts;
- HMAC secrets are server-only and not exposed through browser configuration;
- the internal endpoint is network-restricted to trusted server-to-server traffic;
- public `/v1` remains read-only;
- a controlled end-to-end restart test passes.

Horizontal multi-writer deployment requires a later transactional database-backed persistence design and is outside R3-S2.

## Preserved boundaries

R3-S2 does not change:

- public `/v1` API routes;
- public SDK behavior;
- supplier domain model;
- moderation/verification/lifecycle rules;
- InventoryItem;
- PurchaseOrder;
- Receiving;
- stock or StockMovement;
- pricing;
- Supplier Portal;
- Inventory Base44 runtime.

## Known crash-consistency boundary

R3-S2 certifies restart persistence for completed internal receipts. The existing Supplier Seed ingestion engine still persists supplier, governance events and its domain operation receipt in its existing sequence.

R3-S3 must include a controlled kill/restart acceptance test before LIVE activation. If that test exposes a crash window between domain persistence and internal receipt completion, activation remains blocked and a follow-up atomic persistence repair is required.

This is why `SUPPLIER_SEED_INTERNAL_DEPLOYMENT_CERTIFIED` remains a separate final gate.

## Exit gate

R3-S2 is complete when:

- durable nonce state survives restart;
- durable idempotency receipts survive restart;
- same-key changed-payload conflicts survive restart;
- corrupt or incomplete persistence configuration fails closed;
- the durable runtime does not advertise creation before deployment certification;
- existing R3-S1, Supplier Seed, Phase T and SDK certification suites remain green;
- no public API mutation is introduced.
