import unittest

from supplier_seed.domain.enums import DedupeMatchClassification
from supplier_seed.domain.models import SupplierRecord, SupplierRegionContext
from supplier_seed.intelligence.dedupe import SupplierDedupeEngine
from supplier_seed.intelligence.normalization import SupplierNormalizer


class SupplierSeedPartCTests(unittest.TestCase):
    def setUp(self) -> None:
        self.region = SupplierRegionContext(region_code="NCR", market_code="PH", pilot_enabled=True)
        self.normalizer = SupplierNormalizer()
        self.dedupe_engine = SupplierDedupeEngine(normalizer=self.normalizer)

    def test_normalizer_canonicalizes_name_phone_and_website(self) -> None:
        supplier = SupplierRecord.manual_draft(
            name="Ácme Trading Co., Inc.",
            region_context=self.region,
            contact_phone="0917-555-1234",
            website_url="https://www.Acme.com/suppliers",
            contact_email="Sales@Acme.com",
            tax_identifier="123-456-789-000",
        )
        profile = self.normalizer.normalize_supplier(supplier)
        self.assertEqual(profile.normalized_name, "acme trading co inc")
        self.assertEqual(profile.comparable_name, "acme trading")
        self.assertEqual(profile.normalized_phone, "+639175551234")
        self.assertEqual(profile.normalized_website_host, "acme.com")
        self.assertEqual(profile.normalized_email, "sales@acme.com")
        self.assertEqual(profile.normalized_tax_identifier, "123456789000")

    def test_exact_duplicate_detected_by_tax_identifier(self) -> None:
        target = SupplierRecord.manual_draft(
            name="Acme Corporation",
            region_context=self.region,
            tax_identifier="123-456-789-000",
        )
        existing = SupplierRecord.seeded_draft(
            name="ACME CORP.",
            seeded_source="gov_registry",
            seeded_source_reference="SUP-100",
            region_context=self.region,
            tax_identifier="123456789000",
        )
        evaluation = self.dedupe_engine.evaluate_supplier(target, [existing])
        self.assertEqual(evaluation.best_candidate.classification, DedupeMatchClassification.EXACT_DUPLICATE)
        self.assertEqual(evaluation.best_candidate.signals[0].code, "dedupe.tax_identifier.exact")

    def test_likely_duplicate_detected_by_name_and_email(self) -> None:
        target = SupplierRecord.manual_draft(
            name="Luna Foods Incorporated",
            region_context=self.region,
            contact_email="orders@lunafoods.ph",
        )
        existing = SupplierRecord.manual_draft(
            name="Luna Foods Inc.",
            region_context=self.region,
            contact_email="orders@lunafoods.ph",
        )
        evaluation = self.dedupe_engine.evaluate_supplier(target, [existing])
        self.assertEqual(evaluation.best_candidate.classification, DedupeMatchClassification.LIKELY_DUPLICATE)
        self.assertGreaterEqual(evaluation.best_candidate.score, 70)

    def test_possible_duplicate_detected_by_email_only(self) -> None:
        target = SupplierRecord.manual_draft(
            name="North Harbor Supply",
            region_context=self.region,
            contact_email="hello@sharedmail.ph",
        )
        existing = SupplierRecord.manual_draft(
            name="Harbor North Logistics",
            region_context=self.region,
            contact_email="hello@sharedmail.ph",
        )
        evaluation = self.dedupe_engine.evaluate_supplier(target, [existing])
        self.assertEqual(evaluation.best_candidate.classification, DedupeMatchClassification.POSSIBLE_DUPLICATE)

    def test_distinct_candidate_is_filtered_out(self) -> None:
        target = SupplierRecord.manual_draft(
            name="Sunrise Laundry Supply",
            region_context=self.region,
            contact_email="orders@sunrise.ph",
        )
        existing = SupplierRecord.manual_draft(
            name="Metro Packaging House",
            region_context=self.region,
            contact_email="sales@metro.ph",
        )
        evaluation = self.dedupe_engine.evaluate_supplier(target, [existing])
        self.assertEqual(evaluation.candidates, ())

    def test_self_candidate_is_skipped(self) -> None:
        target = SupplierRecord.manual_draft(name="Self Match Test", region_context=self.region)
        evaluation = self.dedupe_engine.evaluate_supplier(target, [target])
        self.assertEqual(evaluation.candidates, ())

    def test_seeded_reference_can_form_exact_duplicate_signal(self) -> None:
        target = SupplierRecord.seeded_draft(
            name="Acme Supplier",
            seeded_source="Gov Registry",
            seeded_source_reference="SUP-55",
            region_context=self.region,
        )
        existing = SupplierRecord.seeded_draft(
            name="Acme Supplier Duplicate",
            seeded_source="gov registry",
            seeded_source_reference="SUP 55",
            region_context=self.region,
        )
        evaluation = self.dedupe_engine.evaluate_supplier(target, [existing])
        self.assertEqual(evaluation.best_candidate.classification, DedupeMatchClassification.EXACT_DUPLICATE)
        self.assertTrue(any(signal.code == "dedupe.seeded_reference.exact" for signal in evaluation.best_candidate.signals))


if __name__ == "__main__":
    unittest.main()
