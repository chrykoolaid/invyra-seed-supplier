# Part Q - Governance Validation Checklist v1

Status: active Part Q validation document.

This checklist verifies that pilot usage remains governed during real operator activity.

## Purpose

Part Q must prove that governance still holds when real users execute supplier workflows.

## Validation Areas

### Access Control

Confirm:
- participant has registry entry
- participant has correct pilot status
- participant has accepted required terms
- role assignment matches pilot purpose
- suspended users cannot continue active workflows

### Permissions

Confirm:
- allowed actions succeed only for permitted roles
- denied actions are blocked
- denied attempts are auditable
- sensitive read masking remains active where required

### Supplier Lifecycle

Confirm:
- supplier creation follows service rules
- moderation decisions are controlled
- verification decisions are controlled
- activation cannot bypass required gates
- status changes are auditable

### Audit

Confirm:
- governed actions create audit records
- denied actions create audit records
- pilot access changes create audit records
- incident-linked actions can be traced

### Pilot Controls

Confirm:
- access can be disabled
- access can be suspended
- pilot terms are tracked
- pilot scope remains limited
- rollback path remains available

## Failure Handling

Any failed validation item must be logged as an incident or stabilization finding.

## Completion Rule

Governance validation is complete only when all areas are reviewed and exceptions are recorded.
