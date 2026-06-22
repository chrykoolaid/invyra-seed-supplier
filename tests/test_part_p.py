from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from supplier_seed import (
    AccessContext,
    GovernanceEventType,
    GovernanceRole,
    JsonFileSupplierRepository,
    PilotIncidentSeverity,
    PolicyContext,
    SupplierCandidateInput,
    SupplierMode,
    SupplierPolicyEngine,
    SupplierRegionContext,
    SupplierSeedEngine,
)


class SupplierSeedPartPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy_engine = SupplierPolicyEngine()
        self.ph_context = PolicyContext(
            region_code="NCR",
            market_code="PH",
            pilot_enabled=True,
            require_region_for_supplier=True,
            require_legal_acceptance_for_manual=True,
            require_moderation_for_seeded_activation=True,
        )
        self.ph_region = SupplierRegionContext(region_code="NCR", market_code="PH")
        self.us_region = SupplierRegionContext(region_code="CA", market_code="US")
        self.staff = AccessContext(actor_id="staff.user", role=GovernanceRole.STAFF)
        self.manager = AccessContext(actor_id="manager.user", role=GovernanceRole.MANAGER)
        self.moderator = AccessContext(actor_id="moderator.user", role=GovernanceRole.MODERATOR)
        self.admin = AccessContext(actor_id="admin.user", role=GovernanceRole.ADMIN)

    def _repo_path(self, root: str) -> Path:
        return Path(root) / "supplier-seed.json"

    def _engine_for_path(self, root: str) -> SupplierSeedEngine:
        return SupplierSeedEngine(
            repository=JsonFileSupplierRepository(self._repo_path(root)),
            policy_engine=self.policy_engine,
        )

    def _manual_candidate(self, name: str, *, region: SupplierRegionContext | None = None) -> SupplierCandidateInput:
        return SupplierCandidateInput(
            name=name,
            mode=SupplierMode.MANUAL,
            region_context=region or self.ph_region,
            created_by=self.staff.actor_id,
        )

    def _active_manual_supplier(self, engine: SupplierSeedEngine, *, name: str) -> str:
        supplier_id = engine.ingest_supplier(
            self._manual_candidate(name),
            context=self.ph_context,
            access_context=self.staff,
        ).supplier.identity.supplier_id
        engine.accept_legal(
            supplier_id,
            version="v2026.04",
            actor=self.manager.actor_id,
            context=self.ph_context,
            access_context=self.manager,
        )
        engine.submit_for_review(
            supplier_id,
            actor=self.staff.actor_id,
            context=self.ph_context,
            access_context=self.staff,
        )
        engine.approve_moderation(
            supplier_id,
            actor=self.moderator.actor_id,
            context=self.ph_context,
            access_context=self.moderator,
        )
        engine.activate_supplier(
            supplier_id,
            actor=self.manager.actor_id,
            context=self.ph_context,
            access_context=self.manager,
        )
        return supplier_id

    def test_accept_pilot_terms_tracks_consent_and_persists_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = self._engine_for_path(tmpdir)
            supplier_id = self._active_manual_supplier(engine, name="Pilot Terms Supplier")

            result = engine.accept_pilot_terms(
                supplier_id,
                terms_version="pilot-v1",
                actor=self.manager.actor_id,
                access_context=self.manager,
            )

            self.assertTrue(result.allowed)
            self.assertEqual(result.supplier.pilot_terms_accepted_version, "pilot-v1")
            self.assertEqual(result.supplier.pilot_terms_accepted_by, self.manager.actor_id)
            self.assertEqual(result.events[-1].event_type, GovernanceEventType.PILOT_TERMS_ACCEPTED)

            reloaded = engine.get_supplier_record(supplier_id)
            self.assertEqual(reloaded.pilot_terms_accepted_version, "pilot-v1")
            self.assertEqual(reloaded.pilot_terms_accepted_by, self.manager.actor_id)

    def test_enable_pilot_access_is_blocked_without_matching_terms_or_rollout_switch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = self._engine_for_path(tmpdir)
            supplier_id = self._active_manual_supplier(engine, name="Blocked Pilot Enable Supplier")

            blocked = engine.enable_pilot_access(
                supplier_id,
                pilot_name="PH-Alpha",
                terms_version="pilot-v1",
                actor=self.manager.actor_id,
                context=PolicyContext(region_code="NCR", market_code="PH", pilot_enabled=False),
                access_context=self.manager,
            )

            self.assertFalse(blocked.allowed)
            self.assertIn("pilot.rollout.disabled", [issue.code for issue in blocked.issues])
            self.assertIn("pilot.terms.acceptance.required", [issue.code for issue in blocked.issues])
            self.assertEqual(blocked.events[-1].event_type, GovernanceEventType.GOVERNANCE_ACTION_BLOCKED)

    def test_enable_and_disable_pilot_access_create_reversible_audited_rollout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = self._engine_for_path(tmpdir)
            supplier_id = self._active_manual_supplier(engine, name="Reversible Pilot Supplier")
            engine.accept_pilot_terms(
                supplier_id,
                terms_version="pilot-v1",
                actor=self.manager.actor_id,
                access_context=self.manager,
            )

            enabled = engine.enable_pilot_access(
                supplier_id,
                pilot_name="PH-Alpha",
                terms_version="pilot-v1",
                actor=self.manager.actor_id,
                context=self.ph_context,
                access_context=self.manager,
            )
            self.assertTrue(enabled.allowed)
            self.assertTrue(enabled.supplier.region_context.pilot_enabled)
            self.assertEqual(enabled.supplier.region_context.pilot_name, "PH-Alpha")
            self.assertEqual(enabled.events[-1].event_type, GovernanceEventType.PILOT_ACCESS_ENABLED)

            disabled = engine.disable_pilot_access(
                supplier_id,
                actor=self.manager.actor_id,
                reason="rollback after pilot check",
                access_context=self.manager,
            )
            self.assertTrue(disabled.allowed)
            self.assertFalse(disabled.supplier.region_context.pilot_enabled)
            self.assertEqual(disabled.events[-1].event_type, GovernanceEventType.PILOT_ACCESS_DISABLED)

    def test_non_ph_supplier_cannot_be_enabled_for_pilot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = self._engine_for_path(tmpdir)
            supplier_id = engine.ingest_supplier(
                self._manual_candidate("Non PH Pilot Supplier", region=self.us_region),
                context=PolicyContext(region_code="CA", market_code="US", pilot_enabled=True),
                access_context=self.staff,
            ).supplier.identity.supplier_id
            engine.accept_legal(
                supplier_id,
                version="v2026.04",
                actor=self.manager.actor_id,
                context=PolicyContext(region_code="CA", market_code="US", pilot_enabled=True),
                access_context=self.manager,
            )
            engine.submit_for_review(
                supplier_id,
                actor=self.staff.actor_id,
                context=PolicyContext(region_code="CA", market_code="US", pilot_enabled=True),
                access_context=self.staff,
            )
            engine.approve_moderation(
                supplier_id,
                actor=self.moderator.actor_id,
                context=PolicyContext(region_code="CA", market_code="US", pilot_enabled=True),
                access_context=self.moderator,
            )
            engine.activate_supplier(
                supplier_id,
                actor=self.manager.actor_id,
                context=PolicyContext(region_code="CA", market_code="US", pilot_enabled=True),
                access_context=self.manager,
            )
            engine.accept_pilot_terms(
                supplier_id,
                terms_version="pilot-v1",
                actor=self.manager.actor_id,
                access_context=self.manager,
            )

            blocked = engine.enable_pilot_access(
                supplier_id,
                pilot_name="US-Shadow",
                terms_version="pilot-v1",
                actor=self.manager.actor_id,
                context=PolicyContext(region_code="CA", market_code="US", pilot_enabled=True),
                access_context=self.manager,
            )

            self.assertFalse(blocked.allowed)
            self.assertIn("pilot.market.ph_only", [issue.code for issue in blocked.issues])

    def test_pilot_incident_logging_and_release_summary_surface_kpis(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = self._engine_for_path(tmpdir)
            supplier_id = self._active_manual_supplier(engine, name="Pilot KPI Supplier")
            engine.accept_pilot_terms(
                supplier_id,
                terms_version="pilot-v1",
                actor=self.manager.actor_id,
                access_context=self.manager,
            )
            engine.enable_pilot_access(
                supplier_id,
                pilot_name="PH-Alpha",
                terms_version="pilot-v1",
                actor=self.manager.actor_id,
                context=self.ph_context,
                access_context=self.manager,
            )
            incident = engine.log_pilot_incident(
                supplier_id,
                severity=PilotIncidentSeverity.CRITICAL,
                summary="Pilot operator reported a pricing mismatch during rollout.",
                actor=self.manager.actor_id,
                access_context=self.manager,
            )

            self.assertTrue(incident.allowed)
            self.assertEqual(incident.events[-1].event_type, GovernanceEventType.INCIDENT_LOGGED)

            summary = engine.get_pilot_release_summary(pilot_name="PH-Alpha", access_context=self.manager)
            self.assertEqual(summary.enabled_supplier_count, 1)
            self.assertEqual(summary.terms_accepted_count, 1)
            self.assertEqual(summary.incidents.total_incidents, 1)
            self.assertTrue(summary.reversible)
            self.assertGreaterEqual(summary.kpis.active_supplier_count, 1)
            self.assertFalse(summary.expansion_gate.ready)

            runbook = engine.get_pilot_runbook()
            self.assertEqual(runbook.rollback_action, "disable_pilot_access")
            self.assertEqual(runbook.steps[0].action_name, "accept_pilot_terms")

    def test_staff_cannot_view_pilot_internals_or_enable_rollout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = self._engine_for_path(tmpdir)
            supplier_id = self._active_manual_supplier(engine, name="Restricted Pilot Supplier")
            engine.accept_pilot_terms(
                supplier_id,
                terms_version="pilot-v1",
                actor=self.manager.actor_id,
                access_context=self.manager,
            )

            blocked = engine.enable_pilot_access(
                supplier_id,
                pilot_name="PH-Alpha",
                terms_version="pilot-v1",
                actor=self.staff.actor_id,
                context=self.ph_context,
                access_context=self.staff,
            )
            self.assertFalse(blocked.allowed)
            self.assertIn("permission.enable_pilot_access.denied", [issue.code for issue in blocked.issues])

            with self.assertRaises(PermissionError):
                engine.get_pilot_release_summary(pilot_name="PH-Alpha", access_context=self.staff)


if __name__ == "__main__":
    unittest.main()
