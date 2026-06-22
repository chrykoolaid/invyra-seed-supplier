from dataclasses import replace

import unittest

from supplier_seed.domain.enums import (
    LegalAcceptanceState,
    LifecycleStatus,
    ModerationStatus,
    PolicyOutcome,
    SupplierAction,
    VerificationStatus,
)
from supplier_seed.domain.transitions import apply_lifecycle_transition, evaluate_lifecycle_transition
from supplier_seed.domain.validation import validate_supplier
from supplier_seed.domain.models import SupplierRecord, SupplierRegionContext
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine


class SupplierSeedPartATests(unittest.TestCase):
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
        )
        self.policy_engine = SupplierPolicyEngine()

    def test_manual_supplier_activation_is_blocked_without_accepted_legal(self) -> None:
        supplier = SupplierRecord.manual_draft(name="Manual Test", region_context=self.region)
        supplier = supplier.with_updated_metadata(actor="tester")
        supplier = replace(supplier, lifecycle_status=LifecycleStatus.APPROVED)
        result = evaluate_lifecycle_transition(
            supplier,
            target_status=LifecycleStatus.ACTIVE,
            context=self.policy_context,
            policy_engine=self.policy_engine,
        )
        self.assertFalse(result.allowed)
        self.assertTrue(any(issue.code == "policy.activation.blocked.legal_missing" for issue in result.issues))

    def test_seeded_supplier_activation_requires_moderation_approval(self) -> None:
        supplier = SupplierRecord.seeded_draft(
            name="Seeded Test",
            seeded_source="gov_registry",
            seeded_source_reference="SUP-001",
            region_context=self.region,
        )
        supplier = replace(supplier, lifecycle_status=LifecycleStatus.APPROVED)
        result = evaluate_lifecycle_transition(
            supplier,
            target_status=LifecycleStatus.ACTIVE,
            context=self.policy_context,
            policy_engine=self.policy_engine,
        )
        self.assertFalse(result.allowed)
        self.assertTrue(any(issue.code == "policy.activation.blocked.moderation_missing" for issue in result.issues))

    def test_rejected_supplier_must_go_back_through_review_before_active(self) -> None:
        supplier = SupplierRecord.seeded_draft(
            name="Rejected Seeded",
            seeded_source="gov_registry",
            seeded_source_reference="SUP-002",
            region_context=self.region,
        )
        supplier = replace(
            supplier,
            lifecycle_status=LifecycleStatus.REJECTED,
            moderation_status=ModerationStatus.APPROVED,
        )
        result = evaluate_lifecycle_transition(
            supplier,
            target_status=LifecycleStatus.ACTIVE,
            context=self.policy_context,
            policy_engine=self.policy_engine,
        )
        self.assertFalse(result.allowed)
        self.assertTrue(any(issue.code == "transition.lifecycle.path_blocked" for issue in result.issues))

    def test_archived_supplier_is_terminal(self) -> None:
        supplier = SupplierRecord.manual_draft(name="Archived", region_context=self.region)
        supplier = replace(supplier, lifecycle_status=LifecycleStatus.ARCHIVED)
        result = evaluate_lifecycle_transition(
            supplier,
            target_status=LifecycleStatus.ACTIVE,
            context=self.policy_context,
            policy_engine=self.policy_engine,
        )
        self.assertFalse(result.allowed)
        self.assertTrue(any(issue.code == "transition.lifecycle.archived_terminal" for issue in result.issues))

    def test_policy_allows_seeded_creation_in_enabled_pilot(self) -> None:
        result = self.policy_engine.evaluate_action(
            action=SupplierAction.CREATE_SEEDED,
            context=self.policy_context,
        )
        self.assertEqual(result.outcome, PolicyOutcome.ALLOWED)

    def test_validation_detects_seeded_manual_contradiction(self) -> None:
        supplier = SupplierRecord.manual_draft(name="Contradiction", region_context=self.region)
        supplier = replace(supplier, seeded_source="gov_registry", seeded_source_reference="SUP-003")
        result = validate_supplier(supplier, context=self.policy_context, policy_engine=self.policy_engine)
        self.assertTrue(result.has_errors)
        self.assertTrue(any(issue.code == "supplier.mode.manual_seeded_contradiction" for issue in result.issues))

    def test_apply_transition_returns_updated_supplier(self) -> None:
        supplier = SupplierRecord.seeded_draft(
            name="Ready Supplier",
            seeded_source="gov_registry",
            seeded_source_reference="SUP-004",
            region_context=self.region,
        )
        supplier = replace(
            supplier,
            lifecycle_status=LifecycleStatus.APPROVED,
            moderation_status=ModerationStatus.APPROVED,
            verification_status=VerificationStatus.VERIFIED,
        )
        result = apply_lifecycle_transition(
            supplier,
            target_status=LifecycleStatus.ACTIVE,
            actor="system",
            context=self.policy_context,
            policy_engine=self.policy_engine,
        )
        self.assertTrue(result.allowed)
        self.assertEqual(result.supplier.lifecycle_status, LifecycleStatus.ACTIVE)
        self.assertEqual(result.supplier.updated_by, "system")
        self.assertIsNotNone(result.supplier.activated_at)


if __name__ == "__main__":
    unittest.main()
