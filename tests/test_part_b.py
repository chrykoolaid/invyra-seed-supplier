from dataclasses import replace

import unittest

from supplier_seed.domain.enums import (
    GovernanceEventType,
    LegalAcceptanceState,
    LifecycleStatus,
    ModerationStatus,
    VerificationStatus,
)
from supplier_seed.domain.models import SupplierRecord, SupplierRegionContext
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine
from supplier_seed.services.legal_service import LegalService
from supplier_seed.services.moderation_service import ModerationService
from supplier_seed.services.provenance_service import ProvenanceService
from supplier_seed.services.verification_service import VerificationService


class SupplierSeedPartBTests(unittest.TestCase):
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
        self.legal_service = LegalService()
        self.moderation_service = ModerationService()
        self.provenance_service = ProvenanceService()
        self.verification_service = VerificationService()

    def test_seeded_provenance_capture_updates_record_and_event(self) -> None:
        supplier = SupplierRecord.seeded_draft(
            name="Seeded Test",
            seeded_source="legacy_seed",
            seeded_source_reference="OLD-1",
            region_context=self.region,
        )
        result = self.provenance_service.capture_seeded_provenance(
            supplier,
            seeded_source="gov_registry",
            seeded_source_reference="SUP-100",
            actor="seed-bot",
        )
        self.assertTrue(result.allowed)
        self.assertEqual(result.supplier.seeded_source, "gov_registry")
        self.assertEqual(result.events[0].event_type, GovernanceEventType.PROVENANCE_SEEDED_CAPTURED)

    def test_manual_origin_recording_blocks_seeded_supplier(self) -> None:
        supplier = SupplierRecord.seeded_draft(
            name="Seeded Test",
            seeded_source="gov_registry",
            seeded_source_reference="SUP-100",
            region_context=self.region,
        )
        result = self.provenance_service.record_manual_origin(supplier, actor="operator")
        self.assertFalse(result.allowed)
        self.assertEqual(result.issues[0].code, "provenance.manual_origin.seeded_supplier_invalid")

    def test_legal_acceptance_records_version_and_event(self) -> None:
        supplier = SupplierRecord.manual_draft(name="Manual Test", region_context=self.region)
        result = self.legal_service.accept(supplier, version="v2026.04", actor="legal-officer")
        self.assertTrue(result.allowed)
        self.assertEqual(result.supplier.legal_acceptance_state, LegalAcceptanceState.ACCEPTED)
        self.assertEqual(result.supplier.legal_acceptance_version, "v2026.04")
        self.assertEqual(result.events[0].event_type, GovernanceEventType.LEGAL_ACCEPTED)

    def test_cannot_withdraw_legal_while_supplier_is_active(self) -> None:
        supplier = SupplierRecord.manual_draft(name="Manual Test", region_context=self.region)
        supplier = replace(
            supplier,
            lifecycle_status=LifecycleStatus.ACTIVE,
            legal_acceptance_state=LegalAcceptanceState.ACCEPTED,
        )
        result = self.legal_service.withdraw(supplier, actor="legal-officer")
        self.assertFalse(result.allowed)
        self.assertEqual(result.issues[0].code, "legal.withdraw.active_supplier_blocked")

    def test_verification_failure_is_blocked_for_active_supplier(self) -> None:
        supplier = SupplierRecord.manual_draft(name="Manual Test", region_context=self.region)
        supplier = replace(supplier, lifecycle_status=LifecycleStatus.ACTIVE)
        result = self.verification_service.mark_failed(supplier, actor="verifier")
        self.assertFalse(result.allowed)
        self.assertEqual(result.issues[0].code, "verification.failed.active_supplier_blocked")

    def test_verification_verified_updates_status_and_event(self) -> None:
        supplier = SupplierRecord.manual_draft(name="Manual Test", region_context=self.region)
        result = self.verification_service.mark_verified(supplier, actor="verifier")
        self.assertTrue(result.allowed)
        self.assertEqual(result.supplier.verification_status, VerificationStatus.VERIFIED)
        self.assertEqual(result.events[0].event_type, GovernanceEventType.VERIFICATION_VERIFIED)

    def test_moderation_submit_and_approve_moves_supplier_through_lifecycle(self) -> None:
        supplier = SupplierRecord.seeded_draft(
            name="Seeded Test",
            seeded_source="gov_registry",
            seeded_source_reference="SUP-111",
            region_context=self.region,
        )
        submitted = self.moderation_service.submit_for_review(
            supplier,
            actor="reviewer",
            context=self.policy_context,
            policy_engine=self.policy_engine,
        )
        self.assertTrue(submitted.allowed)
        self.assertEqual(submitted.supplier.lifecycle_status, LifecycleStatus.PENDING_REVIEW)
        self.assertEqual(submitted.supplier.moderation_status, ModerationStatus.PENDING_REVIEW)

        approved = self.moderation_service.approve(
            submitted.supplier,
            actor="reviewer",
            context=self.policy_context,
            policy_engine=self.policy_engine,
        )
        self.assertTrue(approved.allowed)
        self.assertEqual(approved.supplier.lifecycle_status, LifecycleStatus.APPROVED)
        self.assertEqual(approved.supplier.moderation_status, ModerationStatus.APPROVED)
        self.assertEqual(approved.events[0].event_type, GovernanceEventType.MODERATION_APPROVED)

    def test_moderation_reject_requires_pending_or_escalated(self) -> None:
        supplier = SupplierRecord.manual_draft(name="Manual Test", region_context=self.region)
        result = self.moderation_service.reject(
            supplier,
            actor="reviewer",
            reason="missing accreditation",
            context=self.policy_context,
            policy_engine=self.policy_engine,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.issues[0].code, "moderation.reject.pending_required")

    def test_moderation_escalation_keeps_pending_review_lifecycle(self) -> None:
        supplier = SupplierRecord.seeded_draft(
            name="Seeded Test",
            seeded_source="gov_registry",
            seeded_source_reference="SUP-222",
            region_context=self.region,
        )
        supplier = replace(
            supplier,
            lifecycle_status=LifecycleStatus.PENDING_REVIEW,
            moderation_status=ModerationStatus.PENDING_REVIEW,
        )
        result = self.moderation_service.escalate(supplier, actor="reviewer", reason="needs second pass")
        self.assertTrue(result.allowed)
        self.assertEqual(result.supplier.lifecycle_status, LifecycleStatus.PENDING_REVIEW)
        self.assertEqual(result.supplier.moderation_status, ModerationStatus.ESCALATED)
        self.assertEqual(result.events[0].event_type, GovernanceEventType.MODERATION_ESCALATED)


if __name__ == "__main__":
    unittest.main()
