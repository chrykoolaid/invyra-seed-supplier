import unittest

from supplier_seed.domain.enums import GovernanceEventType, LifecycleStatus, SupplierMode
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine
from supplier_seed.repository.memory_impl import InMemorySupplierRepository


class SupplierSeedPartKTests(unittest.TestCase):
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
            require_actor_for_moderation_actions=True,
            require_actor_for_verification_actions=True,
            require_assignment_for_verification_decisions=True,
            require_assignment_match_for_verification_decisions=True,
            require_verified_status_for_visible_verification=True,
        )
        self.policy_engine = SupplierPolicyEngine()
        self.repo = InMemorySupplierRepository()
        self.engine = SupplierSeedEngine(repository=self.repo, policy_engine=self.policy_engine)

    def _ingest_manual_supplier(self, name: str = "Part K Manual Supplier") -> str:
        result = self.engine.ingest_supplier(
            SupplierCandidateInput(
                name=name,
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                created_by="operator",
            ),
            context=self.policy_context,
        )
        return result.supplier.identity.supplier_id

    def test_blocked_governance_result_returns_blocked_event_for_ui_contract(self) -> None:
        supplier_id = self._ingest_manual_supplier(name="Blocked Governance Supplier")

        blocked = self.engine.approve_moderation(supplier_id, actor="reviewer", context=self.policy_context)

        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.events[-1].event_type, GovernanceEventType.GOVERNANCE_ACTION_BLOCKED)
        self.assertEqual(blocked.events[-1].metadata["action"], "approve_moderation")
        self.assertEqual(self.engine.list_audit_events(supplier_id)[-1].event_id, blocked.events[-1].event_id)

    def test_blocked_activation_is_audited_and_exposed_in_transition_result(self) -> None:
        supplier_id = self._ingest_manual_supplier(name="Blocked Activation Supplier")

        blocked = self.engine.activate_supplier(supplier_id, actor="reviewer", context=self.policy_context)

        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.events[-1].event_type, GovernanceEventType.GOVERNANCE_ACTION_BLOCKED)
        self.assertEqual(blocked.events[-1].metadata["action"], "activate_supplier")
        self.assertEqual(blocked.events[-1].source, "engine.lifecycle")
        self.assertEqual(self.engine.list_audit_events(supplier_id)[-1].event_id, blocked.events[-1].event_id)

    def test_engine_can_normalize_results_for_ui_consumers(self) -> None:
        manual_supplier_id = self._ingest_manual_supplier(name="UI Envelope Supplier")
        governance_blocked = self.engine.approve_moderation(
            manual_supplier_id,
            actor="reviewer",
            context=self.policy_context,
        )
        governance_view = self.engine.present_governance_result(
            governance_blocked,
            action_name="approve_moderation",
        )
        self.assertEqual(governance_view.status, "policy_violation")
        self.assertEqual(governance_view.events[-1].metadata["action"], "approve_moderation")

        activation_blocked = self.engine.activate_supplier(
            manual_supplier_id,
            actor="reviewer",
            context=self.policy_context,
        )
        activation_view = self.engine.present_transition_result(
            activation_blocked,
            action_name="activate_supplier",
        )
        self.assertEqual(activation_view.status, "policy_violation")
        self.assertEqual(activation_view.metadata["to_status"], LifecycleStatus.ACTIVE.value)

        invalid_ingest = self.engine.ingest_supplier(
            SupplierCandidateInput(
                name="",
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                created_by="operator",
            ),
            context=self.policy_context,
            persist=False,
        )
        ingest_view = self.engine.present_ingestion_result(invalid_ingest)
        self.assertEqual(ingest_view.status, "validation_error")
        self.assertIn("supplier.name.required", ingest_view.metadata["decision_codes"])

        failure_view = self.engine.present_system_failure(
            action_name="approve_moderation",
            error_message="repository unavailable",
        )
        self.assertEqual(failure_view.status, "system_failure")
        self.assertFalse(failure_view.allowed)

    def test_reload_state_matches_returned_supplier_after_each_mutation(self) -> None:
        supplier_id = self._ingest_manual_supplier(name="Fresh Reload Supplier")

        accepted = self.engine.accept_legal(
            supplier_id,
            version="v2026.04",
            actor="legal-officer",
            context=self.policy_context,
        )
        self.assertEqual(self.engine.get_supplier_record(supplier_id).legal_acceptance_state, accepted.supplier.legal_acceptance_state)

        submitted = self.engine.submit_for_review(supplier_id, actor="operator", context=self.policy_context)
        self.assertEqual(self.engine.get_supplier_record(supplier_id).lifecycle_status, submitted.supplier.lifecycle_status)

        approved = self.engine.approve_moderation(supplier_id, actor="reviewer", context=self.policy_context)
        self.assertEqual(self.engine.get_supplier_record(supplier_id).lifecycle_status, approved.supplier.lifecycle_status)

        activated = self.engine.activate_supplier(supplier_id, actor="reviewer", context=self.policy_context)
        persisted = self.engine.get_supplier_record(supplier_id)
        self.assertTrue(activated.allowed)
        self.assertEqual(persisted.lifecycle_status, LifecycleStatus.ACTIVE)
        self.assertEqual(persisted.lifecycle_status, activated.supplier.lifecycle_status)
        self.assertEqual(self.engine.get_supplier_workspace(supplier_id, context=self.policy_context).summary.lifecycle_status, LifecycleStatus.ACTIVE)

    def test_facade_keeps_read_models_and_audit_in_sync_for_full_manual_flow(self) -> None:
        supplier_id = self._ingest_manual_supplier(name="Facade Sync Supplier")
        self.engine.accept_legal(supplier_id, version="v2026.04", actor="legal-officer", context=self.policy_context)
        self.engine.submit_for_review(supplier_id, actor="operator", context=self.policy_context)
        self.engine.approve_moderation(supplier_id, actor="reviewer", context=self.policy_context)
        activated = self.engine.activate_supplier(supplier_id, actor="reviewer", context=self.policy_context)

        self.assertTrue(activated.allowed)
        workspace = self.engine.get_supplier_workspace(supplier_id, context=self.policy_context)
        self.assertEqual(workspace.summary.primary_queue, "operational")
        self.assertEqual(workspace.summary.next_step, "monitor_supplier")
        self.assertEqual(workspace.timeline[0].event_type, GovernanceEventType.LIFECYCLE_STATUS_CHANGED)
        self.assertEqual(workspace.timeline[0].metadata["to_status"], LifecycleStatus.ACTIVE.value)


if __name__ == "__main__":
    unittest.main()
