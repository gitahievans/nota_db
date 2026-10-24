import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "scores"
REFERENCES = FIXTURES / "supplemental"


def inventory():
    return json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))


def fixture_hashes():
    return {
        str(p.relative_to(FIXTURES)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in FIXTURES.rglob("*") if p.is_file()
    }


def parse_reference(name):
    from music21 import converter
    return converter.parse(REFERENCES / f"{name}.musicxml", forceSource=True)
