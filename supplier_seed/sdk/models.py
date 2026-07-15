from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class SdkResourceModel(BaseModel):
    """Forward-compatible SDK resource model for stable v1 read payloads."""

    model_config = ConfigDict(extra="allow")


class SupplierSummaryResource(SdkResourceModel):
    supplier_id: str
    name: str
    mode: str
    region_code: str | None = None
    market_code: str
    seeded_source: str | None = None
    lifecycle_status: str
    moderation_status: str
    verification_status: str


class SupplierDetailResource(SupplierSummaryResource):
    region_context: dict[str, Any]
    seeded_source_reference: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    website_url: str | None = None
    tax_identifier: str | None = None
    legal_acceptance_state: str
    verification_visibility: str
    assigned_verifier: str | None = None
    created_by: str | None = None
    updated_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    activated_at: datetime | None = None


class QueueResource(SupplierSummaryResource):
    queue_bucket: str
    primary_queue: str
    next_step: str
    assigned_verifier: str | None = None


class AuditEventResource(SdkResourceModel):
    event_id: str
    supplier_id: str
    event_type: str
    occurred_at: datetime
    actor: str | None = None
    source: str | None = None
    summary: str | None = None
    metadata: dict[str, Any]
