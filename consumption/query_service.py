"""Query service that prepares workflow-safe read models for UI consumers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from supplier_seed.consumption.models import (
    PilotExpansionGateView,
    PilotIncidentSummaryView,
    PilotKpiView,
    PilotReleaseSummaryView,
    PilotRunbookStepView,
    PilotRunbookView,
    SupplierAuditSummaryView,
    SupplierDetailView,
    SupplierModerationHistoryView,
    SupplierModerationQueueEntryView,
    SupplierProvenanceView,
    SupplierSummaryView,
    SupplierTimelineEntryView,
    SupplierVerificationOverviewView,
    SupplierVerificationQueueEntryView,
    SupplierWorkflowRequirementView,
    SupplierWorkspaceView,
)
from supplier_seed.domain.enums import (
    GovernanceEventType,
    LegalAcceptanceState,
    LifecycleStatus,
    ModerationStatus,
    SupplierMode,
    VerificationStatus,
)
from supplier_seed.domain.models import SupplierRecord
from supplier_seed.domain.transitions import evaluate_lifecycle_transition
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine
from supplier_seed.repository.interfaces import SupplierAuditRepository, SupplierReadRepository
from supplier_seed.services.permissions import AccessContext, GovernanceAuthorizer, GovernancePermission


@dataclass(frozen=True, slots=True)
class _WorkflowDescriptor:
    primary_queue: str
    next_step: str


class SupplierConsumptionService:
    """Build stable read models for lists, queues, and workspaces.

    This service stays read-only. It exists so desktop/admin clients do not need to reconstruct
    governance workflow state from raw supplier snapshots and audit records.
    """

    def __init__(
        self,
        *,
        repository: SupplierReadRepository & SupplierAuditRepository,
        policy_engine: Optional[SupplierPolicyEngine] = None,
        authorizer: Optional[GovernanceAuthorizer] = None,
    ) -> None:
        self.repository = repository
        self.policy_engine = policy_engine or SupplierPolicyEngine()
        self.authorizer = authorizer or GovernanceAuthorizer()

    def list_supplier_summaries(
        self,
        *,
        context: Optional[PolicyContext] = None,
        queue: Optional[str] = None,
        search: Optional[str] = None,
        assigned_to: Optional[str] = None,
        region_code: Optional[str] = None,
        lifecycle_status: Optional[LifecycleStatus] = None,
        moderation_status: Optional[ModerationStatus] = None,
        verification_status: Optional[VerificationStatus] = None,
        mode: Optional[SupplierMode] = None,
        seeded_source: Optional[str] = None,
        access_context: Optional[AccessContext] = None,
    ) -> tuple[SupplierSummaryView, ...]:
        resolved_context = context or PolicyContext()
        normalized_search = (search or "").strip().lower()
        normalized_queue = (queue or "").strip().lower() or None
        normalized_assignee = (assigned_to or "").strip().lower() or None
        normalized_region = (region_code or "").strip().upper() or None
        normalized_source = (seeded_source or "").strip().lower() or None

        views: list[SupplierSummaryView] = []
        for supplier in self.repository.list_suppliers():
            if normalized_search and not self._matches_search(supplier, normalized_search):
                continue
            if normalized_region and (supplier.region_context.region_code or "") != normalized_region:
                continue
            if lifecycle_status is not None and supplier.lifecycle_status is not lifecycle_status:
                continue
            if moderation_status is not None and supplier.moderation_status is not moderation_status:
                continue
            if verification_status is not None and supplier.verification_status is not verification_status:
                continue
            if mode is not None and supplier.mode is not mode:
                continue
            if normalized_source and (supplier.seeded_source or "").lower() != normalized_source:
                continue

            summary = self._build_summary(supplier, context=resolved_context, access_context=access_context)
            if normalized_queue and summary.primary_queue != normalized_queue:
                continue
            if normalized_assignee and (summary.assigned_verifier or "").lower() != normalized_assignee:
                continue
            views.append(summary)
        return tuple(sorted(views, key=lambda item: (item.updated_at, item.name.lower()), reverse=True))

    def search_suppliers(
        self,
        *,
        context: Optional[PolicyContext] = None,
        search: Optional[str] = None,
        region_code: Optional[str] = None,
        lifecycle_status: Optional[LifecycleStatus] = None,
        moderation_status: Optional[ModerationStatus] = None,
        verification_status: Optional[VerificationStatus] = None,
        mode: Optional[SupplierMode] = None,
        seeded_source: Optional[str] = None,
        assigned_to: Optional[str] = None,
        access_context: Optional[AccessContext] = None,
    ) -> tuple[SupplierSummaryView, ...]:
        return self.list_supplier_summaries(
            context=context,
            search=search,
            assigned_to=assigned_to,
            region_code=region_code,
            lifecycle_status=lifecycle_status,
            moderation_status=moderation_status,
            verification_status=verification_status,
            mode=mode,
            seeded_source=seeded_source,
            access_context=access_context,
        )

    def list_moderation_queue(
        self,
        *,
        queue_bucket: str = "open_cases",
        context: Optional[PolicyContext] = None,
        access_context: Optional[AccessContext] = None,
    ) -> tuple[SupplierModerationQueueEntryView, ...]:
        resolved_context = context or PolicyContext()
        normalized_bucket = (queue_bucket or "open_cases").strip().lower() or "open_cases"
        entries: list[SupplierModerationQueueEntryView] = []
        for supplier in self.repository.list_suppliers():
            bucket = self._moderation_queue_bucket(supplier)
            if bucket is None:
                continue
            if normalized_bucket == "open_cases":
                if supplier.moderation_status not in {ModerationStatus.PENDING_REVIEW, ModerationStatus.ESCALATED}:
                    continue
            elif bucket != normalized_bucket:
                continue
            summary = self._build_summary(supplier, context=resolved_context, access_context=access_context)
            entries.append(
                SupplierModerationQueueEntryView(
                    summary=summary,
                    queue_bucket=("open_cases" if normalized_bucket == "open_cases" else bucket),
                    moderation_status=supplier.moderation_status,
                    last_reviewed_at=supplier.last_reviewed_at,
                    last_reviewed_by=supplier.last_reviewed_by,
                )
            )
        return tuple(sorted(entries, key=lambda item: (item.summary.updated_at, item.summary.name.lower()), reverse=True))

    def list_verification_queue(
        self,
        *,
        queue_bucket: str = "eligible",
        context: Optional[PolicyContext] = None,
        access_context: Optional[AccessContext] = None,
    ) -> tuple[SupplierVerificationQueueEntryView, ...]:
        resolved_context = context or PolicyContext()
        normalized_bucket = (queue_bucket or "eligible").strip().lower() or "eligible"
        entries: list[SupplierVerificationQueueEntryView] = []
        for supplier in self.repository.list_suppliers():
            bucket = self._verification_queue_bucket(supplier)
            if bucket is None or bucket != normalized_bucket:
                continue
            summary = self._build_summary(supplier, context=resolved_context, access_context=access_context)
            entries.append(
                SupplierVerificationQueueEntryView(
                    summary=summary,
                    queue_bucket=bucket,
                    verification_status=supplier.verification_status,
                    assigned_to=(supplier.verification_assigned_to if self._can_view_sensitive_verification_details(access_context) else None),
                    assigned_at=supplier.verification_assigned_at,
                    last_updated_at=supplier.verification_last_updated_at,
                )
            )
        return tuple(sorted(entries, key=lambda item: (item.summary.updated_at, item.summary.name.lower()), reverse=True))

    def get_supplier_workspace(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        context: Optional[PolicyContext] = None,
        access_context: Optional[AccessContext] = None,
    ) -> SupplierWorkspaceView:
        supplier = self._resolve_supplier(supplier_or_id)
        resolved_context = context or PolicyContext(region_code=supplier.region_context.region_code)
        summary = self._build_summary(supplier, context=resolved_context, access_context=access_context)
        requirements, activation_allowed, activation_issue_codes = self._build_requirements(
            supplier,
            context=resolved_context,
        )
        timeline = self.get_audit_timeline(
            supplier.identity.supplier_id,
            access_context=access_context,
        )
        return SupplierWorkspaceView(
            summary=summary,
            requirements=requirements,
            timeline=timeline,
            activation_allowed=activation_allowed,
            activation_issue_codes=activation_issue_codes,
        )

    def get_supplier_detail(
        self,
        supplier_or_id: SupplierRecord | str,
        *,
        context: Optional[PolicyContext] = None,
        access_context: Optional[AccessContext] = None,
    ) -> SupplierDetailView:
        supplier = self._resolve_supplier(supplier_or_id)
        resolved_context = context or PolicyContext(region_code=supplier.region_context.region_code)
        summary = self._build_summary(supplier, context=resolved_context, access_context=access_context)
        requirements, activation_allowed, activation_issue_codes = self._build_requirements(
            supplier,
            context=resolved_context,
        )
        timeline = self.get_audit_timeline(
            supplier.identity.supplier_id,
            access_context=access_context,
        )
        moderation_events = tuple(
            entry for entry in timeline if entry.event_type in self._MODERATION_EVENT_TYPES
        )
        provenance = SupplierProvenanceView(
            mode=supplier.mode,
            origin_label=("seeded" if supplier.is_seeded else "manual"),
            seeded_source=supplier.seeded_source,
            seeded_source_reference=supplier.seeded_source_reference,
            created_at=supplier.created_at,
            created_by=supplier.created_by,
            last_updated_at=supplier.provenance_last_updated_at,
            last_updated_by=supplier.provenance_last_updated_by,
        )
        moderation = SupplierModerationHistoryView(
            current_status=supplier.moderation_status,
            lifecycle_status=supplier.lifecycle_status,
            last_reviewed_at=supplier.last_reviewed_at,
            last_reviewed_by=supplier.last_reviewed_by,
            events=moderation_events,
        )
        verification = SupplierVerificationOverviewView(
            current_status=supplier.verification_status,
            visibility=supplier.verification_visibility,
            assigned_to=(supplier.verification_assigned_to if self._can_view_sensitive_verification_details(access_context) else None),
            assigned_at=supplier.verification_assigned_at,
            last_updated_at=supplier.verification_last_updated_at,
            last_updated_by=(supplier.verification_last_updated_by if self._can_view_sensitive_verification_details(access_context) else None),
        )
        latest_event = timeline[0] if timeline else None
        audit_summary = SupplierAuditSummaryView(
            total_events=len(timeline),
            latest_event_type=(latest_event.event_type if latest_event is not None else None),
            latest_occurred_at=(latest_event.occurred_at if latest_event is not None else None),
            blocked_action_count=sum(1 for entry in timeline if entry.event_type is GovernanceEventType.GOVERNANCE_ACTION_BLOCKED),
            visible_actor_count=sum(1 for entry in timeline if entry.actor is not None),
        )
        return SupplierDetailView(
            summary=summary,
            provenance=provenance,
            requirements=requirements,
            moderation=moderation,
            verification=verification,
            audit_summary=audit_summary,
            timeline=timeline,
            activation_allowed=activation_allowed,
            activation_issue_codes=activation_issue_codes,
        )

    def get_audit_timeline(
        self,
        supplier_or_id: Optional[SupplierRecord | str] = None,
        *,
        event_type: Optional[GovernanceEventType] = None,
        actor: Optional[str] = None,
        access_context: Optional[AccessContext] = None,
        limit: Optional[int] = None,
    ) -> tuple[SupplierTimelineEntryView, ...]:
        supplier_id: Optional[str]
        if supplier_or_id is None:
            supplier_id = None
        elif isinstance(supplier_or_id, SupplierRecord):
            supplier_id = supplier_or_id.identity.supplier_id
        else:
            supplier_id = supplier_or_id

        entries = [
            self._build_timeline_entry(event, access_context=access_context)
            for event in sorted(
                self.repository.list_audit_events(supplier_id=supplier_id),
                key=lambda current: (current.occurred_at, current.event_id),
                reverse=True,
            )
        ]
        if event_type is not None:
            entries = [entry for entry in entries if entry.event_type is event_type]
        normalized_actor = (actor or "").strip()
        if normalized_actor:
            entries = [entry for entry in entries if entry.actor == normalized_actor]
        if limit is not None:
            entries = entries[: max(0, limit)]
        return tuple(entries)

    def _resolve_supplier(self, supplier_or_id: SupplierRecord | str) -> SupplierRecord:
        if isinstance(supplier_or_id, SupplierRecord):
            return supplier_or_id
        supplier = self.repository.get_supplier(supplier_or_id)
        if supplier is None:
            raise KeyError(f"Supplier not found: {supplier_or_id}")
        return supplier

    def get_pilot_release_summary(
        self,
        *,
        pilot_name: Optional[str] = None,
        market_code: str = "PH",
        access_context: Optional[AccessContext] = None,
    ) -> PilotReleaseSummaryView:
        self._require_pilot_internal_access(access_context)
        normalized_pilot = (pilot_name or "").strip() or None
        normalized_market = (market_code or "PH").strip().upper() or "PH"

        suppliers = [
            supplier
            for supplier in self.repository.list_suppliers()
            if supplier.region_context.market_code == normalized_market
        ]
        if normalized_pilot is not None:
            suppliers = [
                supplier
                for supplier in suppliers
                if (supplier.region_context.pilot_name or "") == normalized_pilot
            ]

        enabled_suppliers = [supplier for supplier in suppliers if supplier.region_context.pilot_enabled]
        eligible_suppliers = [
            supplier
            for supplier in suppliers
            if supplier.lifecycle_status is LifecycleStatus.ACTIVE and bool(supplier.region_context.region_code)
        ]
        terms_accepted_count = sum(1 for supplier in suppliers if supplier.has_pilot_terms_accepted)

        supplier_ids = {supplier.identity.supplier_id for supplier in suppliers}
        events = [event for event in self.repository.list_audit_events() if event.supplier_id in supplier_ids]
        if normalized_pilot is not None:
            events = [
                event
                for event in events
                if (event.metadata.get("pilot_name") or "") == normalized_pilot
                or event.supplier_id in {supplier.identity.supplier_id for supplier in enabled_suppliers}
            ]

        ingestion_successes = sum(1 for event in events if event.event_type is GovernanceEventType.SUPPLIER_STAGED)
        ingestion_failures = sum(
            1
            for event in events
            if event.event_type is GovernanceEventType.GOVERNANCE_ACTION_BLOCKED
            and event.metadata.get("action") == "ingest_supplier"
        )
        moderation_decisions = sum(
            1
            for event in events
            if event.event_type in {GovernanceEventType.MODERATION_APPROVED, GovernanceEventType.MODERATION_REJECTED}
        )
        moderation_rejections = sum(1 for event in events if event.event_type is GovernanceEventType.MODERATION_REJECTED)
        open_moderation = sum(
            1 for supplier in suppliers if supplier.moderation_status in {ModerationStatus.PENDING_REVIEW, ModerationStatus.ESCALATED}
        )
        verification_terminal = sum(
            1
            for event in events
            if event.event_type in {
                GovernanceEventType.VERIFICATION_VERIFIED,
                GovernanceEventType.VERIFICATION_FAILED,
                GovernanceEventType.VERIFICATION_NEEDS_REVIEW,
            }
        )
        verification_verified = sum(1 for event in events if event.event_type is GovernanceEventType.VERIFICATION_VERIFIED)
        incident_events = [event for event in events if event.event_type is GovernanceEventType.INCIDENT_LOGGED]
        critical_incidents = sum(1 for event in incident_events if event.metadata.get("severity") == "critical")
        latest_incident_at = max((event.occurred_at for event in incident_events), default=None)

        total_ingestion_attempts = ingestion_successes + ingestion_failures
        success_rate = ingestion_successes / total_ingestion_attempts if total_ingestion_attempts else 0.0
        failure_rate = ingestion_failures / total_ingestion_attempts if total_ingestion_attempts else 0.0
        moderation_throughput = moderation_decisions / (moderation_decisions + open_moderation) if (moderation_decisions + open_moderation) else 0.0
        rejection_rate = moderation_rejections / moderation_decisions if moderation_decisions else 0.0
        verification_rate = verification_verified / verification_terminal if verification_terminal else 0.0

        blockers: list[str] = []
        if not enabled_suppliers:
            blockers.append("No suppliers are enabled for the controlled PH pilot.")
        if any(supplier.region_context.market_code != "PH" for supplier in enabled_suppliers):
            blockers.append("Pilot expansion is blocked because a non-PH supplier is enabled.")
        if any(not supplier.has_pilot_terms_accepted for supplier in enabled_suppliers):
            blockers.append("Pilot expansion is blocked because at least one enabled supplier has no tracked terms acceptance.")
        if any(supplier.lifecycle_status is not LifecycleStatus.ACTIVE for supplier in enabled_suppliers):
            blockers.append("Pilot expansion is blocked because at least one enabled supplier is not active.")
        if critical_incidents:
            blockers.append("Pilot expansion is blocked while critical incidents remain logged in the rollout history.")

        return PilotReleaseSummaryView(
            pilot_name=normalized_pilot,
            market_code=normalized_market,
            enabled_supplier_count=len(enabled_suppliers),
            eligible_supplier_count=len(eligible_suppliers),
            terms_accepted_count=terms_accepted_count,
            kpis=PilotKpiView(
                ingestion_success_rate=success_rate,
                moderation_throughput=moderation_throughput,
                rejection_rate=rejection_rate,
                verification_rate=verification_rate,
                failure_rate=failure_rate,
                enabled_supplier_count=len(enabled_suppliers),
                active_supplier_count=sum(1 for supplier in enabled_suppliers if supplier.lifecycle_status is LifecycleStatus.ACTIVE),
            ),
            incidents=PilotIncidentSummaryView(
                total_incidents=len(incident_events),
                critical_incidents=critical_incidents,
                latest_incident_at=latest_incident_at,
            ),
            expansion_gate=PilotExpansionGateView(
                ready=not blockers,
                blocking_reasons=tuple(blockers),
            ),
            reversible=True,
        )

    def get_pilot_runbook(self) -> PilotRunbookView:
        return PilotRunbookView(
            title="PH-first controlled pilot runbook",
            support_flow="Log incidents immediately, review pilot KPIs daily, and disable pilot access for rollback when governance risk appears.",
            rollback_action="disable_pilot_access",
            steps=(
                PilotRunbookStepView(1, "accept_pilot_terms", "Capture pilot consent", "Record the accepted pilot terms version before pilot usage is enabled."),
                PilotRunbookStepView(2, "enable_pilot_access", "Enable controlled rollout", "Enable only active PH suppliers with a region and accepted terms."),
                PilotRunbookStepView(3, "get_pilot_release_summary", "Monitor KPIs", "Track ingestion success, moderation throughput, verification rate, and failures."),
                PilotRunbookStepView(4, "log_pilot_incident", "Capture incidents", "Record rollout issues with severity so support and rollback decisions are auditable."),
                PilotRunbookStepView(5, "disable_pilot_access", "Rollback access", "Disable pilot access with a required reason when the rollout must be reversed."),
            ),
        )

    def _require_pilot_internal_access(self, access_context: Optional[AccessContext]) -> None:
        if access_context is None:
            return
        if not self.authorizer.can(GovernancePermission.VIEW_PILOT_INTERNALS, access_context=access_context):
            raise PermissionError("Pilot internals are restricted for the current role.")

    def _build_summary(
        self,
        supplier: SupplierRecord,
        *,
        context: PolicyContext,
        access_context: Optional[AccessContext] = None,
    ) -> SupplierSummaryView:
        workflow = self._describe_workflow(supplier, context=context)
        return SupplierSummaryView(
            supplier_id=supplier.identity.supplier_id,
            name=supplier.name,
            mode=supplier.mode,
            lifecycle_status=supplier.lifecycle_status,
            moderation_status=supplier.moderation_status,
            legal_acceptance_state=supplier.legal_acceptance_state,
            verification_status=supplier.verification_status,
            verification_visibility=supplier.verification_visibility,
            region_code=supplier.region_context.region_code,
            market_code=supplier.region_context.market_code,
            assigned_verifier=(supplier.verification_assigned_to if self._can_view_sensitive_verification_details(access_context) else None),
            seeded_source=supplier.seeded_source,
            updated_at=supplier.updated_at,
            primary_queue=workflow.primary_queue,
            next_step=workflow.next_step,
        )

    def _describe_workflow(self, supplier: SupplierRecord, *, context: PolicyContext) -> _WorkflowDescriptor:
        activation_result = evaluate_lifecycle_transition(
            supplier,
            target_status=LifecycleStatus.ACTIVE,
            context=context,
            policy_engine=self.policy_engine,
        )

        legal_required_and_missing = self._legal_required_and_missing(supplier, context=context)
        verification_follow_up = supplier.verification_status in {VerificationStatus.FAILED, VerificationStatus.NEEDS_REVIEW}
        verification_in_progress = supplier.has_verification_assignee and supplier.verification_status in {
            VerificationStatus.UNVERIFIED,
            VerificationStatus.PENDING,
        }

        if supplier.lifecycle_status is LifecycleStatus.ARCHIVED:
            return _WorkflowDescriptor(primary_queue="archived", next_step="none")
        if supplier.lifecycle_status is LifecycleStatus.ACTIVE:
            return _WorkflowDescriptor(primary_queue="operational", next_step="monitor_supplier")
        if supplier.lifecycle_status is LifecycleStatus.SUSPENDED:
            next_step = "reactivate_supplier" if activation_result.allowed else "review_reactivation_blockers"
            return _WorkflowDescriptor(primary_queue="operational", next_step=next_step)
        if supplier.lifecycle_status is LifecycleStatus.PENDING_REVIEW or supplier.moderation_status in {
            ModerationStatus.PENDING_REVIEW,
            ModerationStatus.ESCALATED,
        }:
            return _WorkflowDescriptor(primary_queue="moderation_review", next_step="review_moderation")
        if supplier.lifecycle_status is LifecycleStatus.DRAFT:
            return _WorkflowDescriptor(primary_queue="draft_intake", next_step="submit_for_review")
        if legal_required_and_missing:
            return _WorkflowDescriptor(primary_queue="legal_review", next_step="accept_legal")
        if verification_follow_up or verification_in_progress:
            return _WorkflowDescriptor(primary_queue="verification_review", next_step="resolve_verification")
        if activation_result.allowed:
            return _WorkflowDescriptor(primary_queue="activation_ready", next_step="activate_supplier")
        return _WorkflowDescriptor(primary_queue="governance_follow_up", next_step="review_supplier")

    def _build_requirements(
        self,
        supplier: SupplierRecord,
        *,
        context: PolicyContext,
    ) -> tuple[tuple[SupplierWorkflowRequirementView, ...], bool, tuple[str, ...]]:
        activation_result = evaluate_lifecycle_transition(
            supplier,
            target_status=LifecycleStatus.ACTIVE,
            context=context,
            policy_engine=self.policy_engine,
        )
        activation_issue_codes = tuple(issue.code for issue in activation_result.issues)
        requirements = (
            self._moderation_requirement(supplier),
            self._legal_requirement(supplier, context=context),
            self._verification_requirement(supplier),
            SupplierWorkflowRequirementView(
                code="activation",
                label="Activation",
                satisfied=activation_result.allowed or supplier.lifecycle_status is LifecycleStatus.ACTIVE,
                blocking=not activation_result.allowed and supplier.lifecycle_status is not LifecycleStatus.ACTIVE,
                message=(
                    "Supplier is ready for activation."
                    if activation_result.allowed
                    else "Activation is not yet available under the current lifecycle and policy state."
                ),
                issue_codes=activation_issue_codes,
            ),
        )
        return requirements, activation_result.allowed, activation_issue_codes

    @staticmethod
    def _moderation_requirement(supplier: SupplierRecord) -> SupplierWorkflowRequirementView:
        satisfied = supplier.lifecycle_status in {
            LifecycleStatus.APPROVED,
            LifecycleStatus.ACTIVE,
            LifecycleStatus.SUSPENDED,
        }
        return SupplierWorkflowRequirementView(
            code="moderation",
            label="Governance review",
            satisfied=satisfied,
            blocking=not satisfied,
            message=(
                "Governance review is complete."
                if satisfied
                else f"Supplier is still in governance flow with lifecycle {supplier.lifecycle_status.value}."
            ),
        )

    def _legal_requirement(self, supplier: SupplierRecord, *, context: PolicyContext) -> SupplierWorkflowRequirementView:
        required = supplier.is_manual and context.require_legal_acceptance_for_manual
        satisfied = not required or supplier.legal_acceptance_state is LegalAcceptanceState.ACCEPTED
        return SupplierWorkflowRequirementView(
            code="legal_acceptance",
            label="Legal acceptance",
            satisfied=satisfied,
            blocking=required and not satisfied,
            message=(
                "Legal acceptance is satisfied."
                if satisfied
                else f"Manual supplier legal acceptance is still {supplier.legal_acceptance_state.value}."
            ),
        )

    @staticmethod
    def _verification_requirement(supplier: SupplierRecord) -> SupplierWorkflowRequirementView:
        blocking = supplier.verification_status in {VerificationStatus.FAILED, VerificationStatus.NEEDS_REVIEW}
        satisfied = not blocking
        if supplier.verification_status is VerificationStatus.VERIFIED:
            message = "Verification is complete."
        elif supplier.verification_status is VerificationStatus.UNVERIFIED:
            message = "Verification is still unverified. Current policy may still allow activation with warning."
        elif supplier.verification_status is VerificationStatus.PENDING:
            message = "Verification is pending."
        elif supplier.verification_status is VerificationStatus.FAILED:
            message = "Verification failed and must be resolved before activation."
        else:
            message = "Verification needs review before the supplier should move forward."
        return SupplierWorkflowRequirementView(
            code="verification",
            label="Verification",
            satisfied=satisfied,
            blocking=blocking,
            message=message,
        )

    def _build_timeline_entry(
        self,
        event: GovernanceEventRecord,
        *,
        access_context: Optional[AccessContext] = None,
    ) -> SupplierTimelineEntryView:
        actor = event.actor
        summary = event.summary
        metadata = dict(event.metadata)
        if (
            event.event_type in self._SENSITIVE_VERIFICATION_EVENTS
            and not self._can_view_sensitive_verification_details(access_context)
        ):
            actor = None
            summary = "Verification detail is restricted."
            metadata = {"redacted": True}
        if (
            event.event_type is GovernanceEventType.GOVERNANCE_ACTION_BLOCKED
            and not self._can_view_audit_internals(access_context)
        ):
            actor = None
            summary = "Audit detail is restricted."
            metadata = {"redacted": True}
        return SupplierTimelineEntryView(
            event_id=event.event_id,
            supplier_id=event.supplier_id,
            occurred_at=event.occurred_at,
            event_type=event.event_type,
            actor=actor,
            source=event.source,
            summary=summary,
            metadata=metadata,
        )

    _SENSITIVE_VERIFICATION_EVENTS = frozenset(
        {
            GovernanceEventType.VERIFICATION_ASSIGNED,
            GovernanceEventType.VERIFICATION_UNASSIGNED,
            GovernanceEventType.VERIFICATION_PENDING,
            GovernanceEventType.VERIFICATION_VERIFIED,
            GovernanceEventType.VERIFICATION_FAILED,
            GovernanceEventType.VERIFICATION_NEEDS_REVIEW,
            GovernanceEventType.VERIFICATION_VISIBILITY_CHANGED,
        }
    )
    _MODERATION_EVENT_TYPES = frozenset(
        {
            GovernanceEventType.MODERATION_SUBMITTED,
            GovernanceEventType.MODERATION_APPROVED,
            GovernanceEventType.MODERATION_REJECTED,
            GovernanceEventType.MODERATION_ESCALATED,
        }
    )

    def _can_view_sensitive_verification_details(self, access_context: Optional[AccessContext]) -> bool:
        return self.authorizer.can(
            GovernancePermission.VIEW_SENSITIVE_VERIFICATION_DETAILS,
            access_context=access_context,
        )

    def _can_view_audit_internals(self, access_context: Optional[AccessContext]) -> bool:
        return self.authorizer.can(
            GovernancePermission.VIEW_AUDIT_INTERNALS,
            access_context=access_context,
        )

    @staticmethod
    def _legal_required_and_missing(supplier: SupplierRecord, *, context: PolicyContext) -> bool:
        return supplier.is_manual and context.require_legal_acceptance_for_manual and supplier.legal_acceptance_state is not LegalAcceptanceState.ACCEPTED

    @staticmethod
    def _matches_search(supplier: SupplierRecord, search: str) -> bool:
        haystacks: Iterable[str] = (
            supplier.identity.supplier_id,
            supplier.name,
            supplier.identity.supplier_code or "",
            supplier.identity.external_reference or "",
            supplier.seeded_source or "",
            supplier.seeded_source_reference or "",
            supplier.verification_assigned_to or "",
            supplier.region_context.region_code or "",
            supplier.region_context.market_code,
        )
        return any(search in value.lower() for value in haystacks)

    @staticmethod
    def _moderation_queue_bucket(supplier: SupplierRecord) -> Optional[str]:
        if supplier.moderation_status is ModerationStatus.PENDING_REVIEW:
            return "pending_review"
        if supplier.moderation_status is ModerationStatus.ESCALATED:
            return "open_cases"
        if supplier.moderation_status in {ModerationStatus.APPROVED, ModerationStatus.REJECTED}:
            return "completed"
        return None

    @staticmethod
    def _verification_queue_bucket(supplier: SupplierRecord) -> Optional[str]:
        if supplier.verification_status is VerificationStatus.VERIFIED:
            return "verified"
        if supplier.verification_status in {VerificationStatus.PENDING, VerificationStatus.FAILED, VerificationStatus.NEEDS_REVIEW}:
            return "pending"
        if supplier.has_verification_assignee:
            return "pending"
        if supplier.lifecycle_status in {LifecycleStatus.APPROVED, LifecycleStatus.ACTIVE, LifecycleStatus.SUSPENDED} and supplier.verification_status is VerificationStatus.UNVERIFIED:
            return "eligible"
        return None
