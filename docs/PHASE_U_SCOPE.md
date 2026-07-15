# Phase U — Enterprise Integration Validation

Status: Scoped only; implementation not started.

## Purpose

Phase U validates adoption of the certified, read-only Supplier Seed API and Python SDK by approved Invyra consumers without expanding supplier mutation authority.

Phase U begins from the certified Phase T baseline at commit `e4ae708d4e2054776785ce977a6b1014b0e8c35a`.

## Governing principle

Integration must consume Supplier Seed information without moving supplier governance into clients.

The Supplier Seed domain and service layers remain the sole mutation authority.

## In scope

### U1 — Consumer contract inventory

- identify approved consuming applications
- document which read-only endpoints and SDK resources each consumer requires
- map authentication, tenant context, pagination, error handling, and redaction expectations
- identify unsupported assumptions before implementation

### U2 — Integration compatibility profiles

- define a compatibility profile for each approved consumer
- record supported API and SDK versions
- define required headers, timeouts, retry limits, and pagination behaviour
- preserve backward compatibility with the Phase T public SDK surface

### U3 — Read-only adapter reference implementation

- provide a thin consumer-side adapter pattern
- keep transport and presentation concerns outside the Supplier Seed domain
- prohibit hidden writes, local supplier-state authority, and mutation fallbacks
- ensure API errors remain explicit and auditable by the consuming application

### U4 — Contract and failure-path certification

- certify success, empty-state, pagination, authentication failure, authorization failure, redaction, timeout, and unavailable-service behaviour
- verify consumers degrade safely when Supplier Seed is unavailable
- confirm no consumer can bypass server-side governance

### U5 — Ecosystem pilot integration

- integrate one approved Invyra consumer at a time
- require an explicit acceptance gate before adding another consumer
- collect integration evidence without changing supplier lifecycle behaviour
- maintain rollback to the certified Phase T baseline

### U6 — Adoption and support documentation

- publish consumer setup guidance
- document supported versions and compatibility policy
- document operational diagnostics and escalation paths
- record final Phase U certification evidence

## Explicitly out of scope

Phase U must not:

- add supplier creation or mutation endpoints
- approve moderation decisions
- accept or withdraw legal terms
- change verification state
- activate, archive, or enable pilot access for suppliers
- permit direct audit-event writes
- move governance decisions into Inventory, POS, Forecasting, ScanOps, Companion, or another consumer
- add speculative integrations without an approved consumer contract
- perform the deferred timezone migration

## Initial consumer order

The first candidate consumer is Invyra Inventory Desktop because it is the operational system most likely to require governed supplier visibility.

This is a planning priority only. No Inventory integration is authorized until U1 records the exact read-only contract and confirms that no existing supplier workflow is duplicated.

Forecasting, POS, ScanOps, and Companion remain deferred until separately justified by evidence.

## Acceptance gates

Phase U is complete only when:

1. every implemented consumer has an approved compatibility profile
2. all integration and failure-path tests pass
3. no supplier mutation authority exists outside Supplier Seed domain and service layers
4. redaction and permission behaviour match the enterprise API
5. consumer rollback is documented and tested
6. CI evidence is visibly green
7. a Phase U completion manifest is committed

## Implementation gate

The next permitted action is U1 only: inspect the selected consumer repository and produce a contract inventory.

No adapter, endpoint, SDK feature, or client integration may be implemented before that inventory is reviewed and accepted.
