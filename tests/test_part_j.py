import unittest

from supplier_seed.domain.enums import GovernanceEventType, SupplierMode
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine
from supplier_seed.repository.memory_impl import InMemorySupplierRepository


class SupplierSeedPartJTests(unittest.TestCase):
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
        self.policy_engine = SupplierPolicyEngine()
        self.repo = InMemorySupplierRepository()
        self.engine = SupplierSeedEngine(repository=self.repo, policy_engine=self.policy_engine)

    def _ingest_manual_supplier(self, name: str = "Manual Workflow Supplier") -> str:
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

    def _ingest_seeded_supplier(self, name: str = "Seeded Workflow Supplier") -> str:
        result = self.engine.ingest_supplier(
            SupplierCandidateInput(
                name=name,
                mode=SupplierMode.SEEDED,
                region_context=self.region,
                created_by="seed-bot",
                seeded_source="gov_directory",
                seeded_source_reference=f"ref-{name.lower().replace(' ', '-')}",
            ),
            context=self.policy_context,
        )
        return result.supplier.identity.supplier_id

    def test_workspace_for_approved_manual_supplier_surfaces_legal_next_step(self) -> None:
        supplier_id = self._ingest_manual_supplier()
        self.engine.submit_for_review(supplier_id, actor="operator", context=self.policy_context)
        self.engine.approve_moderation(supplier_id, actor="reviewer", context=self.policy_context)

        workspace = self.engine.get_supplier_workspace(supplier_id, context=self.policy_context)

        self.assertEqual(workspace.summary.primary_queue, "legal_review")
        self.assertEqual(workspace.summary.next_step, "accept_legal")
        legal_requirement = next(item for item in workspace.requirements if item.code == "legal_acceptance")
        self.assertFalse(legal_requirement.satisfied)
        self.assertTrue(legal_requirement.blocking)
        self.assertIn("activation", {item.code for item in workspace.requirements})

    def test_list_supplier_summaries_can_filter_moderation_queue(self) -> None:
        seeded_id = self._ingest_seeded_supplier()
        self._ingest_manual_supplier(name="Another Manual Supplier")

        moderation_items = self.engine.list_supplier_summaries(
            context=self.policy_context,
            queue="moderation_review",
        )

        self.assertEqual(len(moderation_items), 1)
        self.assertEqual(moderation_items[0].supplier_id, seeded_id)
        self.assertEqual(moderation_items[0].next_step, "review_moderation")

    def test_activation_ready_queue_contains_supplier_after_governed_prerequisites(self) -> None:
        supplier_id = self._ingest_manual_supplier(name="Activation Ready Supplier")
        self.engine.submit_for_review(supplier_id, actor="operator", context=self.policy_context)
        self.engine.approve_moderation(supplier_id, actor="reviewer", context=self.policy_context)
        self.engine.accept_legal(
            supplier_id,
            version="v2026.04",
            actor="legal-officer",
            context=self.policy_context,
        )

        activation_items = self.engine.list_supplier_summaries(
            context=self.policy_context,
            queue="activation_ready",
        )

        self.assertEqual(len(activation_items), 1)
        self.assertEqual(activation_items[0].supplier_id, supplier_id)
        self.assertEqual(activation_items[0].next_step, "activate_supplier")

        workspace = self.engine.get_supplier_workspace(supplier_id, context=self.policy_context)
        self.assertTrue(workspace.activation_allowed)
        activation_requirement = next(item for item in workspace.requirements if item.code == "activation")
        self.assertTrue(activation_requirement.satisfied)

    def test_workspace_timeline_is_descending_and_contains_latest_governance_event(self) -> None:
        supplier_id = self._ingest_manual_supplier(name="Timeline Supplier")
        self.engine.submit_for_review(supplier_id, actor="operator", context=self.policy_context)
        self.engine.approve_moderation(supplier_id, actor="reviewer", context=self.policy_context)
        self.engine.accept_legal(
            supplier_id,
            version="v2026.04",
            actor="legal-officer",
            context=self.policy_context,
        )

        workspace = self.engine.get_supplier_workspace(supplier_id, context=self.policy_context)

        self.assertGreaterEqual(len(workspace.timeline), 3)
        self.assertEqual(workspace.timeline[0].event_type, GovernanceEventType.LEGAL_ACCEPTED)
        ordered_times = [entry.occurred_at for entry in workspace.timeline]
        self.assertEqual(ordered_times, sorted(ordered_times, reverse=True))


if __name__ == "__main__":
    unittest.main()
