import unittest

from fastapi.testclient import TestClient

from supplier_seed.api.app import create_app
from supplier_seed.domain.enums import SupplierMode
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine


class SupplierSeedPhaseS2ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.region = SupplierRegionContext(region_code="NCR", market_code="PH", pilot_enabled=True)
        self.context = PolicyContext(
            region_code="NCR",
            market_code="PH",
            pilot_enabled=True,
            allow_seeded_supplier_creation=True,
            require_region_for_supplier=True,
            require_legal_acceptance_for_manual=True,
            require_moderation_for_seeded_activation=True,
            require_actor_for_verification_actions=True,
            require_assignment_for_verification_decisions=True,
            require_assignment_match_for_verification_decisions=True,
            require_verified_status_for_visible_verification=True,
        )
        self.engine = SupplierSeedEngine(policy_engine=SupplierPolicyEngine())
        self.client = TestClient(create_app(self.engine))

    def _ingest_manual(self, name: str):
        return self.engine.ingest_supplier(
            SupplierCandidateInput(
                name=name,
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                tax_identifier=f"PH-{name.replace(' ', '-').upper()}",
                created_by="api-test",
            ),
            context=self.context,
        ).supplier

    def _approve_manual(self, name: str):
        supplier = self._ingest_manual(name)
        self.engine.accept_legal(
            supplier.supplier_id,
            version="v2026.07",
            actor="legal-officer",
            context=self.context,
        )
        self.engine.submit_for_review(
            supplier.supplier_id,
            actor="reviewer",
            context=self.context,
        )
        self.engine.approve_moderation(
            supplier.supplier_id,
            actor="reviewer",
            context=self.context,
        )
        return self.engine.get_supplier(supplier.supplier_id)

    def test_moderation_pending_queue_exposes_read_model_contract(self) -> None:
        supplier = self._ingest_manual("Pending Queue Supplier")
        self.engine.submit_for_review(supplier.supplier_id, actor="reviewer", context=self.context)

        response = self.client.get("/v1/queues/moderation/pending_review")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["page"]["total"], 1)
        self.assertEqual(payload["items"][0]["supplier_id"], supplier.supplier_id)
        self.assertEqual(payload["items"][0]["queue_bucket"], "pending_review")
        self.assertEqual(payload["items"][0]["primary_queue"], "supplier_review")
        self.assertEqual(payload["items"][0]["next_step"], "review_supplier")

    def test_activation_ready_and_verification_eligible_queues_share_approved_supplier(self) -> None:
        supplier = self._approve_manual("Approved Queue Supplier")

        activation_response = self.client.get("/v1/queues/activation-ready")
        verification_response = self.client.get("/v1/queues/verification/eligible")

        self.assertEqual(activation_response.status_code, 200)
        self.assertEqual(verification_response.status_code, 200)
        self.assertEqual(activation_response.json()["items"][0]["supplier_id"], supplier.supplier_id)
        self.assertEqual(activation_response.json()["items"][0]["next_step"], "activate_supplier")
        self.assertEqual(verification_response.json()["items"][0]["supplier_id"], supplier.supplier_id)
        self.assertEqual(verification_response.json()["items"][0]["verification_status"], "not_verified")

    def test_audit_timeline_supports_event_type_and_actor_filters(self) -> None:
        supplier = self._approve_manual("Audit API Supplier")

        response = self.client.get(
            f"/v1/suppliers/{supplier.supplier_id}/audit-events",
            params={"event_type": "moderation_approved", "actor": "reviewer"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["page"]["total"], 1)
        self.assertEqual(payload["items"][0]["event_type"], "moderation_approved")
        self.assertEqual(payload["items"][0]["actor"], "reviewer")
        self.assertEqual(payload["items"][0]["supplier_id"], supplier.supplier_id)

    def test_invalid_queue_bucket_and_missing_supplier_use_stable_error_contracts(self) -> None:
        invalid_queue = self.client.get("/v1/queues/moderation/unknown")
        missing_audit = self.client.get("/v1/suppliers/missing/audit-events")

        self.assertEqual(invalid_queue.status_code, 400)
        self.assertEqual(invalid_queue.json()["detail"]["code"], "queue.invalid_bucket")
        self.assertEqual(missing_audit.status_code, 404)
        self.assertEqual(missing_audit.json()["detail"]["code"], "supplier.not_found")


if __name__ == "__main__":
    unittest.main()
