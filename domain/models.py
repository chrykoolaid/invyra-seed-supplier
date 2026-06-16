"""Core supplier domain models and value objects."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from supplier_seed.domain.enums import (
    LegalAcceptanceState,
    LifecycleStatus,
    ModerationStatus,
    SupplierMode,
    VerificationStatus,
    VerificationVisibility,
)


UTC = timezone.utc


def _clean_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_required_text(value: str) -> str:
    return value.strip()


def _normalize_code(value: Optional[str], *, default: Optional[str] = None) -> Optional[str]:
    cleaned = _clean_optional_text(value)
    if cleaned is None:
        return default
    return cleaned.upper()


def _normalize_datetime(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class SupplierIdentity:
    supplier_id: str
    supplier_code: Optional[str] = None
    external_reference: Optional[str] = None

    def __post_init__(self) -> None:
        supplier_id = _clean_required_text(self.supplier_id)
        if not supplier_id:
            raise ValueError("supplier_id is required")
        object.__setattr__(self, "supplier_id", supplier_id)
        object.__setattr__(self, "supplier_code", _clean_optional_text(self.supplier_code))
        object.__setattr__(self, "external_reference", _clean_optional_text(self.external_reference))

    @classmethod
    def new(cls, supplier_code: Optional[str] = None, external_reference: Optional[str] = None) -> "SupplierIdentity":
        return cls(supplier_id=str(uuid4()), supplier_code=supplier_code, external_reference=external_reference)


@dataclass(frozen=True, slots=True)
class SupplierRegionContext:
    region_code: Optional[str] = None
    market_code: str = "PH"
    pilot_name: Optional[str] = None
    pilot_enabled: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "region_code", _normalize_code(self.region_code))
        object.__setattr__(self, "market_code", _normalize_code(self.market_code, default="PH") or "PH")
        object.__setattr__(self, "pilot_name", _clean_optional_text(self.pilot_name))


@dataclass(frozen=True, slots=True)
class SupplierRecord:
    identity: SupplierIdentity
    name: str
    mode: SupplierMode
    lifecycle_status: LifecycleStatus = LifecycleStatus.DRAFT
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    verification_visibility: VerificationVisibility = VerificationVisibility.HIDDEN
    moderation_status: ModerationStatus = ModerationStatus.NOT_REVIEWED
    legal_acceptance_state: LegalAcceptanceState = LegalAcceptanceState.NOT_REQUIRED
    region_context: SupplierRegionContext = field(default_factory=SupplierRegionContext)
    seeded_source: Optional[str] = None
    seeded_source_reference: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    website_url: Optional[str] = None
    tax_identifier: Optional[str] = None
    pilot_terms_accepted_version: Optional[str] = None
    pilot_terms_accepted_at: Optional[datetime] = None
    pilot_terms_accepted_by: Optional[str] = None
    pilot_enabled_at: Optional[datetime] = None
    pilot_enabled_by: Optional[str] = None
    pilot_disabled_at: Optional[datetime] = None
    pilot_disabled_by: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    last_reviewed_at: Optional[datetime] = None
    last_reviewed_by: Optional[str] = None
    activated_at: Optional[datetime] = None
    suspended_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    provenance_last_updated_at: Optional[datetime] = None
    provenance_last_updated_by: Optional[str] = None
    legal_acceptance_version: Optional[str] = None
    legal_last_updated_at: Optional[datetime] = None
    legal_last_updated_by: Optional[str] = None
    verification_assigned_to: Optional[str] = None
    verification_assigned_at: Optional[datetime] = None
    verification_last_updated_at: Optional[datetime] = None
    verification_last_updated_by: Optional[str] = None
    verification_visibility_last_updated_at: Optional[datetime] = None
    verification_visibility_last_updated_by: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _clean_required_text(self.name))
        object.__setattr__(self, "seeded_source", _clean_optional_text(self.seeded_source))
        object.__setattr__(self, "seeded_source_reference", _clean_optional_text(self.seeded_source_reference))
        object.__setattr__(self, "contact_email", _clean_optional_text(self.contact_email))
        object.__setattr__(self, "contact_phone", _clean_optional_text(self.contact_phone))
        object.__setattr__(self, "website_url", _clean_optional_text(self.website_url))
        object.__setattr__(self, "tax_identifier", _clean_optional_text(self.tax_identifier))
        object.__setattr__(self, "pilot_terms_accepted_version", _clean_optional_text(self.pilot_terms_accepted_version))
        object.__setattr__(self, "pilot_terms_accepted_by", _clean_optional_text(self.pilot_terms_accepted_by))
        object.__setattr__(self, "pilot_enabled_by", _clean_optional_text(self.pilot_enabled_by))
        object.__setattr__(self, "pilot_disabled_by", _clean_optional_text(self.pilot_disabled_by))
        object.__setattr__(self, "created_by", _clean_optional_text(self.created_by))
        object.__setattr__(self, "updated_by", _clean_optional_text(self.updated_by))
        object.__setattr__(self, "last_reviewed_by", _clean_optional_text(self.last_reviewed_by))
        object.__setattr__(self, "provenance_last_updated_by", _clean_optional_text(self.provenance_last_updated_by))
        object.__setattr__(self, "legal_acceptance_version", _clean_optional_text(self.legal_acceptance_version))
        object.__setattr__(self, "legal_last_updated_by", _clean_optional_text(self.legal_last_updated_by))
        object.__setattr__(self, "verification_assigned_to", _clean_optional_text(self.verification_assigned_to))
        object.__setattr__(self, "verification_last_updated_by", _clean_optional_text(self.verification_last_updated_by))
        object.__setattr__(
            self,
            "verification_visibility_last_updated_by",
            _clean_optional_text(self.verification_visibility_last_updated_by),
        )

        created_at = _normalize_datetime(self.created_at)
        updated_at = _normalize_datetime(self.updated_at)
        if created_at is None or updated_at is None:
            raise ValueError("created_at and updated_at are required")
        if updated_at < created_at:
            raise ValueError("updated_at cannot be earlier than created_at")

        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "last_reviewed_at", _normalize_datetime(self.last_reviewed_at))
        object.__setattr__(self, "activated_at", _normalize_datetime(self.activated_at))
        object.__setattr__(self, "suspended_at", _normalize_datetime(self.suspended_at))
        object.__setattr__(self, "archived_at", _normalize_datetime(self.archived_at))
        object.__setattr__(self, "pilot_terms_accepted_at", _normalize_datetime(self.pilot_terms_accepted_at))
        object.__setattr__(self, "pilot_enabled_at", _normalize_datetime(self.pilot_enabled_at))
        object.__setattr__(self, "pilot_disabled_at", _normalize_datetime(self.pilot_disabled_at))
        object.__setattr__(self, "provenance_last_updated_at", _normalize_datetime(self.provenance_last_updated_at))
        object.__setattr__(self, "legal_last_updated_at", _normalize_datetime(self.legal_last_updated_at))
        object.__setattr__(self, "verification_assigned_at", _normalize_datetime(self.verification_assigned_at))
        object.__setattr__(self, "verification_last_updated_at", _normalize_datetime(self.verification_last_updated_at))
        object.__setattr__(
            self,
            "verification_visibility_last_updated_at",
            _normalize_datetime(self.verification_visibility_last_updated_at),
        )

    @property
    def is_seeded(self) -> bool:
        return self.mode is SupplierMode.SEEDED

    @property
    def is_manual(self) -> bool:
        return self.mode is SupplierMode.MANUAL

    @property
    def is_operational(self) -> bool:
        return self.lifecycle_status is LifecycleStatus.ACTIVE

    @property
    def has_seeded_provenance(self) -> bool:
        return bool(self.seeded_source and self.seeded_source_reference)

    @property
    def has_region(self) -> bool:
        return bool(self.region_context.region_code)

    @property
    def has_verification_assignee(self) -> bool:
        return bool(self.verification_assigned_to)

    @property
    def has_pilot_terms_accepted(self) -> bool:
        return bool(self.pilot_terms_accepted_version and self.pilot_terms_accepted_at)

    @property
    def is_pilot_enabled(self) -> bool:
        return self.region_context.pilot_enabled

    @property
    def is_verification_visible(self) -> bool:
        return self.verification_visibility is VerificationVisibility.VISIBLE

    @classmethod
    def manual_draft(
        cls,
        *,
        name: str,
        region_context: SupplierRegionContext,
        created_by: Optional[str] = None,
        identity: Optional[SupplierIdentity] = None,
        contact_email: Optional[str] = None,
        contact_phone: Optional[str] = None,
        website_url: Optional[str] = None,
        tax_identifier: Optional[str] = None,
    ) -> "SupplierRecord":
        timestamp = datetime.now(tz=UTC)
        return cls(
            identity=identity or SupplierIdentity.new(),
            name=name,
            mode=SupplierMode.MANUAL,
            lifecycle_status=LifecycleStatus.DRAFT,
            verification_status=VerificationStatus.UNVERIFIED,
            verification_visibility=VerificationVisibility.HIDDEN,
            moderation_status=ModerationStatus.NOT_REVIEWED,
            legal_acceptance_state=LegalAcceptanceState.REQUIRED_MISSING,
            region_context=region_context,
            contact_email=contact_email,
            contact_phone=contact_phone,
            website_url=website_url,
            tax_identifier=tax_identifier,
            created_at=timestamp,
            updated_at=timestamp,
            created_by=created_by,
            updated_by=created_by,
        )

    @classmethod
    def seeded_draft(
        cls,
        *,
        name: str,
        seeded_source: str,
        seeded_source_reference: str,
        region_context: SupplierRegionContext,
        created_by: Optional[str] = None,
        identity: Optional[SupplierIdentity] = None,
        contact_email: Optional[str] = None,
        contact_phone: Optional[str] = None,
        website_url: Optional[str] = None,
        tax_identifier: Optional[str] = None,
    ) -> "SupplierRecord":
        timestamp = datetime.now(tz=UTC)
        return cls(
            identity=identity or SupplierIdentity.new(),
            name=name,
            mode=SupplierMode.SEEDED,
            lifecycle_status=LifecycleStatus.DRAFT,
            verification_status=VerificationStatus.UNVERIFIED,
            verification_visibility=VerificationVisibility.HIDDEN,
            moderation_status=ModerationStatus.PENDING_REVIEW,
            legal_acceptance_state=LegalAcceptanceState.NOT_REQUIRED,
            region_context=region_context,
            seeded_source=seeded_source,
            seeded_source_reference=seeded_source_reference,
            contact_email=contact_email,
            contact_phone=contact_phone,
            website_url=website_url,
            tax_identifier=tax_identifier,
            created_at=timestamp,
            updated_at=timestamp,
            created_by=created_by,
            updated_by=created_by,
            provenance_last_updated_at=timestamp,
            provenance_last_updated_by=created_by,
        )

    def with_updated_metadata(self, *, actor: Optional[str], at: Optional[datetime] = None) -> "SupplierRecord":
        timestamp = _normalize_datetime(at) or datetime.now(tz=UTC)
        return replace(self, updated_at=timestamp, updated_by=actor)

    def with_governance_update(
        self,
        *,
        actor: Optional[str],
        at: Optional[datetime] = None,
        **changes: object,
    ) -> "SupplierRecord":
        timestamp = _normalize_datetime(at) or datetime.now(tz=UTC)
        return replace(self, updated_at=timestamp, updated_by=actor, **changes)
