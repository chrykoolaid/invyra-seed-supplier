# Phase U2 — Invyra Inventory Integration Compatibility Profile

Status: Defined; implementation not started.

## Baselines

Supplier Seed baseline:

- repository: `chrykoolaid/invyra-seed-supplier`
- Phase T certified baseline: `e4ae708d4e2054776785ce977a6b1014b0e8c35a`
- U1 contract baseline: `22ff9193bd0c761a4a7335b30932889e7044c111`
- enterprise API version: `v1`
- service version observed in capabilities: `1.3.0`

Inventory consumer baseline:

- repository: `chrykoolaid/invyra-base44`
- inspected head: `553d791f8c7816594f56869b16f41e50b0f6f6de`
- application type: React/Vite browser application

## Compatibility decision

The approved integration boundary is a trusted local or server-side read adapter.

Browser-direct calls from the Inventory React application to Supplier Seed are not approved for U3.

Reasons:

1. the certified Python SDK cannot run directly in the browser application
2. no production browser CORS contract has been demonstrated
3. no production authentication contract has been demonstrated
4. tenant and role context must not be invented or trusted from arbitrary browser input
5. credentials and service configuration must not be exposed through `VITE_*` client variables
6. the existing browser bridge uses a non-certified POST preview route and local duplicate fallback behaviour

The adapter may use the certified Python SDK or equivalent GET-only transport, but must expose only the U1-approved read contract to Inventory.

## Supported Supplier Seed surfaces

U3 may consume only:

- `GET /health`
- `GET /v1/capabilities`
- `GET /v1/suppliers`
- `GET /v1/suppliers/{supplier_id}`

No queue, audit, pilot, preview, ingestion, or mutation route is approved.

## Version policy

Required API major version:

- `v1`

Required capability assertions before serving supplier data:

- `enterprise_api_read_only` is `true`
- `mutation_authority` is `domain_service_only`
- `/v1/suppliers` is advertised
- `/v1/suppliers/{supplier_id}` is advertised

A service reporting another API major version must fail closed as incompatible.

Minor service-version changes may be accepted only when capability assertions and response validation continue to pass.

## Transport profile

Approved topology:

`Inventory browser -> trusted Inventory/local adapter -> Supplier Seed API`

The browser must call the trusted adapter through the Inventory application's established service boundary.

The adapter must:

- use GET requests only
- use a configured Supplier Seed base URL stored outside browser-delivered code
- validate JSON response shape before returning data
- translate upstream failures into a stable Inventory-facing read error
- avoid persistence of Supplier Seed governance state
- avoid background synchronization during U3

## Authentication and authorization

No production authentication mechanism is evidenced in the current enterprise API implementation.

Therefore U3 must not claim production authentication readiness.

For a local controlled integration test, the adapter may connect only to an explicitly configured trusted Supplier Seed instance in a controlled environment.

Before any external or multi-user pilot, a separately evidenced authentication profile is mandatory.

The adapter must not:

- accept arbitrary actor, role, or permission headers from the browser
- elevate a user based on local UI state
- manufacture Supplier Seed access context
- expose privileged queue, audit, or pilot data

## Tenant context

No enforceable tenant-header contract was demonstrated during U2 inspection.

U3 must therefore operate in single configured tenant context only and must not advertise multi-tenant isolation.

Any future tenant header such as `X-Tenant-Id` requires:

- server-side validation
- mapping from authenticated Inventory tenant context
- tests proving cross-tenant denial
- no browser-controlled free-form tenant override

This is a blocker for multi-tenant production rollout, not for a controlled single-tenant read pilot.

## Redaction profile

Inventory must treat Supplier Seed responses as already governed by the Supplier Seed service.

The adapter must not reconstruct hidden fields or merge privileged data from another source.

Initial supplier-list projection is limited to:

- `supplier_id`
- `name`
- `mode`
- `region_code`
- `market_code`
- `seeded_source`
- `lifecycle_status`
- `moderation_status`
- `verification_status`

Initial supplier-detail projection may additionally include fields present in the governed detail response, but sensitive fields must not be displayed until role/redaction behaviour is separately certified.

Inventory must not copy Supplier Seed lifecycle, moderation, legal, verification, or pilot values into its own authoritative supplier records.

## Pagination profile

Supplier list requests must use offset pagination.

Defaults:

- UI page size: `50`
- adapter maximum page size: `200`
- initial offset: `0`

The adapter must use the returned page object:

- `limit`
- `offset`
- `returned`
- `total`

It must stop when `returned` is zero or the next offset is greater than or equal to `total`.

The initial UI integration must not automatically retrieve every page in the background.

## Filtering and sorting

Approved filters:

- `search`
- `region_code`
- `mode`
- `seeded_source`
- `lifecycle_status`
- `moderation_status`

Supplier Seed remains authoritative for sorting. The observed stable ordering is:

1. supplier name ascending
2. supplier ID ascending

Inventory may filter the currently loaded page for presentation but must not present local filtering as a complete server-side result.

## Timeout and retry profile

Adapter connection timeout: `3 seconds`.

Adapter total request timeout: `10 seconds`.

Retries:

- maximum `1` retry
- GET requests only
- retry only on connection failure, timeout before a response, HTTP `502`, `503`, or `504`
- no retry on `400`, `401`, `403`, `404`, or validation failure
- short bounded backoff; no endless retry loop

The UI must remain usable when Supplier Seed is unavailable.

## Error mapping

Required Inventory-facing categories:

- `SUPPLIER_SEED_UNAVAILABLE`
- `SUPPLIER_SEED_TIMEOUT`
- `SUPPLIER_SEED_UNAUTHORIZED`
- `SUPPLIER_SEED_FORBIDDEN`
- `SUPPLIER_SEED_NOT_FOUND`
- `SUPPLIER_SEED_INCOMPATIBLE`
- `SUPPLIER_SEED_INVALID_RESPONSE`
- `SUPPLIER_SEED_UPSTREAM_ERROR`

Upstream `detail.code` should be retained for diagnostics where safe, but raw stack traces, credentials, and internal URLs must not be returned to the browser.

## Cache profile

U3 may use only short-lived in-memory response caching inside the trusted adapter.

Maximum cache duration:

- capabilities: `5 minutes`
- supplier list and detail: `30 seconds`

No durable Supplier Seed cache, local mirror, background replication, or offline authority is approved.

A stale cache must never be presented as current without an explicit stale indicator.

## UI degradation rules

When Supplier Seed is unavailable:

- Inventory's own supplier master remains operational
- Add Supplier, Edit Supplier, orders, receiving, claims, and commercial workflows must not be blocked
- the Supplier Seed panel shows an unavailable state with retry
- no local duplicate or governance decision is substituted
- no previous Supplier Seed result is silently treated as fresh

## Existing prototype bridge disposition

The existing `supplierSeedBridge.js` and Seed Preview UI are classified as prototype-only.

During U3 they must not be expanded.

The approved reference adapter must be introduced separately and validated before any decision is made to remove or quarantine the prototype preview.

No patch stacking onto the prototype ingestion-preview path is permitted.

## Security requirements before pilot

The following are mandatory before U5 controlled pilot acceptance:

- trusted service configuration outside browser code
- TLS or an explicitly controlled localhost-only channel
- authenticated service-to-service identity
- validated role/redaction propagation where privileged detail is used
- tenant isolation tests if more than one tenant is supported
- request correlation identifier
- secret redaction in logs
- dependency and configuration documentation

## U3 implementation gate

U3 is authorized only as a thin read-only reference adapter and contract test set.

U3 must not:

- modify the Supplier Seed API or SDK public surface
- call `POST /supplier-seed/ingest/preview`
- perform local dedupe decisions
- write Inventory supplier records
- introduce background synchronization
- expose queue, audit, or pilot endpoints
- claim production authentication or multi-tenant readiness

## U3 acceptance criteria

U3 passes only when:

1. capability validation succeeds against the Phase T API
2. supplier list and detail calls work through the trusted adapter
3. all outbound Supplier Seed calls are GET-only
4. pagination and filters match the enterprise API contract
5. timeout and retry limits are enforced
6. invalid and incompatible responses fail closed
7. Inventory remains operational during Supplier Seed outage
8. no Supplier Seed governance state is written into Inventory authority
9. tests prove the prototype preview route is not used by the new adapter
10. CI evidence is visibly green
