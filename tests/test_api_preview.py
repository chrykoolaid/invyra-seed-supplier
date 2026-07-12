from fastapi.testclient import TestClient

from supplier_seed.api.app import app


client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "invyra-supplier-seed"}


def test_preview_endpoint_does_not_persist_and_returns_bridge_contract():
    response = client.post(
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

    assert response.status_code == 200
    payload = response.json()
    assert payload["bridge_mode"] == "api"
    assert payload["persisted"] is False
    assert payload["accepted_for_staging"] is True
    assert payload["source_of_truth"] == "chrykoolaid/invyra-seed-supplier"


def test_preview_endpoint_surfaces_duplicate_decision():
    response = client.post(
        "/supplier-seed/ingest/preview",
        json={
            "candidate": {
                "name": "ChemSupply Company",
                "mode": "manual",
                "region_context": {"region_code": "NCR", "market_code": "PH"},
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

    assert response.status_code == 200
    payload = response.json()
    assert payload["outcome"] in {"blocked", "requires_review", "warning"}
    assert payload["decisions"]
