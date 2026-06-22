import unittest

from supplier_seed.domain.enums import LifecycleStatus, PolicyOutcome, SupplierMode
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput, SupplierIngestionService
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine
from supplier_seed.repository.memory_impl import InMemorySupplierRepository


class SupplierSeedPartDTests(unittest.TestCase):
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
        self.ingestion_service = SupplierIngestionService(policy_engine=self.policy_engine)

    def test_ingestion_blocks_seeded_creation_when_policy_disallows(self) -> None:
        candidate = SupplierCandidateInput(
            name="Gov Seeded Supplier",
            mode=SupplierMode.SEEDED,
            region_context=self.region,
            seeded_source="gov_registry",
            seeded_source_reference="SUP-001",
            created_by="seed-bot",
        )
        blocked_context = PolicyContext(region_code="NCR", allow_seeded_supplier_creation=False)
        result = self.ingestion_service.ingest_supplier(candidate, context=blocked_context)
        self.assertEqual(result.outcome, PolicyOutcome.BLOCKED)
        self.assertFalse(result.accepted_for_staging)
        self.assertEqual(result.decisions[0].code, "policy.seeded_creation.blocked")

    def test_ingestion_requires_review_for_likely_duplicate(self) -> None:
        existing = self.ingestion_service.ingest_supplier(
            SupplierCandidateInput(
                name="Luna Foods Inc.",
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                contact_email="orders@lunafoods.ph",
                created_by="operator",
            ),
            context=self.policy_context,
        ).supplier
        candidate = SupplierCandidateInput(
            name="Luna Foods Incorporated",
            mode=SupplierMode.MANUAL,
            region_context=self.region,
            contact_email="orders@lunafoods.ph",
            created_by="operator",
        )
        result = self.ingestion_service.ingest_supplier(
            candidate,
            existing_suppliers=(existing,),
            context=self.policy_context,
        )
        self.assertEqual(result.outcome, PolicyOutcome.REQUIRES_REVIEW)
        self.assertTrue(any(item.code == "ingestion.dedupe.likely_duplicate" for item in result.decisions))

    def test_ingestion_warns_for_possible_duplicate(self) -> None:
        existing = self.ingestion_service.ingest_supplier(
            SupplierCandidateInput(
                name="North Harbor Supply",
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                contact_email="hello@sharedmail.ph",
                created_by="operator",
            ),
            context=self.policy_context,
        ).supplier
        candidate = SupplierCandidateInput(
            name="Harbor North Logistics",
            mode=SupplierMode.MANUAL,
            region_context=self.region,
            contact_email="hello@sharedmail.ph",
            created_by="operator",
        )
        result = self.ingestion_service.ingest_supplier(
            candidate,
            existing_suppliers=(existing,),
            context=self.policy_context,
        )
        self.assertEqual(result.outcome, PolicyOutcome.ALLOWED_WITH_WARNING)
        self.assertTrue(result.accepted_for_staging)

    def test_engine_ingest_persists_non_blocked_supplier_to_memory_repo(self) -> None:
        repo = InMemorySupplierRepository()
        engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)
        candidate = SupplierCandidateInput(
            name="Bright Wash Supply",
            mode=SupplierMode.MANUAL,
            region_context=self.region,
            created_by="operator",
        )
        result = engine.ingest_supplier(candidate, context=self.policy_context)
        self.assertEqual(result.outcome, PolicyOutcome.ALLOWED)
        self.assertEqual(len(tuple(repo.list_suppliers())), 1)

    def test_engine_batch_uses_staged_results_for_in_batch_duplicate_detection(self) -> None:
        repo = InMemorySupplierRepository()
        engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)
        first = SupplierCandidateInput(
            name="Acme Laundry Supply Inc.",
            mode=SupplierMode.MANUAL,
            region_context=self.region,
            contact_email="orders@acme.ph",
            created_by="operator",
        )
        second = SupplierCandidateInput(
            name="Acme Laundry Supply Incorporated",
            mode=SupplierMode.MANUAL,
            region_context=self.region,
            contact_email="orders@acme.ph",
            created_by="operator",
        )
        batch = engine.ingest_batch((first, second), context=self.policy_context)
        self.assertEqual(batch.results[0].outcome, PolicyOutcome.ALLOWED)
        self.assertEqual(batch.results[1].outcome, PolicyOutcome.REQUIRES_REVIEW)
        self.assertEqual(len(tuple(repo.list_suppliers())), 2)

    def test_engine_can_orchestrate_manual_activation_path(self) -> None:
        repo = InMemorySupplierRepository()
        engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)
        ingest = engine.ingest_supplier(
            SupplierCandidateInput(
                name="Manual Activation Test",
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                created_by="operator",
            ),
            context=self.policy_context,
        )
        supplier_id = ingest.supplier.identity.supplier_id
        legal = engine.accept_legal(supplier_id, version="v2026.04", actor="legal-officer")
        self.assertTrue(legal.allowed)
        submitted = engine.submit_for_review(supplier_id, actor="reviewer", context=self.policy_context)
        self.assertTrue(submitted.allowed)
        approved = engine.approve_moderation(supplier_id, actor="reviewer", context=self.policy_context)
        self.assertTrue(approved.allowed)
        activated = engine.activate_supplier(supplier_id, actor="reviewer", context=self.policy_context)
        self.assertTrue(activated.allowed)
        self.assertEqual(activated.supplier.lifecycle_status, LifecycleStatus.ACTIVE)
        self.assertEqual(repo.get_supplier(supplier_id).lifecycle_status, LifecycleStatus.ACTIVE)


if __name__ == "__main__":
    unittest.main()
