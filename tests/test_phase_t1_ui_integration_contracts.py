import unittest

from fastapi.testclient import TestClient

from supplier_seed.api.app import create_app
from supplier_seed.engine import SupplierSeedEngine


class SupplierSeedPhaseT1ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app(SupplierSeedEngine()))

    def test_capabilities_manifest_declares_read_only_contract_and_limits(self) -> None:
        response = self.client.get("/v1/capabilities")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["api_version"], "v1")
        self.assertEqual(payload["service_version"], "1.3.0")
        self.assertTrue(payload["enterprise_api_read_only"])
        self.assertEqual(payload["mutation_authority"], "domain_service_only")

        endpoints = {entry["path"]: entry for entry in payload["endpoints"]}
        supplier_list = endpoints["/v1/suppliers"]
        self.assertEqual(supplier_list["method"], "GET")
        self.assertTrue(supplier_list["read_only"])
        self.assertEqual(supplier_list["pagination"]["style"], "offset_limit")
        self.assertEqual(supplier_list["pagination"]["default_limit"], 50)
        self.assertEqual(supplier_list["pagination"]["maximum_limit"], 200)
        self.assertIn("moderation_status", supplier_list["filters"])

        audit = endpoints["/v1/suppliers/{supplier_id}/audit-events"]
        self.assertEqual(audit["sort"], ["occurred_at:desc"])
        self.assertEqual(audit["pagination"]["maximum_limit"], 500)
        self.assertIn("supplier.not_found", payload["error_codes"])

    def test_openapi_exposes_named_response_and_error_contracts(self) -> None:
        schema = self.client.get("/openapi.json").json()
        models = schema["components"]["schemas"]

        for model_name in (
            "CapabilitiesResponse",
            "PaginatedResponse",
            "SupplierDetailResponse",
            "PilotReleaseSummaryResponse",
            "PilotRunbookResponse",
            "ErrorEnvelope",
        ):
            self.assertIn(model_name, models)

        supplier_list_schema = schema["paths"]["/v1/suppliers"]["get"]["responses"]["200"]
        self.assertEqual(
            supplier_list_schema["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/PaginatedResponse",
        )
        supplier_detail_errors = schema["paths"]["/v1/suppliers/{supplier_id}"]["get"]["responses"]
        self.assertEqual(
            supplier_detail_errors["404"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/ErrorEnvelope",
        )

    def test_existing_read_payload_envelopes_remain_compatible(self) -> None:
        suppliers = self.client.get("/v1/suppliers")
        runbook = self.client.get("/v1/pilot/runbook")
        missing = self.client.get("/v1/suppliers/missing")

        self.assertEqual(suppliers.status_code, 200)
        self.assertEqual(set(suppliers.json()), {"api_version", "items", "page"})
        self.assertEqual(
            set(suppliers.json()["page"]),
            {"limit", "offset", "returned", "total"},
        )

        self.assertEqual(runbook.status_code, 200)
        self.assertEqual(
            set(runbook.json()),
            {"api_version", "steps", "rollback_action"},
        )

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"]["code"], "supplier.not_found")


if __name__ == "__main__":
    unittest.main()
