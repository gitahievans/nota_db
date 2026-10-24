"""P3 independently read XML positions and source correspondence checks."""
import hashlib
import json
from fractions import Fraction
from unittest.mock import patch
from xml.etree import ElementTree as ET
from django.test import SimpleTestCase

from files.musical_identity import index_musicxml, build_identity, anchor_analysis
from files.music21_analyzer import MusicAnalysisOptimizer
from .references import REFERENCES, parse_reference
from .orchestration import IsolatedScoreCase


def xml(measures, extra=""):
    return ('<score-partwise version="4.0"><part-list><score-part id="P1">'
            '<part-name>Test</part-name></score-part></part-list><part id="P1">' +
            measures + '</part>' + extra + '</score-partwise>').encode()


def pitched(step="C", duration=1, extra=""):
    return (f'<note><pitch><step>{step}</step><octave>4</octave></pitch>'
            f'<duration>{duration}</duration>{extra}</note>')


class IdentityTests(SimpleTestCase):
    def test_P3_meter_change_global_location(self):
        result = MusicAnalysisOptimizer(parse_reference("expression")).analyze_meter_changes()
        self.assertEqual(result["changes"][0]["offset"], 3)
        self.assertEqual(result["changes"][0]["measure"], 2)
        self.assertEqual(result["changes"][0]["locations"][0]["measure_id"], "p0:m1")

    def test_pickup_tie_written_and_linear_occurrence(self):
        result = build_identity(REFERENCES / "rhythm.musicxml")
        self.assertEqual([m["score_onset"] for m in result["measures"]], ["0", "1/2"])
        self.assertEqual([m["actual_duration"] for m in result["measures"]], ["1/2", "3"])
        self.assertEqual(result["events"][1]["tie_previous"], "p0:m0:n0")
        first = result["playback"]["occurrences"][0]
        self.assertEqual(first["event_ids"], ["p0:m0:n0", "p0:m1:n0"])
        self.assertEqual(first["duration"], "2")
        self.assertEqual(result["events"][-1]["kind"], "rest")
        self.assertIsNone(result["events"][-1]["written_pitch"])

    def test_labels_chord_members_voices_and_transposition(self):
        source = xml('<measure number="A"><attributes><divisions>3</divisions>'
            '<transpose><diatonic>-1</diatonic><chromatic>-2</chromatic></transpose>'
            '</attributes>' + pitched(duration=1, extra='<voice>1</voice>') +
            '<note><chord/><pitch><step>E</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice></note>' +
            '<backup><duration>1</duration></backup>' + pitched(duration=3, extra='<voice>2</voice>') +
            '</measure><measure number="A">' + pitched(duration=3) + '</measure>')
        result = index_musicxml(source)
        self.assertEqual([m["label"] for m in result["measures"]], ["A", "A"])
        self.assertEqual([m["score_onset"] for m in result["measures"]], ["0", "1"])
        self.assertEqual([e["measure_onset"] for e in result["events"][:3]], ["0"] * 3)
        self.assertEqual([e["duration"] for e in result["events"][:3]], ["1/3", "2/3", "1"])
        self.assertEqual(len({e["id"] for e in result["events"]}), 4)
        self.assertEqual(result["events"][0]["sounding_pitch"]["midi"], "58")
        self.assertEqual(result["events"][0]["written_pitch"]["step"], "C")
        self.assertEqual(result["events"][1]["chord_group"], "p0:m0:n0")
        self.assertEqual(result["events"][2]["voice"], "2")

    def test_deterministic_reparse_revision_and_literal_source_resolution(self):
        for name in ("melody", "parts", "rhythm", "expression", "harmony", "distributed"):
            data = (REFERENCES / f"{name}.musicxml").read_bytes()
            a, b = index_musicxml(data), index_musicxml(data)
            self.assertEqual(a, b)
            self.assertEqual(a["artifact_revision"], hashlib.sha256(data).hexdigest())
            self.assertNotEqual(a["artifact_revision"], index_musicxml(data + b'\n')["artifact_revision"])
            parts = ET.fromstring(data).findall("part")
            mids = {m["id"] for m in a["measures"]}
            for e in a["events"]:
                loc = e["xml"]
                source = parts[loc["part"]].findall("measure")[loc["measure"]].findall("note")[loc["note"]]
                self.assertEqual(source.findtext("pitch/step"), (e["written_pitch"] or {}).get("step"))
                self.assertIn(e["measure_id"], mids)
                self.assertEqual(Fraction(e["score_onset"]),
                    Fraction(a["measures"][[m["id"] for m in a["measures"]].index(e["measure_id"])]["score_onset"]) +
                    Fraction(e["measure_onset"]))
            json.dumps(a, allow_nan=False)

    def test_shared_markings_do_not_create_fictitious_changes(self):
        text = (REFERENCES / "expression.musicxml").read_text()
        root = ET.fromstring(text)
        p = ET.tostring(root.find("part"), encoding="unicode").replace('id="P1"', 'id="P2"')
        source = text.replace('</score-partwise>', p + '</score-partwise>')
        source = source.replace('</part-list>', '<score-part id="P2"><part-name>Copy</part-name></score-part></part-list>')
        indexed = index_musicxml(source.encode())
        times = [m for m in indexed["markings"] if m["kind"] == "time"]
        self.assertEqual(len(times), 2)
        self.assertEqual([len(m["sources"]) for m in times], [2, 2])
        from music21 import converter
        result = MusicAnalysisOptimizer(converter.parseData(source)).analyze_meter_changes()
        self.assertEqual(result["total_changes"], 1)
        self.assertEqual(len(result["changes"][0]["locations"]), 2)

    def test_repeats_unavailable_without_fabricated_occurrences(self):
        result = index_musicxml(xml('<measure number="1"><attributes><divisions>1</divisions></attributes>' +
            pitched() + '<barline><repeat direction="backward"/></barline></measure>'))
        self.assertEqual(result["playback"]["status"], "unavailable")
        self.assertEqual(result["playback"]["occurrences"], [])
        self.assertEqual(result["playback"]["navigation"], "unsupported_repeats_endings_jumps")

    def test_empty_unpitched_missing_context_and_unresolved_tie(self):
        empty = index_musicxml(xml('<measure number="x"/>'))
        self.assertEqual(empty["status"], "absent")
        self.assertEqual(empty["markings"], [])
        self.assertEqual(empty["measures"][0]["label"], "x")
        self.assertEqual(empty["issues"][0]["code"], "empty_measure_duration_unknown")
        unknown = index_musicxml(xml('<measure/><measure><attributes><divisions>1</divisions></attributes>' +
                                     pitched() + '</measure>'))
        self.assertIsNone(unknown["events"][0]["score_onset"])
        self.assertEqual(anchor_analysis({}, unknown)["code"], "unknown_measure_timeline")
        unpitched = index_musicxml(xml('<measure><attributes><divisions>1</divisions></attributes>'
            '<note><unpitched><display-step>C</display-step><display-octave>5</display-octave></unpitched>'
            '<duration>1</duration></note></measure>'))
        self.assertIsNone(unpitched["events"][0]["sounding_pitch"])
        self.assertEqual(unpitched["playback"]["status"], "unavailable")
        tied = index_musicxml(xml('<measure><attributes><divisions>1</divisions></attributes>' +
                                 pitched(extra='<tie type="stop"/>') + '</measure>'))
        self.assertEqual(tied["issues"][0]["code"], "unresolved_tie")

    def test_limits_are_explicit_and_never_return_partial_identity_lists(self):
        source = xml('<measure><attributes><divisions>1</divisions></attributes>' + pitched() * 3 + '</measure>')
        with patch("files.musical_identity.MAX_EVENTS", 2):
            result = index_musicxml(source)
        self.assertEqual(result["code"], "event_limit")
        self.assertFalse(result["complete"])
        self.assertNotIn("events", result)
        with patch("files.musical_identity.MAX_MEASURES", 0):
            self.assertEqual(index_musicxml(source)["code"], "measure_limit")
        with patch("files.musical_identity.MAX_XML_BYTES", 1):
            self.assertEqual(index_musicxml(source)["code"], "xml_size_limit")

    def test_legacy_harmony_spans_resolve_to_source_events(self):
        indexed = build_identity(REFERENCES / "harmony.musicxml")
        analysis = {"chords": MusicAnalysisOptimizer(parse_reference("harmony")).analyze_chords()}
        refs = anchor_analysis(analysis, indexed)
        self.assertEqual(refs["chords"][4]["start"], "4")
        self.assertEqual(refs["chords"][4]["event_ids"], ["p0:m1:n0", "p0:m1:n1", "p0:m1:n2"])

    def test_tempo_and_meter_changes_anchor_actual_later_measure(self):
        indexed = build_identity(REFERENCES / "expression.musicxml")
        tempos = [m for m in indexed["markings"] if m["kind"] == "metronome"]
        self.assertEqual([m["sources"][0]["location"]["score_onset"] for m in tempos], ["0", "3"])
        self.assertEqual(tempos[1]["sources"][0]["location"]["measure_onset"], "0")
        self.assertEqual(tempos[1]["sources"][0]["location"]["measure_id"], "p0:m1")
        self.assertIn('<beat-unit-dot', tempos[1]["value"])

    def test_large_supported_index_is_complete_and_ambiguous_unisons_explicit(self):
        data = xml('<measure number="1"><attributes><divisions>1</divisions></attributes>' +
                   pitched() * 2000 + '</measure>')
        result = index_musicxml(data)
        self.assertTrue(result["complete"])
        self.assertEqual(len(result["events"]), 2000)
        self.assertEqual(result["events"][-1]["score_onset"], "1999")
        self.assertEqual(len(result["playback"]["occurrences"]), 2000)
        duplicate = pitched().replace('<pitch>', '<chord/><pitch>')
        result = index_musicxml(xml('<measure><attributes><divisions>1</divisions></attributes>' +
                                   pitched() + duplicate + '</measure>'))
        self.assertEqual([e["osmd_join"]["status"] for e in result["events"]],
                         ["ambiguous_or_unsupported"] * 2)
        self.assertEqual(len({e["id"] for e in result["events"]}), 2)

    def test_grand_staff_analysis_references_use_xml_part_and_staff(self):
        data = xml('<measure number="1"><attributes><divisions>1</divisions><staves>2</staves>'
                   '<time><beats>4</beats><beat-type>4</beat-type></time></attributes>' +
                   pitched(duration=4, extra='<staff>1</staff>') +
                   '<backup><duration>4</duration></backup>' +
                   pitched("E", duration=4, extra='<staff>2</staff>') + '</measure>')
        from music21 import converter
        indexed = index_musicxml(data)
        optimizer = MusicAnalysisOptimizer(converter.parseData(data.decode(), format='musicxml'), indexed)
        analysis = {"chords": optimizer.analyze_chords()}
        refs = anchor_analysis(analysis, indexed)
        self.assertEqual(len(refs["chords"]), 1)
        self.assertEqual(refs["chords"][0]["event_ids"], ["p0:m0:n0", "p0:m0:n1"])
        self.assertEqual({e["part_id"] for e in indexed["events"]}, {"p0"})


class IdentityPipelineTests(IsolatedScoreCase):
    def test_identity_revision_matches_served_artifact(self):
        self.prepare_score()
        self.run_pdf()
        identity = self.score.results["musical_identity"]
        self.assertTrue(identity["complete"])
        self.assertEqual(identity["artifact_revision"], hashlib.sha256(
            (self.root / str(self.score.id) / "output.xml").read_bytes()).hexdigest())
        response = self.client.get(self.score.musicxml_url)
        served = b''.join(response.streaming_content)
        response.close()
        self.assertEqual(identity["artifact_revision"], hashlib.sha256(served).hexdigest())
        detail = self.client.get(f'/api/scores/{self.score.id}/')
        self.assertEqual(detail.data["score"]["results"]["musical_identity"], identity)
