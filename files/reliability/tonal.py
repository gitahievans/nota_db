"""P4 key, tempo and simultaneous harmony requirements."""
from django.test import SimpleTestCase
from files.music21_analyzer import MusicAnalysisOptimizer
from .references import parse_reference, REFERENCES
from fractions import Fraction
from unittest.mock import patch
from music21 import converter, midi
from files.musical_identity import build_identity, index_musicxml
from files.tonal_analysis import key_analysis, tempo_analysis, harmony_analysis
from .identity import xml, pitched
from .orchestration import IsolatedScoreCase


class ResolvedTonalDefects(SimpleTestCase):
    def test_P4B_explicit_numeric_tempo(self):
        result = MusicAnalysisOptimizer(parse_reference("melody")).analyze_tempo()
        self.assertNotIn("error", result, result)
        self.assertEqual(result["initial_bpm"], 96)

    def test_P4C_all_twelve_sonorities(self):
        result = MusicAnalysisOptimizer(parse_reference("harmony")).analyze_chords()
        self.assertEqual(len(result), 12, result)

    def test_P4C_distributed_initial_triad(self):
        result = MusicAnalysisOptimizer(parse_reference("distributed")).analyze_chords()
        initial = [c["pitch"] for c in result if c["offset"] == 0]
        self.assertEqual(initial, ["C-major triad"])





def context(measures):
    data = xml(measures)
    return converter.parseData(data.decode(), format="musicxml"), index_musicxml(data)


class TonalTests(SimpleTestCase):
    def test_written_signatures_and_scopes_are_not_estimated_key(self):
        i = build_identity(REFERENCES / "harmony.musicxml")
        r = key_analysis(parse_reference("harmony"), i)
        self.assertEqual([s["written"]["fifths"] for s in r["signatures"]], ["-1", "0"])
        self.assertEqual([s["sources"][0]["location"]["score_onset"] for s in r["signatures"]], ["0", "8"])
        self.assertNotIn("probability", r["estimate"])
        self.assertEqual(r["artifact_revision"], i["artifact_revision"])

    def test_c_major_scale_estimate_without_signature(self):
        score, i = context('<measure><attributes><divisions>1</divisions></attributes>' +
                           ''.join(pitched(n) for n in 'CCCEEEGGGCCDEFGAB') + '</measure>')
        r = key_analysis(score, i)
        self.assertEqual(r["signature_status"], "unspecified")
        self.assertEqual(r["estimate"]["label"], "C major")
        self.assertIn("not a probability", r["estimate"]["limitation"])
        self.assertEqual(key_analysis(score, i, audio=True)["signature_origin"], "inferred_audio_draft")

    def test_no_pitched_content_has_no_estimate_or_sonority(self):
        score, i = context('<measure><attributes><divisions>1</divisions></attributes><note><rest/><duration>1</duration></note></measure>')
        self.assertEqual(key_analysis(score, i)["estimate"]["status"], "absent")
        self.assertEqual(harmony_analysis(i)["sonorities"], [])
        self.assertEqual(tempo_analysis(i)["initial_bpm"], None)

    def test_quarter_and_dotted_quarter_are_normalized_once(self):
        i = build_identity(REFERENCES / "expression.musicxml")
        r = tempo_analysis(i)
        self.assertEqual([(m["offset"], m["bpm"]) for m in r["tempo_markings"] if m["bpm"]], [(0, 80), (3, 90)])
        change = r["bpm_changes"][0]
        self.assertEqual(change["locations"][0]["measure_id"], "p0:m1")
        self.assertEqual(r["tempo_markings"][-1]["printed"][0], {"beat_unit": "quarter", "dots": 1, "per_minute": "60"})
        self.assertIsNone(r["average_bpm"])

    def test_duplicate_metronome_sound_and_parts_do_not_make_changes(self):
        data = xml('<measure><attributes><divisions>1</divisions></attributes><direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>96</per-minute></metronome></direction-type><sound tempo="96"/></direction>'+pitched()+'</measure>')
        data = data.replace(b'</score-partwise>', b'<part id="P2">'+data.split(b'<part id="P1">')[1].split(b'</part>')[0]+b'</part></score-partwise>')
        r = tempo_analysis(index_musicxml(data))
        self.assertEqual(len(r["tempo_markings"]), 1)
        self.assertEqual(len(r["tempo_markings"][0]["locations"]), 2)
        self.assertFalse(r["has_tempo_changes"])

    def test_text_only_and_no_tempo_do_not_invent_bpm(self):
        for direction in ('', '<direction><direction-type><words>Allegro</words></direction-type></direction>'):
            _, i = context('<measure><attributes><divisions>1</divisions></attributes>'+direction+pitched()+'</measure>')
            r = tempo_analysis(i)
            self.assertIsNone(r["initial_bpm"])
            self.assertTrue(all(m["bpm"] is None for m in r["tempo_markings"]))
            self.assertFalse(r["playback_default"]["observed"])

    def test_conflicting_tempos_do_not_create_fictitious_changes(self):
        i = build_identity(REFERENCES / "melody.musicxml")
        m = next(m for m in i["markings"] if m["kind"] == "metronome")
        import copy
        other = copy.deepcopy(m)
        other.update(id="conflict", value=m["value"].replace('96', '120'))
        i["markings"].append(other)
        r = tempo_analysis(i)
        self.assertEqual(r["conflicting_positions"], [0])
        self.assertIsNone(r["initial_bpm"])
        self.assertEqual(r["bpm_changes"], [])

    def test_distributed_harmony_has_all_members_bass_and_inversion(self):
        i = build_identity(REFERENCES / "distributed.musicxml")
        s = harmony_analysis(i)["sonorities"][0]
        self.assertEqual(s["event_ids"], ['p0:m0:n0', 'p0:m0:n1', 'p1:m0:n0'])
        self.assertEqual(s["suggestion"]["label"], "C-major triad")
        self.assertEqual(s["bass_midi"], 48)
        self.assertEqual(s["suggestion"]["inversion"], 0)
        self.assertEqual(s["end"], "4")

    def test_sustained_notes_and_tie_continuations_keep_source_references(self):
        i = build_identity(REFERENCES / "parts.musicxml")
        r = harmony_analysis(i)
        self.assertTrue(r["complete"])
        held = next(e for e in i["events"] if e["duration"] == '4')
        self.assertTrue(all(held["id"] in s["event_ids"] for s in r["sonorities"] if Fraction(s["start"]) < 4))
        i = build_identity(REFERENCES / "rhythm.musicxml")
        r = harmony_analysis(i)
        self.assertIn('p0:m1:n0', [eid for s in r["sonorities"] for eid in s["event_ids"]])
        self.assertEqual(i["events"][1]["tie_previous"], 'p0:m0:n0')

    def test_octaves_and_passing_cluster_are_observations_without_forced_label(self):
        for notes in (pitched()+pitched(extra='<chord/>'), pitched()+pitched('D', extra='<chord/>')+pitched('E', extra='<chord/>')):
            _, i = context('<measure><attributes><divisions>1</divisions></attributes>'+notes+'</measure>')
            s = harmony_analysis(i)["sonorities"][0]
            self.assertIsNone(s["suggestion"])
            self.assertGreaterEqual(len(s["members"]), 2)

    def test_transposition_is_applied_once_and_written_spelling_retained(self):
        _, i = context('<measure><attributes><divisions>1</divisions><transpose><diatonic>-1</diatonic><chromatic>-2</chromatic></transpose></attributes>'+pitched()+pitched('E',extra='<chord/>')+pitched('G',extra='<chord/>')+'</measure>')
        s = harmony_analysis(i)["sonorities"][0]
        self.assertEqual(s["sounding_midis"], [58, 62, 65])
        self.assertEqual(s["members"][0]["written_pitch"]["step"], 'C')
        self.assertEqual(s["suggestion"]["root"], 'B-')

    def test_harmony_bound_and_unknown_timeline_are_explicit(self):
        i = build_identity(REFERENCES / "distributed.musicxml")
        with patch('files.tonal_analysis.MAX_HARMONY_MEMBERS', 2):
            r = harmony_analysis(i)
        self.assertFalse(r["complete"])
        self.assertEqual(r["sonorities"], [])
        i["events"][0]["score_onset"] = None
        self.assertFalse(harmony_analysis(i)["complete"])


class TonalPipelineTests(IsolatedScoreCase):
    def test_legacy_projection_and_all_references_resolve(self):
        self.prepare_score('harmony')
        self.run_pdf()
        r = self.client.get(f'/api/scores/{self.score.id}/').data['score']['results']
        self.assertIsInstance(r['tempo'], str)  # direct React child is renderable
        self.assertIsInstance(r['key'], str)
        self.assertEqual(len(r['chords']), 12)
        i = r['musical_identity']
        events = {e['id'] for e in i['events']}
        measures = {m['id'] for m in i['measures']}
        marks = {m['id'] for m in i['markings']}
        for component in ('key_analysis', 'tempo_analysis', 'harmony', 'accidental_observations'):
            self.assertEqual(r[component]['artifact_revision'], i['artifact_revision'])
        for s in r['harmony']['sonorities']:
            self.assertTrue(set(s['event_ids']) <= events)
            self.assertTrue(set(s['measure_ids']) <= measures)
        for m in r['tempo_analysis']['tempo_markings']:
            self.assertTrue(set(m['marking_ids']) <= marks)
        for s in r['key_analysis']['signatures']:
            self.assertIn(s['marking_id'], marks)
        self.assertTrue(set(r['key_analysis']['estimate']['event_ids']) <= events)
        for obs in r['accidental_observations']['observations']:
            self.assertIn(obs['event_id'], events)
        self.assertEqual(r['analysis_references']['chords'][0]['event_ids'], r['harmony']['sonorities'][0]['event_ids'])

    def test_printed_accidentals_include_chord_members_without_inventing_signs(self):
        self.prepare_score()
        self.recognized.write_bytes(xml('<measure><attributes><divisions>1</divisions><key><fifths>1</fifths></key></attributes>'+
            '<note><pitch><step>F</step><alter>1</alter><octave>4</octave></pitch><duration>1</duration></note>'+
            '<note><chord/><pitch><step>B</step><alter>-1</alter><octave>4</octave></pitch><duration>1</duration><accidental parentheses="yes">flat</accidental></note></measure>'))
        self.run_pdf()
        obs = self.score.results['accidental_observations']['observations']
        self.assertEqual([o['accidental'] for o in obs], [None, 'flat'])
        self.assertEqual([o['pitch_alter'] for o in obs], ['1', '-1'])
        self.assertEqual(obs[1]['attributes'], {'parentheses': 'yes'})

    def test_canonical_midi_tempo_events_match_explicit_map(self):
        directory = self.prepare_score('expression')
        self.run_pdf()
        mf = midi.MidiFile()
        mf.open(str(directory / f'{self.score.id}.mid'))
        mf.read()
        mf.close()
        tempos = []
        for track in mf.tracks:
            ticks = 0
            for e in track.events:
                if isinstance(e, midi.DeltaTime):
                    ticks += e.time
                elif e.type == midi.MetaEvents.SET_TEMPO:
                    tempos.append((ticks / mf.ticksPerQuarterNote, 60000000 / int.from_bytes(e.data, 'big')))
        self.assertEqual(len(tempos), 2)
        for actual, expected in zip(tempos, [(0, 80), (3, 90)]):
            self.assertAlmostEqual(actual[0], expected[0])
            self.assertAlmostEqual(actual[1], expected[1], places=3)

    def test_text_tempo_interpretation_and_no_tempo_export_default_are_separate(self):
        directory = self.prepare_score()
        self.recognized.write_bytes(xml('<measure><attributes><divisions>1</divisions></attributes><direction><direction-type><words>Allegro</words></direction-type></direction>'+pitched()+'</measure>'))
        self.run_pdf()
        r = self.score.results
        self.assertEqual(r['tempo'], 'Not specified')
        m = r['tempo_analysis']['tempo_markings'][0]
        self.assertEqual(m['origin'], 'text_unquantified')
        self.assertIsNone(m['bpm'])
        self.assertEqual(m['interpreted_quarter_bpm'], 132)
        mf = midi.MidiFile()
        mf.open(str(directory / f'{self.score.id}.mid'))
        mf.read()
        mf.close()
        speeds = [60000000 / int.from_bytes(e.data, 'big') for track in mf.tracks for e in track.events
                  if e.type == midi.MetaEvents.SET_TEMPO]
        self.assertAlmostEqual(speeds[0], 120, places=3)  # plain XML words are not export metronomes
        self.assertIsNone(r['tempo_analysis']['playback_default']['applies_at_start'])

    def test_signature_change_and_ambiguous_mode_stay_written(self):
        self.prepare_score('harmony')
        self.run_pdf()
        r = self.score.results['key_analysis']
        self.assertEqual(len(r['changes']), 1)
        self.assertEqual(r['changes'][0]['location']['measure_id'], 'p0:m2')
        self.assertNotIn('mode', r['signatures'][0]['written'])

    def test_first_inversion_is_suggested_without_asserting_function(self):
        self.prepare_score('distributed')
        # Original bass C3 becomes E3: E3/G4/C5 is C major in first inversion.
        self.recognized.write_bytes(xml('<measure><attributes><divisions>1</divisions></attributes>'+pitched('E')+pitched('G', extra='<chord/>')+pitched('C', extra='<chord/>').replace('<octave>4', '<octave>5')+'</measure>'))
        self.run_pdf()
        s = self.score.results['harmony']['sonorities'][0]['suggestion']
        self.assertEqual(s['root'], 'C')
        self.assertEqual(s['bass'], 'E4')
        self.assertEqual(s['inversion'], 1)
        self.assertEqual(s['status'], 'suggested')

    def test_audio_context_is_labelled_in_all_analysis_components(self):
        directory = self.prepare_score('melody', source_type='audio')
        (directory / 'input.wav').write_bytes(b'controlled audio boundary')
        from files.tasks import process_score
        with patch('files.tasks.transcribe_audio_to_musicxml', return_value=(str(self.recognized), {'approximate': True})), patch.object(process_score, 'update_state'), patch('files.tasks.cleanup_temp_files.apply_async'):
            process_score.run(self.score.id, 'wav', 'audio')
        self.score.refresh_from_db()
        self.assertEqual(self.score.results['key_analysis']['signature_origin'], 'inferred_audio_draft')
        self.assertEqual(self.score.results['tempo_analysis']['notation_origin'], 'inferred_audio_draft')
        self.assertEqual(self.score.results['artifacts']['notation_quality'], 'approximate_audio_draft')

    def test_optional_summary_preserves_p4_distinctions_without_service_calls(self):
        from unittest.mock import Mock
        self.prepare_score('harmony')
        self.run_pdf()
        with self.settings(GEMINI_API_KEY='controlled-test-only'), patch('files.views.genai.configure'), patch('files.views.GenerativeModel') as model:
            model.return_value.generate_content.return_value = Mock(text='Controlled explanation')
            response = self.client.post('/api/generate-summary/', {'score_id': self.score.id}, format='json')
        self.assertEqual(response.status_code, 200)
        prompt = model.return_value.generate_content.call_args.args[0]
        self.assertIn('Written signatures and separate tonal estimate', prompt)
        self.assertIn('Do not claim a progression, modulation, harmonic function', prompt)
        self.assertIn('Pitch alterations are not counts of printed accidentals', prompt)
        self.score.refresh_from_db()
        self.assertEqual(self.score.summary, 'Controlled explanation')


    def test_conflicting_signatures_and_unavailable_index_do_not_invent_context(self):
        score, identity = context('<measure><attributes><divisions>1</divisions><key><fifths>0</fifths></key><key><fifths>2</fifths></key></attributes>'+pitched()+'</measure>')
        r = key_analysis(score, identity)
        self.assertEqual(r['changes'], [])
        self.assertEqual(r['signature_conflicts'][0]['code'], 'conflicting_signatures')
        unavailable = {'complete': False, 'status': 'unsupported', 'code': 'event_limit'}
        optimizer = MusicAnalysisOptimizer(score, unavailable)
        self.assertEqual(optimizer.analyze_chords(), [])
        self.assertEqual(optimizer.analyze_tempo()['status'], 'unsupported')
        self.assertFalse(harmony_analysis(unavailable)['complete'])


class UnavailableKeyTests(SimpleTestCase):
    """Small checked XML, independent of recognition output and application records."""

    def test_octave_shift_keeps_signature_and_allows_verified_class_estimate(self):
        score, identity = context('<measure><attributes><divisions>1</divisions>'
            '<key><fifths>-3</fifths></key></attributes>' + pitched('C') +
            '<direction><direction-type><octave-shift type="down" size="8" number="1"/>'
            '</direction-type><staff>1</staff></direction>' + pitched('E') + '</measure>')
        self.assertIn('octave_shift_sounding_unsupported', [i['code'] for i in identity['issues']])
        # Exact-pitch and playback limitations are retained independently.
        self.assertTrue(all(e['sounding_pitch']['midi'] is None for e in identity['events']))
        result = key_analysis(score, identity)
        self.assertEqual(result['signatures'][0]['written'], {'fifths': '-3'})
        self.assertEqual(result['estimate']['status'], 'estimated')
        self.assertEqual(result['estimate']['pitch_basis'], 'verified_sounding_pitch_classes')
        self.assertEqual(result['estimate']['exact_octaves'], 'unresolved')
        self.assertEqual(result['estimate']['source_codes'], ['octave_shift_sounding_unsupported'])
        self.assertEqual(result['estimate']['event_ids'], [e['id'] for e in identity['events']])
        self.assertIn('exact octave-shift interpretation', result['estimate']['limitation'])
        self.assertEqual(identity['playback']['status'], 'unavailable')
        self.assertEqual(identity['playback']['occurrences'], [])
        self.assertEqual(harmony_analysis(identity)['status'], 'unsupported')

    def test_doubling_transposition_retains_specific_reason(self):
        score, identity = context('<measure><attributes><divisions>1</divisions>'
            '<transpose><diatonic>0</diatonic><chromatic>0</chromatic><double/></transpose>'
            '</attributes>' + pitched() + '</measure>')
        result = key_analysis(score, identity)['estimate']
        self.assertEqual(result['status'], 'unsupported')
        self.assertEqual(result['source_codes'], ['double_transposition_unsupported'])

    def test_ordinary_reference_estimates_are_exactly_unchanged(self):
        for name in ('melody', 'harmony', 'distributed', 'expression'):
            score = parse_reference(name)
            identity = build_identity(REFERENCES / (name + '.musicxml'))
            expected = score.toSoundingPitch(inPlace=False).analyze('KrumhanslSchmuckler')
            actual = key_analysis(score, identity)['estimate']
            self.assertEqual(actual['status'], 'estimated')
            self.assertEqual(actual['label'], str(expected))
            self.assertEqual(actual['correlation'], expected.correlationCoefficient)
            self.assertEqual(actual['event_ids'], [e['id'] for e in identity['events'] if e['kind'] == 'pitched'])

    def test_transposing_key_uses_concert_pitch_and_keeps_written_signature(self):
        score, identity = context('<measure><attributes><divisions>1</divisions>'
            '<key><fifths>0</fifths></key><transpose><diatonic>-1</diatonic>'
            '<chromatic>-2</chromatic></transpose></attributes>' +
            ''.join(pitched(n) for n in 'CCCEEEGGGCCDEFGAB') + '</measure>')
        result = key_analysis(score, identity)
        self.assertEqual(result['signatures'][0]['written']['fifths'], '0')
        self.assertEqual(result['estimate']['label'], 'B- major')
        self.assertEqual(result['estimate']['pitch_space'], 'sounding')
        self.assertEqual(identity['events'][0]['written_pitch']['step'], 'C')
        self.assertEqual(identity['events'][0]['sounding_pitch']['midi'], '58')

    def test_failure_absence_and_incomplete_identity_have_safe_feedback(self):
        score, identity = context('<measure><attributes><divisions>1</divisions></attributes>' + pitched() + '</measure>')
        with patch.object(score, 'toSoundingPitch', side_effect=RuntimeError('private diagnostic')):
            failed = key_analysis(score, identity)['estimate']
        self.assertEqual(failed['code'], 'key_estimation_failed')
        self.assertNotIn('private', str(failed))
        self.assertIn('message', failed)
        unavailable = key_analysis(score, {'complete': False})['estimate']
        self.assertEqual(unavailable['code'], 'identity_unavailable')
        score, identity = context('<measure><attributes><divisions>1</divisions></attributes>'
            '<note><rest/><duration>1</duration></note></measure>')
        self.assertEqual(key_analysis(score, identity)['estimate']['code'], 'no_pitched_events')


    @staticmethod
    def octave_example(octave=4, transpose='', direction=None):
        # Reviewed miniature: C C C E E E G G G C C D E F G A B,
        # one quarter each. No stop is supplied, deliberately.
        if direction is None:
            direction = ('<direction><direction-type><octave-shift type="down" '
                         'size="8" number="1"/></direction-type><staff>1</staff></direction>')
        notes = ''.join(pitched(n).replace('<octave>4', '<octave>' + str(octave))
                        for n in 'CCCEEEGGGCCDEFGAB')
        return context('<measure><attributes><divisions>1</divisions>'
            '<key><fifths>-3</fifths></key>' + transpose + '</attributes>' + direction + notes + '</measure>')

    def test_octave_invariance_and_unclosed_or_repeated_shift_directions(self):
        original = None
        for octave in (3, 4, 5):
            for size, direction in (('8', 'up'), ('15', 'down'), ('22', 'up')):
                shift = ('<direction><direction-type><octave-shift type="' + direction +
                    '" size="' + size + '" number="1"/></direction-type></direction>')
                score, identity = self.octave_example(octave, direction=shift + shift)
                estimate = key_analysis(score, identity)['estimate']
                self.assertEqual(estimate['status'], 'estimated')
                self.assertEqual(estimate['label'], 'C major')
                if original is None:
                    original = estimate['correlation']
                self.assertEqual(estimate['correlation'], original)
                self.assertTrue(all(e['sounding_pitch']['midi'] is None for e in identity['events']))

    def test_installed_importer_preserves_classes_and_durations_for_shift_spans(self):
        # Check actual import, before key eligibility, with both closed and open
        # directions. XML C4/E4/G4 remains C/E/G, irrespective of octave symbols.
        from music21.analysis.discrete import KrumhanslSchmuckler
        for kind, size in (('up', '8'), ('down', '15')):
            start = ('<direction><direction-type><octave-shift type="' + kind +
                '" size="' + size + '" number="1"/></direction-type></direction>')
            stop = '<direction><direction-type><octave-shift type="stop" number="1"/></direction-type></direction>'
            for end in ('', stop):
                score, identity = context('<measure><attributes><divisions>1</divisions></attributes>' +
                    start + pitched('C', 2) + pitched('E', 3) + pitched('G', 3, '<chord/>') + end + '</measure>')
                concert = score.toSoundingPitch(inPlace=False)
                self.assertEqual([(n.quarterLength, [p.pitchClass for p in n.pitches])
                    for n in concert.flatten().notes], [(2, [0]), (3, [4, 7])])
                self.assertEqual(KrumhanslSchmuckler()._getPitchClassDistribution(concert.flatten()),
                    [2, 0, 0, 0, 3, 0, 0, 3, 0, 0, 0, 0])
                self.assertEqual(key_analysis(score, identity)['estimate']['status'], 'estimated')

    def test_all_members_parts_ties_and_grace_use_imported_duration_weights(self):
        from music21.analysis.discrete import KrumhanslSchmuckler
        # Explicit arithmetic: C=2+1+2=5, E=2, G=1, Bb=3.
        # Tied segments both contribute their written duration, rest contributes
        # nothing, and the F# grace contributes zero. Chord E gets a full 2.
        body = ('<measure><attributes><divisions>1</divisions></attributes>'
            '<direction><direction-type><octave-shift type="down" size="8"/></direction-type></direction>' +
            pitched('C', 2) + pitched('E', 2, '<chord/>') + pitched('G', 1) +
            pitched('C', 1, '<tie type="start"/>') + pitched('C', 2, '<tie type="stop"/>') +
            '<note><grace/><pitch><step>F</step><alter>1</alter><octave>4</octave></pitch></note>' +
            '<note><rest/><duration>1</duration></note></measure>')
        second = ('<part id="P2"><measure><attributes><divisions>1</divisions></attributes>'
            '<note><pitch><step>B</step><alter>-1</alter><octave>3</octave></pitch><duration>3</duration></note>'
            '</measure></part>')
        data = xml(body, second).replace(b'</part-list>',
            b'<score-part id="P2"><part-name>Second</part-name></score-part></part-list>')
        score = converter.parseData(data.decode(), format='musicxml')
        identity = index_musicxml(data)
        actual_profiles = []
        original = KrumhanslSchmuckler._getPitchClassDistribution
        def capture(analyzer, stream):
            profile = original(analyzer, stream)
            actual_profiles.append(profile)
            return profile
        with patch.object(KrumhanslSchmuckler, '_getPitchClassDistribution', capture):
            estimate = key_analysis(score, identity)['estimate']
        self.assertEqual(estimate['status'], 'estimated')
        self.assertEqual(actual_profiles, [[5, 0, 0, 0, 2, 0, 0, 1, 0, 0, 3, 0]])
        self.assertEqual(len(estimate['event_ids']), 7)
        self.assertEqual(set(estimate['event_ids']), {e['id'] for e in identity['events'] if e['kind'] == 'pitched'})

    def test_octave_exception_applies_instrument_transposition_exactly_once(self):
        transpose = ('<transpose><diatonic>-1</diatonic><chromatic>-2</chromatic>'
                     '<octave-change>-1</octave-change></transpose>')
        score, identity = self.octave_example(transpose=transpose)
        estimate = key_analysis(score, identity)['estimate']
        self.assertEqual(estimate['status'], 'estimated')
        self.assertEqual(estimate['label'], 'B- major')
        self.assertEqual(identity['events'][0]['sounding_pitch_class']['value'], '10')
        # Same result/correlation with an ordinary, no-shift control.
        ordinary, ordinary_identity = self.octave_example(transpose=transpose, direction='')
        control = key_analysis(ordinary, ordinary_identity)['estimate']
        self.assertEqual((estimate['label'], estimate['correlation']), (control['label'], control['correlation']))
        self.assertEqual(identity['events'][0]['written_pitch']['step'], 'C')
        self.assertEqual(key_analysis(score, identity)['signatures'][0]['written'], {'fifths': '-3'})

    def test_missing_fractional_or_doubled_transposition_is_not_octave_only(self):
        for transpose in (
            '<transpose><diatonic>-1</diatonic></transpose>',
            '<transpose><chromatic>0.5</chromatic></transpose>',
            '<transpose><chromatic>0</chromatic><double/></transpose>',
        ):
            # Malformed/fractional transpose may itself fail import; verify
            # source eligibility independently with a parsed control stream.
            score, _ = self.octave_example()
            data = xml('<measure><attributes><divisions>1</divisions>' + transpose +
                '</attributes><direction><direction-type><octave-shift type="down" size="8"/>'
                '</direction-type></direction>' + pitched() + '</measure>')
            identity = index_musicxml(data)
            self.assertEqual(key_analysis(score, identity)['estimate']['status'], 'unsupported')
        score, identity = self.octave_example()
        identity['events'][0]['sounding_pitch_class'] = None
        self.assertEqual(key_analysis(score, identity)['estimate']['status'], 'unsupported')
        score, identity = self.octave_example()
        identity['issues'].append({'code': 'future_unknown_pitch_issue'})
        self.assertEqual(key_analysis(score, identity)['estimate']['status'], 'unsupported')

    def test_bad_shift_size_and_microtonal_content_stay_unsupported(self):
        shift = '<direction><direction-type><octave-shift type="down" size="7"/></direction-type></direction>'
        # Unsupported sizes may fail music21 import, so independently use a
        # parsed control stream while testing the source identity safeguard.
        score, _ = self.octave_example()
        data = xml('<measure><attributes><divisions>1</divisions></attributes>' + shift + pitched() + '</measure>')
        identity = index_musicxml(data)
        self.assertEqual(key_analysis(score, identity)['estimate']['status'], 'unsupported')
        data = data.replace(b'size="7"', b'size="8"').replace(b'<step>C</step>', b'<step>C</step><alter>0.5</alter>')
        self.assertEqual(key_analysis(score, index_musicxml(data))['estimate']['status'], 'unsupported')

    def test_imported_missing_extra_reweighted_or_double_transposed_content_is_rejected(self):
        for change in ('missing', 'extra', 'duration', 'pitch'):
            score, identity = self.octave_example()
            part = score.parts[0]
            first = part.recurse().notes.first()
            if change == 'missing':
                first.activeSite.remove(first)
            elif change == 'extra':
                from music21 import note
                part.append(note.Note('C4'))
            elif change == 'duration':
                first.quarterLength = 2
            else:
                first.transpose(-2, inPlace=True)
            estimate = key_analysis(score, identity)['estimate']
            self.assertEqual(estimate['status'], 'unsupported', change)
            self.assertEqual(estimate['code'], 'unverified_pitch_class_content', change)
            self.assertNotIn('label', estimate)


    def test_fractional_durations_and_explicit_accidentals_keep_full_profile(self):
        from music21.analysis.discrete import KrumhanslSchmuckler
        data = xml('<measure><attributes><divisions>3</divisions></attributes>'
            '<direction><direction-type><octave-shift type="down" size="8"/></direction-type></direction>' +
            pitched('C', 1) + pitched('F', 2).replace('<step>F</step>', '<step>F</step><alter>1</alter>') +
            pitched('B', 2, '<chord/>').replace('<step>B</step>', '<step>B</step><alter>-1</alter>') + '</measure>')
        score = converter.parseData(data.decode(), format='musicxml')
        identity = index_musicxml(data)
        estimate = key_analysis(score, identity)['estimate']
        self.assertEqual(estimate['status'], 'estimated')
        profile = KrumhanslSchmuckler()._getPitchClassDistribution(score.flatten())
        self.assertEqual(profile, [Fraction(1, 3), 0, 0, 0, 0, 0, Fraction(2, 3), 0, 0, 0, Fraction(2, 3), 0])
        self.assertEqual([e['sounding_pitch_class']['value'] for e in identity['events']], ['0', '6', '10'])

    def test_transposition_changes_remain_contextual_with_octave_exception(self):
        start = '<direction><direction-type><octave-shift type="down" size="8"/></direction-type></direction>'
        score, identity = context('<measure><attributes><divisions>1</divisions>'
            '<transpose><diatonic>-1</diatonic><chromatic>-2</chromatic></transpose></attributes>' +
            start + pitched('C', 2) + '</measure><measure><attributes>'
            '<transpose><diatonic>0</diatonic><chromatic>0</chromatic></transpose></attributes>' +
            pitched('C', 3) + '</measure>')
        self.assertEqual([e['sounding_pitch_class']['value'] for e in identity['events']], ['10', '0'])
        estimate = key_analysis(score, identity)['estimate']
        self.assertEqual(estimate['status'], 'estimated')
        from music21.analysis.discrete import KrumhanslSchmuckler
        concert = score.toSoundingPitch(inPlace=False)
        self.assertEqual(KrumhanslSchmuckler()._getPitchClassDistribution(concert.flatten()),
            [3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0])
