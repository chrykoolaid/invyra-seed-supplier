import json
import tempfile
import unittest
from pathlib import Path

from supplier_seed.domain.enums import GovernanceEventType, SupplierMode
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput
from supplier_seed.integration.sources import JsonFileSupplierCandidateSource
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine
from supplier_seed.repository.json_file import JsonFileSupplierRepository


class SupplierSeedPartITests(unittest.TestCase):
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

    def test_json_file_repository_round_trips_supplier_and_audit_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "supplier_seed_snapshot.json"
            repo = JsonFileSupplierRepository(repo_path)
            engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)

            ingest = engine.ingest_supplier(
                SupplierCandidateInput(
                    name="Persistent Supplier",
                    mode=SupplierMode.MANUAL,
                    region_context=self.region,
                    created_by="operator",
                ),
                context=self.policy_context,
            )
            supplier_id = ingest.supplier.identity.supplier_id
            engine.accept_legal(
                supplier_id,
                version="v2026.04",
                actor="legal-officer",
                context=self.policy_context,
            )

            reopened_repo = JsonFileSupplierRepository(repo_path)
            reopened_engine = SupplierSeedEngine(repository=reopened_repo, policy_engine=self.policy_engine)
            persisted_supplier = reopened_repo.get_supplier(supplier_id)
            self.assertIsNotNone(persisted_supplier)
            self.assertEqual(persisted_supplier.name, "Persistent Supplier")
            events = reopened_engine.list_audit_events(supplier_id)
            self.assertEqual(events[0].event_type, GovernanceEventType.SUPPLIER_STAGED)
            self.assertEqual(events[-1].event_type, GovernanceEventType.LEGAL_ACCEPTED)

    def test_json_file_repository_rejects_foreign_audit_event_without_partial_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "supplier_seed_snapshot.json"
            repo = JsonFileSupplierRepository(repo_path)
            supplier = SupplierCandidateInput(
                name="Atomic Repo Supplier",
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                created_by="operator",
            )
            engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)
            ingest = engine.ingest_supplier(supplier, context=self.policy_context)
            supplier_id = ingest.supplier.identity.supplier_id
            before_payload = json.loads(repo_path.read_text(encoding="utf-8"))

            foreign_event = ingest.events[0].__class__(
                event_id="foreign-event",
                supplier_id="foreign-supplier",
                event_type=GovernanceEventType.LEGAL_ACCEPTED,
                occurred_at=ingest.supplier.updated_at,
                actor="legal-officer",
                source="test",
                summary="Foreign event",
                metadata={},
            )
            with self.assertRaises(ValueError):
                repo.save_supplier_with_events(ingest.supplier, events=(foreign_event,))

            after_payload = json.loads(repo_path.read_text(encoding="utf-8"))
            self.assertEqual(before_payload, after_payload)
            self.assertIsNotNone(repo.get_supplier(supplier_id))
            self.assertEqual(len(tuple(repo.list_audit_events(supplier_id))), 1)

    def test_engine_can_ingest_from_json_candidate_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "supplier_candidates.json"
            source_path.write_text(
                json.dumps(
                    [
                        {
                            "name": "North Harbor Supply",
                            "mode": "manual",
                            "region_context": {"region_code": "NCR", "market_code": "PH", "pilot_enabled": True},
                            "created_by": "operator",
                        },
                        {
                            "name": "Seeded Fresh Source",
                            "mode": "seeded",
                            "region_context": {"region_code": "NCR", "market_code": "PH", "pilot_enabled": True},
                            "created_by": "seed-bot",
                            "seeded_source": "gov_directory",
                            "seeded_source_reference": "ref-1001",
                        },
                    ]
                ),
                encoding="utf-8",
            )

            repo = JsonFileSupplierRepository(Path(tmpdir) / "supplier_repo.json")
            engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)
            batch = engine.ingest_from_source(
                JsonFileSupplierCandidateSource(source_path),
                context=self.policy_context,
            )

            self.assertEqual(len(batch.results), 2)
            self.assertEqual(batch.allowed_count + batch.warning_count + batch.review_count, 2)
            persisted_suppliers = tuple(repo.list_suppliers())
            self.assertEqual(len(persisted_suppliers), 2)
            self.assertTrue(any(supplier.is_seeded for supplier in persisted_suppliers))
            self.assertTrue(any(supplier.is_manual for supplier in persisted_suppliers))

    def test_json_candidate_source_rejects_non_list_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "bad_supplier_candidates.json"
            source_path.write_text(json.dumps({"name": "not-a-list"}), encoding="utf-8")

            source = JsonFileSupplierCandidateSource(source_path)
            with self.assertRaises(ValueError):
                tuple(source.list_candidates())


if __name__ == "__main__":
    unittest.main()
