# PART Q — Daily Pilot Checklist

**Document ID:** PART_Q_01  
**Version:** 1.0  
**Status:** Approved  
**Phase:** Part Q — Controlled Pilot Execution  
**Owner:** Pilot Coordinator  
**Review Cadence:** Daily  
**Approval Status:** Approved for controlled pilot execution  

---

## Purpose

Provide a standardized daily operational checklist for the controlled pilot to ensure consistent execution, governance compliance, audit readiness, and evidence collection.

This checklist supports Part Q only and does not introduce new product functionality, architecture, or implementation requirements.

---

## Scope

This document applies to:

- Pilot Coordinator
- Pilot Support Lead
- Approved pilot operators
- Supervisors participating in pilot validation
- Any support personnel involved in incident review or daily sign-off

This checklist applies only to the controlled pilot execution window and must remain aligned with the locked Parts K–P baseline.

---

## Governance Rules

1. Pilot execution must follow approved workflows only.
2. UI observations are evidence only; UI must not be treated as governance authority.
3. Domain/service behavior remains the source of mutation authority.
4. Audit evidence must be retained for every pilot day.
5. Incidents must be logged before operational conclusions are made.
6. Rollback readiness must be confirmed daily.
7. No feature requests may be promoted into pilot execution without post-pilot review.

---

## Daily Startup Checklist

### Environment

- [ ] Correct pilot environment confirmed.
- [ ] Approved software version confirmed.
- [ ] Approved configuration loaded.
- [ ] No unauthorized configuration changes detected.
- [ ] Pilot rollback checklist is accessible.

### User Access

- [ ] Pilot participants verified against the Pilot Participant Registry.
- [ ] Required permissions confirmed.
- [ ] No unexpected access changes detected.
- [ ] Unauthorized users are not present in the pilot workflow.

### System Health

- [ ] Application starts successfully.
- [ ] Required services are operational.
- [ ] Audit logging is active.
- [ ] No critical warnings are present before pilot use.
- [ ] Known limitations have been communicated to pilot operators.

### Support Readiness

- [ ] Support contacts are available.
- [ ] Escalation contacts are verified.
- [ ] Incident Log Template is available.
- [ ] KPI and Incident Tracking artifact is available.
- [ ] Evidence collection location is confirmed.

---

## During-Pilot Checklist

Pilot operators or supervisors confirm:

- [ ] Approved workflow completed.
- [ ] No governance violations observed.
- [ ] No unexpected permission behavior observed.
- [ ] No unauthorized mutation path used.
- [ ] Required screenshots, notes, or audit references captured.
- [ ] Any deviation has been logged as an incident or observation.

---

## Incident Review Checklist

If an incident occurs:

- [ ] Incident logged using the Incident Log Template.
- [ ] Severity assigned.
- [ ] Affected workflow identified.
- [ ] Evidence attached or referenced.
- [ ] Audit trail reference captured where applicable.
- [ ] Escalation completed if severity requires it.
- [ ] Temporary workaround documented if used.
- [ ] Rollback decision assessed if required.

Incidents must not be resolved informally without documentation.

---

## End-of-Day Checklist

- [ ] Daily pilot objectives reviewed.
- [ ] KPI measurements recorded.
- [ ] Incidents reviewed and classified.
- [ ] Audit logs verified for pilot activity.
- [ ] Operator evidence archived.
- [ ] Governance checklist reviewed.
- [ ] Decision log updated if any decision was made.
- [ ] Daily summary prepared.
- [ ] Open risks or blockers carried forward.

---

## Daily Sign-Off

**Pilot Coordinator Name:**  
**Date:**  
**Pilot Day Number:**  
**Status:** Pass / Pass with Observations / Blocked  
**Signature / Approval Reference:**  

---

## Required Evidence References

Daily checklist completion may reference:

- Pilot Participant Registry
- Pilot Onboarding Checklist
- KPI and Incident Tracking
- Incident Log Template
- Governance Validation Checklist
- Operator Workflow Evidence Checklist
- Exit Gate Checklist
- Pilot Rollback Checklist
- Weekly Pilot Review Template

---

## Non-Goals

This checklist does not:

- Add new product features
- Change system architecture
- Override locked Part P readiness rules
- Replace incident logging
- Replace audit verification
- Replace rollback governance

---

## Revision History

| Version | Date | Description | Owner |
|---|---|---|---|
| 1.0 | 2026-07-06 | Initial Part Q daily pilot checklist | Pilot Coordinator |
