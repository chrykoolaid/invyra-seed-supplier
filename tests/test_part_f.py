import unittest
from dataclasses import replace

from supplier_seed.domain.enums import GovernanceEventType, LifecycleStatus, ModerationStatus, SupplierMode
from supplier_seed.domain.models import SupplierRecord, SupplierRegionContext
from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine
from supplier_seed.repository.memory_impl import InMemorySupplierRepository
from supplier_seed.services.moderation_service import ModerationService


class SupplierSeedPartFTests(unittest.TestCase):
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
            require_reason_for_moderation_rejection=True,
            require_reason_for_moderation_escalation=True,
        )
        self.policy_engine = SupplierPolicyEngine()
        self.moderation_service = ModerationService()

    def test_moderation_rejection_requires_non_empty_reason(self) -> None:
        supplier = SupplierRecord.seeded_draft(
            name="Seeded Test",
            seeded_source="gov_registry",
            seeded_source_reference="SUP-300",
            region_context=self.region,
        )
        supplier = replace(
            supplier,
            lifecycle_status=LifecycleStatus.PENDING_REVIEW,
            moderation_status=ModerationStatus.PENDING_REVIEW,
        )
        result = self.moderation_service.reject(
            supplier,
            actor="reviewer",
            reason="   ",
            context=self.policy_context,
            policy_engine=self.policy_engine,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.issues[0].code, "policy.moderation.reject.blocked.reason_required")

    def test_engine_persists_blocked_moderation_attempt_as_audit_event(self) -> None:
        repo = InMemorySupplierRepository()
        engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)
        ingest = engine.ingest_supplier(
            SupplierCandidateInput(
                name="Blocked Moderation Supplier",
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                created_by="operator",
            ),
            context=self.policy_context,
        )
        supplier_id = ingest.supplier.identity.supplier_id
        blocked = engine.approve_moderation(supplier_id, actor="reviewer", context=self.policy_context)
        self.assertFalse(blocked.allowed)
        events = engine.list_audit_events(supplier_id)
        self.assertEqual(events[-1].event_type, GovernanceEventType.GOVERNANCE_ACTION_BLOCKED)
        self.assertEqual(events[-1].metadata["action"], "approve_moderation")
        self.assertIn("moderation.approve.pending_required", events[-1].metadata["issue_codes"])

    def test_engine_can_escalate_and_reject_with_audit_history(self) -> None:
        repo = InMemorySupplierRepository()
        engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)
        ingest = engine.ingest_supplier(
            SupplierCandidateInput(
                name="Escalation Workflow Supplier",
                mode=SupplierMode.SEEDED,
                region_context=self.region,
                seeded_source="gov_registry",
                seeded_source_reference="SUP-301",
                created_by="seed-bot",
            ),
            context=self.policy_context,
        )
        supplier_id = ingest.supplier.identity.supplier_id
        submitted = engine.submit_for_review(supplier_id, actor="reviewer", context=self.policy_context)
        self.assertTrue(submitted.allowed)
        escalated = engine.escalate_moderation(
            supplier_id,
            actor="reviewer",
            reason="needs legal cross-check",
            context=self.policy_context,
        )
        self.assertTrue(escalated.allowed)
        self.assertEqual(escalated.supplier.moderation_status, ModerationStatus.ESCALATED)
        rejected = engine.reject_moderation(
            supplier_id,
            actor="reviewer",
            reason="documentation mismatch",
            context=self.policy_context,
        )
        self.assertTrue(rejected.allowed)
        self.assertEqual(rejected.supplier.lifecycle_status, LifecycleStatus.REJECTED)
        events = engine.list_audit_events(supplier_id)
        event_types = [event.event_type for event in events]
        self.assertIn(GovernanceEventType.MODERATION_ESCALATED, event_types)
        self.assertIn(GovernanceEventType.MODERATION_REJECTED, event_types)
        self.assertEqual(events[-1].metadata["reason"], "documentation mismatch")


if __name__ == "__main__":
    unittest.main()
