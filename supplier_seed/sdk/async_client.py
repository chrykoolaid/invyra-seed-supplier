from __future__ import annotations

from typing import Any, AsyncIterator, Mapping, Protocol

import httpx

from supplier_seed.api.contracts import (
    CapabilitiesResponse,
    PaginatedResponse,
    PilotReleaseSummaryResponse,
    PilotRunbookResponse,
    SupplierDetailResponse,
)
from supplier_seed.sdk.client import SupplierSeedApiError


class AsyncHttpResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...


class AsyncHttpTransport(Protocol):
    async def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> AsyncHttpResponse: ...


class SupplierSeedAsyncReadClient:
    """Typed, asynchronous, read-only client for the Supplier Seed v1 API."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        transport: AsyncHttpTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        if transport is None and not base_url:
            raise ValueError("base_url is required when transport is not supplied")
        self._owns_transport = transport is None
        self._transport: AsyncHttpTransport = transport or httpx.AsyncClient(
            base_url=str(base_url).rstrip("/"),
            timeout=timeout,
        )

    async def close(self) -> None:
        if self._owns_transport and hasattr(self._transport, "aclose"):
            await self._transport.aclose()  # type: ignore[attr-defined]

    async def __aenter__(self) -> "SupplierSeedAsyncReadClient":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.close()

    async def _get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        response = await self._transport.get(path, params=params)
        payload = response.json()
        if response.status_code >= 400:
            detail = payload.get("detail", payload) if isinstance(payload, dict) else {"message": str(payload)}
            code = str(detail.get("code", "api.error"))
            raise SupplierSeedApiError(response.status_code, code, detail)
        return payload

    async def capabilities(self) -> CapabilitiesResponse:
        return CapabilitiesResponse.model_validate(await self._get("/v1/capabilities"))

    async def get_supplier(self, supplier_id: str) -> SupplierDetailResponse:
        return SupplierDetailResponse.model_validate(await self._get(f"/v1/suppliers/{supplier_id}"))

    async def list_suppliers(
        self,
        *,
        search: str | None = None,
        region_code: str | None = None,
        mode: str | None = None,
        seeded_source: str | None = None,
        lifecycle_status: str | None = None,
        moderation_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PaginatedResponse:
        params = _clean_params(
            {
                "search": search,
                "region_code": region_code,
                "mode": mode,
                "seeded_source": seeded_source,
                "lifecycle_status": lifecycle_status,
                "moderation_status": moderation_status,
                "limit": limit,
                "offset": offset,
            }
        )
        return PaginatedResponse.model_validate(await self._get("/v1/suppliers", params))

    async def iter_suppliers(self, *, page_size: int = 200, **filters: Any) -> AsyncIterator[dict[str, Any]]:
        async for item in self._iterate_pages(
            lambda offset: self.list_suppliers(limit=page_size, offset=offset, **filters),
            page_size,
        ):
            yield item

    async def moderation_queue(self, bucket: str, *, limit: int = 50, offset: int = 0) -> PaginatedResponse:
        return PaginatedResponse.model_validate(
            await self._get(f"/v1/queues/moderation/{bucket}", {"limit": limit, "offset": offset})
        )

    async def verification_queue(self, bucket: str, *, limit: int = 50, offset: int = 0) -> PaginatedResponse:
        return PaginatedResponse.model_validate(
            await self._get(f"/v1/queues/verification/{bucket}", {"limit": limit, "offset": offset})
        )

    async def activation_ready(self, *, limit: int = 50, offset: int = 0) -> PaginatedResponse:
        return PaginatedResponse.model_validate(
            await self._get("/v1/queues/activation-ready", {"limit": limit, "offset": offset})
        )

    async def audit_events(
        self,
        supplier_id: str,
        *,
        event_type: str | None = None,
        actor: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> PaginatedResponse:
        params = _clean_params(
            {"event_type": event_type, "actor": actor, "limit": limit, "offset": offset}
        )
        return PaginatedResponse.model_validate(
            await self._get(f"/v1/suppliers/{supplier_id}/audit-events", params)
        )

    async def pilot_release_summary(self, pilot_name: str) -> PilotReleaseSummaryResponse:
        return PilotReleaseSummaryResponse.model_validate(
            await self._get(f"/v1/pilots/{pilot_name}/release-summary")
        )

    async def pilot_incidents(
        self,
        pilot_name: str,
        *,
        severity: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> PaginatedResponse:
        params = _clean_params({"severity": severity, "limit": limit, "offset": offset})
        return PaginatedResponse.model_validate(
            await self._get(f"/v1/pilots/{pilot_name}/incidents", params)
        )

    async def pilot_runbook(self) -> PilotRunbookResponse:
        return PilotRunbookResponse.model_validate(await self._get("/v1/pilot/runbook"))

    async def _iterate_pages(self, fetch_page, page_size: int) -> AsyncIterator[dict[str, Any]]:
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        offset = 0
        while True:
            page = await fetch_page(offset)
            for item in page.items:
                yield item
            offset += page.page.returned
            if page.page.returned == 0 or offset >= page.page.total:
                return


def _clean_params(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}
