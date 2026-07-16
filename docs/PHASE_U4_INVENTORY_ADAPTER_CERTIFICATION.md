# Phase U4 — Inventory Adapter Contract and Failure-Path Certification

Status: Implementation complete; visible GitHub Actions result pending.

## Consumer

- Supplier Seed source of truth: `chrykoolaid/invyra-seed-supplier`
- Inventory consumer: `chrykoolaid/invyra-base44`

## Certified implementation

Inventory reference adapter:

- `src/lib/supplierSeedReadAdapter.js`

Executable certification suite:

- `scripts/certify-supplier-seed-read-adapter.mjs`
- commit: `464394381c3c4bbe555cce9625fb8fb7b39695fa`

Repeatable CI workflow:

- `.github/workflows/supplier-seed-u4-certification.yml`
- commit: `63f36da38d707330de1ecf10aa04b0db94a0d834`

## Executed certification cases

The certification suite verifies:

1. successful health read
2. successful capabilities read
3. empty supplier list handling
4. search, region, lifecycle, limit, and offset query forwarding
5. successful supplier detail read
6. GET-only requests
7. no request body
8. invalid JSON normalization
9. supplier-not-found 404 normalization
10. one retry for HTTP 502
11. one retry for HTTP 503
12. one retry for HTTP 504
13. one retry after a transport failure
14. timeout normalization
15. unavailable-adapter normalization
16. retry limit enforcement
17. required supplier ID enforcement
18. absence of POST, PUT, PATCH, and DELETE methods
19. absence of the prototype ingestion-preview route
20. absence of browser local or session storage coupling

## Local execution evidence

The committed adapter and executable certification suite were reproduced from their exact repository contents and executed with Node.js.

Observed result:

```text
Supplier Seed U4 read adapter certification passed.
```

## Governance result

The U4 implementation does not:

- create or mutate suppliers
- call Supplier Seed ingestion or lifecycle routes
- write audit events
- copy Supplier Seed governance state into Inventory authority
- wire the adapter into the Inventory UI
- claim production authentication, tenant isolation, or role propagation readiness

## CI closure gate

U4 is formally closed only after the `Supplier Seed U4 Certification` workflow is visibly green on the Inventory repository `main` branch.

The workflow runs:

1. static read-only boundary validation
2. executable contract and failure-path certification

## Next-phase rule

Do not begin U5 ecosystem pilot wiring until the U4 workflow result is visibly green.
