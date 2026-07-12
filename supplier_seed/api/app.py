from __future__ import annotations

from typing import Any

from fastapi import FastAPI
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


app = FastAPI(
    title="Invyra Supplier Seed API",
    version="0.1.0",
    description="Governed Supplier Seed preview API. Preview endpoints never persist mutations.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "invyra-supplier-seed"}


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
    candidates: list[SupplierCandidateInput] = []
    for payload in payloads:
        candidates.append(
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
        )
    return candidates


@app.post("/supplier-seed/ingest/preview")
def preview_supplier_ingestion(request: PreviewRequest) -> dict[str, Any]:
    engine = SupplierSeedEngine()

    for existing in _existing_supplier_candidates(request.existing_suppliers):
        engine.ingest_supplier(existing, persist=True)

    candidate = _candidate_from_payload(request.candidate)
    context = PolicyContext(
        region_code=candidate.region_context.region_code,
        market_code=candidate.region_context.market_code,
        pilot_enabled=candidate.region_context.pilot_enabled,
    )
    result = engine.ingest_supplier(candidate, context=context, persist=False)

    return {
        "bridge_mode": "api",
        "outcome": result.outcome.value,
        "accepted_for_staging": result.accepted_for_staging,
        "decisions": [
            {
                "code": decision.code,
                "outcome": decision.outcome.value,
                "message": decision.message,
            }
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
