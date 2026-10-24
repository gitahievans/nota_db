"""P2 downstream notation and playback contracts; recognition is controlled."""
from fractions import Fraction
import shutil
import zipfile
from unittest.mock import patch
from music21 import converter, midi, stream, note, meter
from django.test import SimpleTestCase
from files.serializers import FileSerializer
from files.tasks import process_score
from files.score_cleanup import normalize_score_stream
from files.music21_analyzer import MusicAnalysisOptimizer
from .orchestration import IsolatedScoreCase
from .references import REFERENCES


class PreservationTests(IsolatedScoreCase):
    def test_P2_recognized_parts_preserved(self):
        self.prepare_score("parts")
        self.run_pdf()
        self.assertEqual(self.score.results["parts"], ["Upper", "Lower"])

    def test_P2_recognized_expression_preserved(self):
        from music21 import converter
        directory = self.prepare_score("expression")
        self.run_pdf()
        served = converter.parse(directory / "output.xml", forceSource=True)
        self.assertEqual(served.recurse().notes.first().lyric, "la")
        self.assertEqual([n.nameWithOctave for n in served.recurse().notes], ["C#4", "D-4"])

    def test_P2_audio_default_uses_canonical_midi(self):
        directory = self.prepare_score(source_type="audio")
        (directory / "preview.mid").write_bytes(b"raw comparison MIDI")
        (directory / f"{self.score.id}.mid").write_bytes(b"MThd canonical test artifact")
        self.score.midi_url = f"/api/serve-midi/{self.score.id}/"
        self.assertEqual(FileSerializer(self.score).data["playback_midi_url"], self.score.midi_url)


    def test_checked_notation_survives_and_analysis_uses_served_xml(self):
        for reference in ("parts", "expression", "rhythm", "harmony"):
            with self.subTest(reference=reference):
                directory = self.prepare_score(reference)
                original = self.recognized.read_bytes()
                with patch("files.tasks.analyze_with_music21", wraps=__import__("files.music21_analyzer", fromlist=["analyze_with_music21"]).analyze_with_music21) as analyze:
                    self.run_pdf()
                self.assertEqual(analyze.call_args.args[0], str(directory / "output.xml"))
                response = self.client.get(self.score.musicxml_url)
                self.assertEqual(b"".join(response.streaming_content), original)
                response.close()
                self.assertFalse(self.score.results["score_cleanup"]["applied"])
                self.assertEqual(self.score.results["artifacts"]["roles"]["canonical_displayed_xml"]["also_roles"], ["recognized_musicxml"])

    def test_archive_extraction_uses_declared_root_without_member_paths(self):
        from files.audiveris_processor import extract_xml_from_mxl
        directory = self.prepare_score("expression")
        archive = directory / "recognition.mxl"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="../score.musicxml"/></rootfiles></container>')
            z.writestr("../score.musicxml", self.recognized.read_bytes())
        target = directory / "extracted.xml"
        extract_xml_from_mxl(str(archive), str(target))
        self.assertEqual(target.read_bytes(), self.recognized.read_bytes())
        self.assertFalse((self.root / "score.musicxml").exists())

    def test_compressed_root_overrides_stale_xml_and_preserves_nested_score(self):
        directory = self.prepare_score("expression")
        archive = directory / "output.mxl"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="scores/notation.musicxml" media-type="application/vnd.recordare.musicxml+xml"/></rootfiles></container>')
            z.writestr("scores/notation.musicxml", self.recognized.read_bytes())
            z.writestr("decoy.xml", (REFERENCES / "melody.musicxml").read_bytes())
        (directory / "output.xml").write_bytes(b"stale extracted data")
        self.recognized = archive
        self.run_pdf()
        self.assertEqual((directory / "output.xml").read_bytes(), (REFERENCES / "expression.musicxml").read_bytes())
        self.assertEqual(self.score.results["parts"], ["Solo"])

    def assert_playback(self, directory, expected):
        mf = midi.MidiFile()
        mf.open(str(directory / f"{self.score.id}.mid"))
        mf.read()
        mf.close()
        sounding = []
        for track in mf.tracks:
            tick = 0
            active = {}
            for event in track.events:
                if event.isDeltaTime():
                    tick += event.time
                elif event.isNoteOn():
                    active.setdefault((event.channel, event.pitch), []).append(tick)
                elif event.isNoteOff():
                    starts = active.get((event.channel, event.pitch), [])
                    if starts:
                        start = starts.pop(0)
                        sounding.append((event.pitch, start / mf.ticksPerQuarterNote, (tick - start) / mf.ticksPerQuarterNote))
        self.assertEqual(len(sounding), len(expected), sounding)
        for actual, wanted in zip(sorted(sounding), sorted(expected)):
            self.assertEqual(actual[0], wanted[0])
            self.assertAlmostEqual(actual[1], wanted[1], delta=0.002)
            self.assertAlmostEqual(actual[2], wanted[2], delta=0.002)

    def test_independent_same_pitches_midi(self):
        directory = self.prepare_score("parts")
        self.run_pdf()
        self.assert_playback(directory, [(60, 0, 4), (60, 0, 1), (64, 0, 1), (67, 0, 1)])

    def test_tie_and_dotted_playback(self):
        directory = self.prepare_score("rhythm")
        self.run_pdf()
        self.assert_playback(directory, [(60, 0, 2), (62, 2, 0.75), (64, 2.75, 0.25)])

    def test_image_voices_tuplets_and_repeats_preserved(self):
        directory = self.prepare_score(source_type="image")
        self.recognized.write_text(VOICE_XML)
        (directory / "input.png").write_bytes(b"controlled image")
        with patch("files.tasks.process_with_audiveris", return_value=(str(self.recognized), None)), patch.object(process_score, "update_state"), patch("files.tasks.cleanup_temp_files.apply_async"):
            process_score.run(self.score.id, "png", "image")
        served = converter.parse(directory / "output.xml", forceSource=True)
        self.assertEqual(len(served.parts[0].recurse().getElementsByClass(stream.Voice)), 2)
        self.assertEqual([n.quarterLength for n in served.recurse().notes], [Fraction(1, 3), Fraction(1, 3), Fraction(1, 3), 1])
        self.assertEqual((directory / "output.xml").read_text(), VOICE_XML)
        # Repeat notation is retained; traversal synchronization remains unverified.

    def test_tuplet_voice_midi_without_navigation(self):
        directory = self.prepare_score()
        self.recognized.write_text(VOICE_XML.replace('<repeat direction="forward"/>', '').replace('<repeat direction="backward"/>', ''))
        self.run_pdf()
        self.assert_playback(directory, [(60, 0, 1/3), (62, 1/3, 1/3), (64, 2/3, 1/3), (60, 0, 1)])

    def test_audio_wrapper_draft_and_comparison_remain_distinct(self):
        from types import ModuleType
        from unittest.mock import Mock
        directory = self.prepare_score(source_type="audio")
        (directory / "input.wav").write_bytes(b"controlled audio")
        raw = stream.Stream([note.Note("C4", quarterLength=1), note.Note("D4", quarterLength=1)])
        raw_midi = Mock()
        raw_midi.write.side_effect = lambda path: raw.write("midi", fp=path)
        inference = ModuleType("basic_pitch.inference")
        inference.predict = Mock(return_value=(None, raw_midi, None))
        with patch.dict("sys.modules", {"basic_pitch": ModuleType("basic_pitch"), "basic_pitch.inference": inference}), patch.object(process_score, "update_state"), patch("files.tasks.cleanup_temp_files.apply_async"):
            process_score.run(self.score.id, "wav", "audio")
        self.score.refresh_from_db()
        self.assertTrue(self.score.results["audio_transcription"]["approximate"])
        self.assertFalse((directory / "basic_pitch_raw.mid").exists())
        payload = FileSerializer(self.score).data
        self.assertEqual(payload["playback_midi_url"], self.score.midi_url)
        self.assertNotEqual(payload["raw_preview_midi_url"], payload["playback_midi_url"])
        self.assertEqual(payload["results"]["artifacts"]["notation_quality"], "approximate_audio_draft")
        self.assert_playback(directory, [(60, 0, 1), (62, 1, 1)])
        for url in (payload["source_audio_url"], payload["raw_preview_midi_url"], payload["musicxml_url"], payload["playback_midi_url"]):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            response.close()

    def test_midi_failure_exposes_failure_without_raw_fallback_or_stale_file(self):
        directory = self.prepare_score(source_type="audio")
        shutil.copyfile(self.recognized, directory / "output.xml")
        (directory / "input.wav").write_bytes(b"controlled")
        (directory / "preview.mid").write_bytes(b"comparison")
        (directory / f"{self.score.id}.mid").write_bytes(b"stale midi")
        original_write = stream.Stream.write
        def fail_midi(obj, fmt=None, *args, **kwargs):
            if fmt == "midi":
                raise RuntimeError("controlled export failure")
            return original_write(obj, fmt, *args, **kwargs)
        with patch("files.tasks.transcribe_audio_to_musicxml", return_value=(directory / "output.xml", {"approximate": True})), patch.object(process_score, "update_state"), patch("files.tasks.cleanup_temp_files.apply_async"), patch.object(stream.Stream, "write", fail_midi):
            process_score.run(self.score.id, "wav", "audio")
        self.score.refresh_from_db()
        payload = FileSerializer(self.score).data
        self.assertIsNone(payload["playback_midi_url"])
        self.assertIsNone(payload["midi_url"])
        self.assertEqual(payload["raw_preview_midi_url"], f"/api/serve-preview-midi/{self.score.id}/")
        self.assertEqual(payload["results"]["playback"]["status"], "failed")
        self.assertEqual(payload["results"]["processing"]["components"]["midi"]["code"], "midi_unavailable")
        self.assertNotIn("controlled export failure", payload["results"]["playback"]["error"])
        self.assertEqual(self.client.get(f"/api/serve-midi/{self.score.id}/").status_code, 404)
        response = self.client.get(payload["raw_preview_midi_url"])
        self.assertEqual(response.status_code, 200)
        response.close()


VOICE_XML = '''<?xml version="1.0"?><score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Written Voices</part-name></score-part></part-list><part id="P1"><measure number="1"><attributes><divisions>3</divisions><time><beats>1</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes><barline location="left"><repeat direction="forward"/></barline><note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice><type>eighth</type><time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes><normal-type>eighth</normal-type></time-modification></note><note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice><type>eighth</type><time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification></note><note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice><type>eighth</type><time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification></note><backup><duration>3</duration></backup><note><pitch><step>C</step><octave>4</octave></pitch><duration>3</duration><voice>2</voice><type>quarter</type></note><barline location="right"><repeat direction="backward"/></barline></measure></part></score-partwise>'''


class AudioDraftTests(SimpleTestCase):
    def test_audio_meter_applied_before_measure_construction(self):
        source = stream.Score()
        part = stream.Part()
        part.insert(0, meter.TimeSignature("3/4"))
        for i in range(6):
            part.insert(i, note.Note("C4", quarterLength=1))
        source.insert(0, part)
        draft, metadata = normalize_score_stream(source, "audio")
        measures = list(draft.parts[0].getElementsByClass(stream.Measure))
        self.assertEqual([m.offset for m in measures], [0, 3])
        self.assertEqual([m.duration.quarterLength for m in measures], [3, 3])
        self.assertTrue(metadata["approximate"])
        self.assertIn("inferred_choices", metadata)
        with self.assertRaises(ValueError):
            normalize_score_stream(source, "pdf")

    def test_inferred_satb_does_not_replace_written_names(self):
        source = stream.Score()
        for index, pitch in enumerate(("C5", "G4", "C4", "C3")):
            part = stream.Part()
            part.partName = f"Written {index}"
            part.append(note.Note(pitch))
            source.insert(0, part)
        structure = {"parts": [p.partName for p in source.parts]}
        result = MusicAnalysisOptimizer(source)._detect_ensemble_type(structure, [])
        self.assertEqual(structure["parts"], [f"Written {i}" for i in range(4)])
        self.assertEqual(structure["inferred_part_roles"], ["Soprano", "Alto", "Tenor", "Bass"])
        self.assertEqual(result, "Custom Ensemble")
