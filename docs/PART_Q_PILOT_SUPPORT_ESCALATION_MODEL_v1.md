# Part Q - Pilot Support Escalation Model v1

Status: active Part Q execution document.

This document defines how pilot support issues are captured, triaged, and escalated during controlled pilot execution.

## Purpose

Pilot support must create evidence. No support issue should be handled only verbally or outside the pilot record.

## Support Tiers

### Tier 1 - Operator Guidance

Use for:
- onboarding questions
- navigation help
- terminology confusion
- simple workflow guidance

### Tier 2 - Governance Review

Use for:
- permission questions
- access state concerns
- moderation or verification uncertainty
- terms acceptance issues
- audit review questions

### Tier 3 - Technical Correction

Use for:
- repeat failures
- reliability issues
- persistence issues
- blocked workflows
- suspected data or audit faults

## Required Support Record Fields

Each support item should capture:

- support ID
- date opened
- participant
- affected workflow
- support tier
- summary
- status
- owner
- resolution notes
- related incident ID, if any

## Escalation Rules

Escalate from Tier 1 to Tier 2 if the issue involves permissions, governance, supplier activation, or audit interpretation.

Escalate from Tier 2 to Tier 3 if the issue indicates a possible technical failure, repeated workflow break, or data integrity concern.

## Closure Rule

A support item may close only when the outcome is recorded and any linked incident or follow-up action is identified.

## Part R Input

Repeated support questions should feed Part R stabilization as evidence of training, documentation, workflow, or governance friction.
