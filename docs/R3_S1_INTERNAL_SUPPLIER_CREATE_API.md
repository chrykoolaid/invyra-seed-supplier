# R3-S1 — Internal Supplier Creation API

Status: **IMPLEMENTED ON FEATURE BRANCH / NOT PRODUCTION-ACTIVATED**

## Scope

R3-S1 adds a separate server-only FastAPI application for governed supplier creation while preserving the existing public Supplier Seed enterprise API as read-only.

Feature branch:

`r3-s1-internal-supplier-create-api`

Locked predecessor:

`0613af29c54601967c302e2439f8cc71f3d3361b`

Inventory cross-repository contract:

`R3-P0A-v1`

## Internal surface

The new internal app exposes only:

```text
GET  /internal/v1/capabilities
POST /internal/v1/suppliers
```

The existing public app continues to expose its existing `/v1/...` read contracts. R3-S1 does not add POST/PUT/PATCH/DELETE supplier mutations to the public enterprise API.

The internal app is intentionally separate so it can later be deployed behind a server-only/private boundary without exposing its write URL or credentials to browser code.

## Safe default

The module-level internal application is disabled by default.

Without explicit server configuration, signed internal requests fail closed with:

```text
503 service.unavailable
```

No Inventory browser integration is added in this phase.

## HMAC authentication

R3-S1 implements the `R3-P0A-v1` HMAC-SHA256 request contract.

Required headers:

```text
X-Invyra-Service
X-Invyra-Key-Id
X-Invyra-Timestamp
X-Invyra-Nonce
X-Invyra-Content-SHA256
X-Invyra-Signature
Idempotency-Key
X-Correlation-Id
```

Signature material:

```text
HTTP_METHOD + "\n" +
REQUEST_PATH + "\n" +
TIMESTAMP + "\n" +
NONCE + "\n" +
CONTENT_SHA256 + "\n" +
IDEMPOTENCY_KEY + "\n" +
CORRELATION_ID
```

Controls implemented in R3-S1:

- known service ID required;
- active key ID required;
- multiple active HMAC keys supported through the keyring;
- timestamp must be within 300 seconds;
- body SHA-256 must match before request parsing;
- signature comparison uses constant-time comparison;
- accepted nonce cannot be reused within the replay window;
- correlation and idempotency identities are required.

The shared secret is never accepted from the request body and no browser configuration surface is introduced.

## Inventory role boundary

The signed request body contains the authenticated Inventory actor and Inventory role.

Only:

```text
admin
owner
```

are accepted.

After the HMAC body is verified, those roles are mapped to:

```text
AccessContext(
  actor_id="inventory:<actor>",
  role=GovernanceRole.ADMIN
)
```

The Supplier Seed engine is never invoked by the internal endpoint with `access_context=None`.

## Supplier creation behavior

R3-S1 reuses the existing authoritative domain action:

```text
SupplierSeedEngine.ingest_supplier(...)
```

Creation mode is always:

```text
SupplierMode.MANUAL
```

The browser cannot supply `created_by`; it is derived from the authenticated signed actor.

`pilot_enabled=true` is rejected.

A normally accepted manual supplier is staged as a governed draft and returns:

```text
202 REVIEW_REQUIRED
supplier_usable=false
```

R3-S1 never marks a newly staged supplier active or usable.

## Duplicate behavior

The internal endpoint reuses `SupplierDedupeEngine` against the authoritative Supplier Seed repository before ingestion.

- exact duplicate -> `409 DUPLICATE_FOUND`, no second supplier is staged;
- likely duplicate -> supplier may be staged under existing engine governance and returns `REVIEW_REQUIRED` with match context;
- possible duplicate -> supplier may be staged under existing engine governance and returns `REVIEW_REQUIRED` with match context.

Automatic merge is not implemented.

## Idempotency hardening

The R3-S1 endpoint fingerprints the full validated signed creation payload.

```text
same Idempotency-Key + same fingerprint
  -> replay original normalized result

same Idempotency-Key + different fingerprint
  -> 409 idempotency.conflict
```

The endpoint also passes the same idempotency key to the existing Supplier Seed engine.

## Durability gate

R3-S1 intentionally does **not** claim LIVE write readiness.

The included `InMemoryInternalMutationStateStore` exists only to test authentication, replay, duplicate and idempotency behavior.

It reports:

```text
durable = false
```

The internal capability reports `supplier_creation_supported=true` only when all of the following are true:

- internal mutation feature enabled;
- HMAC keyring configured;
- Supplier Seed repository is durable;
- mutation replay/idempotency state store is durable.

The default in-memory Supplier Seed repository is not considered durable.

A non-durable test override exists only as an explicit constructor option for automated tests and is never enabled from environment configuration.

## Capability contract

Authenticated `GET /internal/v1/capabilities` reports:

```text
service_version
supplier_creation_supported
supplier_creation_contract_version
idempotency_payload_conflict_detection
hmac_authentication
manual_supplier_mode_supported
durable_repository
durable_mutation_state
public_enterprise_api_read_only
```

Inventory must continue to fail closed while `supplier_creation_supported` is false.

## R3-S1 test coverage

Focused tests cover:

- authenticated capability discovery;
- valid Admin creation;
- valid Owner creation;
- Manager rejection;
- invalid HMAC rejection;
- expired timestamp rejection;
- body-hash mismatch rejection;
- nonce replay rejection;
- same-key/same-payload replay;
- same-key/different-payload conflict;
- exact duplicate rejection without second staging;
- fail-closed behavior without durable state;
- non-null Supplier Seed `AccessContext`;
- public `/v1` API remains read-only;
- internal app does not expose public supplier routes.

## Remaining R3-S2 gates

R3-S1 is not a production deployment approval.

Before `supplier_creation_supported` may become true in a LIVE deployment, R3-S2 must certify and/or implement:

1. durable nonce replay storage;
2. durable payload-fingerprint/idempotency receipts;
3. durable Supplier Seed repository configuration for the deployed service;
4. consistent failure semantics across supplier persistence, governance events and receipts;
5. server secret provisioning and key rotation procedure;
6. deployed internal-network exposure controls;
7. end-to-end cross-repository contract tests.

Inventory `+ Add supplier` remains blocked until those gates pass and R3-P1 is explicitly approved.
