import unittest

from supplier_seed.domain.enums import GovernanceEventType, LifecycleStatus, SupplierMode, VerificationStatus
from supplier_seed.domain.models import SupplierRegionContext
from supplier_seed.engine import SupplierSeedEngine
from supplier_seed.ingestion.ingestion_service import SupplierCandidateInput
from supplier_seed.policy.rules import PolicyContext, SupplierPolicyEngine
from supplier_seed.repository.memory_impl import InMemorySupplierRepository
from supplier_seed.services.permissions import AccessContext, GovernanceRole


class SupplierSeedPartMTests(unittest.TestCase):
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

    def _ingest_manual_supplier(self, name: str = "Part M Manual Supplier") -> str:
        result = self.engine.ingest_supplier(
            SupplierCandidateInput(
                name=name,
                mode=SupplierMode.MANUAL,
                region_context=self.region,
                created_by=self.staff.actor_id,
            ),
            context=self.policy_context,
            access_context=self.staff,
        )
        self.assertTrue(result.accepted_for_staging)
        return result.supplier.identity.supplier_id

    def test_staff_cannot_ingest_seeded_supplier_and_attempt_is_audited(self) -> None:
        result = self.engine.ingest_supplier(
            SupplierCandidateInput(
                name="Blocked Seeded Supplier",
                mode=SupplierMode.SEEDED,
                region_context=self.region,
                created_by=self.staff.actor_id,
                seeded_source="dti",
                seeded_source_reference="ref-001",
            ),
            context=self.policy_context,
            access_context=self.staff,
        )

        self.assertFalse(result.accepted_for_staging)
        self.assertEqual(result.events[-1].event_type, GovernanceEventType.GOVERNANCE_ACTION_BLOCKED)
        self.assertIn("permission.ingest_seeded_supplier.denied", [decision.code for decision in result.decisions])
        self.assertEqual(len(tuple(self.repo.list_suppliers())), 0)
        self.assertEqual(self.engine.list_audit_events()[-1].event_id, result.events[-1].event_id)

    def test_permission_matrix_blocks_staff_but_allows_manager_and_moderator_flows(self) -> None:
        supplier_id = self._ingest_manual_supplier(name="Permission Matrix Supplier")

        blocked_legal = self.engine.accept_legal(
            supplier_id,
            version="v2026.04",
            actor=self.staff.actor_id,
            context=self.policy_context,
            access_context=self.staff,
        )
        self.assertFalse(blocked_legal.allowed)
        self.assertIn("permission.accept_legal.denied", [issue.code for issue in blocked_legal.issues])
        self.assertEqual(blocked_legal.events[-1].event_type, GovernanceEventType.GOVERNANCE_ACTION_BLOCKED)

        accepted = self.engine.accept_legal(
            supplier_id,
            version="v2026.04",
            actor=self.manager.actor_id,
            context=self.policy_context,
            access_context=self.manager,
        )
        self.assertTrue(accepted.allowed)

        submitted = self.engine.submit_for_review(
            supplier_id,
            actor=self.staff.actor_id,
            context=self.policy_context,
            access_context=self.staff,
        )
        self.assertTrue(submitted.allowed)

        blocked_approval = self.engine.approve_moderation(
            supplier_id,
            actor=self.staff.actor_id,
            context=self.policy_context,
            access_context=self.staff,
        )
        self.assertFalse(blocked_approval.allowed)
        self.assertIn("permission.approve_moderation.denied", [issue.code for issue in blocked_approval.issues])

        approved = self.engine.approve_moderation(
            supplier_id,
            actor=self.moderator.actor_id,
            context=self.policy_context,
            access_context=self.moderator,
        )
        self.assertTrue(approved.allowed)
        self.assertEqual(self.engine.get_supplier_record(supplier_id).lifecycle_status, LifecycleStatus.APPROVED)

    def test_only_manager_or_admin_can_activate_supplier(self) -> None:
        supplier_id = self._ingest_manual_supplier(name="Activation Permission Supplier")
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

        blocked = self.engine.activate_supplier(
            supplier_id,
            actor=self.staff.actor_id,
            context=self.policy_context,
            access_context=self.staff,
        )
        self.assertFalse(blocked.allowed)
        self.assertIn("permission.activate_supplier.denied", [issue.code for issue in blocked.issues])
        self.assertEqual(blocked.events[-1].event_type, GovernanceEventType.GOVERNANCE_ACTION_BLOCKED)

        activated = self.engine.activate_supplier(
            supplier_id,
            actor=self.manager.actor_id,
            context=self.policy_context,
            access_context=self.manager,
        )
        self.assertTrue(activated.allowed)
        self.assertEqual(self.engine.get_supplier_record(supplier_id).lifecycle_status, LifecycleStatus.ACTIVE)

    def test_staff_read_models_redact_sensitive_verification_and_audit_details(self) -> None:
        supplier_id = self._ingest_manual_supplier(name="Read Redaction Supplier")
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
        self.engine.assign_verification(
            supplier_id,
            assignee=self.moderator.actor_id,
            actor=self.manager.actor_id,
            context=self.policy_context,
            access_context=self.manager,
        )
        failed = self.engine.mark_verification_failed(
            supplier_id,
            actor=self.moderator.actor_id,
            reason="document mismatch",
            context=self.policy_context,
            access_context=self.moderator,
        )
        self.assertTrue(failed.allowed)
        self.assertEqual(self.engine.get_supplier_record(supplier_id).verification_status, VerificationStatus.FAILED)

        blocked = self.engine.activate_supplier(
            supplier_id,
            actor=self.staff.actor_id,
            context=self.policy_context,
            access_context=self.staff,
        )
        self.assertFalse(blocked.allowed)

        manager_workspace = self.engine.get_supplier_workspace(
            supplier_id,
            context=self.policy_context,
            access_context=self.manager,
        )
        staff_workspace = self.engine.get_supplier_workspace(
            supplier_id,
            context=self.policy_context,
            access_context=self.staff,
        )

        manager_failed = next(item for item in manager_workspace.timeline if item.event_type is GovernanceEventType.VERIFICATION_FAILED)
        staff_failed = next(item for item in staff_workspace.timeline if item.event_type is GovernanceEventType.VERIFICATION_FAILED)
        self.assertEqual(manager_workspace.summary.assigned_verifier, self.moderator.actor_id)
        self.assertIsNone(staff_workspace.summary.assigned_verifier)
        self.assertEqual(manager_failed.metadata["reason"], "document mismatch")
        self.assertEqual(manager_failed.actor, self.moderator.actor_id)
        self.assertEqual(staff_failed.metadata, {"redacted": True})
        self.assertIsNone(staff_failed.actor)

        manager_blocked = next(item for item in manager_workspace.timeline if item.event_type is GovernanceEventType.GOVERNANCE_ACTION_BLOCKED)
        staff_blocked = next(item for item in staff_workspace.timeline if item.event_type is GovernanceEventType.GOVERNANCE_ACTION_BLOCKED)
        self.assertEqual(manager_blocked.metadata["action"], "activate_supplier")
        self.assertEqual(staff_blocked.metadata, {"redacted": True})
        self.assertIsNone(staff_blocked.actor)

        staff_events = self.engine.list_audit_events(supplier_id, access_context=self.staff)
        manager_events = self.engine.list_audit_events(supplier_id, access_context=self.manager)
        self.assertEqual(
            next(event for event in staff_events if event.event_type is GovernanceEventType.VERIFICATION_FAILED).metadata,
            {"redacted": True},
        )
        self.assertEqual(
            next(event for event in manager_events if event.event_type is GovernanceEventType.VERIFICATION_FAILED).metadata["reason"],
            "document mismatch",
        )


if __name__ == "__main__":
    unittest.main()
