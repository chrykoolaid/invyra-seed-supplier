"""Read models and query services for UI/workflow consumption.

This package intentionally stays read-only. It prepares stable, workflow-oriented views
for desktop/admin surfaces without introducing UI framework concerns into the engine.
"""

from supplier_seed.consumption.models import (
    SupplierAuditSummaryView,
    SupplierDetailView,
    SupplierModerationHistoryView,
    SupplierModerationQueueEntryView,
    SupplierProvenanceView,
    SupplierSummaryView,
    SupplierTimelineEntryView,
    SupplierVerificationOverviewView,
    SupplierVerificationQueueEntryView,
    SupplierWorkflowRequirementView,
    SupplierWorkspaceView,
)
from supplier_seed.consumption.query_service import SupplierConsumptionService

__all__ = [
    "SupplierAuditSummaryView",
    "SupplierConsumptionService",
    "SupplierDetailView",
    "SupplierModerationHistoryView",
    "SupplierModerationQueueEntryView",
    "SupplierProvenanceView",
    "SupplierSummaryView",
    "SupplierTimelineEntryView",
    "SupplierVerificationOverviewView",
    "SupplierVerificationQueueEntryView",
    "SupplierWorkflowRequirementView",
    "SupplierWorkspaceView",
]
