import unittest

from fastapi.testclient import TestClient

from supplier_seed.api.app import create_app
from supplier_seed.domain.enums import SupplierMode
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput
from supplier_seed.policy.rules import PolicyContext
from supplier_seed.sdk import SupplierSeedReadClient


class SupplierSeedPhaseT3SdkPaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SupplierSeedEngine()
        self.context = PolicyContext(region_code="NCR", market_code="PH", pilot_enabled=True)
        self.region = SupplierRegionContext(region_code="NCR", market_code="PH")
        self.client = SupplierSeedReadClient(transport=TestClient(create_app(self.engine)))

    def _ingest(self, name: str, tax_id: str):
        return self.engine.ingest_supplier(
            SupplierCandidateInput(
                name=name,
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                tax_identifier=tax_id,
                created_by="phase-t3",
            ),
            context=self.context,
        ).supplier

    def test_moderation_iterator_consumes_all_offset_pages(self) -> None:
        for index, name in enumerate(("Alpha T3", "Beta T3", "Gamma T3"), start=1):
            supplier = self._ingest(name, f"PH-T3-{index}")
            self.engine.submit_for_review(
                supplier.supplier_id,
                actor="phase-t3-reviewer",
                context=self.context,
            )

        items = list(self.client.iter_moderation_queue("pending_review", page_size=2))

        self.assertEqual(len(items), 3)
        self.assertEqual([item["name"] for item in items], ["Alpha T3", "Beta T3", "Gamma T3"])

    def test_audit_iterator_preserves_filters_across_pages(self) -> None:
        supplier = self._ingest("Audit T3", "PH-T3-AUDIT")
        self.engine.submit_for_review(
            supplier.supplier_id,
            actor="phase-t3-reviewer",
            context=self.context,
        )

        items = list(
            self.client.iter_audit_events(
                supplier.supplier_id,
                actor="phase-t3-reviewer",
                page_size=1,
            )
        )

        self.assertGreaterEqual(len(items), 1)
        self.assertTrue(all(item["actor"] == "phase-t3-reviewer" for item in items))

    def test_iterators_reject_invalid_page_size_before_request(self) -> None:
        with self.assertRaisesRegex(ValueError, "page_size must be at least 1"):
            list(self.client.iter_suppliers(page_size=0))


if __name__ == "__main__":
    unittest.main()
