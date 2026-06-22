import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from supplier_seed.domain.enums import GovernanceEventType, LifecycleStatus, SupplierMode
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine
from supplier_seed.repository.json_file import JsonFileSupplierRepository
from supplier_seed.repository.serialization import deserialize_snapshot


class SupplierSeedPartLTests(unittest.TestCase):
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

    def test_json_repository_snapshot_includes_revision_and_accepts_v1_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "supplier_seed_snapshot.json"
            repo = JsonFileSupplierRepository(repo_path)
            engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)
            ingest = engine.ingest_supplier(
                SupplierCandidateInput(
                    name="Revision Supplier",
                    mode=SupplierMode.MANUAL,
                    region_context=self.region,
                    created_by="operator",
                ),
                context=self.policy_context,
            )

            payload = json.loads(repo_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 4)
            self.assertEqual(payload["snapshot_revision"], 1)
            snapshot = deserialize_snapshot(payload)
            self.assertEqual(snapshot.revision, 1)
            self.assertEqual(snapshot.operation_receipts, ())
            self.assertEqual(snapshot.suppliers[0].identity.supplier_id, ingest.supplier.identity.supplier_id)

            legacy_payload = {
                "schema_version": 1,
                "suppliers": payload["suppliers"],
                "audit_events": payload["audit_events"],
            }
            legacy_snapshot = deserialize_snapshot(legacy_payload)
            self.assertEqual(legacy_snapshot.revision, 0)
            self.assertEqual(len(legacy_snapshot.suppliers), 1)

    def test_repeated_same_event_persistence_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "supplier_seed_snapshot.json"
            repo = JsonFileSupplierRepository(repo_path)
            engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)
            ingest = engine.ingest_supplier(
                SupplierCandidateInput(
                    name="Idempotent Supplier",
                    mode=SupplierMode.MANUAL,
                    region_context=self.region,
                    created_by="operator",
                ),
                context=self.policy_context,
            )
            supplier = ingest.supplier
            events = ingest.events

            repo.save_supplier_with_events(supplier, events=events)
            reopened = JsonFileSupplierRepository(repo_path)
            stored_events = tuple(reopened.list_audit_events(supplier.identity.supplier_id))
            self.assertEqual(len(stored_events), 1)
            self.assertEqual(stored_events[0].event_id, events[0].event_id)

    def test_stale_repository_instance_does_not_overwrite_other_commits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "supplier_seed_snapshot.json"
            repo_a = JsonFileSupplierRepository(repo_path)
            repo_b = JsonFileSupplierRepository(repo_path)
            engine_a = SupplierSeedEngine(repository=repo_a, policy_engine=self.policy_engine)
            engine_b = SupplierSeedEngine(repository=repo_b, policy_engine=self.policy_engine)

            engine_a.ingest_supplier(
                SupplierCandidateInput(
                    name="Supplier A",
                    mode=SupplierMode.MANUAL,
                    region_context=self.region,
                    created_by="operator-a",
                ),
                context=self.policy_context,
            )
            engine_b.ingest_supplier(
                SupplierCandidateInput(
                    name="Supplier B",
                    mode=SupplierMode.MANUAL,
                    region_context=self.region,
                    created_by="operator-b",
                ),
                context=self.policy_context,
            )

            reopened = JsonFileSupplierRepository(repo_path)
            names = {supplier.name for supplier in reopened.list_suppliers()}
            self.assertEqual(names, {"Supplier A", "Supplier B"})
            self.assertEqual(len(tuple(reopened.list_audit_events())), 2)

    def test_failed_replace_leaves_previous_snapshot_intact_for_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "supplier_seed_snapshot.json"
            repo = JsonFileSupplierRepository(repo_path)
            engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)
            ingest = engine.ingest_supplier(
                SupplierCandidateInput(
                    name="Recovery Supplier",
                    mode=SupplierMode.MANUAL,
                    region_context=self.region,
                    created_by="operator",
                ),
                context=self.policy_context,
            )
            before_payload = json.loads(repo_path.read_text(encoding="utf-8"))

            with patch.object(JsonFileSupplierRepository, "_replace_snapshot_file", side_effect=RuntimeError("replace failed")):
                with self.assertRaises(RuntimeError):
                    engine.accept_legal(
                        ingest.supplier.identity.supplier_id,
                        version="v2026.04",
                        actor="legal-officer",
                        context=self.policy_context,
                    )

            after_payload = json.loads(repo_path.read_text(encoding="utf-8"))
            self.assertEqual(after_payload, before_payload)

            reopened = JsonFileSupplierRepository(repo_path)
            recovered = reopened.get_supplier(ingest.supplier.identity.supplier_id)
            self.assertIsNotNone(recovered)
            self.assertEqual(recovered.legal_acceptance_state.value, "required_missing")
            event_types = [event.event_type for event in reopened.list_audit_events(ingest.supplier.identity.supplier_id)]
            self.assertEqual(event_types, [GovernanceEventType.SUPPLIER_STAGED])

    def test_persistence_backed_reload_matches_state_after_multi_step_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "supplier_seed_snapshot.json"
            repo = JsonFileSupplierRepository(repo_path)
            engine = SupplierSeedEngine(repository=repo, policy_engine=self.policy_engine)
            ingest = engine.ingest_supplier(
                SupplierCandidateInput(
                    name="Persistent Flow Supplier",
                    mode=SupplierMode.MANUAL,
                    region_context=self.region,
                    created_by="operator",
                ),
                context=self.policy_context,
            )
            supplier_id = ingest.supplier.identity.supplier_id
            engine.accept_legal(supplier_id, version="v2026.04", actor="legal-officer", context=self.policy_context)
            engine.submit_for_review(supplier_id, actor="reviewer", context=self.policy_context)
            engine.approve_moderation(supplier_id, actor="reviewer", context=self.policy_context)
            transition = engine.activate_supplier(supplier_id, actor="reviewer", context=self.policy_context)

            reopened = JsonFileSupplierRepository(repo_path)
            persisted_supplier = reopened.get_supplier(supplier_id)
            self.assertIsNotNone(persisted_supplier)
            self.assertEqual(persisted_supplier.lifecycle_status, LifecycleStatus.ACTIVE)
            self.assertEqual(persisted_supplier.updated_at, transition.supplier.updated_at)
            self.assertEqual(persisted_supplier.activated_at, transition.supplier.activated_at)

            event_types = [event.event_type for event in reopened.list_audit_events(supplier_id)]
            self.assertEqual(
                event_types,
                [
                    GovernanceEventType.SUPPLIER_STAGED,
                    GovernanceEventType.LEGAL_ACCEPTED,
                    GovernanceEventType.MODERATION_SUBMITTED,
                    GovernanceEventType.MODERATION_APPROVED,
                    GovernanceEventType.LIFECYCLE_STATUS_CHANGED,
                ],
            )


if __name__ == "__main__":
    unittest.main()
