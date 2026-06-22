# Part Q - Pilot Participant Registry v1

Status: active Part Q control document.

The pilot participant registry defines who is allowed into the controlled Supplier Seed pilot.

No user, business, operator, or supplier entry should be treated as part of the pilot unless it has a registry record.

## Required Fields

Each registry entry should capture:

- Participant ID
- Organization name
- Contact name
- Contact email or phone
- Pilot group
- Assigned role
- Pilot status
- Terms version accepted
- Terms accepted timestamp
- Enabled date
- Suspended date, if any
- Closed date, if any
- Last activity timestamp
- Notes

## Pilot Groups

Allowed pilot groups:

- Internal Operator
- Friendly Pilot Business
- Controlled Supplier Entry

## Pilot Status Values

Allowed statuses:

- Disabled
- Pending Acceptance
- Active
- Suspended
- Closed

## Rules

- No hidden pilot participants.
- No access without registry entry.
- No activation without terms acceptance.
- No status change without audit trail.
- Suspended and closed records must remain historically visible.

## Part Q Usage

The registry is used to confirm that the pilot remains limited, reversible, and PH-first.

It also supports the Part Q Pilot Completion Report by providing participant counts, access history, and activity evidence.
