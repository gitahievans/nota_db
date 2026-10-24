import tempfile
from pathlib import Path

from django.test import SimpleTestCase
from music21 import converter, dynamics, meter, note, stream, tempo

from files.music21_analyzer import MusicAnalysisOptimizer, analyze_with_music21
from .references import REFERENCES, inventory, parse_reference


class SymbolicReferenceTests(SimpleTestCase):
    def test_melody_counts_and_numeric_tempo_reference(self):
        score = parse_reference("melody")
        expected = inventory()["supplemental"]["melody"]
        self.assertEqual(len(score.recurse().getElementsByClass(note.Note)), expected["notes"])
        self.assertEqual(len(score.recurse().getElementsByClass(note.Rest)), expected["rests"])
        self.assertEqual([float(n.quarterLength) for n in score.recurse().notesAndRests], expected["quarter_lengths"])
        self.assertEqual(score.recurse().getElementsByClass(tempo.MetronomeMark).first().number, 96)
        analyzer = MusicAnalysisOptimizer(score)
        self.assertEqual(analyzer.analyze_parts(), ["Melody"])
        self.assertEqual(analyzer.analyze_time_signature(), "4/4")
        self.assertEqual(analyzer.analyze_measures()["total_measures"], 2)

    def test_pickup_dots_ties_and_absolute_positions_in_reference(self):
        score = parse_reference("rhythm")
        expected = inventory()["supplemental"]["rhythm"]
        measures = list(score.parts[0].getElementsByClass(stream.Measure))
        events = list(score.recurse().notesAndRests)
        self.assertEqual([m.number for m in measures], expected["measure_labels"])
        self.assertEqual([float(m.duration.quarterLength) for m in measures], expected["measure_lengths"])
        self.assertEqual([float(n.getOffsetInHierarchy(score)) for n in events], expected["event_onsets"])
        self.assertEqual([float(n.quarterLength) for n in events], expected["event_durations"])
        self.assertEqual([n.tie.type for n in events if n.tie], expected["ties"])
        self.assertTrue(MusicAnalysisOptimizer(score).analyze_measures()["has_pickup"])

    def test_independent_parts_unison_and_unequal_durations_in_reference(self):
        score = parse_reference("parts")
        self.assertEqual(MusicAnalysisOptimizer(score).analyze_parts(), ["Upper", "Lower"])
        self.assertEqual(score.parts[0].recurse().notes.first().nameWithOctave, "C4")
        self.assertEqual(float(score.parts[0].recurse().notes.first().quarterLength), 4)
        lower = score.parts[1].recurse().notes.first()
        self.assertEqual([p.nameWithOctave for p in lower.pitches], ["C4", "E4", "G4"])
        self.assertEqual(float(lower.quarterLength), 1)

    def test_written_signatures_and_spelling_in_reference(self):
        from music21 import key
        score = parse_reference("harmony")
        expected = inventory()["supplemental"]["harmony"]
        self.assertEqual([k.sharps for k in score.recurse().getElementsByClass(key.KeySignature)], expected["written_fifths"])
        self.assertEqual(len(score.recurse().notes), 12)
        for i, c in enumerate(score.recurse().notes):
            self.assertEqual([p.nameWithOctave for p in c.pitches], expected["pitches_cycle"][i % 2])

    def test_distributed_harmony_reference_contains_no_per_part_triad(self):
        score = parse_reference("distributed")
        self.assertEqual(sorted(p.nameWithOctave for p in score.pitches), ["C3", "E4", "G4"])
        self.assertEqual([len(p.pitches) for p in score.parts], [2, 1])
        self.assertEqual([float(n.quarterLength) for n in score.recurse().notes], [4, 4])

    def test_expression_and_change_locations_in_reference(self):
        score = parse_reference("expression")
        notes = list(score.recurse().notes)
        self.assertEqual([n.nameWithOctave for n in notes], ["C#4", "D-4"])
        self.assertEqual([n.articulations[0].name for n in notes], ["staccato", "tenuto"])
        self.assertEqual(notes[0].lyric, "la")
        self.assertEqual([d.value for d in score.recurse().getElementsByClass(dynamics.Dynamic)], ["p"])
        self.assertEqual([float(t.getOffsetInHierarchy(score)) for t in score.recurse().getElementsByClass(meter.TimeSignature)], [0, 3])
        self.assertEqual([t.getQuarterBPM() for t in score.recurse().getElementsByClass(tempo.MetronomeMark)], [80, 90])
        notable = MusicAnalysisOptimizer(score).analyze_notable_elements()
        self.assertEqual(notable["articulations"]["staccato"]["count"], 1)
        self.assertEqual(notable["dynamics"]["values"], ["p"])

    def test_malformed_input_is_reported_as_parse_failure(self):
        from types import SimpleNamespace
        result = analyze_with_music21(str(REFERENCES / "malformed.musicxml"), SimpleNamespace(id=1))
        self.assertIn("error", result)
        self.assertEqual(result["key"], "Error")

    def test_reference_xml_roundtrip_retains_expression(self):
        # Parser/export sanity only: this does NOT exercise backend normalization.
        score = parse_reference("expression")
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "copy.musicxml"
            score.write("musicxml", fp=target)
            reparsed = converter.parse(target, forceSource=True)
            self.assertEqual([n.nameWithOctave for n in reparsed.recurse().notes], ["C#4", "D-4"])
            self.assertEqual(reparsed.recurse().notes.first().lyric, "la")
