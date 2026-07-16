# Phase U1 — Invyra Inventory Consumer Contract Inventory

Status: Complete for review; implementation not authorized.

## Repositories inspected

- Supplier Seed source of truth: `chrykoolaid/invyra-seed-supplier`
- Candidate consumer: `chrykoolaid/invyra-base44`

## Purpose

This document records the exact read-only contract that Invyra Inventory Desktop may consume from the certified Phase T Supplier Seed enterprise API.

It does not authorize adapter, UI, API, SDK, or runtime implementation.

## Existing Inventory state

Inventory already contains a prototype bridge:

- `src/lib/supplierSeedBridge.js`
- `src/pages/Suppliers.jsx`
- `scripts/validate-supplier-seed-bridge-adapter.mjs`
- `scripts/validate-supplier-seed-suppliers-page-wiring.mjs`

The prototype currently:

- maps an Inventory supplier into a Supplier Seed candidate
- calls `POST /supplier-seed/ingest/preview` when an API base is configured
- falls back to local duplicate-check fixture logic when no API base is configured
- displays a Seed Preview result in the Suppliers page
- keeps the preview non-persistent

This is a controlled prototype and is not the Phase U enterprise adoption contract.

## Critical compatibility finding

The certified Phase T public API and SDK are read-only, but the existing Inventory bridge is candidate-oriented and uses a POST preview operation.

Although the preview endpoint returns `persisted: false`, it exercises ingestion-domain behaviour and is outside the Phase T enterprise read-only surface.

Therefore:

- the existing preview bridge must not be treated as the Phase U integration
- Phase U must not extend or normalize the POST preview path
- the preview feature must remain isolated until a separate decision explicitly retains, removes, or replaces it
- no Inventory supplier record may be submitted to Supplier Seed through the Phase U adapter

## Approved initial Inventory use case

Inventory may consume governed supplier visibility only.

The initial approved use case is:

1. list Supplier Seed supplier summaries
2. search and filter those summaries
3. open a read-only Supplier Seed supplier detail view
4. show service capability and availability state
5. degrade safely when Supplier Seed is unavailable

Inventory remains responsible for its own operational supplier references, purchasing relationships, claims, receiving workflows, and local commercial data.

Supplier Seed remains responsible for seeded-supplier governance, lifecycle, moderation, legal state, verification state, and audit truth.

## Required enterprise endpoints

### Required for the first integration slice

- `GET /health`
- `GET /v1/capabilities`
- `GET /v1/suppliers`
- `GET /v1/suppliers/{supplier_id}`

### Deferred and not required by Inventory initially

- moderation queues
- verification queues
- activation-ready queue
- supplier audit-event timeline
- pilot release summaries
- pilot incidents
- pilot runbook

These endpoints may only be added to an Inventory compatibility profile after a separately justified operator use case.

## Required supplier summary fields

Inventory may read:

- `supplier_id`
- `name`
- `mode`
- `region_code`
- `market_code`
- `seeded_source`
- `lifecycle_status`
- `moderation_status`
- `verification_status`

Inventory must not reinterpret these values as local governance decisions.

## Required supplier detail fields

Inventory may read:

- all summary fields
- `region_context`
- `seeded_source_reference`
- `contact_email`
- `contact_phone`
- `website_url`
- `tax_identifier`, subject to server-side permission and redaction policy
- `legal_acceptance_state`
- `verification_visibility`
- `assigned_verifier`, subject to server-side permission and redaction policy
- `created_by`, `updated_by`, and lifecycle timestamps, subject to server-side permission and redaction policy

Inventory must display unavailable or redacted values without attempting alternate retrieval or local reconstruction.

## Query and pagination contract

Inventory may use these list filters:

- `search`
- `region_code`
- `mode`
- `seeded_source`
- `lifecycle_status`
- `moderation_status`

Pagination is offset-based:

- default limit: 50
- maximum limit: 200
- response page fields: `limit`, `offset`, `returned`, `total`
- stable ordering: supplier name ascending, then supplier ID ascending

The consumer must stop pagination when `returned` is zero or the accumulated offset reaches `total`.

## Transport profile inputs for U2

The following must be resolved in U2 before implementation:

- Inventory-side API base configuration name
- browser-direct versus local-server/proxy transport
- authentication mechanism
- tenant-context header requirements
- role/access-context propagation
- request timeout
- retry policy
- CORS and local-network deployment constraints
- TLS expectations
- production secret storage

The current Phase T Python SDK does not by itself solve a JavaScript browser consumer integration. Inventory will require a thin JavaScript/TypeScript read adapter or a trusted local service boundary. This must be selected in U2.

## Error-handling contract

Inventory must explicitly handle:

- service unavailable or network failure
- timeout
- malformed response
- validation error
- `supplier.not_found`
- authentication failure when introduced
- authorization or redaction denial
- unsupported API version or missing capability

Failure behaviour must be read-safe:

- retain Inventory operational functionality
- show Supplier Seed information as unavailable
- do not synthesize governance status
- do not fall back to local governance decisions
- do not retry indefinitely
- do not write or mutate Inventory supplier records as a side effect of a failed read

## UI boundary

The first Phase U Inventory integration may add a clearly separated read-only Supplier Seed view or panel.

It must not:

- replace the Inventory supplier master
- convert Supplier Seed IDs into Inventory supplier authority
- merge local and governed records silently
- expose moderation, legal, verification, activation, or pilot controls
- imply endorsement or approval beyond the server-provided status
- reuse the existing `Seed Preview` action as the enterprise read-only entry point

## Data ownership boundary

### Inventory owns

- operational supplier records used by Inventory
- purchasing and ordering relationships
- receiving and delivery claims
- local contacts and commercial terms
- local supplier performance derived from Inventory transactions

### Supplier Seed owns

- seeded supplier identity and provenance
- governed lifecycle state
- moderation state
- legal acceptance state
- verification state and visibility
- pilot eligibility and access state
- Supplier Seed audit history

Neither system may silently overwrite the other system's data.

## Unsupported assumptions identified

1. Existing Inventory static supplier fixtures are not evidence of Supplier Seed records.
2. Inventory supplier IDs such as `SUP-001` are not Supplier Seed IDs.
3. The current POST preview bridge is not part of the certified Phase T enterprise read-only API.
4. The Python SDK cannot be imported directly into the Vite/React browser application.
5. Authentication and tenant propagation are not yet defined for the browser consumer.
6. Supplier Seed detail fields may require future permission-aware redaction before production browser exposure.
7. Inventory Add Supplier and Edit Supplier actions must remain local and must not call Supplier Seed mutation or preview flows through the Phase U adapter.

## U1 decision

Invyra Inventory is an approved candidate consumer for governed, read-only supplier visibility.

The approved minimum contract is limited to health, capabilities, supplier list, and supplier detail reads.

No implementation is authorized until U2 defines and accepts the Inventory compatibility profile, especially the trusted transport, authentication, tenant, timeout, retry, and redaction model.

## Next gate

The next permitted action is:

**U2 — Define the Invyra Inventory integration compatibility profile.**

No Inventory or Supplier Seed runtime code should change before that profile is reviewed and accepted.
