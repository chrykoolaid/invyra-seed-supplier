import unittest

from supplier_seed.domain.enums import (
    GovernanceEventType,
    LifecycleStatus,
    ModerationStatus,
    SupplierMode,
    VerificationStatus,
)
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine
from supplier_seed.repository.memory_impl import InMemorySupplierRepository
from supplier_seed.services.permissions import AccessContext, GovernanceRole


class SupplierSeedPartNTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ncr_region = SupplierRegionContext(region_code="NCR", market_code="PH", pilot_enabled=True)
        self.ceb_region = SupplierRegionContext(region_code="CEB", market_code="PH", pilot_enabled=True)
        self.policy_context = PolicyContext(
            region_code="NCR",
            market_code="PH",
            pilot_enabled=True,
            allow_seeded_supplier_creation=True,
            require_region_for_supplier=True,
            require_legal_acceptance_for_manual=True,
            require_moderation_for_seeded_activation=True,
            require_actor_for_moderation_actions=True,
            require_actor_for_legal_actions=True,
            require_actor_for_verification_actions=True,
            require_assignment_for_verification_decisions=True,
            require_assignment_match_for_verification_decisions=True,
            require_verified_status_for_visible_verification=True,
        )
        self.policy_engine = SupplierPolicyEngine()
        self.repo = InMemorySupplierRepository()
        self.engine = SupplierSeedEngine(repository=self.repo, policy_engine=self.policy_engine)

        self.admin = AccessContext(actor_id="admin.user", role=GovernanceRole.ADMIN)
        self.manager = AccessContext(actor_id="manager.user", role=GovernanceRole.MANAGER)
        self.moderator = AccessContext(actor_id="moderator.user", role=GovernanceRole.MODERATOR)
        self.staff = AccessContext(actor_id="staff.user", role=GovernanceRole.STAFF)

    def _ingest_manual_supplier(self, *, name: str, region: SupplierRegionContext | None = None) -> str:
        result = self.engine.ingest_supplier(
            SupplierCandidateInput(
                name=name,
                mode=SupplierMode.MANUAL,
                region_context=region or self.ncr_region,
                created_by=self.staff.actor_id,
            ),
            context=self.policy_context,
            access_context=self.staff,
        )
        self.assertTrue(result.accepted_for_staging)
        return result.supplier.identity.supplier_id

    def _ingest_seeded_supplier(self, *, name: str, region: SupplierRegionContext | None = None, source: str = "dti") -> str:
        result = self.engine.ingest_supplier(
            SupplierCandidateInput(
                name=name,
                mode=SupplierMode.SEEDED,
                region_context=region or self.ncr_region,
                created_by=self.manager.actor_id,
                seeded_source=source,
                seeded_source_reference=f"ref-{name.lower().replace(' ', '-')}",
            ),
            context=self.policy_context,
            access_context=self.manager,
        )
        self.assertTrue(result.accepted_for_staging)
        return result.supplier.identity.supplier_id

    def _approve_manual_supplier(self, *, name: str, region: SupplierRegionContext | None = None) -> str:
        supplier_id = self._ingest_manual_supplier(name=name, region=region)
        self.engine.accept_legal(
            supplier_id,
            version="v2026.04",
            actor=self.manager.actor_id,
            context=self.policy_context,
            access_context=self.manager,
        )
        self.engine.submit_for_review(
            supplier_id,
            actor=self.staff.actor_id,
            context=self.policy_context,
            access_context=self.staff,
        )
        self.engine.approve_moderation(
            supplier_id,
            actor=self.moderator.actor_id,
            context=self.policy_context,
            access_context=self.moderator,
        )
        return supplier_id

    def test_search_suppliers_supports_name_region_status_and_source_filters(self) -> None:
        seeded_id = self._ingest_seeded_supplier(name="Metro Foods Seed", region=self.ncr_region, source="dti")
        manual_id = self._approve_manual_supplier(name="Laguna Parts Manual", region=self.ceb_region)

        seeded_results = self.engine.search_suppliers(
            context=self.policy_context,
            search="metro",
            region_code="NCR",
            mode=SupplierMode.SEEDED,
            seeded_source="dti",
            access_context=self.manager,
        )
        self.assertEqual([item.supplier_id for item in seeded_results], [seeded_id])

        active_results = self.engine.search_suppliers(
            context=self.policy_context,
            lifecycle_status=LifecycleStatus.APPROVED,
            moderation_status=ModerationStatus.APPROVED,
            mode=SupplierMode.MANUAL,
            region_code="CEB",
            access_context=self.manager,
        )
        self.assertEqual([item.supplier_id for item in active_results], [manual_id])

    def test_moderation_queue_views_cover_open_pending_and_completed(self) -> None:
        pending_id = self._ingest_seeded_supplier(name="Queued Seeded Supplier")
        completed_id = self._approve_manual_supplier(name="Completed Moderation Supplier")

        open_cases = self.engine.list_moderation_queue(
            queue_bucket="open_cases",
            context=self.policy_context,
            access_context=self.manager,
        )
        pending_review = self.engine.list_moderation_queue(
            queue_bucket="pending_review",
            context=self.policy_context,
            access_context=self.manager,
        )
        completed = self.engine.list_moderation_queue(
            queue_bucket="completed",
            context=self.policy_context,
            access_context=self.manager,
        )

        self.assertIn(pending_id, {entry.summary.supplier_id for entry in open_cases})
        self.assertIn(pending_id, {entry.summary.supplier_id for entry in pending_review})
        self.assertIn(completed_id, {entry.summary.supplier_id for entry in completed})
        self.assertTrue(all(entry.queue_bucket == "completed" for entry in completed))

    def test_verification_queue_views_cover_eligible_pending_and_verified(self) -> None:
        eligible_id = self._approve_manual_supplier(name="Eligible Verification Supplier")

        pending_id = self._approve_manual_supplier(name="Pending Verification Supplier")
        self.engine.assign_verification(
            pending_id,
            assignee=self.moderator.actor_id,
            actor=self.manager.actor_id,
            context=self.policy_context,
            access_context=self.manager,
        )
        self.engine.mark_verification_pending(
            pending_id,
            actor=self.moderator.actor_id,
            context=self.policy_context,
            access_context=self.moderator,
        )

        verified_id = self._approve_manual_supplier(name="Verified Supplier")
        self.engine.assign_verification(
            verified_id,
            assignee=self.moderator.actor_id,
            actor=self.manager.actor_id,
            context=self.policy_context,
            access_context=self.manager,
        )
        self.engine.mark_verified(
            verified_id,
            actor=self.moderator.actor_id,
            context=self.policy_context,
            access_context=self.moderator,
        )

        eligible = self.engine.list_verification_queue(
            queue_bucket="eligible",
            context=self.policy_context,
            access_context=self.manager,
        )
        pending = self.engine.list_verification_queue(
            queue_bucket="pending",
            context=self.policy_context,
            access_context=self.manager,
        )
        verified = self.engine.list_verification_queue(
            queue_bucket="verified",
            context=self.policy_context,
            access_context=self.manager,
        )

        self.assertIn(eligible_id, {entry.summary.supplier_id for entry in eligible})
        self.assertIn(pending_id, {entry.summary.supplier_id for entry in pending})
        self.assertIn(verified_id, {entry.summary.supplier_id for entry in verified})
        pending_entry = next(entry for entry in pending if entry.summary.supplier_id == pending_id)
        self.assertEqual(pending_entry.assigned_to, self.moderator.actor_id)
        verified_entry = next(entry for entry in verified if entry.summary.supplier_id == verified_id)
        self.assertEqual(verified_entry.verification_status, VerificationStatus.VERIFIED)

    def test_supplier_detail_view_includes_provenance_status_history_verification_and_audit_summary(self) -> None:
        supplier_id = self._approve_manual_supplier(name="Detail Manual Supplier")
        self.engine.assign_verification(
            supplier_id,
            assignee=self.moderator.actor_id,
            actor=self.manager.actor_id,
            context=self.policy_context,
            access_context=self.manager,
        )
        self.engine.mark_verification_pending(
            supplier_id,
            actor=self.moderator.actor_id,
            context=self.policy_context,
            access_context=self.moderator,
        )

        detail = self.engine.get_supplier_detail(
            supplier_id,
            context=self.policy_context,
            access_context=self.manager,
        )

        self.assertEqual(detail.summary.supplier_id, supplier_id)
        self.assertEqual(detail.provenance.origin_label, "manual")
        self.assertIsNone(detail.provenance.seeded_source)
        self.assertEqual(detail.moderation.current_status, ModerationStatus.APPROVED)
        self.assertEqual(
            [event.event_type for event in detail.moderation.events],
            [GovernanceEventType.MODERATION_APPROVED, GovernanceEventType.MODERATION_SUBMITTED],
        )
        self.assertEqual(detail.verification.current_status, VerificationStatus.PENDING)
        self.assertEqual(detail.verification.assigned_to, self.moderator.actor_id)
        self.assertGreaterEqual(detail.audit_summary.total_events, 5)
        self.assertEqual(detail.audit_summary.latest_event_type, GovernanceEventType.VERIFICATION_PENDING)
        self.assertEqual(detail.timeline[0].event_type, GovernanceEventType.VERIFICATION_PENDING)

    def test_audit_timeline_supports_event_filtering_and_role_scoped_actor_visibility(self) -> None:
        supplier_id = self._approve_manual_supplier(name="Timeline Filter Supplier")
        self.engine.assign_verification(
            supplier_id,
            assignee=self.moderator.actor_id,
            actor=self.manager.actor_id,
            context=self.policy_context,
            access_context=self.manager,
        )
        self.engine.mark_verified(
            supplier_id,
            actor=self.moderator.actor_id,
            context=self.policy_context,
            access_context=self.moderator,
        )

        manager_timeline = self.engine.get_audit_timeline(
            supplier_id,
            event_type=GovernanceEventType.VERIFICATION_VERIFIED,
            access_context=self.manager,
        )
        staff_timeline = self.engine.get_audit_timeline(
            supplier_id,
            event_type=GovernanceEventType.VERIFICATION_VERIFIED,
            access_context=self.staff,
        )
        moderator_actor_view = self.engine.get_audit_timeline(
            supplier_id,
            actor=self.moderator.actor_id,
            access_context=self.manager,
        )

        self.assertEqual(len(manager_timeline), 1)
        self.assertEqual(manager_timeline[0].actor, self.moderator.actor_id)
        self.assertEqual(manager_timeline[0].metadata["to_status"], VerificationStatus.VERIFIED.value)
        self.assertEqual(len(staff_timeline), 1)
        self.assertIsNone(staff_timeline[0].actor)
        self.assertEqual(staff_timeline[0].metadata, {"redacted": True})
        self.assertTrue(all(entry.actor == self.moderator.actor_id for entry in moderator_actor_view))
        self.assertGreaterEqual(len(moderator_actor_view), 2)


if __name__ == "__main__":
    unittest.main()
