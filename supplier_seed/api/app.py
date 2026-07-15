from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from supplier_seed import (
    AccessContext,
    GovernanceEventType,
    PolicyContext,
    SupplierCandidateInput,
    SupplierMode,
    SupplierRegionContext,
    SupplierSeedEngine,
)
from supplier_seed.api.contracts import (
    CapabilitiesResponse,
    ErrorEnvelope,
    HealthResponse,
    PaginatedResponse,
    PilotReleaseSummaryResponse,
    PilotRunbookResponse,
    SupplierDetailResponse,
)


class RegionContextPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_code: str | None = None
    market_code: str = "PH"
    pilot_enabled: bool = False


class SupplierCandidatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    mode: SupplierMode = SupplierMode.MANUAL
    region_context: RegionContextPayload
    seeded_source: str | None = None
    seeded_source_reference: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    website_url: str | None = None
    tax_identifier: str | None = None
    created_by: str | None = None


class ExistingSupplierPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    supplier_id: str | None = None
    name: str
    email: str | None = None
    contact_email: str | None = None
    phone: str | None = None
    contact_phone: str | None = None
    website_url: str | None = None
    tax_identifier: str | None = None


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate: SupplierCandidatePayload
    existing_suppliers: list[ExistingSupplierPayload] = Field(default_factory=list)


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _supplier_summary(supplier) -> dict[str, Any]:
    return {
        "supplier_id": supplier.supplier_id,
        "name": supplier.name,
        "mode": _enum_value(supplier.mode),
        "region_code": supplier.region_context.region_code,
        "market_code": supplier.region_context.market_code,
        "seeded_source": supplier.seeded_source,
        "lifecycle_status": _enum_value(supplier.lifecycle_status),
        "moderation_status": _enum_value(supplier.moderation_status),
        "verification_status": _enum_value(supplier.verification_status),
    }


def _supplier_detail(supplier) -> dict[str, Any]:
    payload = _supplier_summary(supplier)
    payload.update(
        {
            "region_context": {
                "region_code": supplier.region_context.region_code,
                "market_code": supplier.region_context.market_code,
                "pilot_enabled": supplier.region_context.pilot_enabled,
                "pilot_name": supplier.region_context.pilot_name,
            },
            "seeded_source_reference": supplier.seeded_source_reference,
            "contact_email": supplier.contact_email,
            "contact_phone": supplier.contact_phone,
            "website_url": supplier.website_url,
            "tax_identifier": supplier.tax_identifier,
            "legal_acceptance_state": _enum_value(supplier.legal_acceptance_state),
            "verification_visibility": _enum_value(supplier.verification_visibility),
            "assigned_verifier": supplier.assigned_verifier,
            "created_by": supplier.created_by,
            "updated_by": supplier.updated_by,
            "created_at": supplier.created_at.isoformat() if supplier.created_at else None,
            "updated_at": supplier.updated_at.isoformat() if supplier.updated_at else None,
            "activated_at": supplier.activated_at.isoformat() if supplier.activated_at else None,
        }
    )
    return payload


def _event_payload(event) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "supplier_id": event.supplier_id,
        "event_type": _enum_value(event.event_type),
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
        "actor": event.actor,
        "source": event.source,
        "summary": event.summary,
        "metadata": event.metadata,
    }


def _candidate_from_payload(payload: SupplierCandidatePayload) -> SupplierCandidateInput:
    return SupplierCandidateInput(
        name=payload.name,
        mode=payload.mode,
        region_context=SupplierRegionContext(
            region_code=payload.region_context.region_code,
            market_code=payload.region_context.market_code,
            pilot_enabled=payload.region_context.pilot_enabled,
        ),
        seeded_source=payload.seeded_source,
        seeded_source_reference=payload.seeded_source_reference,
        contact_email=payload.contact_email,
        contact_phone=payload.contact_phone,
        website_url=payload.website_url,
        tax_identifier=payload.tax_identifier,
        created_by=payload.created_by,
    )


def _existing_supplier_candidates(payloads: list[ExistingSupplierPayload]) -> list[SupplierCandidateInput]:
    return [
        SupplierCandidateInput(
            name=payload.name,
            mode=SupplierMode.MANUAL,
            region_context=SupplierRegionContext(market_code="PH"),
            contact_email=payload.contact_email or payload.email,
            contact_phone=payload.contact_phone or payload.phone,
            website_url=payload.website_url,
            tax_identifier=payload.tax_identifier,
            created_by="preview-existing-supplier",
        )
        for payload in payloads
    ]


def _paginated(items, limit: int, offset: int) -> dict[str, Any]:
    total = len(items)
    page = items[offset : offset + limit]
    return {
        "api_version": "v1",
        "items": page,
        "page": {"limit": limit, "offset": offset, "returned": len(page), "total": total},
    }


def _capabilities() -> dict[str, Any]:
    return {
        "api_version": "v1",
        "service_version": "1.3.0",
        "mutation_authority": "domain_service_only",
        "enterprise_api_read_only": True,
        "error_codes": [
            "queue.invalid_bucket",
            "supplier.not_found",
            "permission.view_pilot_internals.denied",
            "request.validation_failed",
        ],
        "endpoints": [
            {
                "path": "/v1/suppliers",
                "filters": ["search", "region_code", "mode", "seeded_source", "lifecycle_status", "moderation_status"],
                "sort": ["name:asc", "supplier_id:asc"],
                "pagination": {"default_limit": 50, "maximum_limit": 200},
            },
            {
                "path": "/v1/suppliers/{supplier_id}",
                "filters": [],
                "sort": [],
                "pagination": None,
            },
            {
                "path": "/v1/queues/moderation/{queue_bucket}",
                "filters": ["queue_bucket"],
                "sort": ["name:asc", "supplier_id:asc"],
                "pagination": {"default_limit": 50, "maximum_limit": 200},
            },
            {
                "path": "/v1/queues/verification/{queue_bucket}",
                "filters": ["queue_bucket"],
                "sort": ["name:asc", "supplier_id:asc"],
                "pagination": {"default_limit": 50, "maximum_limit": 200},
            },
            {
                "path": "/v1/queues/activation-ready",
                "filters": [],
                "sort": ["name:asc", "supplier_id:asc"],
                "pagination": {"default_limit": 50, "maximum_limit": 200},
            },
            {
                "path": "/v1/suppliers/{supplier_id}/audit-events",
                "filters": ["event_type", "actor"],
                "sort": ["occurred_at:desc"],
                "pagination": {"default_limit": 100, "maximum_limit": 500},
            },
            {
                "path": "/v1/pilots/{pilot_name}/release-summary",
                "filters": ["pilot_name"],
                "sort": [],
                "pagination": None,
            },
            {
                "path": "/v1/pilots/{pilot_name}/incidents",
                "filters": ["pilot_name", "severity"],
                "sort": ["occurred_at:desc"],
                "pagination": {"default_limit": 100, "maximum_limit": 500},
            },
            {
                "path": "/v1/pilot/runbook",
                "filters": [],
                "sort": [],
                "pagination": None,
            },
        ],
    }


def create_app(engine: SupplierSeedEngine | None = None, access_context: AccessContext | None = None) -> FastAPI:
    read_engine = engine or SupplierSeedEngine()
    application = FastAPI(
        title="Invyra Supplier Seed API",
        version="1.3.0",
        description="Governed Supplier Seed API. Enterprise endpoints are read-only unless explicitly documented.",
    )

    @application.get("/health", response_model=HealthResponse)
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "invyra-supplier-seed"}

    @application.get("/v1/capabilities", response_model=CapabilitiesResponse)
    def capabilities() -> dict[str, Any]:
        return _capabilities()

    @application.get("/v1/suppliers", response_model=PaginatedResponse)
    def list_suppliers(
        search: str | None = None,
        region_code: str | None = None,
        mode: SupplierMode | None = None,
        seeded_source: str | None = None,
        lifecycle_status: str | None = None,
        moderation_status: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        suppliers = list(read_engine.list_suppliers())
        if search:
            suppliers = [supplier for supplier in suppliers if search.casefold() in supplier.name.casefold()]
        if region_code:
            suppliers = [supplier for supplier in suppliers if supplier.region_context.region_code == region_code]
        if mode:
            suppliers = [supplier for supplier in suppliers if supplier.mode == mode]
        if seeded_source:
            suppliers = [supplier for supplier in suppliers if supplier.seeded_source == seeded_source]
        if lifecycle_status:
            suppliers = [supplier for supplier in suppliers if _enum_value(supplier.lifecycle_status) == lifecycle_status]
        if moderation_status:
            suppliers = [supplier for supplier in suppliers if _enum_value(supplier.moderation_status) == moderation_status]
        suppliers.sort(key=lambda supplier: (supplier.name.casefold(), supplier.supplier_id))
        return _paginated([_supplier_summary(supplier) for supplier in suppliers], limit, offset)

    @application.get(
        "/v1/suppliers/{supplier_id}",
        response_model=SupplierDetailResponse,
        responses={404: {"model": ErrorEnvelope}},
    )
    def get_supplier(supplier_id: str) -> dict[str, Any]:
        supplier = read_engine.get_supplier(supplier_id)
        if supplier is None:
            raise HTTPException(status_code=404, detail={"code": "supplier.not_found", "supplier_id": supplier_id})
        return {"api_version": "v1", "supplier": _supplier_detail(supplier)}

    @application.get(
        "/v1/queues/moderation/{queue_bucket}",
        response_model=PaginatedResponse,
        responses={400: {"model": ErrorEnvelope}},
    )
    def moderation_queue(
        queue_bucket: str,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        if queue_bucket not in {"open_cases", "pending_review", "completed"}:
            raise HTTPException(status_code=400, detail={"code": "queue.invalid_bucket", "queue": "moderation", "bucket": queue_bucket})
        entries = list(read_engine.list_moderation_queue(queue_bucket))
        items = [
            {
                **_supplier_summary(read_engine.get_supplier(entry.summary.supplier_id)),
                "queue_bucket": entry.queue_bucket,
                "primary_queue": entry.summary.primary_queue,
                "next_step": entry.summary.next_step,
            }
            for entry in entries
        ]
        items.sort(key=lambda item: (item["name"].casefold(), item["supplier_id"]))
        return _paginated(items, limit, offset)

    @application.get(
        "/v1/queues/verification/{queue_bucket}",
        response_model=PaginatedResponse,
        responses={400: {"model": ErrorEnvelope}},
    )
    def verification_queue(
        queue_bucket: str,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        if queue_bucket not in {"eligible", "pending", "verified"}:
            raise HTTPException(status_code=400, detail={"code": "queue.invalid_bucket", "queue": "verification", "bucket": queue_bucket})
        entries = list(read_engine.list_verification_queue(queue_bucket))
        items = [
            {
                **_supplier_summary(read_engine.get_supplier(entry.summary.supplier_id)),
                "queue_bucket": entry.queue_bucket,
                "primary_queue": entry.summary.primary_queue,
                "next_step": entry.summary.next_step,
                "assigned_verifier": entry.assigned_to,
                "verification_status": _enum_value(entry.verification_status),
            }
            for entry in entries
        ]
        items.sort(key=lambda item: (item["name"].casefold(), item["supplier_id"]))
        return _paginated(items, limit, offset)

    @application.get("/v1/queues/activation-ready", response_model=PaginatedResponse)
    def activation_ready_queue(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        summaries = list(read_engine.list_supplier_summaries(queue="activation_ready"))
        items = [
            {
                **_supplier_summary(read_engine.get_supplier(summary.supplier_id)),
                "queue_bucket": summary.primary_queue,
                "primary_queue": summary.primary_queue,
                "next_step": summary.next_step,
            }
            for summary in summaries
        ]
        items.sort(key=lambda item: (item["name"].casefold(), item["supplier_id"]))
        return _paginated(items, limit, offset)

    @application.get(
        "/v1/suppliers/{supplier_id}/audit-events",
        response_model=PaginatedResponse,
        responses={404: {"model": ErrorEnvelope}},
    )
    def supplier_audit_events(
        supplier_id: str,
        event_type: str | None = None,
        actor: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        if read_engine.get_supplier(supplier_id) is None:
            raise HTTPException(status_code=404, detail={"code": "supplier.not_found", "supplier_id": supplier_id})
        events = list(read_engine.get_audit_timeline(supplier_id, actor=actor))
        if event_type:
            events = [event for event in events if _enum_value(event.event_type) == event_type]
        return _paginated([_event_payload(event) for event in events], limit, offset)

    @application.get(
        "/v1/pilots/{pilot_name}/release-summary",
        response_model=PilotReleaseSummaryResponse,
        responses={403: {"model": ErrorEnvelope}},
    )
    def pilot_release_summary(pilot_name: str) -> dict[str, Any]:
        try:
            summary = read_engine.get_pilot_release_summary(pilot_name, access_context=access_context)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail={"code": str(exc), "pilot_name": pilot_name}) from exc
        return {
            "api_version": "v1",
            "pilot_name": pilot_name,
            "enabled_supplier_count": summary.enabled_supplier_count,
            "terms_accepted_count": summary.terms_accepted_count,
            "incidents": {"total": summary.incidents.total_incidents, "critical": summary.incidents.critical_incidents},
            "reversible": summary.reversible,
            "kpis": {"active_supplier_count": summary.kpis.active_supplier_count},
            "expansion_gate": {"ready": summary.expansion_gate.ready, "blockers": list(summary.expansion_gate.blockers)},
        }

    @application.get(
        "/v1/pilots/{pilot_name}/incidents",
        response_model=PaginatedResponse,
        responses={403: {"model": ErrorEnvelope}},
    )
    def pilot_incidents(
        pilot_name: str,
        severity: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        try:
            read_engine.get_pilot_release_summary(pilot_name, access_context=access_context)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail={"code": str(exc), "pilot_name": pilot_name}) from exc
        incidents = [
            event
            for event in read_engine.list_audit_events(access_context=access_context)
            if event.event_type == GovernanceEventType.INCIDENT_LOGGED and event.metadata.get("pilot_name") == pilot_name
        ]
        if severity:
            incidents = [event for event in incidents if event.metadata.get("severity") == severity]
        incidents.sort(key=lambda event: event.occurred_at, reverse=True)
        return _paginated([_event_payload(event) for event in incidents], limit, offset)

    @application.get("/v1/pilot/runbook", response_model=PilotRunbookResponse)
    def pilot_runbook() -> dict[str, Any]:
        runbook = read_engine.get_pilot_runbook()
        return {
            "api_version": "v1",
            "steps": [step.action_name for step in runbook.steps],
            "rollback_action": runbook.rollback_action,
        }

    @application.post("/supplier-seed/ingest/preview")
    def preview_supplier_ingestion(request: PreviewRequest) -> dict[str, Any]:
        preview_engine = SupplierSeedEngine()
        for existing in _existing_supplier_candidates(request.existing_suppliers):
            preview_engine.ingest_supplier(existing, persist=True)
        candidate = _candidate_from_payload(request.candidate)
        context = PolicyContext(
            region_code=candidate.region_context.region_code,
            market_code=candidate.region_context.market_code,
            pilot_enabled=candidate.region_context.pilot_enabled,
        )
        result = preview_engine.ingest_supplier(candidate, context=context, persist=False)
        return {
            "bridge_mode": "api",
            "outcome": result.outcome.value,
            "accepted_for_staging": result.accepted_for_staging,
            "decisions": [
                {"code": decision.code, "outcome": decision.outcome.value, "message": decision.message}
                for decision in result.decisions
            ],
            "supplier": {
                "supplier_id": result.supplier.supplier_id if result.supplier else None,
                "name": result.supplier.name if result.supplier else request.candidate.name,
                "mode": result.supplier.mode.value if result.supplier else request.candidate.mode.value,
                "region_context": request.candidate.region_context.model_dump(),
            },
            "persisted": False,
            "source_of_truth": "chrykoolaid/invyra-seed-supplier",
        }

    return application


app = create_app()
