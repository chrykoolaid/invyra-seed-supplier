from dataclasses import dataclass
from typing import Optional, Tuple

from supplier_seed.domain.enums import DedupeMatchClassification
from supplier_seed.intelligence.normalization import SupplierNormalizer


@dataclass(frozen=True)
class DuplicateSignal:
    code: str
    weight: float
    message: str = ""


@dataclass(frozen=True)
class SupplierMatchCandidate:
    supplier: object
    classification: DedupeMatchClassification
    confidence: float
    signals: Tuple[DuplicateSignal, ...]

    @property
    def score(self) -> int:
        return round(self.confidence * 100)


@dataclass(frozen=True)
class DedupeEvaluation:
    best_candidate: Optional[SupplierMatchCandidate]
    candidates: Tuple[SupplierMatchCandidate, ...]


class SupplierDedupeEngine:
    def __init__(self, normalizer=None):
        self.normalizer = normalizer or SupplierNormalizer()

    @staticmethod
    def _reference_key(value):
        return "".join(ch for ch in (value or "").lower() if ch.isalnum())

    def evaluate_supplier(self, target, existing_suppliers):
        target_profile = self.normalizer.normalize_supplier(target)
        candidates = []
        for existing in existing_suppliers:
            if existing.supplier_id == target.supplier_id:
                continue
            profile = self.normalizer.normalize_supplier(existing)
            signals = []
            score = 0.0
            target_reference = self._reference_key(target.seeded_source_reference)
            existing_reference = self._reference_key(existing.seeded_source_reference)
            target_source = self._reference_key(target.seeded_source)
            existing_source = self._reference_key(existing.seeded_source)
            if target_reference and target_reference == existing_reference and target_source == existing_source:
                signals.append(DuplicateSignal("dedupe.seeded_reference.exact", 1.0))
                score = 1.0
            elif target_profile.normalized_tax_identifier and target_profile.normalized_tax_identifier == profile.normalized_tax_identifier:
                signals.append(DuplicateSignal("dedupe.tax_identifier.exact", 1.0))
                score = 1.0
            elif target_profile.normalized_email and target_profile.normalized_email == profile.normalized_email and target_profile.comparable_name == profile.comparable_name:
                signals.append(DuplicateSignal("dedupe.name_email.match", 0.86))
                score = 0.86
            elif target_profile.normalized_email and target_profile.normalized_email == profile.normalized_email:
                signals.append(DuplicateSignal("dedupe.email.shared", 0.55))
                score = 0.55
            elif target_profile.comparable_name and target_profile.comparable_name == profile.comparable_name:
                signals.append(DuplicateSignal("dedupe.name.match", 0.6))
                score = 0.6
            if not signals:
                continue
            classification = (
                DedupeMatchClassification.EXACT_DUPLICATE if score >= 0.95
                else DedupeMatchClassification.LIKELY_DUPLICATE if score >= 0.8
                else DedupeMatchClassification.POSSIBLE_DUPLICATE
            )
            candidates.append(SupplierMatchCandidate(existing, classification, score, tuple(signals)))
        candidates.sort(key=lambda item: item.confidence, reverse=True)
        return DedupeEvaluation(candidates[0] if candidates else None, tuple(candidates))
