import unittest

from fastapi.testclient import TestClient

from supplier_seed.api.app import create_app
from supplier_seed.domain.enums import SupplierMode
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine


class SupplierSeedPhaseSTests(unittest.TestCase):
    def setUp(self) -> None:
        self.region = SupplierRegionContext(region_code="NCR", market_code="PH", pilot_enabled=True)
        self.policy_context = PolicyContext(
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
        self.alpha = self.engine.ingest_supplier(
            SupplierCandidateInput(
                name="Alpha Office Supply",
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                contact_email="alpha@example.com",
                tax_identifier="PH-S-0001",
                created_by="operator",
            ),
            context=self.policy_context,
        ).supplier
        self.beta = self.engine.ingest_supplier(
            SupplierCandidateInput(
                name="Beta Wholesale",
                mode=SupplierMode.SEEDED,
                region_context=self.region,
                seeded_source="pilot-catalogue",
                seeded_source_reference="BETA-001",
                tax_identifier="PH-S-0002",
                created_by="operator",
            ),
            context=self.policy_context,
        ).supplier
        self.client = TestClient(create_app(self.engine))

    def test_supplier_list_is_versioned_sorted_and_paginated(self) -> None:
        response = self.client.get("/v1/suppliers", params={"limit": 1, "offset": 0})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["api_version"], "v1")
        self.assertEqual(payload["page"], {"limit": 1, "offset": 0, "returned": 1, "total": 2})
        self.assertEqual(payload["items"][0]["name"], "Alpha Office Supply")

    def test_supplier_list_supports_search_region_mode_and_source_filters(self) -> None:
        response = self.client.get(
            "/v1/suppliers",
            params={
                "search": "beta",
                "region_code": "NCR",
                "mode": "seeded",
                "seeded_source": "pilot-catalogue",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["page"]["total"], 1)
        self.assertEqual(payload["items"][0]["supplier_id"], self.beta.supplier_id)

    def test_supplier_detail_returns_stable_read_contract_and_404(self) -> None:
        response = self.client.get(f"/v1/suppliers/{self.alpha.supplier_id}")
        self.assertEqual(response.status_code, 200)
        supplier = response.json()["supplier"]
        self.assertEqual(supplier["supplier_id"], self.alpha.supplier_id)
        self.assertEqual(supplier["contact_email"], "alpha@example.com")
        self.assertEqual(supplier["region_context"]["market_code"], "PH")
        self.assertIn("legal_acceptance_state", supplier)
        self.assertIn("verification_visibility", supplier)

        missing = self.client.get("/v1/suppliers/missing-supplier")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"]["code"], "supplier.not_found")


if __name__ == "__main__":
    unittest.main()
