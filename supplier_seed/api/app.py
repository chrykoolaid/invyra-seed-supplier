from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from supplier_seed import PolicyContext, SupplierCandidateInput, SupplierMode, SupplierRegionContext, SupplierSeedEngine


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


def _candidate_from_payload(payload: SupplierCandidatePayload) -> SupplierCandidateInput:
    region = SupplierRegionContext(
        region_code=payload.region_context.region_code,
        market_code=payload.region_context.market_code,
        pilot_enabled=payload.region_context.pilot_enabled,
    )
    return SupplierCandidateInput(
        name=payload.name,
        mode=payload.mode,
        region_context=region,
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


def create_app(engine: SupplierSeedEngine | None = None) -> FastAPI:
    read_engine = engine or SupplierSeedEngine()
    application = FastAPI(
        title="Invyra Supplier Seed API",
        version="1.0.0",
        description="Governed Supplier Seed API. Enterprise endpoints are read-only unless explicitly documented.",
    )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "invyra-supplier-seed"}

    @application.get("/v1/suppliers")
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
        total = len(suppliers)
        page = suppliers[offset : offset + limit]
        return {
            "api_version": "v1",
            "items": [_supplier_summary(supplier) for supplier in page],
            "page": {"limit": limit, "offset": offset, "returned": len(page), "total": total},
        }

    @application.get("/v1/suppliers/{supplier_id}")
    def get_supplier(supplier_id: str) -> dict[str, Any]:
        supplier = read_engine.get_supplier(supplier_id)
        if supplier is None:
            raise HTTPException(status_code=404, detail={"code": "supplier.not_found", "supplier_id": supplier_id})
        return {"api_version": "v1", "supplier": _supplier_detail(supplier)}

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
