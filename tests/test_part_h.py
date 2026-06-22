import unittest

from supplier_seed.domain.enums import GovernanceEventType, SupplierMode, VerificationVisibility
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine
from supplier_seed.repository.memory_impl import InMemorySupplierRepository


class SupplierSeedPartHTests(unittest.TestCase):
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

    def _ingest_manual_supplier(self, engine: SupplierSeedEngine, *, name: str = "Verification Supplier") -> str:
        ingest = engine.ingest_supplier(
            SupplierCandidateInput(
                name=name,
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                created_by="operator",
            ),
            context=self.policy_context,
        )
        return ingest.supplier.identity.supplier_id

    def test_verification_assignment_updates_supplier_and_event(self) -> None:
        repo = InMemorySupplierRepository()
        engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)
        supplier_id = self._ingest_manual_supplier(engine)

        assigned = engine.assign_verification(
            supplier_id,
            assignee="verifier.a",
            actor="manager",
            context=self.policy_context,
        )
        self.assertTrue(assigned.allowed)
        self.assertEqual(assigned.supplier.verification_assigned_to, "verifier.a")
        self.assertEqual(assigned.events[0].event_type, GovernanceEventType.VERIFICATION_ASSIGNED)
        self.assertEqual(assigned.events[0].metadata["to_assignee"], "verifier.a")

    def test_engine_persists_blocked_verification_decision_as_audit_event(self) -> None:
        repo = InMemorySupplierRepository()
        engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)
        supplier_id = self._ingest_manual_supplier(engine, name="Blocked Verification Supplier")
        engine.assign_verification(
            supplier_id,
            assignee="verifier.a",
            actor="manager",
            context=self.policy_context,
        )

        blocked = engine.mark_verified(
            supplier_id,
            actor="verifier.b",
            context=self.policy_context,
        )
        self.assertFalse(blocked.allowed)
        events = engine.list_audit_events(supplier_id)
        self.assertEqual(events[-1].event_type, GovernanceEventType.GOVERNANCE_ACTION_BLOCKED)
        self.assertEqual(events[-1].metadata["action"], "mark_verified")
        self.assertIn(
            "policy.verification.status_change.blocked.actor_assignment_mismatch",
            events[-1].metadata["issue_codes"],
        )

    def test_verification_visibility_requires_verified_status(self) -> None:
        repo = InMemorySupplierRepository()
        engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)
        supplier_id = self._ingest_manual_supplier(engine, name="Visibility Blocked Supplier")
        engine.assign_verification(
            supplier_id,
            assignee="verifier.a",
            actor="manager",
            context=self.policy_context,
        )

        blocked = engine.set_verification_visibility(
            supplier_id,
            visibility=VerificationVisibility.VISIBLE,
            actor="verifier.a",
            context=self.policy_context,
        )
        self.assertFalse(blocked.allowed)
        events = engine.list_audit_events(supplier_id)
        self.assertEqual(events[-1].metadata["action"], "set_verification_visibility")
        self.assertIn(
            "policy.verification.visibility.blocked.verification_required",
            events[-1].metadata["issue_codes"],
        )

    def test_engine_can_verify_then_make_supplier_visibility_visible(self) -> None:
        repo = InMemorySupplierRepository()
        engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)
        supplier_id = self._ingest_manual_supplier(engine, name="Visible Verification Supplier")
        engine.assign_verification(
            supplier_id,
            assignee="verifier.a",
            actor="manager",
            context=self.policy_context,
        )

        verified = engine.mark_verified(
            supplier_id,
            actor="verifier.a",
            context=self.policy_context,
        )
        self.assertTrue(verified.allowed)

        visible = engine.set_verification_visibility(
            supplier_id,
            visibility=VerificationVisibility.VISIBLE,
            actor="verifier.a",
            context=self.policy_context,
        )
        self.assertTrue(visible.allowed)
        self.assertEqual(visible.supplier.verification_visibility, VerificationVisibility.VISIBLE)
        events = engine.list_audit_events(supplier_id)
        event_types = [event.event_type for event in events]
        self.assertIn(GovernanceEventType.VERIFICATION_VERIFIED, event_types)
        self.assertIn(GovernanceEventType.VERIFICATION_VISIBILITY_CHANGED, event_types)
        self.assertEqual(events[-1].metadata["to_visibility"], VerificationVisibility.VISIBLE.value)

    def test_verification_visibility_is_downgraded_when_status_leaves_verified(self) -> None:
        repo = InMemorySupplierRepository()
        engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)
        supplier_id = self._ingest_manual_supplier(engine, name="Visibility Downgrade Supplier")
        engine.assign_verification(
            supplier_id,
            assignee="verifier.a",
            actor="manager",
            context=self.policy_context,
        )
        engine.mark_verified(
            supplier_id,
            actor="verifier.a",
            context=self.policy_context,
        )
        engine.set_verification_visibility(
            supplier_id,
            visibility=VerificationVisibility.VISIBLE,
            actor="verifier.a",
            context=self.policy_context,
        )

        needs_review = engine.mark_verification_needs_review(
            supplier_id,
            actor="verifier.a",
            reason="identity mismatch needs follow-up",
            context=self.policy_context,
        )
        self.assertTrue(needs_review.allowed)
        self.assertEqual(needs_review.supplier.verification_visibility, VerificationVisibility.INTERNAL_ONLY)
        self.assertEqual(needs_review.events[0].event_type, GovernanceEventType.VERIFICATION_NEEDS_REVIEW)
        self.assertEqual(needs_review.events[1].event_type, GovernanceEventType.VERIFICATION_VISIBILITY_CHANGED)
        self.assertEqual(needs_review.events[1].metadata["to_visibility"], VerificationVisibility.INTERNAL_ONLY.value)


if __name__ == "__main__":
    unittest.main()
