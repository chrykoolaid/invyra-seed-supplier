import json
import tempfile
import unittest
from pathlib import Path

from supplier_seed.domain.enums import SupplierMode
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine
from supplier_seed.repository.json_file import JsonFileSupplierRepository


class SupplierSeedPartRTests(unittest.TestCase):
    def setUp(self) -> None:
        self.region = SupplierRegionContext(
            region_code="NCR",
            market_code="PH",
            pilot_enabled=True,
        )
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

    def _candidate(self, index: int, actor: str = "load-test") -> SupplierCandidateInput:
        return SupplierCandidateInput(
            name=f"Hardening Supplier {index:04d}",
            mode=SupplierMode.MANUAL,
            region_context=self.region,
            tax_identifier=f"PH-R-{index:08d}",
            created_by=actor,
        )

    def test_large_batch_persists_and_reloads_without_supplier_or_event_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "supplier_seed_snapshot.json"
            repo = JsonFileSupplierRepository(repo_path)
            engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)

            result = engine.ingest_batch(
                tuple(self._candidate(index) for index in range(100)),
                context=self.policy_context,
            )

            self.assertEqual(len(result.results), 100)
            self.assertTrue(all(item.accepted_for_staging for item in result.results))

            reopened = JsonFileSupplierRepository(repo_path)
            suppliers = tuple(reopened.list_suppliers())
            events = tuple(reopened.list_audit_events())
            payload = json.loads(repo_path.read_text(encoding="utf-8"))

            self.assertEqual(len(suppliers), 100)
            self.assertEqual(len(events), 100)
            self.assertEqual(len({supplier.supplier_id for supplier in suppliers}), 100)
            self.assertEqual(len({event.event_id for event in events}), 100)
            self.assertEqual(payload["snapshot_revision"], 100)

    def test_repeated_stale_repository_writers_preserve_all_commits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "supplier_seed_snapshot.json"
            repo_a = JsonFileSupplierRepository(repo_path)
            repo_b = JsonFileSupplierRepository(repo_path)
            engine_a = SupplierSeedEngine(repository=repo_a, policy_engine=self.policy_engine)
            engine_b = SupplierSeedEngine(repository=repo_b, policy_engine=self.policy_engine)

            for index in range(40):
                engine = engine_a if index % 2 == 0 else engine_b
                engine.ingest_supplier(
                    self._candidate(index, actor=f"writer-{index % 2}"),
                    context=self.policy_context,
                )

            reopened = JsonFileSupplierRepository(repo_path)
            suppliers = tuple(reopened.list_suppliers())
            events = tuple(reopened.list_audit_events())

            self.assertEqual(len(suppliers), 40)
            self.assertEqual(len(events), 40)
            self.assertEqual(
                {supplier.name for supplier in suppliers},
                {f"Hardening Supplier {index:04d}" for index in range(40)},
            )

    def test_corrupt_snapshot_is_rejected_without_rewriting_original_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "supplier_seed_snapshot.json"
            corrupt_bytes = b'{"schema_version": 4, "suppliers": ['
            repo_path.write_bytes(corrupt_bytes)

            with self.assertRaises(json.JSONDecodeError):
                JsonFileSupplierRepository(repo_path)

            self.assertEqual(repo_path.read_bytes(), corrupt_bytes)


if __name__ == "__main__":
    unittest.main()
