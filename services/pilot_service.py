"""Pilot readiness services for controlled PH-first rollout."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from supplier_seed.domain.enums import GovernanceEventType, LifecycleStatus, PilotIncidentSeverity
from supplier_seed.domain.models import SupplierRecord
from supplier_seed.domain.validation import ValidationIssue
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.policy.rules import PolicyContext
from supplier_seed.services.permissions import (
    AccessContext,
    GovernanceAuthorizer,
    GovernancePermission,
    resolve_actor,
)
from supplier_seed.services.results import GovernanceServiceResult

UTC = timezone.utc


class PilotReadinessService:
    def __init__(self, *, authorizer: Optional[GovernanceAuthorizer] = None) -> None:
        self.authorizer = authorizer or GovernanceAuthorizer()

    def accept_terms(
        self,
        supplier: SupplierRecord,
        *,
        terms_version: str,
        actor: Optional[str],
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        effective_actor = resolve_actor(actor, access_context)
        permission_result = self.authorizer.authorize(
            GovernancePermission.ACCEPT_PILOT_TERMS,
            access_context=access_context,
        )
        if not permission_result.allowed:
            return GovernanceServiceResult(False, supplier=supplier, issues=permission_result.issues)

        terms = (terms_version or "").strip()
        issues: list[ValidationIssue] = []
        if not terms:
            issues.append(
                ValidationIssue(
                    code="pilot.terms.version.required",
                    field="terms_version",
                    message="Pilot terms version is required before pilot usage can be enabled.",
                )
            )
        if supplier.region_context.market_code != "PH":
            issues.append(
                ValidationIssue(
                    code="pilot.market.ph_only",
                    field="region_context.market_code",
                    message="Pilot terms can only be accepted for the PH-first rollout.",
                )
            )
        if issues:
            return GovernanceServiceResult(False, supplier=supplier, issues=tuple(issues))

        timestamp = datetime.now(tz=UTC)
        updated = supplier.with_governance_update(
            actor=effective_actor,
            at=timestamp,
            pilot_terms_accepted_version=terms,
            pilot_terms_accepted_at=timestamp,
            pilot_terms_accepted_by=effective_actor,
        )
        event = GovernanceEventRecord.new(
            supplier_id=updated.identity.supplier_id,
            event_type=GovernanceEventType.PILOT_TERMS_ACCEPTED,
            occurred_at=timestamp,
            actor=effective_actor,
            source="service.pilot",
            summary=f"Pilot terms {terms} were accepted for controlled rollout.",
            metadata={"terms_version": terms, "market_code": updated.region_context.market_code},
        )
        return GovernanceServiceResult(True, supplier=updated, events=(event,))

    def enable_access(
        self,
        supplier: SupplierRecord,
        *,
        pilot_name: str,
        terms_version: str,
        actor: Optional[str],
        context: Optional[PolicyContext] = None,
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        effective_actor = resolve_actor(actor, access_context)
        permission_result = self.authorizer.authorize(
            GovernancePermission.ENABLE_PILOT_ACCESS,
            access_context=access_context,
        )
        if not permission_result.allowed:
            return GovernanceServiceResult(False, supplier=supplier, issues=permission_result.issues)

        resolved_context = context or PolicyContext(region_code=supplier.region_context.region_code)
        pilot = (pilot_name or "").strip()
        terms = (terms_version or "").strip()
        issues: list[ValidationIssue] = []
        if not resolved_context.pilot_enabled:
            issues.append(
                ValidationIssue(
                    code="pilot.rollout.disabled",
                    field="context.pilot_enabled",
                    message="Pilot access cannot be enabled until the controlled rollout switch is enabled.",
                )
            )
        if supplier.region_context.market_code != "PH":
            issues.append(
                ValidationIssue(
                    code="pilot.market.ph_only",
                    field="region_context.market_code",
                    message="Controlled rollout is restricted to the PH-first market.",
                )
            )
        if supplier.lifecycle_status is not LifecycleStatus.ACTIVE:
            issues.append(
                ValidationIssue(
                    code="pilot.lifecycle.active_required",
                    field="lifecycle_status",
                    message="Pilot access can only be enabled for active suppliers.",
                )
            )
        if not supplier.region_context.region_code:
            issues.append(
                ValidationIssue(
                    code="pilot.region.required",
                    field="region_context.region_code",
                    message="Pilot access requires a supplier region for controlled rollout.",
                )
            )
        if not pilot:
            issues.append(
                ValidationIssue(
                    code="pilot.name.required",
                    field="region_context.pilot_name",
                    message="Pilot name is required when enabling controlled rollout.",
                )
            )
        if not terms:
            issues.append(
                ValidationIssue(
                    code="pilot.terms.version.required",
                    field="terms_version",
                    message="Pilot terms version is required when enabling controlled rollout.",
                )
            )
        if supplier.pilot_terms_accepted_version != terms or not supplier.has_pilot_terms_accepted:
            issues.append(
                ValidationIssue(
                    code="pilot.terms.acceptance.required",
                    field="pilot_terms_accepted_version",
                    message="Matching pilot terms must be accepted before enabling supplier access.",
                )
            )
        if issues:
            return GovernanceServiceResult(False, supplier=supplier, issues=tuple(issues))

        timestamp = datetime.now(tz=UTC)
        region_context = replace(supplier.region_context, pilot_name=pilot, pilot_enabled=True)
        updated = supplier.with_governance_update(
            actor=effective_actor,
            at=timestamp,
            region_context=region_context,
            pilot_enabled_at=timestamp,
            pilot_enabled_by=effective_actor,
            pilot_disabled_at=None,
            pilot_disabled_by=None,
        )
        event = GovernanceEventRecord.new(
            supplier_id=updated.identity.supplier_id,
            event_type=GovernanceEventType.PILOT_ACCESS_ENABLED,
            occurred_at=timestamp,
            actor=effective_actor,
            source="service.pilot",
            summary=f"Supplier was enabled for pilot '{pilot}'.",
            metadata={
                "pilot_name": pilot,
                "terms_version": terms,
                "market_code": updated.region_context.market_code,
                "region_code": updated.region_context.region_code,
            },
        )
        return GovernanceServiceResult(True, supplier=updated, events=(event,))

    def disable_access(
        self,
        supplier: SupplierRecord,
        *,
        actor: Optional[str],
        reason: Optional[str],
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        effective_actor = resolve_actor(actor, access_context)
        permission_result = self.authorizer.authorize(
            GovernancePermission.DISABLE_PILOT_ACCESS,
            access_context=access_context,
        )
        if not permission_result.allowed:
            return GovernanceServiceResult(False, supplier=supplier, issues=permission_result.issues)

        rollback_reason = (reason or "").strip()
        issues: list[ValidationIssue] = []
        if not supplier.region_context.pilot_enabled:
            issues.append(
                ValidationIssue(
                    code="pilot.disable.not_enabled",
                    field="region_context.pilot_enabled",
                    message="Pilot access is not currently enabled for this supplier.",
                )
            )
        if not rollback_reason:
            issues.append(
                ValidationIssue(
                    code="pilot.disable.reason.required",
                    field="reason",
                    message="A rollback reason is required when disabling pilot access.",
                )
            )
        if issues:
            return GovernanceServiceResult(False, supplier=supplier, issues=tuple(issues))

        timestamp = datetime.now(tz=UTC)
        region_context = replace(supplier.region_context, pilot_enabled=False)
        updated = supplier.with_governance_update(
            actor=effective_actor,
            at=timestamp,
            region_context=region_context,
            pilot_disabled_at=timestamp,
            pilot_disabled_by=effective_actor,
        )
        event = GovernanceEventRecord.new(
            supplier_id=updated.identity.supplier_id,
            event_type=GovernanceEventType.PILOT_ACCESS_DISABLED,
            occurred_at=timestamp,
            actor=effective_actor,
            source="service.pilot",
            summary="Supplier pilot access was disabled.",
            metadata={
                "pilot_name": updated.region_context.pilot_name,
                "reason": rollback_reason,
                "market_code": updated.region_context.market_code,
            },
        )
        return GovernanceServiceResult(True, supplier=updated, events=(event,))

    def log_incident(
        self,
        supplier: SupplierRecord,
        *,
        severity: PilotIncidentSeverity,
        summary: str,
        actor: Optional[str],
        access_context: Optional[AccessContext] = None,
    ) -> GovernanceServiceResult:
        effective_actor = resolve_actor(actor, access_context)
        permission_result = self.authorizer.authorize(
            GovernancePermission.RECORD_PILOT_INCIDENT,
            access_context=access_context,
        )
        if not permission_result.allowed:
            return GovernanceServiceResult(False, supplier=supplier, issues=permission_result.issues)

        clean_summary = (summary or "").strip()
        if not clean_summary:
            issue = ValidationIssue(
                code="pilot.incident.summary.required",
                field="summary",
                message="Incident summary is required for controlled rollout issue capture.",
            )
            return GovernanceServiceResult(False, supplier=supplier, issues=(issue,))

        timestamp = datetime.now(tz=UTC)
        event = GovernanceEventRecord.new(
            supplier_id=supplier.identity.supplier_id,
            event_type=GovernanceEventType.INCIDENT_LOGGED,
            occurred_at=timestamp,
            actor=effective_actor,
            source="service.pilot",
            summary=clean_summary,
            metadata={
                "severity": severity.value,
                "pilot_name": supplier.region_context.pilot_name,
                "pilot_enabled": supplier.region_context.pilot_enabled,
                "market_code": supplier.region_context.market_code,
            },
        )
        return GovernanceServiceResult(True, supplier=supplier, events=(event,))
