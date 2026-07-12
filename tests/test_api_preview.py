import unittest

from fastapi.testclient import TestClient

from supplier_seed.api.app import app


class SupplierSeedApiPreviewTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "ok", "service": "invyra-supplier-seed"},
        )

    def test_preview_endpoint_does_not_persist_and_returns_bridge_contract(self):
        response = self.client.post(
            "/supplier-seed/ingest/preview",
            json={
                "candidate": {
                    "name": "Example Supplier",
                    "mode": "manual",
                    "region_context": {
                        "region_code": "NCR",
                        "market_code": "PH",
                        "pilot_enabled": True,
                    },
                    "contact_email": "hello@example.test",
                    "created_by": "base44-prototype",
                },
                "existing_suppliers": [],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["bridge_mode"], "api")
        self.assertFalse(payload["persisted"])
        self.assertTrue(payload["accepted_for_staging"])
        self.assertEqual(
            payload["source_of_truth"],
            "chrykoolaid/invyra-seed-supplier",
        )

    def test_preview_endpoint_surfaces_duplicate_decision(self):
        response = self.client.post(
            "/supplier-seed/ingest/preview",
            json={
                "candidate": {
                    "name": "ChemSupply Company",
                    "mode": "manual",
                    "region_context": {
                        "region_code": "NCR",
                        "market_code": "PH",
                    },
                    "contact_email": "alan@chemsupply.com",
                },
                "existing_suppliers": [
                    {
                        "id": "SUP-001",
                        "name": "ChemSupply Co",
                        "email": "alan@chemsupply.com",
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(
            payload["outcome"],
            {"blocked", "requires_review", "warning"},
        )
        self.assertTrue(payload["decisions"])


if __name__ == "__main__":
    unittest.main()
