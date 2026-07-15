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
from supplier_seed.repository.recovery import create_snapshot_backup, inspect_snapshot, restore_snapshot


class SupplierSeedPartRRecoveryTests(unittest.TestCase):
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

    def _candidate(self, name: str, tax_identifier: str) -> SupplierCandidateInput:
        return SupplierCandidateInput(
            name=name,
            mode=SupplierMode.MANUAL,
            region_context=self.region,
            tax_identifier=tax_identifier,
            created_by="recovery-test",
        )

    def test_backup_and_restore_preserve_complete_snapshot_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "source.json"
            backup_path = root / "backup.json"
            restored_path = root / "restored.json"
            engine = SupplierSeedEngine(
                repository=JsonFileSupplierRepository(source_path),
                policy_engine=self.policy_engine,
            )

            first = engine.ingest_supplier(
                self._candidate("Recovery Supplier A", "PH-REC-A"),
                context=self.context,
                idempotency_key="recovery-a",
            )
            second = engine.ingest_supplier(
                self._candidate("Recovery Supplier B", "PH-REC-B"),
                context=self.context,
                idempotency_key="recovery-b",
            )

            source_payload = json.loads(source_path.read_text(encoding="utf-8"))
            backup_report = create_snapshot_backup(source_path, backup_path)
            restored_report = restore_snapshot(backup_path, restored_path)
            restored_payload = json.loads(restored_path.read_text(encoding="utf-8"))
            restored = JsonFileSupplierRepository(restored_path)

            self.assertTrue(backup_report.valid)
            self.assertEqual(restored_report, backup_report)
            self.assertEqual(restored_payload, source_payload)
            self.assertEqual(
                {supplier.supplier_id for supplier in restored.list_suppliers()},
                {first.supplier.supplier_id, second.supplier.supplier_id},
            )
            self.assertEqual(len(tuple(restored.list_audit_events())), 2)
            self.assertEqual(len(restored.operation_receipts), 2)

    def test_invalid_backup_does_not_replace_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target_path = root / "target.json"
            invalid_backup_path = root / "invalid-backup.json"
            engine = SupplierSeedEngine(
                repository=JsonFileSupplierRepository(target_path),
                policy_engine=self.policy_engine,
            )
            engine.ingest_supplier(
                self._candidate("Protected Supplier", "PH-PROTECTED"),
                context=self.context,
            )
            original_bytes = target_path.read_bytes()
            invalid_backup_path.write_text('{"schema_version": 4, "suppliers": [', encoding="utf-8")

            with self.assertRaises(ValueError):
                restore_snapshot(invalid_backup_path, target_path)

            self.assertEqual(target_path.read_bytes(), original_bytes)

    def test_integrity_report_detects_orphan_audit_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_path = Path(tmpdir) / "snapshot.json"
            engine = SupplierSeedEngine(
                repository=JsonFileSupplierRepository(snapshot_path),
                policy_engine=self.policy_engine,
            )
            engine.ingest_supplier(
                self._candidate("Integrity Supplier", "PH-INTEGRITY"),
                context=self.context,
            )
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            payload["audit_events"][0]["supplier_id"] = "missing-supplier"
            snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

            report = inspect_snapshot(snapshot_path)

            self.assertFalse(report.valid)
            self.assertIn("snapshot.orphan_audit_event", report.errors)


if __name__ == "__main__":
    unittest.main()
