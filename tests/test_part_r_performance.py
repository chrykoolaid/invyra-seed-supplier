import tempfile
import unittest
from pathlib import Path

from supplier_seed.domain.enums import SupplierMode
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput
from supplier_seed.operations.performance import measure_repository_workload
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine


class SupplierSeedPartRPerformanceTests(unittest.TestCase):
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

    def _candidate(self, index: int) -> SupplierCandidateInput:
        return SupplierCandidateInput(
            name=f"Performance Supplier {index:04d}",
            mode=SupplierMode.MANUAL,
            region_context=self.region,
            tax_identifier=f"PH-PERF-{index:08d}",
            created_by="performance-baseline",
        )

    def test_representative_workload_stays_within_ci_safe_resource_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report = measure_repository_workload(
                Path(tmpdir) / "supplier_seed_snapshot.json",
                (self._candidate(index) for index in range(100)),
                policy_context=self.policy_context,
                policy_engine=SupplierPolicyEngine(),
            )

            self.assertEqual(report.supplier_count, 100)
            self.assertEqual(report.accepted_count, 100)
            self.assertEqual(report.persisted_supplier_count, 100)
            self.assertEqual(report.persisted_event_count, 100)
            self.assertLess(report.ingest_seconds, 15.0)
            self.assertLess(report.reload_seconds, 3.0)
            self.assertLess(report.peak_memory_bytes, 128 * 1024 * 1024)
            self.assertGreater(report.snapshot_size_bytes, 0)

    def test_empty_workload_produces_zero_records_and_valid_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report = measure_repository_workload(
                Path(tmpdir) / "supplier_seed_snapshot.json",
                (),
                policy_context=self.policy_context,
                policy_engine=SupplierPolicyEngine(),
            )

            self.assertEqual(report.supplier_count, 0)
            self.assertEqual(report.accepted_count, 0)
            self.assertEqual(report.persisted_supplier_count, 0)
            self.assertEqual(report.persisted_event_count, 0)
            self.assertGreater(report.snapshot_size_bytes, 0)


if __name__ == "__main__":
    unittest.main()
