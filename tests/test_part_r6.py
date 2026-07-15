import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from supplier_seed.domain.enums import SupplierMode
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine
from supplier_seed.repository.json_file import JsonFileSupplierRepository
from supplier_seed.repository.recovery import inspect_snapshot


class SupplierSeedPartR6Tests(unittest.TestCase):
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

    def _candidate(self, index: int) -> SupplierCandidateInput:
        return SupplierCandidateInput(
            name=f"Soak Supplier {index:04d}",
            mode=SupplierMode.MANUAL,
            region_context=self.region,
            tax_identifier=f"PH-R6-{index:08d}",
            created_by="phase-r6",
        )

    def test_repeated_interrupted_writes_preserve_last_valid_snapshot_and_recover(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_path = Path(tmpdir) / "supplier_seed_snapshot.json"
            repository = JsonFileSupplierRepository(snapshot_path)
            engine = SupplierSeedEngine(repository=repository, policy_engine=self.policy_engine)
            engine.ingest_supplier(self._candidate(0), context=self.policy_context)

            last_valid_bytes = snapshot_path.read_bytes()

            for index in range(1, 4):
                failing_repository = JsonFileSupplierRepository(snapshot_path)
                failing_engine = SupplierSeedEngine(
                    repository=failing_repository,
                    policy_engine=self.policy_engine,
                )
                with patch.object(
                    JsonFileSupplierRepository,
                    "_replace_snapshot_file",
                    side_effect=RuntimeError("injected replace failure"),
                ):
                    with self.assertRaises(RuntimeError):
                        failing_engine.ingest_supplier(
                            self._candidate(index),
                            context=self.policy_context,
                        )

                self.assertEqual(snapshot_path.read_bytes(), last_valid_bytes)
                report = inspect_snapshot(snapshot_path)
                self.assertTrue(report.valid, report.errors)
                self.assertEqual(report.supplier_count, 1)
                self.assertEqual(report.audit_event_count, 1)

            recovery_repository = JsonFileSupplierRepository(snapshot_path)
            recovery_engine = SupplierSeedEngine(
                repository=recovery_repository,
                policy_engine=self.policy_engine,
            )
            recovered = recovery_engine.ingest_supplier(
                self._candidate(4),
                context=self.policy_context,
            )

            self.assertTrue(recovered.accepted_for_staging)
            report = inspect_snapshot(snapshot_path)
            self.assertTrue(report.valid, report.errors)
            self.assertEqual(report.supplier_count, 2)
            self.assertEqual(report.audit_event_count, 2)

    def test_long_running_commit_sequence_survives_periodic_restarts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_path = Path(tmpdir) / "supplier_seed_snapshot.json"
            repository = JsonFileSupplierRepository(snapshot_path)
            engine = SupplierSeedEngine(repository=repository, policy_engine=self.policy_engine)
            commit_count = 150

            for index in range(commit_count):
                result = engine.ingest_supplier(
                    self._candidate(index),
                    context=self.policy_context,
                )
                self.assertTrue(result.accepted_for_staging)

                if (index + 1) % 25 == 0:
                    report = inspect_snapshot(snapshot_path)
                    self.assertTrue(report.valid, report.errors)
                    self.assertEqual(report.supplier_count, index + 1)
                    self.assertEqual(report.audit_event_count, index + 1)
                    repository = JsonFileSupplierRepository(snapshot_path)
                    engine = SupplierSeedEngine(
                        repository=repository,
                        policy_engine=self.policy_engine,
                    )

            final_repository = JsonFileSupplierRepository(snapshot_path)
            suppliers = tuple(final_repository.list_suppliers())
            events = tuple(final_repository.list_audit_events())
            report = inspect_snapshot(snapshot_path)

            self.assertTrue(report.valid, report.errors)
            self.assertEqual(len(suppliers), commit_count)
            self.assertEqual(len(events), commit_count)
            self.assertEqual(report.snapshot_revision, commit_count)
            self.assertEqual(
                {supplier.name for supplier in suppliers},
                {f"Soak Supplier {index:04d}" for index in range(commit_count)},
            )


if __name__ == "__main__":
    unittest.main()
