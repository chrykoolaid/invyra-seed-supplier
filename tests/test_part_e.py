import unittest
from dataclasses import replace

from supplier_seed.domain.enums import GovernanceEventType, LifecycleStatus, ModerationStatus, SupplierMode
from supplier_seed.domain.models import SupplierRecord, SupplierRegionContext
from supplier_seed.domain.validation import validate_supplier
from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.events.audit import GovernanceEventRecord
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput, SupplierIngestionService
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine
from supplier_seed.repository.memory_impl import InMemorySupplierRepository


class SupplierSeedPartETests(unittest.TestCase):
    def setUp(self) -> None:
        self.region = SupplierRegionContext(region_code=" ncr ", market_code=" ph ", pilot_enabled=True)
        self.policy_context = PolicyContext(
            region_code=" NCR ",
            market_code=" ph ",
            pilot_enabled=True,
            allow_seeded_supplier_creation=True,
            require_region_for_supplier=True,
            require_legal_acceptance_for_manual=True,
            require_moderation_for_seeded_activation=True,
        )
        self.policy_engine = SupplierPolicyEngine()

    def test_domain_factories_normalize_whitespace_and_codes(self) -> None:
        supplier = SupplierRecord.manual_draft(
            name="  Bright Wash Supply  ",
            region_context=self.region,
            created_by="  operator  ",
            contact_email="  contact@brightwash.ph  ",
        )
        self.assertEqual(supplier.name, "Bright Wash Supply")
        self.assertEqual(supplier.region_context.region_code, "NCR")
        self.assertEqual(supplier.region_context.market_code, "PH")
        self.assertEqual(supplier.created_by, "operator")
        self.assertEqual(supplier.contact_email, "contact@brightwash.ph")

    def test_validation_flags_pending_review_without_pending_moderation_state(self) -> None:
        supplier = SupplierRecord.manual_draft(name="Manual Review Test", region_context=self.region)
        supplier = replace(
            supplier,
            lifecycle_status=LifecycleStatus.PENDING_REVIEW,
            moderation_status=ModerationStatus.NOT_REVIEWED,
        )
        result = validate_supplier(supplier, context=self.policy_context, policy_engine=self.policy_engine)
        self.assertTrue(result.has_errors)
        self.assertTrue(any(issue.code == "supplier.state.pending_review_moderation_invalid" for issue in result.issues))

    def test_ingestion_result_emits_staging_event_when_candidate_is_accepted(self) -> None:
        service = SupplierIngestionService(policy_engine=self.policy_engine)
        result = service.ingest_supplier(
            SupplierCandidateInput(
                name="North Harbor Supply",
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                created_by="operator",
            ),
            context=self.policy_context,
        )
        self.assertTrue(result.accepted_for_staging)
        self.assertEqual(result.events[0].event_type, GovernanceEventType.SUPPLIER_STAGED)
        self.assertEqual(result.events[0].source, "ingestion.service")

    def test_engine_persists_ingestion_and_lifecycle_audit_events(self) -> None:
        repo = InMemorySupplierRepository()
        engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)
        ingest = engine.ingest_supplier(
            SupplierCandidateInput(
                name="Lifecycle Audit Supplier",
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                created_by="operator",
            ),
            context=self.policy_context,
        )
        supplier_id = ingest.supplier.identity.supplier_id
        engine.accept_legal(supplier_id, version="v2026.04", actor="legal-officer")
        engine.submit_for_review(supplier_id, actor="reviewer", context=self.policy_context)
        engine.approve_moderation(supplier_id, actor="reviewer", context=self.policy_context)
        engine.activate_supplier(supplier_id, actor="reviewer", context=self.policy_context)

        event_types = [event.event_type for event in repo.list_audit_events(supplier_id)]
        self.assertIn(GovernanceEventType.SUPPLIER_STAGED, event_types)
        self.assertIn(GovernanceEventType.LEGAL_ACCEPTED, event_types)
        self.assertIn(GovernanceEventType.MODERATION_SUBMITTED, event_types)
        self.assertIn(GovernanceEventType.MODERATION_APPROVED, event_types)
        self.assertIn(GovernanceEventType.LIFECYCLE_STATUS_CHANGED, event_types)

    def test_memory_repository_rejects_foreign_audit_event(self) -> None:
        repo = InMemorySupplierRepository()
        supplier = SupplierRecord.manual_draft(name="Repo Contract Supplier", region_context=self.region)
        foreign_event = GovernanceEventRecord.new(
            supplier_id="foreign-id",
            event_type=GovernanceEventType.LEGAL_ACCEPTED,
            occurred_at=supplier.updated_at,
            actor="legal-officer",
            source="test",
            summary="Foreign event",
        )
        with self.assertRaises(ValueError):
            repo.save_supplier_with_events(supplier, events=(foreign_event,))


if __name__ == "__main__":
    unittest.main()
