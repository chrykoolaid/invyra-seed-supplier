import unittest

from fastapi.testclient import TestClient

from supplier_seed.api.app import create_app
from supplier_seed.domain.enums import SupplierMode
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput
from supplier_seed.policy.rules import PolicyContext
from supplier_seed.sdk import (
    AuditEventResource,
    QueueResource,
    SupplierDetailResource,
    SupplierSummaryResource,
)


class SupplierSeedPhaseT5TypedResourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SupplierSeedEngine()
        self.context = PolicyContext(region_code="NCR", market_code="PH", pilot_enabled=True)
        self.region = SupplierRegionContext(region_code="NCR", market_code="PH")
        self.http = TestClient(create_app(self.engine))
        self.supplier = self.engine.ingest_supplier(
            SupplierCandidateInput(
                name="Typed SDK Supplier",
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                tax_identifier="PH-TYPED-SDK",
                created_by="typed-sdk-test",
            ),
            context=self.context,
        ).supplier

    def test_supplier_summary_and_detail_payloads_validate_as_typed_resources(self) -> None:
        summary_payload = self.http.get("/v1/suppliers").json()["items"][0]
        detail_payload = self.http.get(f"/v1/suppliers/{self.supplier.supplier_id}").json()["supplier"]

        summary = SupplierSummaryResource.model_validate(summary_payload)
        detail = SupplierDetailResource.model_validate(detail_payload)

        self.assertEqual(summary.supplier_id, self.supplier.supplier_id)
        self.assertEqual(summary.market_code, "PH")
        self.assertEqual(detail.name, "Typed SDK Supplier")
        self.assertEqual(detail.tax_identifier, "PH-TYPED-SDK")
        self.assertIsNotNone(detail.created_at)

    def test_queue_payload_validates_as_typed_resource(self) -> None:
        self.engine.submit_for_review(
            self.supplier.supplier_id,
            actor="typed-reviewer",
            context=self.context,
        )
        payload = self.http.get("/v1/queues/moderation/pending_review").json()["items"][0]

        resource = QueueResource.model_validate(payload)

        self.assertEqual(resource.supplier_id, self.supplier.supplier_id)
        self.assertEqual(resource.queue_bucket, "pending_review")
        self.assertEqual(resource.next_step, "review_supplier")

    def test_audit_payload_validates_datetime_and_metadata(self) -> None:
        payload = self.http.get(
            f"/v1/suppliers/{self.supplier.supplier_id}/audit-events"
        ).json()["items"][0]

        resource = AuditEventResource.model_validate(payload)

        self.assertEqual(resource.supplier_id, self.supplier.supplier_id)
        self.assertEqual(resource.event_type, "supplier_staged")
        self.assertIsNotNone(resource.occurred_at)
        self.assertIsInstance(resource.metadata, dict)


if __name__ == "__main__":
    unittest.main()
