import unittest

import httpx

from supplier_seed.api.app import create_app
from supplier_seed.domain.enums import SupplierMode
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput
from supplier_seed.policy.rules import PolicyContext
from supplier_seed.sdk import SupplierSeedApiError, SupplierSeedAsyncReadClient


class SupplierSeedPhaseT4AsyncSdkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = SupplierSeedEngine()
        self.context = PolicyContext(region_code="NCR", market_code="PH", pilot_enabled=True)
        self.region = SupplierRegionContext(region_code="NCR", market_code="PH")
        transport = httpx.ASGITransport(app=create_app(self.engine))
        self.http = httpx.AsyncClient(transport=transport, base_url="http://supplier-seed.test")
        self.client = SupplierSeedAsyncReadClient(transport=self.http)

    async def asyncTearDown(self) -> None:
        await self.http.aclose()

    def _ingest(self, name: str, tax_id: str):
        return self.engine.ingest_supplier(
            SupplierCandidateInput(
                name=name,
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                tax_identifier=tax_id,
                created_by="async-sdk-test",
            ),
            context=self.context,
        ).supplier

    async def test_async_client_returns_typed_capabilities_and_runbook(self) -> None:
        capabilities = await self.client.capabilities()
        runbook = await self.client.pilot_runbook()

        self.assertEqual(capabilities.api_version, "v1")
        self.assertTrue(capabilities.enterprise_api_read_only)
        self.assertEqual(runbook.rollback_action, "disable_pilot_access")

    async def test_async_supplier_iterator_consumes_all_pages(self) -> None:
        self._ingest("Alpha Async Supplier", "PH-ASYNC-A")
        self._ingest("Beta Async Supplier", "PH-ASYNC-B")
        self._ingest("Gamma Async Supplier", "PH-ASYNC-C")

        items = [item async for item in self.client.iter_suppliers(page_size=2)]

        self.assertEqual(
            [item["name"] for item in items],
            ["Alpha Async Supplier", "Beta Async Supplier", "Gamma Async Supplier"],
        )

    async def test_async_client_preserves_governed_error_contract(self) -> None:
        with self.assertRaises(SupplierSeedApiError) as captured:
            await self.client.get_supplier("missing-supplier")

        self.assertEqual(captured.exception.status_code, 404)
        self.assertEqual(captured.exception.code, "supplier.not_found")

    async def test_async_iterator_rejects_invalid_page_size_before_request(self) -> None:
        iterator = self.client.iter_suppliers(page_size=0)
        with self.assertRaisesRegex(ValueError, "page_size must be at least 1"):
            await anext(iterator)


if __name__ == "__main__":
    unittest.main()
