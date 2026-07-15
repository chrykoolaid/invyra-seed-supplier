from __future__ import annotations

from typing import Any, AsyncIterator, Iterator

from supplier_seed.sdk.async_client import SupplierSeedAsyncReadClient
from supplier_seed.sdk.client import SupplierSeedReadClient
from supplier_seed.sdk.models import (
    AuditEventResource,
    QueueResource,
    SupplierDetailResource,
    SupplierSummaryResource,
)


class SupplierSeedTypedReadClient(SupplierSeedReadClient):
    """Additive synchronous client returning validated SDK resource models."""

    def get_supplier_resource(self, supplier_id: str) -> SupplierDetailResource:
        response = self.get_supplier(supplier_id)
        return SupplierDetailResource.model_validate(response.supplier)

    def list_supplier_resources(self, **filters: Any) -> list[SupplierSummaryResource]:
        page = self.list_suppliers(**filters)
        return [SupplierSummaryResource.model_validate(item) for item in page.items]

    def iter_supplier_resources(
        self,
        *,
        page_size: int = 200,
        **filters: Any,
    ) -> Iterator[SupplierSummaryResource]:
        for item in self.iter_suppliers(page_size=page_size, **filters):
            yield SupplierSummaryResource.model_validate(item)

    def moderation_queue_resources(
        self,
        bucket: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[QueueResource]:
        page = self.moderation_queue(bucket, limit=limit, offset=offset)
        return [QueueResource.model_validate(item) for item in page.items]

    def verification_queue_resources(
        self,
        bucket: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[QueueResource]:
        page = self.verification_queue(bucket, limit=limit, offset=offset)
        return [QueueResource.model_validate(item) for item in page.items]

    def activation_ready_resources(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[QueueResource]:
        page = self.activation_ready(limit=limit, offset=offset)
        return [QueueResource.model_validate(item) for item in page.items]

    def audit_event_resources(
        self,
        supplier_id: str,
        *,
        event_type: str | None = None,
        actor: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEventResource]:
        page = self.audit_events(
            supplier_id,
            event_type=event_type,
            actor=actor,
            limit=limit,
            offset=offset,
        )
        return [AuditEventResource.model_validate(item) for item in page.items]


class SupplierSeedAsyncTypedReadClient(SupplierSeedAsyncReadClient):
    """Additive asynchronous client returning validated SDK resource models."""

    async def get_supplier_resource(self, supplier_id: str) -> SupplierDetailResource:
        response = await self.get_supplier(supplier_id)
        return SupplierDetailResource.model_validate(response.supplier)

    async def list_supplier_resources(self, **filters: Any) -> list[SupplierSummaryResource]:
        page = await self.list_suppliers(**filters)
        return [SupplierSummaryResource.model_validate(item) for item in page.items]

    async def iter_supplier_resources(
        self,
        *,
        page_size: int = 200,
        **filters: Any,
    ) -> AsyncIterator[SupplierSummaryResource]:
        async for item in self.iter_suppliers(page_size=page_size, **filters):
            yield SupplierSummaryResource.model_validate(item)

    async def moderation_queue_resources(
        self,
        bucket: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[QueueResource]:
        page = await self.moderation_queue(bucket, limit=limit, offset=offset)
        return [QueueResource.model_validate(item) for item in page.items]

    async def verification_queue_resources(
        self,
        bucket: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[QueueResource]:
        page = await self.verification_queue(bucket, limit=limit, offset=offset)
        return [QueueResource.model_validate(item) for item in page.items]

    async def activation_ready_resources(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[QueueResource]:
        page = await self.activation_ready(limit=limit, offset=offset)
        return [QueueResource.model_validate(item) for item in page.items]

    async def audit_event_resources(
        self,
        supplier_id: str,
        *,
        event_type: str | None = None,
        actor: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEventResource]:
        page = await self.audit_events(
            supplier_id,
            event_type=event_type,
            actor=actor,
            limit=limit,
            offset=offset,
        )
        return [AuditEventResource.model_validate(item) for item in page.items]
