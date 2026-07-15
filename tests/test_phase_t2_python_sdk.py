import unittest

from fastapi.testclient import TestClient

from supplier_seed.api.app import create_app
from supplier_seed.domain.enums import SupplierMode
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput
from supplier_seed.policy.rules import PolicyContext
from supplier_seed.sdk import SupplierSeedApiError, SupplierSeedReadClient


class SupplierSeedPhaseT2PythonSdkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SupplierSeedEngine()
        self.context = PolicyContext(region_code="NCR", market_code="PH", pilot_enabled=True)
        self.region = SupplierRegionContext(region_code="NCR", market_code="PH")
        self.http = TestClient(create_app(self.engine))
        self.client = SupplierSeedReadClient(transport=self.http)

    def _ingest(self, name: str, tax_id: str):
        return self.engine.ingest_supplier(
            SupplierCandidateInput(
                name=name,
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                tax_identifier=tax_id,
                created_by="sdk-test",
            ),
            context=self.context,
        ).supplier

    def test_capabilities_and_runbook_are_returned_as_typed_contracts(self) -> None:
        capabilities = self.client.capabilities()
        runbook = self.client.pilot_runbook()

        self.assertEqual(capabilities.api_version, "v1")
        self.assertTrue(capabilities.enterprise_api_read_only)
        self.assertEqual(capabilities.mutation_authority, "domain_service_only")
        self.assertIn("/v1/suppliers", {endpoint.path for endpoint in capabilities.endpoints})
        self.assertEqual(runbook.rollback_action, "disable_pilot_access")
        self.assertEqual(runbook.steps[0], "accept_pilot_terms")

    def test_list_and_get_supplier_validate_existing_v1_payloads(self) -> None:
        supplier = self._ingest("SDK Detail Supplier", "PH-SDK-DETAIL")

        page = self.client.list_suppliers(search="SDK Detail", region_code="NCR")
        detail = self.client.get_supplier(supplier.supplier_id)

        self.assertEqual(page.page.total, 1)
        self.assertEqual(page.items[0]["supplier_id"], supplier.supplier_id)
        self.assertEqual(detail.supplier["supplier_id"], supplier.supplier_id)
        self.assertEqual(detail.supplier["name"], "SDK Detail Supplier")

    def test_iter_suppliers_automatically_consumes_offset_pages(self) -> None:
        self._ingest("Alpha SDK Supplier", "PH-SDK-A")
        self._ingest("Beta SDK Supplier", "PH-SDK-B")
        self._ingest("Gamma SDK Supplier", "PH-SDK-C")

        items = list(self.client.iter_suppliers(page_size=2))

        self.assertEqual(len(items), 3)
        self.assertEqual(
            [item["name"] for item in items],
            ["Alpha SDK Supplier", "Beta SDK Supplier", "Gamma SDK Supplier"],
        )

    def test_governed_error_envelope_becomes_stable_sdk_exception(self) -> None:
        with self.assertRaises(SupplierSeedApiError) as captured:
            self.client.get_supplier("missing-supplier")

        error = captured.exception
        self.assertEqual(error.status_code, 404)
        self.assertEqual(error.code, "supplier.not_found")
        self.assertEqual(error.detail["supplier_id"], "missing-supplier")

    def test_queue_and_audit_helpers_preserve_pagination_contract(self) -> None:
        supplier = self._ingest("SDK Queue Supplier", "PH-SDK-QUEUE")
        self.engine.submit_for_review(supplier.supplier_id, actor="reviewer", context=self.context)

        queue = self.client.moderation_queue("pending_review", limit=10)
        audit = self.client.audit_events(supplier.supplier_id, actor="reviewer")

        self.assertEqual(queue.page.total, 1)
        self.assertEqual(queue.items[0]["supplier_id"], supplier.supplier_id)
        self.assertGreaterEqual(audit.page.total, 1)
        self.assertTrue(all(item["actor"] == "reviewer" for item in audit.items))


if __name__ == "__main__":
    unittest.main()
