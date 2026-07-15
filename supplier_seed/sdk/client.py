from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping, Protocol

import httpx

from supplier_seed.api.contracts import (
    CapabilitiesResponse,
    PaginatedResponse,
    PilotReleaseSummaryResponse,
    PilotRunbookResponse,
    SupplierDetailResponse,
)


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...


class HttpTransport(Protocol):
    def get(self, url: str, *, params: Mapping[str, Any] | None = None) -> HttpResponse: ...


@dataclass(frozen=True)
class SupplierSeedApiError(RuntimeError):
    status_code: int
    code: str
    detail: Mapping[str, Any]

    def __str__(self) -> str:
        return f"Supplier Seed API error {self.status_code}: {self.code}"


class SupplierSeedReadClient:
    """Typed, read-only client for the Supplier Seed v1 enterprise API."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        transport: HttpTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        if transport is None and not base_url:
            raise ValueError("base_url is required when transport is not supplied")
        self._owns_transport = transport is None
        self._transport: HttpTransport = transport or httpx.Client(
            base_url=str(base_url).rstrip("/"),
            timeout=timeout,
        )

    def close(self) -> None:
        if self._owns_transport and hasattr(self._transport, "close"):
            self._transport.close()  # type: ignore[attr-defined]

    def __enter__(self) -> "SupplierSeedReadClient":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        response = self._transport.get(path, params=params)
        payload = response.json()
        if response.status_code >= 400:
            detail = payload.get("detail", payload) if isinstance(payload, dict) else {"message": str(payload)}
            code = str(detail.get("code", "api.error"))
            raise SupplierSeedApiError(response.status_code, code, detail)
        return payload

    def _iter_pages(
        self,
        fetch_page: Callable[..., PaginatedResponse],
        *,
        page_size: int,
        **filters: Any,
    ) -> Iterator[dict[str, Any]]:
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        offset = 0
        while True:
            page = fetch_page(limit=page_size, offset=offset, **filters)
            yield from page.items
            offset += page.page.returned
            if page.page.returned == 0 or offset >= page.page.total:
                return

    def capabilities(self) -> CapabilitiesResponse:
        return CapabilitiesResponse.model_validate(self._get("/v1/capabilities"))

    def get_supplier(self, supplier_id: str) -> SupplierDetailResponse:
        return SupplierDetailResponse.model_validate(self._get(f"/v1/suppliers/{supplier_id}"))

    def list_suppliers(
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
        return PaginatedResponse.model_validate(self._get("/v1/suppliers", params))

    def iter_suppliers(self, *, page_size: int = 200, **filters: Any) -> Iterator[dict[str, Any]]:
        return self._iter_pages(self.list_suppliers, page_size=page_size, **filters)

    def moderation_queue(self, bucket: str, *, limit: int = 50, offset: int = 0) -> PaginatedResponse:
        return PaginatedResponse.model_validate(
            self._get(f"/v1/queues/moderation/{bucket}", {"limit": limit, "offset": offset})
        )

    def iter_moderation_queue(self, bucket: str, *, page_size: int = 200) -> Iterator[dict[str, Any]]:
        return self._iter_pages(
            lambda *, limit, offset: self.moderation_queue(bucket, limit=limit, offset=offset),
            page_size=page_size,
        )

    def verification_queue(self, bucket: str, *, limit: int = 50, offset: int = 0) -> PaginatedResponse:
        return PaginatedResponse.model_validate(
            self._get(f"/v1/queues/verification/{bucket}", {"limit": limit, "offset": offset})
        )

    def iter_verification_queue(self, bucket: str, *, page_size: int = 200) -> Iterator[dict[str, Any]]:
        return self._iter_pages(
            lambda *, limit, offset: self.verification_queue(bucket, limit=limit, offset=offset),
            page_size=page_size,
        )

    def activation_ready(self, *, limit: int = 50, offset: int = 0) -> PaginatedResponse:
        return PaginatedResponse.model_validate(
            self._get("/v1/queues/activation-ready", {"limit": limit, "offset": offset})
        )

    def iter_activation_ready(self, *, page_size: int = 200) -> Iterator[dict[str, Any]]:
        return self._iter_pages(self.activation_ready, page_size=page_size)

    def audit_events(
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
            self._get(f"/v1/suppliers/{supplier_id}/audit-events", params)
        )

    def iter_audit_events(
        self,
        supplier_id: str,
        *,
        event_type: str | None = None,
        actor: str | None = None,
        page_size: int = 500,
    ) -> Iterator[dict[str, Any]]:
        return self._iter_pages(
            lambda *, limit, offset, **filters: self.audit_events(
                supplier_id,
                limit=limit,
                offset=offset,
                **filters,
            ),
            page_size=page_size,
            event_type=event_type,
            actor=actor,
        )

    def pilot_release_summary(self, pilot_name: str) -> PilotReleaseSummaryResponse:
        return PilotReleaseSummaryResponse.model_validate(
            self._get(f"/v1/pilots/{pilot_name}/release-summary")
        )

    def pilot_incidents(
        self,
        pilot_name: str,
        *,
        severity: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> PaginatedResponse:
        params = _clean_params({"severity": severity, "limit": limit, "offset": offset})
        return PaginatedResponse.model_validate(
            self._get(f"/v1/pilots/{pilot_name}/incidents", params)
        )

    def iter_pilot_incidents(
        self,
        pilot_name: str,
        *,
        severity: str | None = None,
        page_size: int = 500,
    ) -> Iterator[dict[str, Any]]:
        return self._iter_pages(
            lambda *, limit, offset, **filters: self.pilot_incidents(
                pilot_name,
                limit=limit,
                offset=offset,
                **filters,
            ),
            page_size=page_size,
            severity=severity,
        )

    def pilot_runbook(self) -> PilotRunbookResponse:
        return PilotRunbookResponse.model_validate(self._get("/v1/pilot/runbook"))


def _clean_params(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}
