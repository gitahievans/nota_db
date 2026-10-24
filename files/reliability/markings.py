"""Notation-marking counts; literal XML expectations are independent of export."""
import tempfile
from pathlib import Path

from django.test import SimpleTestCase
from music21 import articulations, chord, converter, dynamics, note, stream

from files.music21_analyzer import MusicAnalysisOptimizer
from .orchestration import IsolatedScoreCase


def chord_xml(first="", second="", third=""):
    # One quarter-note C-major chord, three XML note nodes. No music21 writer.
    notes = []
    for index, (step, marks) in enumerate(zip("CEG", (first, second, third))):
        notation = f"<notations><articulations>{marks}</articulations></notations>" if marks else ""
        notes.append(f'<note>{"<chord/>" if index else ""}'
                     f'<pitch><step>{step}</step><octave>4</octave></pitch>'
                     f'<duration>1</duration><type>quarter</type>{notation}</note>')
    return ('<score-partwise version="4.0"><part-list><score-part id="P1">'
            '<part-name>Marked chord</part-name></score-part></part-list><part id="P1">'
            '<measure number="1"><attributes><divisions>1</divisions>'
            '<time><beats>1</beats><beat-type>4</beat-type></time></attributes>'
            + ''.join(notes) + '</measure></part></score-partwise>')


class MarkingAssertions:
    def assert_markings(self, result, expected):
        self.assertNotIn("error", result)
        chart = result["visualizations"]["notable_elements_chart"]["data"]
        for name, count in zip(("staccato", "accent", "tenuto"), expected):
            self.assertEqual(result["articulations"][name],
                             {"count": count, f"has_{name}": count > 0})
            self.assertIs(type(result["articulations"][name]["count"]), int)
            self.assertIs(type(result["articulations"][name][f"has_{name}"]), bool)
            for dataset in chart["datasets"]:
                self.assertEqual(dataset["data"][chart["labels"].index(name.title())], count)
                self.assertEqual(len(dataset["data"]), len(chart["labels"]))

    def analyze(self, *events):
        return MusicAnalysisOptimizer(stream.Score([stream.Part(events)])).analyze_notable_elements()


class ArticulationTests(MarkingAssertions, SimpleTestCase):
    def test_standalone_note_types(self):
        for kind, expected in ((articulations.Staccato, (1, 0, 0)),
                               (articulations.Accent, (0, 1, 0)),
                               (articulations.Tenuto, (0, 0, 1))):
            with self.subTest(kind=kind.__name__):
                n = note.Note("C4")
                n.articulations.append(kind())
                self.assert_markings(self.analyze(n), expected)

    def test_chord_types_count_once_for_three_pitches(self):
        for kind, expected in ((articulations.Staccato, (1, 0, 0)),
                               (articulations.Accent, (0, 1, 0)),
                               (articulations.Tenuto, (0, 0, 1))):
            with self.subTest(kind=kind.__name__):
                c = chord.Chord(["C4", "E4", "G4"])
                c.articulations.append(kind())
                self.assert_markings(self.analyze(c), expected)

    def test_mixed_passage(self):
        n = note.Note("C4")
        n.articulations = [articulations.Staccato(), articulations.Tenuto()]
        c = chord.Chord(["C4", "E4", "G4"])
        c.articulations = [articulations.Staccato(), articulations.Accent()]
        self.assert_markings(self.analyze(n, c, note.Rest(), note.Note("D4"),
                                         chord.Chord(["D4", "F4"])), (2, 1, 1))

    def test_multiple_types_on_one_event(self):
        for event in (note.Note("C4"), chord.Chord(["C4", "E4", "G4"])):
            with self.subTest(event=type(event).__name__):
                event.articulations = [articulations.Staccato(), articulations.Accent(), articulations.Tenuto()]
                self.assert_markings(self.analyze(event), (1, 1, 1))

    def test_rest_only(self):
        self.assert_markings(self.analyze(note.Rest(), note.Rest()), (0, 0, 0))

    def test_unmarked_passage(self):
        self.assert_markings(self.analyze(note.Note("C4"), chord.Chord(["C4", "E4", "G4"])), (0, 0, 0))

    def test_empty_score(self):
        self.assert_markings(self.analyze(), (0, 0, 0))

    def test_separate_member_markings_are_preserved(self):
        c = chord.Chord(["C4", "E4", "G4"])
        c.articulations = [articulations.Staccato()]
        c.notes[0].articulations = [articulations.Staccato(), articulations.Accent()]
        c.notes[1].articulations = [articulations.Accent(), articulations.Tenuto()]
        # Distinct instances of the same type on different owners remain distinct.
        self.assert_markings(self.analyze(c), (2, 2, 1))

    def test_same_marking_reference_on_chord_and_members_counts_once(self):
        c = chord.Chord(["C4", "E4", "G4"])
        shared = articulations.Staccato()
        c.articulations = [shared]
        for member in c.notes:
            member.articulations = [shared]
        self.assert_markings(self.analyze(c), (1, 0, 0))

    def test_member_also_in_stream_is_not_counted_twice(self):
        c = chord.Chord(["C4", "E4", "G4"])
        c.articulations = [articulations.Staccato()]
        c.notes[0].articulations = [articulations.Accent()]
        # music21 permits a member Note also to be inserted into a stream.
        for events in ((c.notes[0], c), (c, c.notes[0])):
            with self.subTest(member_first=isinstance(events[0], note.Note)):
                self.assert_markings(self.analyze(*events), (1, 1, 0))

    def test_shared_articulation_instance_on_independent_events_counts_each(self):
        a, b = note.Note("C4"), note.Note("D4")
        shared = articulations.Staccato()
        a.articulations = [shared]
        b.articulations = [shared]
        self.assert_markings(self.analyze(a, b), (2, 0, 0))

    def test_real_xml_file_reproduces_chord_omission(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "marked.musicxml"
            path.write_text(chord_xml("<staccato/>"), encoding="utf-8")
            original = path.read_bytes()
            parsed = converter.parse(path, forceSource=True)
            events = list(parsed.recurse().notes)
            self.assertEqual(len(events), 1)
            self.assertIsInstance(events[0], chord.Chord)
            self.assertEqual([a.name for a in events[0].articulations], ["staccato"])
            self.assertEqual([n.articulations for n in events[0].notes], [[], [], []])
            self.assert_markings(MusicAnalysisOptimizer(parsed).analyze_notable_elements(), (1, 0, 0))
            self.assertEqual(path.read_bytes(), original)

    def test_xml_promotes_markings_from_all_members(self):
        parsed = converter.parseData(chord_xml("<staccato/>", "<accent/>", "<tenuto/>"), format="musicxml")
        c = parsed.recurse().notes.first()
        self.assertEqual([a.name for a in c.articulations], ["staccato", "accent", "tenuto"])
        self.assertEqual([n.articulations for n in c.notes], [[], [], []])
        self.assert_markings(MusicAnalysisOptimizer(parsed).analyze_notable_elements(), (1, 1, 1))

    def test_xml_parser_collapses_same_type_on_multiple_members(self):
        parsed = converter.parseData(chord_xml("<staccato/>", "<staccato/>"), format="musicxml")
        c = parsed.recurse().notes.first()
        # music21 9.1.0 loses this distinction before the analyzer sees the chord.
        self.assertEqual(len(c.articulations), 1)
        self.assertEqual([n.articulations for n in c.notes], [[], [], []])
        self.assert_markings(MusicAnalysisOptimizer(parsed).analyze_notable_elements(), (1, 0, 0))

    def test_accidental_scope_and_unique_dynamics_values_unchanged(self):
        c = chord.Chord(["F#4", "B-4", "C4"])
        c.articulations = [articulations.Staccato()]
        score = stream.Score([stream.Part([note.Note("C#4"), c, dynamics.Dynamic("p"),
                                          dynamics.Dynamic("f"), dynamics.Dynamic("p")])])
        optimizer = MusicAnalysisOptimizer(score)
        self.assertEqual([n.nameWithOctave for n in optimizer.get_all_notes()], ["C#4"])
        result = optimizer.analyze_notable_elements()
        self.assert_markings(result, (1, 0, 0))
        self.assertEqual(result["accidentals"], {"sharps": 1, "flats": 0, "naturals": 0,
                                                "others": 0, "has_accidentals": True})
        self.assertEqual(result["dynamics"], {"values": ["f", "p"], "has_dynamics": True})
        chart = result["visualizations"]["notable_elements_chart"]["data"]
        self.assertEqual(chart["labels"][-2:], ["f", "p"])
        self.assertEqual(chart["datasets"][0]["data"], [1, 0, 0, 0, 1, 0, 0, 1, 1])


class ArticulationPipelineTests(MarkingAssertions, IsolatedScoreCase):
    def test_canonical_chord_analysis_matches_served_notation(self):
        directory = self.prepare_score()
        original = chord_xml("<staccato/>", "<accent/>", "<tenuto/>").encode()
        self.recognized.write_bytes(original)
        self.run_pdf()
        self.assert_markings(self.score.results["notable_elements"], (1, 1, 1))
        self.assertEqual((directory / "output.xml").read_bytes(), original)
        self.assertEqual(len(self.score.results["musical_identity"]["events"]), 3)
        self.assertTrue((directory / f"{self.score.id}.mid").is_file())
