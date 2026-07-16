# Phase U3 — Inventory Read-Only Adapter Reference Implementation

Status: Reference implementation complete; UI wiring not started.

## Consumer

- Repository: `chrykoolaid/invyra-base44`
- Consumer role: Inventory Desktop read-only consumer
- Supplier Seed remains the governance and mutation authority.

## Implemented files

- `src/lib/supplierSeedReadAdapter.js`
- `scripts/validate-supplier-seed-read-adapter.mjs`

Inventory commits:

- `a0752c7de5447956e61a5ee3e5009902a5b5529b` — GET-only reference adapter
- `632a8c1d33daa0356573e0c9047a636230d57bb3` — static governance validator

## Approved adapter surface

The reference adapter exposes only:

- `health()`
- `capabilities()`
- `listSuppliers(filters)`
- `getSupplier(supplierId)`

The adapter permits only the U2-approved read paths:

- `GET /health`
- `GET /v1/capabilities`
- `GET /v1/suppliers`
- `GET /v1/suppliers/{supplier_id}`

## Compatibility controls

The adapter implements:

- explicit GET method use
- endpoint allowlisting
- default 10-second timeout
- at most one retry
- retries for transport failures and HTTP 502, 503, and 504
- offset and limit query support
- normalized error codes and details
- same-origin credentials for the trusted adapter boundary
- injectable fetch transport for later contract tests

## Governance controls

The implementation does not:

- call `POST /supplier-seed/ingest/preview`
- map Inventory suppliers into ingestion candidates
- create or mutate Supplier Seed records
- create or mutate Inventory supplier records
- write audit events
- persist a local Supplier Seed mirror
- use localStorage or sessionStorage
- wire the adapter into the Inventory Suppliers page

The existing prototype preview bridge remains separate and unchanged.

## Validation status

The committed static validator checks for:

- required GET-only controls
- allowed endpoint fragments
- timeout and retry defaults
- normalized adapter error handling
- absence of POST, PUT, PATCH, DELETE, preview-ingestion, candidate-mapping, and browser-storage fragments

Repository-level runtime execution remains part of U4 contract and failure-path certification.

## U3 closure

U3 is complete as a reference implementation only.

No production claim is made for authentication, tenant isolation, CORS, or role propagation. Those remain outside the current single-tenant controlled profile.

## Next gate

The next permitted action is U4 — contract and failure-path certification.

U4 must test success, empty state, pagination, invalid JSON, 404, 502/503/504 retry, timeout, transport failure, and path rejection before any Inventory UI wiring is authorized.
