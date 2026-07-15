import unittest

from fastapi.testclient import TestClient

from supplier_seed import (
    AccessContext,
    GovernanceRole,
    PilotIncidentSeverity,
    PolicyContext,
    SupplierCandidateInput,
    SupplierMode,
    SupplierRegionContext,
    SupplierSeedEngine,
)
from supplier_seed.api.app import create_app


class SupplierSeedPhaseS3ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = PolicyContext(
            region_code="NCR",
            market_code="PH",
            pilot_enabled=True,
            require_region_for_supplier=True,
            require_legal_acceptance_for_manual=True,
            require_moderation_for_seeded_activation=True,
        )
        self.region = SupplierRegionContext(region_code="NCR", market_code="PH")
        self.staff = AccessContext(actor_id="staff.user", role=GovernanceRole.STAFF)
        self.manager = AccessContext(actor_id="manager.user", role=GovernanceRole.MANAGER)
        self.moderator = AccessContext(actor_id="moderator.user", role=GovernanceRole.MODERATOR)
        self.engine = SupplierSeedEngine()
        self.client = TestClient(create_app(self.engine, access_context=self.manager))

    def _enabled_supplier(self) -> str:
        supplier = self.engine.ingest_supplier(
            SupplierCandidateInput(
                name="S3 Pilot Supplier",
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                created_by=self.staff.actor_id,
            ),
            context=self.context,
            access_context=self.staff,
        ).supplier
        supplier_id = supplier.supplier_id
        self.engine.accept_legal(
            supplier_id,
            version="v2026.07",
            actor=self.manager.actor_id,
            context=self.context,
            access_context=self.manager,
        )
        self.engine.submit_for_review(
            supplier_id,
            actor=self.staff.actor_id,
            context=self.context,
            access_context=self.staff,
        )
        self.engine.approve_moderation(
            supplier_id,
            actor=self.moderator.actor_id,
            context=self.context,
            access_context=self.moderator,
        )
        self.engine.activate_supplier(
            supplier_id,
            actor=self.manager.actor_id,
            context=self.context,
            access_context=self.manager,
        )
        self.engine.accept_pilot_terms(
            supplier_id,
            terms_version="pilot-v1",
            actor=self.manager.actor_id,
            access_context=self.manager,
        )
        self.engine.enable_pilot_access(
            supplier_id,
            pilot_name="PH-Alpha",
            terms_version="pilot-v1",
            actor=self.manager.actor_id,
            context=self.context,
            access_context=self.manager,
        )
        return supplier_id

    def test_release_summary_exposes_governed_pilot_kpis_and_gate(self) -> None:
        self._enabled_supplier()
        response = self.client.get("/v1/pilots/PH-Alpha/release-summary")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["pilot_name"], "PH-Alpha")
        self.assertEqual(payload["enabled_supplier_count"], 1)
        self.assertEqual(payload["terms_accepted_count"], 1)
        self.assertTrue(payload["reversible"])
        self.assertGreaterEqual(payload["kpis"]["active_supplier_count"], 1)
        self.assertTrue(payload["expansion_gate"]["ready"])

    def test_incident_list_supports_severity_filter_and_descending_timeline(self) -> None:
        supplier_id = self._enabled_supplier()
        self.engine.log_pilot_incident(
            supplier_id,
            severity=PilotIncidentSeverity.LOW,
            summary="Minor operator delay.",
            actor=self.manager.actor_id,
            access_context=self.manager,
        )
        self.engine.log_pilot_incident(
            supplier_id,
            severity=PilotIncidentSeverity.CRITICAL,
            summary="Critical pilot mismatch.",
            actor=self.manager.actor_id,
            access_context=self.manager,
        )

        response = self.client.get(
            "/v1/pilots/PH-Alpha/incidents",
            params={"severity": "critical"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["page"]["total"], 1)
        self.assertEqual(payload["items"][0]["metadata"]["severity"], "critical")
        self.assertEqual(payload["items"][0]["summary"], "Critical pilot mismatch.")

    def test_staff_context_cannot_view_pilot_internals_but_runbook_is_readable(self) -> None:
        restricted = TestClient(create_app(self.engine, access_context=self.staff))

        summary = restricted.get("/v1/pilots/PH-Alpha/release-summary")
        incidents = restricted.get("/v1/pilots/PH-Alpha/incidents")
        runbook = restricted.get("/v1/pilot/runbook")

        self.assertEqual(summary.status_code, 403)
        self.assertEqual(summary.json()["detail"]["code"], "permission.view_pilot_internals.denied")
        self.assertEqual(incidents.status_code, 403)
        self.assertEqual(runbook.status_code, 200)
        self.assertEqual(runbook.json()["rollback_action"], "disable_pilot_access")
        self.assertEqual(runbook.json()["steps"][0], "accept_pilot_terms")


if __name__ == "__main__":
    unittest.main()
