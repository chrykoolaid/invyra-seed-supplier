import tempfile
import unittest
from pathlib import Path

from supplier_seed.domain.enums import SupplierMode
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput
from supplier_seed.operations.certification import certify_production_hardening
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine


class SupplierSeedPartR7Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.region = SupplierRegionContext(region_code="NCR", market_code="PH", pilot_enabled=True)
        self.context = PolicyContext(
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

    def _candidates(self, count):
        return tuple(
            SupplierCandidateInput(
                name=f"Certification Supplier {index:04d}",
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                tax_identifier=f"PH-CERT-{index:08d}",
                created_by="certification",
            )
            for index in range(count)
        )

    def test_production_hardening_certification_passes_representative_workload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report = certify_production_hardening(
                Path(tmpdir) / "supplier_seed_snapshot.json",
                self._candidates(50),
                policy_context=self.context,
                policy_engine=self.policy_engine,
            )

            self.assertTrue(report.certified)
            self.assertTrue(all(gate.passed for gate in report.gates))
            self.assertEqual(report.performance.persisted_supplier_count, 50)
            self.assertEqual(report.performance.persisted_event_count, 50)

    def test_certification_exposes_failed_gate_without_hiding_other_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report = certify_production_hardening(
                Path(tmpdir) / "supplier_seed_snapshot.json",
                self._candidates(5),
                policy_context=self.context,
                policy_engine=self.policy_engine,
                max_ingest_seconds=-1.0,
            )

            gates = {gate.code: gate for gate in report.gates}
            self.assertFalse(report.certified)
            self.assertFalse(gates["performance.ingest"].passed)
            self.assertTrue(gates["integrity.valid"].passed)
            self.assertTrue(gates["recovery.round_trip"].passed)


if __name__ == "__main__":
    unittest.main()
