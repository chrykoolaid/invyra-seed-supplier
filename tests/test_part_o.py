from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from supplier_seed import (
    AccessContext,
    GovernanceEventType,
    GovernanceRole,
    JsonFileSupplierRepository,
    PolicyContext,
    RetryPolicy,
    SupplierCandidateInput,
    SupplierMode,
    SupplierPolicyEngine,
    SupplierRegionContext,
    SupplierSeedEngine,
)


class FlakyCandidateSource:
    def __init__(self, candidates, *, failures_before_success: int = 0, error_factory=None) -> None:
        self._candidates = tuple(candidates)
        self.failures_before_success = failures_before_success
        self.error_factory = error_factory or (lambda: TimeoutError("transient source timeout"))
        self.calls = 0

    def list_candidates(self):
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise self.error_factory()
        return tuple(self._candidates)


class SupplierSeedPartOTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy_context = PolicyContext(
            region_code="NCR",
            require_region_for_supplier=True,
            require_legal_acceptance_for_manual=True,
            require_moderation_for_seeded_activation=True,
            require_verified_status_for_visible_verification=True,
        )
        self.policy_engine = SupplierPolicyEngine()
        self.ncr_region = SupplierRegionContext(region_code="NCR", market_code="PH", pilot_enabled=True)
        self.staff = AccessContext(actor_id="staff.user", role=GovernanceRole.STAFF)
        self.manager = AccessContext(actor_id="manager.user", role=GovernanceRole.MANAGER)
        self.moderator = AccessContext(actor_id="moderator.user", role=GovernanceRole.MODERATOR)

    def _repo_path(self, root: str) -> Path:
        return Path(root) / "supplier-seed.json"

    def _engine_for_path(self, root: str) -> SupplierSeedEngine:
        return SupplierSeedEngine(
            repository=JsonFileSupplierRepository(self._repo_path(root)),
            policy_engine=self.policy_engine,
        )

    def _manual_candidate(self, name: str) -> SupplierCandidateInput:
        return SupplierCandidateInput(
            name=name,
            mode=SupplierMode.MANUAL,
            region_context=self.ncr_region,
            created_by=self.staff.actor_id,
        )

    def _approved_manual_supplier(self, engine: SupplierSeedEngine, *, name: str) -> str:
        staged = engine.ingest_supplier(
            self._manual_candidate(name),
            context=self.policy_context,
            access_context=self.staff,
        )
        supplier_id = staged.supplier.identity.supplier_id
        engine.accept_legal(
            supplier_id,
            version="v2026.04",
            actor=self.manager.actor_id,
            context=self.policy_context,
            access_context=self.manager,
        )
        engine.submit_for_review(
            supplier_id,
            actor=self.staff.actor_id,
            context=self.policy_context,
            access_context=self.staff,
        )
        engine.approve_moderation(
            supplier_id,
            actor=self.moderator.actor_id,
            context=self.policy_context,
            access_context=self.moderator,
        )
        return supplier_id

    def test_ingest_from_source_retries_transient_failure_and_persists_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = self._engine_for_path(tmpdir)
            source = FlakyCandidateSource(
                [self._manual_candidate("Retry Source Supplier")],
                failures_before_success=2,
            )

            result = engine.ingest_from_source(
                source,
                context=self.policy_context,
                access_context=self.staff,
                retry_policy=RetryPolicy(max_attempts=3, backoff_seconds=0.0),
            )

            self.assertEqual(source.calls, 3)
            self.assertEqual(result.allowed_count, 1)
            self.assertEqual(len(tuple(engine.repository.list_suppliers())), 1)

    def test_source_failure_after_retry_does_not_corrupt_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = self._engine_for_path(tmpdir)
            engine.ingest_supplier(
                self._manual_candidate("Stable Existing Supplier"),
                context=self.policy_context,
                access_context=self.staff,
            )
            before_supplier_ids = [item.identity.supplier_id for item in engine.repository.list_suppliers()]
            before_event_ids = [item.event_id for item in engine.repository.list_audit_events()]

            source = FlakyCandidateSource(
                [self._manual_candidate("Never Reached")],
                failures_before_success=10,
            )
            with self.assertRaises(TimeoutError):
                engine.ingest_from_source(
                    source,
                    context=self.policy_context,
                    access_context=self.staff,
                    retry_policy=RetryPolicy(max_attempts=3, backoff_seconds=0.0),
                )

            after_supplier_ids = [item.identity.supplier_id for item in engine.repository.list_suppliers()]
            after_event_ids = [item.event_id for item in engine.repository.list_audit_events()]
            self.assertEqual(after_supplier_ids, before_supplier_ids)
            self.assertEqual(after_event_ids, before_event_ids)

    def test_idempotent_manual_ingestion_reuses_original_supplier_and_events_across_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine1 = self._engine_for_path(tmpdir)
            first = engine1.ingest_supplier(
                self._manual_candidate("Idempotent Manual Supplier"),
                context=self.policy_context,
                access_context=self.staff,
                idempotency_key="ingest:manual:001",
            )
            first_event_ids = [item.event_id for item in first.events]
            first_supplier_id = first.supplier.identity.supplier_id

            engine2 = self._engine_for_path(tmpdir)
            second = engine2.ingest_supplier(
                self._manual_candidate("Idempotent Manual Supplier"),
                context=self.policy_context,
                access_context=self.staff,
                idempotency_key="ingest:manual:001",
            )

            self.assertEqual(second.supplier.identity.supplier_id, first_supplier_id)
            self.assertEqual([item.event_id for item in second.events], first_event_ids)
            self.assertEqual(len(tuple(engine2.repository.list_suppliers())), 1)
            staged_events = [
                item
                for item in engine2.repository.list_audit_events(first_supplier_id)
                if item.event_type is GovernanceEventType.SUPPLIER_STAGED
            ]
            self.assertEqual(len(staged_events), 1)

    def test_idempotent_moderation_approval_reuses_original_event_without_duplication(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine1 = self._engine_for_path(tmpdir)
            supplier_id = engine1.ingest_supplier(
                self._manual_candidate("Idempotent Moderation Supplier"),
                context=self.policy_context,
                access_context=self.staff,
            ).supplier.identity.supplier_id
            engine1.accept_legal(
                supplier_id,
                version="v2026.04",
                actor=self.manager.actor_id,
                context=self.policy_context,
                access_context=self.manager,
                idempotency_key="legal:001",
            )
            engine1.submit_for_review(
                supplier_id,
                actor=self.staff.actor_id,
                context=self.policy_context,
                access_context=self.staff,
                idempotency_key="submit:001",
            )
            first = engine1.approve_moderation(
                supplier_id,
                actor=self.moderator.actor_id,
                context=self.policy_context,
                access_context=self.moderator,
                idempotency_key="moderation:approve:001",
            )
            first_event_ids = [item.event_id for item in first.events]

            engine2 = self._engine_for_path(tmpdir)
            second = engine2.approve_moderation(
                supplier_id,
                actor=self.moderator.actor_id,
                context=self.policy_context,
                access_context=self.moderator,
                idempotency_key="moderation:approve:001",
            )

            self.assertEqual([item.event_id for item in second.events], first_event_ids)
            approved_events = [
                item
                for item in engine2.repository.list_audit_events(supplier_id)
                if item.event_type is GovernanceEventType.MODERATION_APPROVED
            ]
            self.assertEqual(len(approved_events), 1)

    def test_idempotent_activation_reuses_original_transition_without_duplication(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            engine1 = self._engine_for_path(tmpdir)
            supplier_id = self._approved_manual_supplier(engine1, name="Idempotent Activation Supplier")
            first = engine1.activate_supplier(
                supplier_id,
                actor=self.manager.actor_id,
                context=self.policy_context,
                access_context=self.manager,
                idempotency_key="activation:001",
            )
            first_event_ids = [item.event_id for item in first.events]

            engine2 = self._engine_for_path(tmpdir)
            second = engine2.activate_supplier(
                supplier_id,
                actor=self.manager.actor_id,
                context=self.policy_context,
                access_context=self.manager,
                idempotency_key="activation:001",
            )

            self.assertTrue(second.allowed)
            self.assertEqual([item.event_id for item in second.events], first_event_ids)
            lifecycle_events = [
                item
                for item in engine2.repository.list_audit_events(supplier_id)
                if item.event_type is GovernanceEventType.LIFECYCLE_STATUS_CHANGED
            ]
            self.assertEqual(len(lifecycle_events), 1)


if __name__ == "__main__":
    unittest.main()
