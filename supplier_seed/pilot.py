from dataclasses import dataclass, replace
from datetime import datetime

from supplier_seed.domain.enums import GovernanceEventType, LifecycleStatus, PilotIncidentSeverity
from supplier_seed.domain.validation import ValidationIssue
from supplier_seed.engine import SupplierSeedEngine as CoreSupplierSeedEngine
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.services.permissions import GovernancePermission
from supplier_seed.services.results import GovernanceServiceResult

@dataclass(frozen=True)
class PilotIncidentSummary:
    total_incidents: int
    critical_incidents: int

@dataclass(frozen=True)
class PilotKpis:
    active_supplier_count: int

@dataclass(frozen=True)
class ExpansionGate:
    ready: bool
    blockers: tuple = ()

@dataclass(frozen=True)
class PilotReleaseSummary:
    enabled_supplier_count: int
    terms_accepted_count: int
    incidents: PilotIncidentSummary
    reversible: bool
    kpis: PilotKpis
    expansion_gate: ExpansionGate

@dataclass(frozen=True)
class PilotRunbookStep:
    action_name: str

@dataclass(frozen=True)
class PilotRunbook:
    steps: tuple
    rollback_action: str

class SupplierSeedEngine(CoreSupplierSeedEngine):
    def _pilot_auth(self, access_context, permission, supplier_id, action):
        auth = self._has_permission(access_context, permission)
        if auth.allowed:
            return None
        supplier = self.repository.get(supplier_id)
        return self._blocked_result(supplier, supplier_id, action, auth.reason, source="engine.pilot")

    def accept_pilot_terms(self, supplier_id, terms_version, actor=None, access_context=None):
        denied = self._pilot_auth(access_context, GovernancePermission.ACCEPT_PILOT_TERMS, supplier_id, "accept_pilot_terms")
        if denied:
            return denied
        supplier = self.repository.get(supplier_id)
        updated = replace(
            supplier,
            pilot_terms_accepted_version=terms_version,
            pilot_terms_accepted_by=actor,
            pilot_terms_accepted_at=datetime.utcnow(),
        ).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(
            supplier_id,
            GovernanceEventType.PILOT_TERMS_ACCEPTED,
            actor=actor,
            source="engine.pilot",
            metadata={"terms_version": terms_version},
        )
        return self._apply_result("accept_pilot_terms", supplier_id, GovernanceServiceResult(True, updated, (), (event,)), source="engine.pilot")

    def enable_pilot_access(self, supplier_id, pilot_name, terms_version, actor=None, context=None, access_context=None):
        denied = self._pilot_auth(access_context, GovernancePermission.ENABLE_PILOT_ACCESS, supplier_id, "enable_pilot_access")
        if denied:
            return denied
        supplier = self.repository.get(supplier_id)
        issues = []
        if not context or not context.pilot_enabled:
            issues.append(ValidationIssue("pilot.rollout.disabled"))
        if supplier.pilot_terms_accepted_version != terms_version:
            issues.append(ValidationIssue("pilot.terms.acceptance.required"))
        if supplier.region_context.market_code != "PH":
            issues.append(ValidationIssue("pilot.market.ph_only"))
        if supplier.lifecycle_status != LifecycleStatus.ACTIVE:
            issues.append(ValidationIssue("pilot.supplier.active_required"))
        if issues:
            return self._apply_result("enable_pilot_access", supplier_id, GovernanceServiceResult(False, supplier, tuple(issues), ()), source="engine.pilot")
        updated = replace(supplier, region_context=replace(supplier.region_context, pilot_enabled=True, pilot_name=pilot_name)).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(supplier_id, GovernanceEventType.PILOT_ACCESS_ENABLED, actor=actor, source="engine.pilot", metadata={"pilot_name": pilot_name, "terms_version": terms_version})
        return self._apply_result("enable_pilot_access", supplier_id, GovernanceServiceResult(True, updated, (), (event,)), source="engine.pilot")

    def disable_pilot_access(self, supplier_id, actor=None, reason="", access_context=None):
        denied = self._pilot_auth(access_context, GovernancePermission.DISABLE_PILOT_ACCESS, supplier_id, "disable_pilot_access")
        if denied:
            return denied
        supplier = self.repository.get(supplier_id)
        updated = replace(supplier, region_context=replace(supplier.region_context, pilot_enabled=False)).with_updated_metadata(actor)
        event = GovernanceEventRecord.for_supplier(supplier_id, GovernanceEventType.PILOT_ACCESS_DISABLED, actor=actor, source="engine.pilot", metadata={"reason": reason, "pilot_name": supplier.region_context.pilot_name})
        return self._apply_result("disable_pilot_access", supplier_id, GovernanceServiceResult(True, updated, (), (event,)), source="engine.pilot")

    def log_pilot_incident(self, supplier_id, severity, summary, actor=None, access_context=None):
        denied = self._pilot_auth(access_context, GovernancePermission.LOG_PILOT_INCIDENT, supplier_id, "log_pilot_incident")
        if denied:
            return denied
        supplier = self.repository.get(supplier_id)
        severity = PilotIncidentSeverity(severity)
        event = GovernanceEventRecord.for_supplier(supplier_id, GovernanceEventType.INCIDENT_LOGGED, actor=actor, source="engine.pilot", summary=summary, metadata={"severity": severity.value, "pilot_name": supplier.region_context.pilot_name})
        self.repository.append_events((event,))
        return GovernanceServiceResult(True, supplier, (), (event,))

    def get_pilot_release_summary(self, pilot_name, access_context=None):
        auth = self._has_permission(access_context, GovernancePermission.VIEW_PILOT_INTERNALS)
        if not auth.allowed:
            raise PermissionError(auth.reason)
        suppliers = tuple(self.repository.list())
        enabled = tuple(s for s in suppliers if s.region_context.pilot_enabled and s.region_context.pilot_name == pilot_name)
        accepted = tuple(s for s in suppliers if s.pilot_terms_accepted_version)
        incidents = tuple(e for e in self.repository.list_events() if e.event_type == GovernanceEventType.INCIDENT_LOGGED and e.metadata.get("pilot_name") == pilot_name)
        critical = sum(1 for e in incidents if e.metadata.get("severity") == PilotIncidentSeverity.CRITICAL.value)
        active_count = sum(1 for s in suppliers if s.lifecycle_status == LifecycleStatus.ACTIVE)
        blockers = tuple(filter(None, ("critical_incidents" if critical else None, "no_enabled_suppliers" if not enabled else None)))
        return PilotReleaseSummary(len(enabled), len(accepted), PilotIncidentSummary(len(incidents), critical), True, PilotKpis(active_count), ExpansionGate(not blockers, blockers))

    def get_pilot_runbook(self):
        return PilotRunbook((PilotRunbookStep("accept_pilot_terms"), PilotRunbookStep("enable_pilot_access"), PilotRunbookStep("monitor_pilot")), "disable_pilot_access")


# Phase T compatibility: enterprise API consumers may provide the core engine
# directly. Reuse the authoritative read-only runbook implementation without
# changing mutation authority or duplicating the response contract.
if not hasattr(CoreSupplierSeedEngine, "get_pilot_runbook"):
    CoreSupplierSeedEngine.get_pilot_runbook = SupplierSeedEngine.get_pilot_runbook
