"""P5 observable failure, recovery and compatibility contracts; services controlled."""
from datetime import timedelta
from unittest.mock import Mock, patch
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from files.models import PDFFile
from files.tasks import process_score
from files.serializers import FileSerializer
from files.outcomes import read_results
from .orchestration import IsolatedScoreCase


class PartialSuccessTests(IsolatedScoreCase):
    def components(self):
        self.score.refresh_from_db()
        return self.score.results['processing']['components']

    def detail(self, query=''):
        response = self.client.get(f'/api/scores/{self.score.id}/{query}')
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_P5_nested_analysis_error_is_not_unqualified_completion(self):
        self.prepare_score()
        def partial(path, score):
            score.midi_url = 'Error: controlled MIDI failure'
            return {'key': 'C major', 'parts': ['Melody'], 'chords': [], 'time_signature': '4/4',
                    'notable_elements': {'accidentals': {'error': '/private/server/path'}}, 'score_structure': {}}
        with patch('files.tasks.analyze_with_music21', side_effect=partial):
            result, _, _, _ = self.run_pdf()
        self.assertEqual(result['stage'], 'PARTIAL')
        self.assertTrue(self.score.processed)
        c = self.components()
        self.assertEqual(c['notable_elements']['status'], 'failed')
        self.assertEqual(c['midi']['status'], 'failed')
        self.assertNotIn('/private', str(c))
        self.assertEqual(self.detail()['task_status']['state'], 'SUCCESS')

    def test_one_component_exception_preserves_other_analyses_and_artifacts(self):
        self.prepare_score('expression')
        with patch('files.music21_analyzer.MusicAnalysisOptimizer.analyze_notable_elements', side_effect=RuntimeError('/private/secret')):
            result, *_ = self.run_pdf()
        self.assertEqual(result['stage'], 'PARTIAL')
        self.assertEqual(self.components()['notable_elements']['status'], 'failed')
        self.assertEqual(self.score.results['tempo'], '80 quarter notes/min')
        self.assertEqual(self.score.results['key_analysis']['signature_origin'], 'canonical_notation')
        self.assertTrue(self.detail()['score']['capabilities']['default_playback'])
        self.assertNotIn('/private', str(self.detail()))

    def test_parse_failure_preserves_served_notation_without_claiming_analysis(self):
        self.prepare_score()
        with patch('files.music21_analyzer.converter.parse', side_effect=ValueError('private parse path')):
            result, *_ = self.run_pdf()
        self.assertEqual(result['stage'], 'PARTIAL')
        self.assertEqual(self.components()['pipeline']['stage'], 'PARSING_MUSICXML')
        self.assertTrue(self.detail()['score']['capabilities']['notation'])
        self.assertFalse(self.detail()['score']['capabilities']['default_playback'])

    def test_invalid_xml_is_terminal_failure_and_sanitized(self):
        self.prepare_score()
        self.recognized.write_text('<broken>')
        with self.assertRaises(Exception):
            self.run_pdf()
        d = self.detail()
        self.assertEqual(d['task_status']['state'], 'FAILURE')
        self.assertFalse(d['score']['processed'])
        self.assertEqual(self.components()['pipeline']['stage'], 'GENERATING_MUSICXML')
        self.assertNotIn(str(self.root), str(d))

    def test_recognition_failure_remains_terminal_without_backend_metadata(self):
        self.prepare_score()
        with patch('files.tasks.process_with_audiveris', side_effect=RuntimeError('/private/secret')), patch.object(process_score, 'update_state'), patch('files.tasks.cleanup_temp_files.apply_async'):
            with self.assertRaises(RuntimeError):
                process_score.run(self.score.id, 'pdf', 'pdf')
        with patch('files.views.AsyncResult') as backend:
            d = self.detail('?task_id=unrelated')
        backend.assert_not_called()
        self.assertEqual(d['task_status']['state'], 'FAILURE')
        self.assertEqual(self.components()['recognition']['stage'], 'GENERATING_MUSICXML')
        self.assertNotIn('/private', str(d))

    def test_audio_failure_reports_callback_substage(self):
        directory = self.prepare_score(source_type='audio')
        (directory / 'input.wav').write_bytes(b'audio')
        def fail(**kwargs):
            kwargs['progress_callback']('CLEANING_TRANSCRIPTION', 'Cleaning', 50)
            raise RuntimeError('/private/decoder')
        with patch('files.tasks.transcribe_audio_to_musicxml', side_effect=fail), patch.object(process_score, 'update_state'), patch('files.tasks.cleanup_temp_files.apply_async'):
            with self.assertRaises(RuntimeError):
                process_score.run(self.score.id, 'wav', 'audio')
        self.assertEqual(self.components()['recognition']['stage'], 'CLEANING_TRANSCRIPTION')
        self.assertEqual(self.detail()['task_status']['state'], 'FAILURE')

    def test_midi_failure_keeps_xml_and_never_uses_raw_preview(self):
        directory = self.prepare_score()
        (directory / 'preview.mid').write_bytes(b'raw')
        with patch('music21.stream.base.Stream.write', side_effect=RuntimeError('export failed')):
            result, *_ = self.run_pdf()
        self.assertEqual(result['stage'], 'PARTIAL')
        d = self.detail()['score']
        self.assertIsNone(d['playback_midi_url'])
        self.assertTrue(d['capabilities']['notation'])
        self.assertEqual(self.components()['midi']['stage'], 'GENERATING_MIDI')

    def test_ocr_failure_does_not_invalidate_transcription(self):
        directory = self.prepare_score()
        (directory / 'text_results.json').write_text('{"error": "OCR failed"}')
        result, *_ = self.run_pdf()
        self.assertEqual(result['stage'], 'PARTIAL')
        self.assertEqual(self.components()['text']['status'], 'failed')
        self.assertTrue(self.score.processed)
        self.assertEqual(self.components()['recognition']['status'], 'success')

    def test_missing_text_is_not_applicable(self):
        self.prepare_score()
        result, *_ = self.run_pdf()
        self.assertEqual(result['stage'], 'COMPLETED')
        self.assertEqual(self.components()['text']['status'], 'not_applicable')
        self.assertEqual(self.components()['summary']['code'], 'summary_not_requested')

    def test_empty_and_unsupported_are_distinct_from_exception(self):
        # Exercise the actual analyzer on literal empty and rest-only notation.
        self.prepare_score()
        self.recognized.write_text('<score-partwise version="4.0"><part-list><score-part id="P"><part-name>Empty</part-name></score-part></part-list><part id="P"><measure number="1"><attributes><divisions>1</divisions></attributes><note><rest/><duration>1</duration><type>quarter</type></note></measure></part></score-partwise>')
        self.run_pdf()
        self.assertTrue(self.score.processed)
        self.assertEqual(self.score.results['key_analysis']['estimate']['status'], 'absent')
        self.assertNotEqual(self.components()['key_analysis']['status'], 'failed')
        self.assertEqual(self.score.results['tempo'], 'Not specified')
        self.assertEqual(self.components()['time_signature']['status'], 'absent')

    def test_cleanup_scheduling_failure_keeps_original_exception(self):
        self.prepare_score()
        with patch('files.tasks.process_with_audiveris', side_effect=ValueError('original recognition failure')), patch.object(process_score, 'update_state'), patch('files.tasks.cleanup_temp_files.apply_async', side_effect=RuntimeError('broker down')):
            with self.assertRaisesRegex(ValueError, 'original recognition failure'):
                process_score.run(self.score.id, 'pdf', 'pdf')
        self.assertEqual(self.components()['cleanup_scheduling']['code'], 'cleanup_schedule_failed')
        self.assertEqual(self.detail()['task_status']['state'], 'FAILURE')

    def test_cleanup_scheduling_failure_changes_completion_to_partial(self):
        self.prepare_score()
        with patch('files.tasks.process_with_audiveris', return_value=(str(self.recognized), {})), patch.object(process_score, 'update_state'), patch('files.tasks.cleanup_temp_files.apply_async', side_effect=RuntimeError('broker down')):
            result = process_score.run(self.score.id, 'pdf', 'pdf')
        self.assertEqual(result['stage'], 'PARTIAL')
        self.assertEqual(self.components()['cleanup_scheduling']['stage'], 'SCHEDULING_CLEANUP')
        self.assertEqual(self.detail()['task_status']['info']['stage'], 'PARTIAL')

    def test_upload_stores_association_and_ignores_other_task(self):
        with patch('files.views.TextExtractor') as text, patch('files.views.process_score.delay', return_value=Mock(id='owned-job')):
            text.return_value.extract_from_file.return_value = {}
            r = self.client.post('/api/upload/', {'title': 'association', 'analyze': 'true', 'file': SimpleUploadedFile('a.pdf', b'%PDF', content_type='application/pdf')}, format='multipart')
        self.assertEqual(r.status_code, 201)
        self.score = PDFFile.objects.get(pk=r.data['score_id'])
        self.assertEqual(self.score.analysis_task_id, 'owned-job')
        with patch('files.views.AsyncResult', return_value=Mock(state='PENDING')) as backend:
            d = self.detail('?task_id=foreign-job')
        backend.assert_called_once_with('owned-job')
        self.assertEqual(d['task_status']['state'], 'QUEUED')
        self.assertEqual(d['task_status']['info']['task_id_status'], 'unassociated_ignored')

    def test_dispatch_failure_is_persisted_and_pollable(self):
        with patch('files.views.TextExtractor') as text, patch('files.views.process_score.delay', side_effect=RuntimeError('/private/broker')):
            text.return_value.extract_from_file.return_value = {}
            r = self.client.post('/api/upload/', {'title': 'failed dispatch', 'analyze': 'true', 'file': SimpleUploadedFile('a.pdf', b'%PDF', content_type='application/pdf')}, format='multipart')
        self.assertEqual(r.status_code, 503)
        self.score = PDFFile.objects.get(pk=r.data['score_id'])
        self.assertEqual(self.components()['job']['code'], 'dispatch_failed')
        self.assertEqual(self.detail()['task_status']['state'], 'FAILURE')

    def active_job(self, stale=False):
        self.prepare_score()
        self.score.analysis_task_id = 'owned'
        self.score.job_state = 'RUNNING'
        self.score.job_stage = 'ANALYZING_SCORE'
        self.score.job_updated_at = timezone.now() - timedelta(seconds=4000 if stale else 0)
        self.score.save()

    def test_missing_metadata_does_not_invent_failure_for_recent_job(self):
        self.active_job()
        with patch('files.views.AsyncResult', return_value=Mock(state='PENDING')):
            self.assertEqual(self.detail()['task_status']['state'], 'ANALYZING_SCORE')

    def test_worker_restart_stale_job_is_terminal_and_retains_outputs(self):
        self.prepare_score(); self.run_pdf()
        old_key = self.score.results['key_analysis']
        self.score.job_state = 'RUNNING'; self.score.analysis_task_id = 'owned'
        self.score.job_updated_at = timezone.now() - timedelta(seconds=4000)
        self.score.save()
        with patch('files.views.AsyncResult', return_value=Mock(state='PENDING')):
            d = self.detail()
        self.assertEqual(d['task_status']['state'], 'SUCCESS')
        self.assertEqual(d['task_status']['info']['stage'], 'PARTIAL')
        self.assertEqual(d['score']['results']['key_analysis'], old_key)
        self.assertEqual(self.components()['job']['code'], 'job_progress_timeout')

    def test_backend_failure_and_revocation_are_terminal_safe_and_persisted(self):
        for state in ('FAILURE', 'REVOKED', 'SUCCESS'):
            with self.subTest(state=state):
                self.active_job()
                with patch('files.views.AsyncResult', return_value=Mock(state=state, info=RuntimeError('/private/secret'))):
                    d = self.detail()
                self.assertEqual(d['task_status']['state'], 'FAILURE')
                self.assertNotIn('/private', str(d))
                with patch('files.views.AsyncResult') as backend:
                    self.assertEqual(self.detail()['task_status']['state'], 'FAILURE')
                backend.assert_not_called()

    def test_terminal_metadata_survives_artifact_loss_and_ignores_backend(self):
        directory = self.prepare_score(); self.run_pdf()
        (directory / 'output.xml').unlink(); (directory / f'{self.score.id}.mid').unlink()
        with patch('files.views.AsyncResult') as backend:
            d = self.detail('?task_id=expired')
        backend.assert_not_called()
        self.assertEqual(d['task_status']['state'], 'SUCCESS')
        self.assertEqual(d['score']['results']['processing']['status'], 'success')
        self.assertEqual(d['score']['capabilities'], {'notation': False, 'default_playback': False})
        self.assertIsNone(d['score']['musicxml_url'])

    def test_legacy_payloads_are_readable_without_artifacts_or_backend(self):
        for value in ({'parts': ['Flute'], 'tempo': '96 quarter notes/min'}, '{"parts":["Flute"]}', '[1]', '{broken'):
            self.score = PDFFile.objects.create(title='Legacy', results=value, processed=True)
            with patch('files.views.AsyncResult') as backend:
                d = self.detail('?task_id=untrusted')
            backend.assert_not_called()
            self.assertIsInstance(d['score']['results'], dict)
            self.assertEqual(d['score']['results_schema_version'], 1)
            self.assertEqual(d['task_status']['state'], 'SUCCESS')
        self.assertEqual(read_results('{broken')['code'], 'invalid_stored_results')

    def test_optional_summary_failure_preserves_findings_and_previous_summary(self):
        self.prepare_score(); self.run_pdf()
        key = self.score.results['key_analysis']
        self.score.summary = 'Previous summary'; self.score.save()
        with self.settings(GEMINI_API_KEY='controlled'), patch('files.views.genai.configure'), patch('files.views.GenerativeModel') as model:
            model.return_value.generate_content.side_effect = RuntimeError('/private/model')
            r = self.client.post('/api/generate-summary/', {'score_id': self.score.id}, format='json')
        self.assertEqual(r.status_code, 503)
        self.assertEqual(self.components()['summary']['status'], 'failed')
        self.assertEqual(self.score.summary, 'Previous summary')
        self.assertEqual(self.score.results['key_analysis'], key)
        self.assertTrue(self.score.processed)
        self.assertNotIn('/private', str(r.data if hasattr(r, 'data') else r.content))

    def test_summary_uses_usable_findings_and_provenance_without_missing_text_task(self):
        self.prepare_score(); self.run_pdf()
        self.score.results['notable_elements'] = {'error': 'private failure'}; self.score.save()
        with self.settings(GEMINI_API_KEY='controlled'), patch('files.views.genai.configure'), patch('files.views.GenerativeModel') as model:
            model.return_value.generate_content.return_value = Mock(text='Explanation')
            r = self.client.post('/api/generate-summary/', {'score_id': self.score.id}, format='json')
        self.assertEqual(r.status_code, 200)
        prompt = model.return_value.generate_content.call_args.args[0]
        self.assertIn('unverified_recognition', prompt)
        self.assertNotIn('private failure', prompt)
        self.assertNotIn('Clean readable OCR text', prompt)
        self.assertEqual(self.components()['summary']['status'], 'success')

    def test_progress_backend_outage_does_not_destroy_usable_result(self):
        self.prepare_score()
        with patch('files.tasks.process_with_audiveris', return_value=(str(self.recognized), {})), patch.object(process_score, 'update_state', side_effect=RuntimeError('offline')), patch('files.tasks.cleanup_temp_files.apply_async'):
            result = process_score.run(self.score.id, 'pdf', 'pdf')
        self.assertEqual(result['stage'], 'COMPLETED')
        self.assertEqual(self.detail()['task_status']['state'], 'SUCCESS')

    def test_summary_retry_replaces_only_summary_failure_and_finishes_cleanly(self):
        self.prepare_score(); self.run_pdf()
        with self.settings(GEMINI_API_KEY='controlled'), patch('files.views.genai.configure'), patch('files.views.GenerativeModel') as model:
            model.return_value.generate_content.side_effect = RuntimeError('service down')
            self.client.post('/api/generate-summary/', {'score_id': self.score.id}, format='json')
            self.assertEqual(self.detail()['task_status']['info']['stage'], 'PARTIAL')
            model.return_value.generate_content.side_effect = None
            model.return_value.generate_content.return_value = Mock(text='Recovered summary')
            r = self.client.post('/api/generate-summary/', {'score_id': self.score.id}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.components()['summary']['status'], 'success')
        self.assertEqual(self.detail()['task_status']['info']['stage'], 'COMPLETED')

    def test_unsupported_traversal_keeps_identity_and_partial_component(self):
        self.prepare_score()
        self.recognized.write_text(self.recognized.read_text().replace('</measure>', '<barline location="right"><repeat direction="backward"/></barline></measure>', 1))
        result, *_ = self.run_pdf()
        self.assertEqual(result['stage'], 'PARTIAL')
        self.assertEqual(self.components()['events']['status'], 'partial')
        self.assertTrue(self.score.results['musical_identity']['complete'])
        self.assertEqual(self.score.results['musical_identity']['playback']['status'], 'unavailable')
        self.assertTrue(self.score.processed)

    def test_input_preprocessing_failure_is_persisted(self):
        with patch('files.views.FileUploadView.preprocess_image_for_audiveris', return_value=(False, '/private/image')):
            r = self.client.post('/api/upload/', {'title': 'bad image', 'analyze': 'true', 'file': SimpleUploadedFile('a.png', b'bad image', content_type='image/png')}, format='multipart')
        self.assertEqual(r.status_code, 500)
        self.score = PDFFile.objects.get(pk=r.data['score_id'])
        self.assertEqual(self.components()['job']['stage'], 'PREPROCESSING_IMAGE')
        self.assertEqual(self.detail()['task_status']['state'], 'FAILURE')
        self.assertNotIn('/private', str(r.data))

    def test_foreign_worker_task_cannot_process_or_schedule_cleanup_for_score(self):
        self.prepare_score()
        self.score.analysis_task_id = 'owner'; self.score.save()
        process_score.push_request(id='foreign')
        try:
            with patch('files.tasks.process_with_audiveris') as omr, patch('files.tasks.cleanup_temp_files.apply_async') as cleanup:
                r = process_score.run(self.score.id, 'pdf', 'pdf')
        finally:
            process_score.pop_request()
        self.assertEqual(r['stage'], 'SUPERSEDED')
        omr.assert_not_called(); cleanup.assert_not_called()
        self.score.refresh_from_db()
        self.assertIsNone(self.score.results)

    def test_summary_can_read_available_metadata_after_artifact_loss(self):
        directory = self.prepare_score(); self.run_pdf()
        (directory / 'output.xml').unlink(); (directory / f'{self.score.id}.mid').unlink()
        with self.settings(GEMINI_API_KEY='controlled'), patch('files.views.genai.configure'), patch('files.views.GenerativeModel') as model:
            model.return_value.generate_content.return_value = Mock(text='Metadata explanation')
            r = self.client.post('/api/generate-summary/', {'score_id': self.score.id}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.components()['notation']['status'] == 'success')
        self.assertTrue(self.score.processed)
        self.assertFalse(self.detail()['score']['capabilities']['notation'])

    def test_canonical_notation_is_checkpointed_before_worker_interruption(self):
        self.prepare_score()
        def interrupted(path, score):
            persisted = PDFFile.objects.get(pk=score.id)
            self.assertTrue(persisted.musicxml_url)
            self.assertFalse(persisted.processed)
            self.assertFalse(persisted.results['processing']['terminal'])
            raise SystemExit('controlled worker termination')
        with patch('files.tasks.analyze_with_music21', side_effect=interrupted):
            with self.assertRaises(SystemExit):
                self.run_pdf()
        PDFFile.objects.filter(pk=self.score.id).update(job_updated_at=timezone.now() - timedelta(seconds=4000))
        with patch('files.views.AsyncResult', return_value=Mock(state='PENDING')):
            d = self.detail()
        self.assertTrue(d['score']['processed'])
        self.assertTrue(d['score']['capabilities']['notation'])
        self.assertEqual(d['task_status']['info']['stage'], 'PARTIAL')
        self.assertEqual(self.components()['recognition']['status'], 'success')

    def test_late_worker_cannot_replace_recorded_terminal_recovery(self):
        from files.music21_analyzer import analyze_with_music21
        self.prepare_score()
        def late(path, score):
            results = analyze_with_music21(path, score)
            PDFFile.objects.filter(pk=score.id).update(job_updated_at=timezone.now() - timedelta(seconds=4000))
            with patch('files.views.AsyncResult', return_value=Mock(state='PENDING')):
                self.detail()
            return results
        with patch('files.tasks.analyze_with_music21', side_effect=late):
            result, _, _, cleanup = self.run_pdf()
        self.assertEqual(result['stage'], 'PARTIAL')
        self.assertEqual(self.components()['job']['code'], 'job_progress_timeout')
        cleanup.assert_not_called()

    def test_optional_ocr_constructor_failure_still_dispatches_and_records_failure(self):
        with patch('files.views.TextExtractor', side_effect=RuntimeError('/private/ocr')), patch('files.views.process_score.delay', return_value=Mock(id='owned')):
            r = self.client.post('/api/upload/', {'title': 'OCR failure', 'analyze': 'true', 'file': SimpleUploadedFile('a.pdf', b'%PDF', content_type='application/pdf')}, format='multipart')
        self.assertEqual(r.status_code, 201)
        self.score = PDFFile.objects.get(pk=r.data['score_id'])
        self.assertIn('error', self.score.results['text_content'])
        self.assertNotIn('/private', str(self.detail()))

    def test_failed_legacy_fields_keep_renderable_string_and_list_types(self):
        self.prepare_score()
        with patch('files.music21_analyzer.MusicAnalysisOptimizer.analyze_parts', side_effect=ValueError('failure')), patch('files.music21_analyzer.MusicAnalysisOptimizer.analyze_chords', side_effect=ValueError('failure')), patch('files.music21_analyzer.MusicAnalysisOptimizer.analyze_time_signature', side_effect=ValueError('failure')):
            result, *_ = self.run_pdf()
        self.assertEqual(result['stage'], 'PARTIAL')
        d = self.detail()['score']['results']
        self.assertIsInstance(d['parts'], list)
        self.assertIsInstance(d['chords'], list)
        self.assertEqual(d['time_signature'], 'Not specified')
        self.assertIsInstance(d['tempo'], str)
        for name in ('parts', 'chords', 'time_signature'):
            self.assertEqual(self.components()[name]['status'], 'failed')
