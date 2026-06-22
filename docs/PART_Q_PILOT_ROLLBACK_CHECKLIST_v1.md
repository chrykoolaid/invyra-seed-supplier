# Part Q - Pilot Rollback Checklist v1

Status: active Part Q control document.

This checklist defines when and how a controlled pilot rollback should be reviewed.

## Purpose

Rollback must remain available throughout the pilot. It is a controlled safety action, not a failure of the project.

## Rollback Triggers

Review rollback immediately if any of these occur:

- governance failure
- permission bypass
- audit integrity issue
- data integrity issue
- critical reliability issue
- repeated blocked workflows
- uncontrolled participant access

## Immediate Actions

If rollback is triggered:

1. suspend new pilot activation
2. preserve audit records
3. preserve incident evidence
4. record affected participants
5. stop affected workflow if required
6. assign incident owner
7. review latest stable baseline

## Evidence To Capture

- incident ID
- trigger type
- time detected
- detecting actor
- affected participant or workflow
- affected data, if any
- audit event references
- current pilot status
- recommended action

## Decision Options

Choose one:

- continue pilot with no rollback
- continue pilot with restrictions
- pause affected participant only
- pause full pilot
- roll back to last accepted baseline

## Recovery Review

Before reactivation:

- root cause reviewed
- evidence retained
- audit trail confirmed
- corrective action approved
- pilot status updated
- participant access reviewed

## Completion Rule

Rollback review is complete only when the decision, evidence, owner, and follow-up action are recorded.
