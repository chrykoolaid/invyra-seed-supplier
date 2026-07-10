from __future__ import annotations
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Optional
from uuid import uuid4
from supplier_seed.domain.enums import SupplierMode, LifecycleStatus, ModerationStatus, LegalAcceptanceState, VerificationStatus, VerificationVisibility

def _clean(v): return v.strip() if isinstance(v, str) else v
def _upper(v): return _clean(v).upper() if isinstance(v, str) and _clean(v) else None

@dataclass(frozen=True)
class SupplierRegionContext:
    region_code: Optional[str] = None
    market_code: str = "PH"
    pilot_enabled: bool = False
    pilot_name: Optional[str] = None
    def __post_init__(self):
        object.__setattr__(self, "region_code", _upper(self.region_code))
        object.__setattr__(self, "market_code", _upper(self.market_code) or "PH")
        object.__setattr__(self, "pilot_name", _clean(self.pilot_name))

@dataclass(frozen=True)
class SupplierIdentity:
    supplier_id: str = field(default_factory=lambda: str(uuid4()))
    external_reference: Optional[str] = None

@dataclass(frozen=True)
class SupplierRecord:
    supplier_id: str
    name: str
    mode: SupplierMode
    region_context: SupplierRegionContext
    lifecycle_status: LifecycleStatus = LifecycleStatus.DRAFT
    moderation_status: ModerationStatus = ModerationStatus.NOT_REVIEWED
    legal_acceptance_state: LegalAcceptanceState = LegalAcceptanceState.NOT_ACCEPTED
    verification_status: VerificationStatus = VerificationStatus.NOT_VERIFIED
    verification_visibility: VerificationVisibility = VerificationVisibility.INTERNAL_ONLY
    seeded_source: Optional[str] = None
    seeded_source_reference: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    website_url: Optional[str] = None
    tax_identifier: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    activated_at: Optional[datetime] = None
    legal_acceptance_version: Optional[str] = None
    assigned_verifier: Optional[str] = None
    assigned_at: Optional[datetime] = None
    last_reviewed_at: Optional[datetime] = None
    last_reviewed_by: Optional[str] = None
    pilot_terms_accepted_version: Optional[str] = None
    pilot_terms_accepted_by: Optional[str] = None
    pilot_terms_accepted_at: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "name", _clean(self.name) or "")
        if isinstance(self.mode, str): object.__setattr__(self, "mode", SupplierMode(self.mode))
        if isinstance(self.verification_visibility, str): object.__setattr__(self, "verification_visibility", VerificationVisibility(self.verification_visibility))
        for attr in ("created_by", "updated_by", "contact_email", "contact_phone", "website_url", "tax_identifier", "seeded_source", "seeded_source_reference", "assigned_verifier", "pilot_terms_accepted_version", "pilot_terms_accepted_by"):
            object.__setattr__(self, attr, _clean(getattr(self, attr)))

    @property
    def identity(self): return SupplierIdentity(supplier_id=self.supplier_id, external_reference=self.seeded_source_reference)
    @property
    def verification_assigned_to(self): return self.assigned_verifier
    @property
    def is_seeded(self): return self.mode == SupplierMode.SEEDED
    @property
    def is_manual(self): return self.mode == SupplierMode.MANUAL

    @classmethod
    def manual_draft(cls, name: str, region_context: SupplierRegionContext, **kw):
        return cls(kw.pop("supplier_id", str(uuid4())), name, SupplierMode.MANUAL, region_context, **kw)
    @classmethod
    def seeded_draft(cls, name: str, seeded_source: str, seeded_source_reference: str, region_context: SupplierRegionContext, **kw):
        return cls(kw.pop("supplier_id", str(uuid4())), name, SupplierMode.SEEDED, region_context, seeded_source=_clean(seeded_source), seeded_source_reference=_clean(seeded_source_reference), legal_acceptance_state=LegalAcceptanceState.NOT_REQUIRED, **kw)
    def with_updated_metadata(self, actor: Optional[str] = None):
        return replace(self, updated_by=_clean(actor), updated_at=datetime.utcnow())
