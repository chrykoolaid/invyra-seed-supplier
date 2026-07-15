# Phase T — Enterprise SDKs Completion Manifest

Status: Engineering complete; CI closure workflow installed.

## Delivered scope

Phase T provides the governed, read-only enterprise SDK surface for the Supplier Seed System.

Completed slices:

- T1 — UI integration contracts and capabilities manifest
- T2 — synchronous Python read SDK
- T3 — automatic pagination helpers
- T4 — asynchronous Python read SDK
- T5 — typed supplier, queue, and audit resource models
- T6 — typed synchronous and asynchronous SDK clients
- T7 — package metadata and PEP 561 typing readiness
- T8 — wheel and source-distribution certification
- T9 — developer quick-start documentation and executable examples

## Public SDK surface

The package exports:

- SupplierSeedReadClient
- SupplierSeedAsyncReadClient
- SupplierSeedTypedReadClient
- SupplierSeedAsyncTypedReadClient
- SupplierSeedApiError
- SupplierSummaryResource
- SupplierDetailResource
- QueueResource
- AuditEventResource

## Governance boundary

The SDK is intentionally read-only.

It does not:

- create or mutate suppliers
- approve moderation decisions
- change verification state
- activate suppliers
- alter pilot controls
- bypass server-side permission or governance checks

The Supplier Seed domain and service layers remain the sole mutation authority.

## Certification gates

The consolidated Supplier Seed Tests workflow is the authoritative Phase T closure gate.

A release-ready run requires:

1. Full pytest suite passing on Python 3.11
2. Full pytest suite passing on Python 3.12
3. Wheel and source distribution build succeeding
4. Distribution metadata validation succeeding
5. PEP 561 py.typed marker present in the wheel
6. Built wheel installation succeeding
7. Public SDK namespace smoke import succeeding

## Current baseline

- Test suite size: 136 tests
- Last known test defect: corrected queue next-step expectation
- Unified release-certification workflow: installed
- Runtime/API/governance changes after T6: none

## Non-blocking technical debt

The remaining datetime.utcnow() deprecation warnings should be handled in a separate controlled maintenance phase. They are not part of Phase T functionality and should not be mixed into the SDK completion baseline.

## Lock rule

No additional Phase T runtime features should be added after this manifest. Any future SDK expansion must begin as a separately scoped phase from a green consolidated CI baseline.
