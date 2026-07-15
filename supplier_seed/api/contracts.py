from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageMetadata(ContractModel):
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    returned: int = Field(ge=0)
    total: int = Field(ge=0)


class PaginatedResponse(ContractModel):
    api_version: Literal["v1"] = "v1"
    items: list[dict[str, Any]]
    page: PageMetadata


class SupplierDetailResponse(ContractModel):
    api_version: Literal["v1"] = "v1"
    supplier: dict[str, Any]


class PilotIncidentCounts(ContractModel):
    total: int = Field(ge=0)
    critical: int = Field(ge=0)


class PilotKpisResponse(ContractModel):
    active_supplier_count: int = Field(ge=0)


class ExpansionGateResponse(ContractModel):
    ready: bool
    blockers: list[str]


class PilotReleaseSummaryResponse(ContractModel):
    api_version: Literal["v1"] = "v1"
    pilot_name: str
    enabled_supplier_count: int = Field(ge=0)
    terms_accepted_count: int = Field(ge=0)
    incidents: PilotIncidentCounts
    reversible: bool
    kpis: PilotKpisResponse
    expansion_gate: ExpansionGateResponse


class PilotRunbookResponse(ContractModel):
    api_version: Literal["v1"] = "v1"
    steps: list[str]
    rollback_action: str


class HealthResponse(ContractModel):
    status: Literal["ok"]
    service: Literal["invyra-supplier-seed"]


class ErrorDetail(ContractModel):
    code: str
    supplier_id: str | None = None
    pilot_name: str | None = None
    queue: str | None = None
    bucket: str | None = None


class ErrorEnvelope(ContractModel):
    detail: ErrorDetail


class PaginationCapability(ContractModel):
    style: Literal["offset_limit"] = "offset_limit"
    default_limit: int
    maximum_limit: int


class EndpointCapability(ContractModel):
    path: str
    method: Literal["GET"] = "GET"
    read_only: Literal[True] = True
    filters: list[str] = Field(default_factory=list)
    sort: list[str] = Field(default_factory=list)
    pagination: PaginationCapability | None = None


class CapabilitiesResponse(ContractModel):
    api_version: Literal["v1"] = "v1"
    service_version: str
    mutation_authority: Literal["domain_service_only"] = "domain_service_only"
    enterprise_api_read_only: Literal[True] = True
    error_codes: list[str]
    endpoints: list[EndpointCapability]
