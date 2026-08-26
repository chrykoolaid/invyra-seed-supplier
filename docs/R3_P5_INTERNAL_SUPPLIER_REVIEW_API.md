# R3-P5 Internal Supplier Review API

## Purpose

Expose Supplier Seed's existing moderation workflow to the Inventory server authority without exposing mutation capability to the browser.

## Authority boundary

Inventory UI → Base44 governed review function → HMAC-authenticated Supplier Seed internal API → Supplier Seed governance engine.

Supplier Seed remains authoritative for lifecycle, moderation, verification, audit events and operation idempotency.

## Contract

Review contract version: `R3-P5-v1`.

### Read review snapshot

`GET /internal/v1/suppliers/{supplier_id}/review`

Returns the current supplier review snapshot, governance state and possible duplicate matches. The route is HMAC authenticated and does not mutate the supplier.

### Decide review

`POST /internal/v1/suppliers/{supplier_id}/review/decision`

Supported decisions:

- `approve`
- `reject`

A rejection requires a human-readable reason.

The request carries the state observed by the caller (`expected_lifecycle_status` and `expected_moderation_status`). A stale state fails closed with HTTP 409.

When a newly-created manual supplier is still `draft / not_reviewed`, the decision route first uses the existing `submit_for_review` operation and then the existing moderation decision operation. Stable per-operation idempotency keys make this retry safe.

## Result semantics

Approval transitions the Supplier Seed record to:

- lifecycle: `approved`
- moderation: `approved`

Rejection transitions it to:

- lifecycle: `rejected`
- moderation: `rejected`

R3-P5 never activates a supplier. `supplier_usable` remains false after review approval.

## Security

- HMAC authentication is required on every review request.
- Admin/Owner is required for review decisions from Inventory.
- Durable repository and durable mutation state are required for production decisions.
- Nonce replay protection and payload/idempotency conflict detection remain enforced.
- Public enterprise API remains read-only.
- No HMAC secret or internal mutation endpoint is exposed to browser code.

## Out of scope

- supplier activation
- purchasing eligibility
- Base44 supplier creation
- verification decisions
- request-changes state
- duplicate-resolution mutation
- escalation UI
