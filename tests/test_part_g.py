import unittest
from dataclasses import replace

from supplier_seed.domain.enums import GovernanceEventType, LegalAcceptanceState, LifecycleStatus, SupplierMode
from supplier_seed.domain.models import SupplierRecord, SupplierRegionContext
from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine
from supplier_seed.repository.memory_impl import InMemorySupplierRepository
from supplier_seed.services.legal_service import LegalService


class SupplierSeedPartGTests(unittest.TestCase):
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
            require_actor_for_legal_actions=True,
            require_reason_for_legal_withdrawal=True,
            require_reason_for_legal_supersede=True,
            allow_seeded_legal_acceptance=False,
        )
        self.policy_engine = SupplierPolicyEngine()
        self.legal_service = LegalService()

    def test_seeded_supplier_legal_acceptance_is_blocked_by_policy(self) -> None:
        supplier = SupplierRecord.seeded_draft(
            name="Seeded Supplier",
            seeded_source="gov_registry",
            seeded_source_reference="SUP-400",
            region_context=self.region,
        )
        result = self.legal_service.accept(
            supplier,
            version="v2026.05",
            actor="legal-officer",
            context=self.policy_context,
            policy_engine=self.policy_engine,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.issues[0].code, "policy.legal.accept.blocked.seeded_not_applicable")

    def test_legal_acceptance_requires_supersede_before_direct_version_replacement(self) -> None:
        supplier = SupplierRecord.manual_draft(name="Manual Supplier", region_context=self.region)
        accepted = self.legal_service.accept(
            supplier,
            version="v2026.04",
            actor="legal-officer",
            context=self.policy_context,
            policy_engine=self.policy_engine,
        )
        self.assertTrue(accepted.allowed)
        replaced = self.legal_service.accept(
            accepted.supplier,
            version="v2026.05",
            actor="legal-officer",
            context=self.policy_context,
            policy_engine=self.policy_engine,
        )
        self.assertFalse(replaced.allowed)
        self.assertEqual(replaced.issues[-1].code, "legal.accept.supersede_required")

    def test_engine_persists_blocked_legal_attempt_as_audit_event(self) -> None:
        repo = InMemorySupplierRepository()
        engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)
        ingest = engine.ingest_supplier(
            SupplierCandidateInput(
                name="Blocked Legal Supplier",
                mode=SupplierMode.SEEDED,
                region_context=self.region,
                seeded_source="gov_registry",
                seeded_source_reference="SUP-401",
                created_by="seed-bot",
            ),
            context=self.policy_context,
        )
        supplier_id = ingest.supplier.identity.supplier_id
        blocked = engine.accept_legal(
            supplier_id,
            version="v2026.05",
            actor="legal-officer",
            context=self.policy_context,
        )
        self.assertFalse(blocked.allowed)
        events = engine.list_audit_events(supplier_id)
        self.assertEqual(events[-1].event_type, GovernanceEventType.GOVERNANCE_ACTION_BLOCKED)
        self.assertEqual(events[-1].metadata["action"], "accept_legal")
        self.assertIn("policy.legal.accept.blocked.seeded_not_applicable", events[-1].metadata["issue_codes"])

    def test_engine_can_supersede_then_accept_new_legal_version_with_audit_history(self) -> None:
        repo = InMemorySupplierRepository()
        engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)
        ingest = engine.ingest_supplier(
            SupplierCandidateInput(
                name="Legal Workflow Supplier",
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                created_by="operator",
            ),
            context=self.policy_context,
        )
        supplier_id = ingest.supplier.identity.supplier_id
        accepted = engine.accept_legal(
            supplier_id,
            version="v2026.04",
            actor="legal-officer",
            context=self.policy_context,
        )
        self.assertTrue(accepted.allowed)
        superseded = engine.supersede_legal(
            supplier_id,
            pending_version="v2026.05",
            actor="legal-officer",
            reason="terms updated",
            context=self.policy_context,
        )
        self.assertTrue(superseded.allowed)
        self.assertEqual(superseded.supplier.legal_acceptance_state, LegalAcceptanceState.SUPERSEDED)
        accepted_new = engine.accept_legal(
            supplier_id,
            version="v2026.05",
            actor="legal-officer",
            context=self.policy_context,
        )
        self.assertTrue(accepted_new.allowed)
        self.assertEqual(accepted_new.supplier.legal_acceptance_state, LegalAcceptanceState.ACCEPTED)
        self.assertEqual(accepted_new.supplier.legal_acceptance_version, "v2026.05")
        events = engine.list_audit_events(supplier_id)
        event_types = [event.event_type for event in events]
        self.assertIn(GovernanceEventType.LEGAL_ACCEPTED, event_types)
        self.assertIn(GovernanceEventType.LEGAL_SUPERSEDED, event_types)
        self.assertEqual(events[-2].metadata["pending_version"], "v2026.05")
        self.assertEqual(events[-1].metadata["version"], "v2026.05")

    def test_legal_withdrawal_requires_reason_when_policy_demands_it(self) -> None:
        supplier = SupplierRecord.manual_draft(name="Withdraw Supplier", region_context=self.region)
        supplier = replace(
            supplier,
            lifecycle_status=LifecycleStatus.APPROVED,
            legal_acceptance_state=LegalAcceptanceState.ACCEPTED,
            legal_acceptance_version="v2026.04",
        )
        result = self.legal_service.withdraw(
            supplier,
            actor="legal-officer",
            reason="   ",
            context=self.policy_context,
            policy_engine=self.policy_engine,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.issues[0].code, "policy.legal.withdraw.blocked.reason_required")


if __name__ == "__main__":
    unittest.main()
