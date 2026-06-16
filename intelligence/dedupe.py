"""Deterministic duplicate matching for supplier records."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Optional

from supplier_seed.domain.enums import DedupeMatchClassification
from supplier_seed.domain.models import SupplierRecord
from supplier_seed.intelligence.normalization import NormalizedSupplierProfile, SupplierNormalizer


@dataclass(frozen=True, slots=True)
class DuplicateSignal:
    code: str
    message: str
    weight: int
    field: Optional[str] = None


@dataclass(frozen=True, slots=True)
class SupplierMatchCandidate:
    supplier: SupplierRecord
    normalized_profile: NormalizedSupplierProfile
    score: int
    classification: DedupeMatchClassification
    signals: tuple[DuplicateSignal, ...] = ()

    @property
    def is_duplicate_candidate(self) -> bool:
        return self.classification is not DedupeMatchClassification.DISTINCT


@dataclass(frozen=True, slots=True)
class DedupeEvaluation:
    target_supplier: SupplierRecord
    target_profile: NormalizedSupplierProfile
    candidates: tuple[SupplierMatchCandidate, ...] = ()

    @property
    def best_candidate(self) -> Optional[SupplierMatchCandidate]:
        return self.candidates[0] if self.candidates else None


class SupplierDedupeEngine:
    """Produces deterministic duplicate classifications from normalized supplier profiles."""

    def __init__(self, *, normalizer: Optional[SupplierNormalizer] = None) -> None:
        self.normalizer = normalizer or SupplierNormalizer()

    def evaluate_supplier(
        self,
        supplier: SupplierRecord,
        existing_suppliers: Iterable[SupplierRecord],
    ) -> DedupeEvaluation:
        target_profile = self.normalizer.normalize_supplier(supplier)
        candidates: list[SupplierMatchCandidate] = []
        for existing in existing_suppliers:
            if existing.identity.supplier_id == supplier.identity.supplier_id:
                continue
            candidate = self.compare_suppliers(supplier, existing, left_profile=target_profile)
            if candidate.classification is not DedupeMatchClassification.DISTINCT:
                candidates.append(candidate)
        candidates.sort(key=lambda item: (-item.score, item.supplier.name.lower(), item.supplier.identity.supplier_id))
        return DedupeEvaluation(
            target_supplier=supplier,
            target_profile=target_profile,
            candidates=tuple(candidates),
        )

    def compare_suppliers(
        self,
        left: SupplierRecord,
        right: SupplierRecord,
        *,
        left_profile: Optional[NormalizedSupplierProfile] = None,
        right_profile: Optional[NormalizedSupplierProfile] = None,
    ) -> SupplierMatchCandidate:
        left_profile = left_profile or self.normalizer.normalize_supplier(left)
        right_profile = right_profile or self.normalizer.normalize_supplier(right)

        signals: list[DuplicateSignal] = []
        score = 0

        if (
            left_profile.normalized_tax_identifier
            and left_profile.normalized_tax_identifier == right_profile.normalized_tax_identifier
        ):
            signals.append(
                DuplicateSignal(
                    code="dedupe.tax_identifier.exact",
                    field="tax_identifier",
                    weight=100,
                    message="Tax identifiers match exactly.",
                )
            )
            score += 100

        if (
            left_profile.normalized_seeded_reference
            and left_profile.normalized_seeded_reference == right_profile.normalized_seeded_reference
        ):
            signals.append(
                DuplicateSignal(
                    code="dedupe.seeded_reference.exact",
                    field="seeded_source_reference",
                    weight=100,
                    message="Seeded source and source reference match exactly.",
                )
            )
            score += 100

        if left_profile.comparable_name and left_profile.comparable_name == right_profile.comparable_name:
            signals.append(
                DuplicateSignal(
                    code="dedupe.name.exact",
                    field="name",
                    weight=35,
                    message="Comparable supplier names match exactly.",
                )
            )
            score += 35
        else:
            ratio = self._similarity(left_profile.comparable_name, right_profile.comparable_name)
            if ratio >= 0.94:
                signals.append(
                    DuplicateSignal(
                        code="dedupe.name.high_similarity",
                        field="name",
                        weight=25,
                        message="Comparable supplier names are highly similar.",
                    )
                )
                score += 25
            elif ratio >= 0.88:
                signals.append(
                    DuplicateSignal(
                        code="dedupe.name.medium_similarity",
                        field="name",
                        weight=15,
                        message="Comparable supplier names are moderately similar.",
                    )
                )
                score += 15

        if left_profile.normalized_email and left_profile.normalized_email == right_profile.normalized_email:
            signals.append(
                DuplicateSignal(
                    code="dedupe.email.exact",
                    field="contact_email",
                    weight=40,
                    message="Contact email matches exactly.",
                )
            )
            score += 40

        if left_profile.normalized_phone and left_profile.normalized_phone == right_profile.normalized_phone:
            signals.append(
                DuplicateSignal(
                    code="dedupe.phone.exact",
                    field="contact_phone",
                    weight=35,
                    message="Contact phone matches exactly.",
                )
            )
            score += 35

        if (
            left_profile.normalized_website_host
            and left_profile.normalized_website_host == right_profile.normalized_website_host
        ):
            signals.append(
                DuplicateSignal(
                    code="dedupe.website.exact",
                    field="website_url",
                    weight=25,
                    message="Website host matches exactly.",
                )
            )
            score += 25

        if left_profile.region_code and left_profile.region_code == right_profile.region_code:
            signals.append(
                DuplicateSignal(
                    code="dedupe.region.same",
                    field="region_context.region_code",
                    weight=5,
                    message="Region matches.",
                )
            )
            score += 5

        classification = self._classify(score)
        return SupplierMatchCandidate(
            supplier=right,
            normalized_profile=right_profile,
            score=score,
            classification=classification,
            signals=tuple(signals),
        )

    @staticmethod
    def _similarity(left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        return SequenceMatcher(a=left, b=right).ratio()

    @staticmethod
    def _classify(score: int) -> DedupeMatchClassification:
        if score >= 100:
            return DedupeMatchClassification.EXACT_DUPLICATE
        if score >= 70:
            return DedupeMatchClassification.LIKELY_DUPLICATE
        if score >= 40:
            return DedupeMatchClassification.POSSIBLE_DUPLICATE
        return DedupeMatchClassification.DISTINCT
