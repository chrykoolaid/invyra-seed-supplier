import unittest

import httpx
from fastapi.testclient import TestClient

from supplier_seed.api.app import create_app
from supplier_seed.domain.enums import SupplierMode
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput
from supplier_seed.policy.rules import PolicyContext
from supplier_seed.sdk import (
    AuditEventResource,
    SupplierDetailResource,
    SupplierSeedAsyncTypedReadClient,
    SupplierSeedTypedReadClient,
    SupplierSummaryResource,
)


class SupplierSeedPhaseT6TypedClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SupplierSeedEngine()
        self.context = PolicyContext(region_code="NCR", market_code="PH", pilot_enabled=True)
        self.region = SupplierRegionContext(region_code="NCR", market_code="PH")
        self.client = SupplierSeedTypedReadClient(
            transport=TestClient(create_app(self.engine))
        )
        self.supplier = self.engine.ingest_supplier(
            SupplierCandidateInput(
                name="Typed Client Supplier",
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                tax_identifier="PH-TYPED-CLIENT",
                created_by="typed-client-test",
            ),
            context=self.context,
        ).supplier

    def test_sync_typed_client_returns_resource_models(self) -> None:
        detail = self.client.get_supplier_resource(self.supplier.supplier_id)
        summaries = self.client.list_supplier_resources(search="Typed Client")
        audit = self.client.audit_event_resources(self.supplier.supplier_id)

        self.assertIsInstance(detail, SupplierDetailResource)
        self.assertIsInstance(summaries[0], SupplierSummaryResource)
        self.assertIsInstance(audit[0], AuditEventResource)
        self.assertEqual(detail.tax_identifier, "PH-TYPED-CLIENT")

    def test_sync_typed_iterator_preserves_pagination(self) -> None:
        for index in range(2):
            self.engine.ingest_supplier(
                SupplierCandidateInput(
                    name=f"Typed Page Supplier {index}",
                    mode=SupplierMode.MANUAL,
                    region_context=self.region,
                    tax_identifier=f"PH-TYPED-PAGE-{index}",
                    created_by="typed-client-test",
                ),
                context=self.context,
            )

        resources = list(self.client.iter_supplier_resources(page_size=1))

        self.assertEqual(len(resources), 3)
        self.assertTrue(all(isinstance(item, SupplierSummaryResource) for item in resources))


class SupplierSeedPhaseT6AsyncTypedClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = SupplierSeedEngine()
        self.context = PolicyContext(region_code="NCR", market_code="PH", pilot_enabled=True)
        self.region = SupplierRegionContext(region_code="NCR", market_code="PH")
        transport = httpx.ASGITransport(app=create_app(self.engine))
        self.http = httpx.AsyncClient(transport=transport, base_url="http://supplier-seed.test")
        self.client = SupplierSeedAsyncTypedReadClient(transport=self.http)
        self.supplier = self.engine.ingest_supplier(
            SupplierCandidateInput(
                name="Async Typed Client Supplier",
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                tax_identifier="PH-ASYNC-TYPED-CLIENT",
                created_by="async-typed-client-test",
            ),
            context=self.context,
        ).supplier

    async def asyncTearDown(self) -> None:
        await self.http.aclose()

    async def test_async_typed_client_returns_resource_models(self) -> None:
        detail = await self.client.get_supplier_resource(self.supplier.supplier_id)
        summaries = await self.client.list_supplier_resources(search="Async Typed")
        resources = [item async for item in self.client.iter_supplier_resources(page_size=1)]

        self.assertIsInstance(detail, SupplierDetailResource)
        self.assertIsInstance(summaries[0], SupplierSummaryResource)
        self.assertIsInstance(resources[0], SupplierSummaryResource)


if __name__ == "__main__":
    unittest.main()
