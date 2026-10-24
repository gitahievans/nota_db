import hashlib
import unittest
import xml.etree.ElementTree as ET

from .references import FIXTURES, REFERENCES, inventory


class FixtureInventoryTests(unittest.TestCase):
    def test_primary_identities_and_immutable_originals(self):
        samples = inventory()["primary"]
        self.assertEqual([s["id"] for s in samples], [
            "01-simple-melody", "02-rhythm-and-meter", "03-multiple-parts",
            "04-keys-and-chords", "05-expression-and-changes",
        ])
        for sample in samples:
            with self.subTest(sample=sample["id"]):
                data = (FIXTURES / sample["source"]).read_bytes()
                self.assertTrue(data.startswith(b"%PDF-"))
                self.assertEqual(len(data), sample["bytes"])
                self.assertEqual(hashlib.sha256(data).hexdigest(), sample["sha256"])

    def test_inventory_covers_all_primary_files_and_declares_review(self):
        samples = inventory()["primary"]
        declared = {p for s in samples for p in s["counterparts"].values() if p}
        actual = {p.name for p in FIXTURES.iterdir() if p.suffix.lower() in {
            ".pdf", ".png", ".jpg", ".musicxml", ".mxl", ".xml", ".wav", ".mp3"
        }}
        self.assertEqual(actual, declared, "New counterparts need inventory/review")
        for sample in samples:
            self.assertTrue(sample["review_status"])
            self.assertTrue(sample["uncertainty"])

    def test_supplemental_xml_has_independent_review_records(self):
        for name, record in inventory()["supplemental"].items():
            with self.subTest(reference=name):
                self.assertTrue(record["review"])
                if name == "malformed":
                    with self.assertRaises(ET.ParseError):
                        ET.parse(REFERENCES / f"{name}.musicxml")
                else:
                    self.assertEqual(ET.parse(REFERENCES / f"{name}.musicxml").getroot().tag, "score-partwise")
